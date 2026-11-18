"""Bookkeeping routes: /api/books/* and /api/plaid/*."""

import asyncio
import json
import re
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from . import categorize, config, plaid, quickbooks, statements
from .auth import require_login
from .db import delete_setting, get_setting, set_setting
from .ledger import (
    BankAccount, BankLink, LedgerAccount, Rule, Txn, TxnSplit, add_starter_chart, is_money_account, kind, set_splits, splits_for, txn_lines,
)

router = APIRouter()
_tasks: set[asyncio.Task] = set()


def _background(coro) -> None:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def _acct_json(a: LedgerAccount) -> dict:
    return {"id": a.id, "name": a.name, "type": a.type, "kind": kind(a.type), "active": a.active, "source": a.source}


# ---------- overview ----------


@router.get("/api/books/summary")
def summary(db: Session = Depends(require_login)):
    chart = db.exec(select(LedgerAccount)).all()
    names = {a.id: a.name for a in chart}
    kinds = {a.id: kind(a.type) for a in chart}
    banks = db.exec(select(BankAccount)).all()
    links = {l.item_id: l for l in db.exec(select(BankLink)).all()}
    visible = select(Txn).where(Txn.hidden == False)  # noqa: E712

    today = date.today()
    month_start = today.replace(day=1)
    month = db.exec(visible.where(Txn.date >= month_start)).all()
    parts = splits_for(db, [t.id for t in month])
    lines = [ln for t in month for ln in txn_lines(t, parts)]
    money_in = sum(c for cat, c in lines if kinds.get(cat) == "income")
    money_out = -sum(c for cat, c in lines if kinds.get(cat) == "expense")

    qb_count = db.exec(select(func.count()).select_from(Txn).where(Txn.source == "quickbooks")).one()
    review = db.exec(select(func.count()).select_from(Txn).where(Txn.needs_review == True, Txn.hidden == False)).one()  # noqa: E712
    client_id, secret = plaid.keys(db)
    return {
        "chart_count": len(chart),
        "chart_from_quickbooks": any(a.source == "quickbooks" for a in chart),
        "quickbooks_history": qb_count,
        "plaid_keys": bool(client_id and secret),
        "plaid_items_used": plaid.items_used(db), "plaid_item_limit": plaid.item_limit(db),
        "plaid_institutions": sorted({lk.institution for lk in db.exec(select(BankLink)).all() if lk.institution}),
        "claude_connected": bool(get_setting(db, "claude_key")),
        "start_date": get_setting(db, "books_start_date"),
        "review_count": review,
        "month": {"label": today.strftime("%B"), "in_cents": money_in, "out_cents": money_out},
        "banks": [
            {
                "id": b.id, "name": b.name, "mask": b.mask, "type": b.type,
                "balance_cents": b.balance_cents, "ledger_account_id": b.ledger_account_id,
                "ledger_name": names.get(b.ledger_account_id, ""),
                "institution": links[b.item_id].institution if b.item_id in links else "",
                "error": links[b.item_id].error if b.item_id in links else "",
                "item_id": b.item_id,
            }
            for b in banks
        ],
        "syncing": plaid.state["syncing"],
        "last_sync_at": plaid.state["last_sync_at"],
        "last_error": plaid.state["last_error"],
        "last_result": plaid.state["last_result"],
    }


# ---------- chart of accounts ----------


@router.get("/api/books/accounts")
def accounts(db: Session = Depends(require_login)):
    rows = db.exec(select(LedgerAccount).order_by(LedgerAccount.name)).all()
    return [_acct_json(a) for a in rows]


class NewAccount(BaseModel):
    name: str
    type: str


@router.post("/api/books/accounts")
def add_account(body: NewAccount, db: Session = Depends(require_login)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Give the category a name.")
    if db.exec(select(LedgerAccount).where(LedgerAccount.name == name)).first():
        raise HTTPException(409, "A category with that name already exists.")
    a = LedgerAccount(name=name, type=body.type or "Expense", source="you")
    db.add(a)
    db.commit()
    db.refresh(a)
    return _acct_json(a)


@router.post("/api/books/starter-chart")
def starter_chart(db: Session = Depends(require_login)):
    return {"added": add_starter_chart(db)}


# ---------- QuickBooks files ----------

ALLOWED = (".xlsx", ".xlsm", ".csv", ".xls")


@router.get("/api/books/imports")
def import_files(db: Session = Depends(require_login)):
    config.IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted((p for p in config.IMPORTS_DIR.iterdir() if p.suffix.lower() in ALLOWED), key=lambda p: -p.stat().st_mtime)
    return {
        "folder": str(config.IMPORTS_DIR),
        "files": [{"name": p.name, "size": p.stat().st_size, "kind": quickbooks.guess_kind(p)} for p in files],
    }


@router.post("/api/books/imports/upload")
async def upload(file: UploadFile, db: Session = Depends(require_login)):
    name = re.sub(r"[^A-Za-z0-9 ._()-]", "_", file.filename or "upload.xlsx")
    if not name.lower().endswith(ALLOWED):
        raise HTTPException(422, "Savannah reads Excel (.xlsx) or CSV files.")
    config.IMPORTS_DIR.mkdir(parents=True, exist_ok=True)
    data = await file.read()
    if len(data) > 30_000_000:
        raise HTTPException(422, "That file is too big (over 30 MB).")
    (config.IMPORTS_DIR / name).write_bytes(data)
    return {"name": name, "kind": quickbooks.guess_kind(config.IMPORTS_DIR / name)}


def _import_path(name: str):
    p = (config.IMPORTS_DIR / name).resolve()
    if p.parent != config.IMPORTS_DIR.resolve() or not p.exists():
        raise HTTPException(404, "That file isn't in the imports folder anymore.")
    return p


class FileBody(BaseModel):
    file: str
    flip: bool = False


@router.post("/api/books/import/accounts")
def import_accounts(body: FileBody, db: Session = Depends(require_login)):
    try:
        return quickbooks.import_accounts(db, _import_path(body.file))
    except quickbooks.ImportProblem as e:
        raise HTTPException(422, str(e))


@router.post("/api/books/import/transactions/preview")
def preview_transactions(body: FileBody, db: Session = Depends(require_login)):
    try:
        return quickbooks.parse_transactions(db, _import_path(body.file), body.flip)["summary"]
    except quickbooks.ImportProblem as e:
        raise HTTPException(422, str(e))


@router.post("/api/books/import/transactions")
def import_transactions(body: FileBody, db: Session = Depends(require_login)):
    try:
        parsed = quickbooks.parse_transactions(db, _import_path(body.file), body.flip)
    except quickbooks.ImportProblem as e:
        raise HTTPException(422, str(e))
    result = quickbooks.save_transactions(db, parsed["rows"])
    # Savannah's own books start the day after QuickBooks history ends.
    last = date.fromisoformat(parsed["summary"]["last"])
    current = get_setting(db, "books_start_date")
    new_start = (last + timedelta(days=1)).isoformat()
    if not current or current < new_start:
        _set_start(db, new_start)
    return {**result, "start_date": get_setting(db, "books_start_date")}


@router.post("/api/books/import/journal/preview")
def preview_journal(body: FileBody, db: Session = Depends(require_login)):
    try:
        return quickbooks.parse_journal(db, _import_path(body.file))["summary"]
    except quickbooks.ImportProblem as e:
        raise HTTPException(422, str(e))


@router.post("/api/books/import/journal")
def import_journal(body: FileBody, db: Session = Depends(require_login)):
    try:
        parsed = quickbooks.parse_journal(db, _import_path(body.file))
    except quickbooks.ImportProblem as e:
        raise HTTPException(422, str(e))
    return quickbooks.save_journal(db, parsed)


class StartBody(BaseModel):
    date: str


def _set_start(db: Session, d: str) -> None:
    set_setting(db, "books_start_date", d)
    _rehide(db)


def _rehide(db: Session) -> None:
    """Which Chase transactions count: after the start date, unless the account is left out
    (personal) or isn't in QuickBooks (then its whole history counts)."""
    s = get_setting(db, "books_start_date")
    start = date.fromisoformat(s) if s else None
    banks = {b.ledger_account_id: b for b in db.exec(select(BankAccount)).all()}
    for t in db.exec(select(Txn).where(Txn.source == "plaid")).all():
        b = banks.get(t.account_id)
        t.hidden = bool(b and b.ignored) or bool(start and t.date < start and not (b and b.full_history))
        db.add(t)
    db.commit()


@router.post("/api/books/start-date")
def start_date(body: StartBody, db: Session = Depends(require_login)):
    try:
        date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(422, "Pick a date.")
    _set_start(db, body.date)
    return {"ok": True}


# ---------- transactions ----------


@router.get("/api/books/transactions")
def transactions(view: str = "review", q: str = "", month: str = "", offset: int = 0, db: Session = Depends(require_login)):
    names = {a.id: a for a in db.exec(select(LedgerAccount)).all()}
    stmt = select(Txn).where(Txn.hidden == False)  # noqa: E712
    if view == "review":
        stmt = stmt.where(Txn.needs_review == True)  # noqa: E712
    if q:
        stmt = stmt.where(Txn.description.ilike(f"%{q}%"))
    if month:
        y, m = (int(x) for x in month.split("-"))
        start = date(y, m, 1)
        end = date(y + (m == 12), m % 12 + 1, 1)
        stmt = stmt.where(Txn.date >= start, Txn.date < end)
    total = db.exec(select(func.count()).select_from(stmt.subquery())).one()
    rows = db.exec(stmt.order_by(Txn.date.desc(), Txn.id.desc()).offset(offset).limit(100)).all()
    parts = splits_for(db, [t.id for t in rows])
    return {
        "total": total,
        "items": [
            {
                "id": t.id, "date": t.date.isoformat(), "description": t.description, "merchant": t.merchant,
                "amount_cents": t.amount_cents, "source": t.source,
                "account": names[t.account_id].name if t.account_id in names else "",
                "category_id": t.category_id,
                "category": names[t.category_id].name if t.category_id in names else "",
                "category_source": t.category_source, "needs_review": t.needs_review,
                "suggested_rule": categorize.merchant_key(t.merchant or t.description),
                "splits": [
                    {"category_id": sp.category_id, "category": names[sp.category_id].name if sp.category_id in names else "",
                     "amount_cents": sp.amount_cents, "memo": sp.memo}
                    for sp in parts.get(t.id, [])
                ],
            }
            for t in rows
        ],
    }


class CategoryBody(BaseModel):
    category_id: int
    always: bool = False
    match: str = ""
    mode: str = "auto"  # auto | suggest


@router.post("/api/books/transactions/{txn_id}/category")
def set_category(txn_id: int, body: CategoryBody, db: Session = Depends(require_login)):
    t = db.get(Txn, txn_id)
    if not t:
        raise HTTPException(404, "That transaction is gone. Refresh the page.")
    if not db.get(LedgerAccount, body.category_id):
        raise HTTPException(422, "Pick a category.")
    t.category_id, t.category_source, t.needs_review = body.category_id, "you", False
    db.add(t)
    db.commit()
    also = 0
    if body.always and body.match.strip():
        before = db.exec(select(func.count()).select_from(Txn).where(Txn.needs_review == True)).one()  # noqa: E712
        categorize.make_rule(db, body.match, body.category_id, "in" if t.amount_cents > 0 else "out",
                             "suggest" if body.mode == "suggest" else "auto")
        after = db.exec(select(func.count()).select_from(Txn).where(Txn.needs_review == True)).one()  # noqa: E712
        also = before - after
    return {"ok": True, "also_sorted": also}


class SplitLine(BaseModel):
    category_id: int
    amount_cents: int
    memo: str = ""


class SplitBody(BaseModel):
    lines: list[SplitLine]
    remember: bool = False
    match: str = ""


@router.post("/api/books/transactions/{txn_id}/split")
def split_txn(txn_id: int, body: SplitBody, db: Session = Depends(require_login)):
    """Split one transaction across several categories (or undo a split with an empty list)."""
    t = db.get(Txn, txn_id)
    if not t:
        raise HTTPException(404, "That transaction is gone. Refresh the page.")
    lines = [ln for ln in body.lines if ln.amount_cents != 0]
    if not lines:
        set_splits(db, t, [])
        t.needs_review = True
        db.add(t)
        db.commit()
        return {"ok": True}
    for ln in lines:
        if not db.get(LedgerAccount, ln.category_id):
            raise HTTPException(422, "Pick a category for every part.")
    total = sum(ln.amount_cents for ln in lines)
    if total != t.amount_cents:
        diff = (abs(t.amount_cents) - abs(total)) / 100
        raise HTTPException(422, f"The parts must add up to the full amount: ${abs(diff):,.2f} {'still to place' if diff > 0 else 'too much'}.")
    set_splits(db, t, [(ln.category_id, ln.amount_cents, ln.memo[:120]) for ln in lines], source="split")
    t.needs_review = False
    db.add(t)
    db.commit()
    if body.remember and body.match.strip():
        categorize.make_split_rule(
            db, body.match, [(ln.category_id, ln.amount_cents) for ln in lines], "in" if t.amount_cents > 0 else "out"
        )
    return {"ok": True}


@router.post("/api/books/transactions/{txn_id}/statement")
async def read_statement(txn_id: int, file: UploadFile, db: Session = Depends(require_login)):
    """Read a mortgage statement and suggest how to split this payment (nothing is saved until you press Save)."""
    t = db.get(Txn, txn_id)
    if not t:
        raise HTTPException(404, "That transaction is gone. Refresh the page.")
    data = await file.read()
    try:
        return await statements.split_from_statement(db, t, file.filename or "statement.pdf", data)
    except statements.StatementError as e:
        raise HTTPException(422, str(e))


@router.get("/api/books/rules")
def rules(db: Session = Depends(require_login)):
    names = {a.id: a.name for a in db.exec(select(LedgerAccount)).all()}
    return [
        {"id": r.id, "match": r.match, "direction": r.direction, "times_used": r.times_used,
         "mode": r.mode or "auto", "split": bool(r.split_json),
         "category": (" + ".join(names.get(p["category_id"], "?") for p in json.loads(r.split_json)) if r.split_json
                      else names.get(r.category_id, ""))}
        for r in db.exec(select(Rule).order_by(Rule.created_at.desc())).all()
    ]


@router.post("/api/books/rules/run")
def run_rules(db: Session = Depends(require_login)):
    return {"sorted": categorize.run_rules_everywhere(db)}


class ModeBody(BaseModel):
    mode: str


@router.post("/api/books/rules/{rule_id}/mode")
def set_rule_mode(rule_id: int, body: ModeBody, db: Session = Depends(require_login)):
    """Auto: file matching transactions by themselves. Suggest: fill in the category, wait for your OK."""
    if body.mode not in ("auto", "suggest"):
        raise HTTPException(422, "Choose auto or suggest.")
    r = db.get(Rule, rule_id)
    if not r:
        raise HTTPException(404, "That rule is gone. Refresh the page.")
    r.mode = body.mode
    db.add(r)
    db.commit()
    filed = 0
    if body.mode == "auto" and not r.split_json:
        # Anything this rule was only suggesting is now filed.
        waiting = db.exec(select(Txn).where(Txn.needs_review == True, Txn.category_source == "rule", Txn.hidden == False)).all()  # noqa: E712
        for t in waiting:
            if categorize.rule_matches(r, t) and t.category_id == r.category_id:
                t.needs_review = False
                db.add(t)
                filed += 1
        db.commit()
    return {"ok": True, "filed": filed}


@router.delete("/api/books/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(require_login)):
    r = db.get(Rule, rule_id)
    if r:
        db.delete(r)
        db.commit()
    return {"ok": True}


# ---------- bank (Plaid) ----------


class PlaidKeys(BaseModel):
    client_id: str
    secret: str


@router.post("/api/connections/plaid")
async def save_plaid(body: PlaidKeys, db: Session = Depends(require_login)):
    cid, sec = body.client_id.strip(), body.secret.strip()
    if len(cid) < 10 or len(sec) < 10:
        raise HTTPException(422, "Paste both the client ID and the secret.")
    try:
        await plaid.link_token(cid, sec)
    except plaid.PlaidError as e:
        if e.code == "INVALID_API_KEYS":
            return {"ok": False, "message": str(e)}
        set_setting(db, "plaid_client_id", cid)
        set_setting(db, "plaid_secret", sec)
        return {"ok": False, "message": "Saved, but couldn't check it right now: " + str(e)}
    set_setting(db, "plaid_client_id", cid)
    set_setting(db, "plaid_secret", sec)
    return {"ok": True, "message": "Connected. Now go to Books and press Connect Chase."}


@router.delete("/api/connections/plaid")
def remove_plaid(db: Session = Depends(require_login)):
    delete_setting(db, "plaid_client_id")
    delete_setting(db, "plaid_secret")
    return {"ok": True}


class LinkBody(BaseModel):
    item_id: str = ""
    products: list[str] = []  # extra permissions to ask for in update mode, e.g. ["liabilities"]


@router.post("/api/plaid/link-token")
async def make_link_token(body: LinkBody, db: Session = Depends(require_login)):
    client_id, secret = plaid.keys(db)
    if not (client_id and secret):
        raise HTTPException(409, "Add your Plaid keys in Settings first.")
    access = None
    if body.item_id:
        link = db.get(BankLink, body.item_id)
        access = link.access_token if link else None
    elif plaid.items_used(db) >= plaid.item_limit(db):
        raise HTTPException(409, f"You've used all {plaid.item_limit(db)} free Plaid connections. Adding another needs a paid Plaid plan.")
    try:
        extra = [p for p in body.products if p in ("liabilities",)] if access else None
        return {"link_token": await plaid.link_token(client_id, secret, access, extra)}
    except plaid.PlaidError as e:
        raise HTTPException(502, str(e))


class ExchangeBody(BaseModel):
    public_token: str = ""
    institution: str = ""
    reconnected_item: str = ""


@router.post("/api/plaid/exchange")
async def exchange(body: ExchangeBody, db: Session = Depends(require_login)):
    if body.reconnected_item:
        link = db.get(BankLink, body.reconnected_item)
        if link:
            link.error = ""
            db.add(link)
            db.commit()
        delete_setting(db, plaid.CARD_BILLS_KEY)  # ask the bank for card bills again
    else:
        try:
            await plaid.connect(body.public_token, body.institution)
        except plaid.PlaidError as e:
            raise HTTPException(502, str(e))
    _background(plaid.sync_all())
    return {"ok": True}


@router.post("/api/books/sync")
async def sync_now(db: Session = Depends(require_login)):
    client_id, secret = plaid.keys(db)
    if not (client_id and secret):
        raise HTTPException(409, "Add your Plaid keys in Settings first.")
    plaid.state["syncing"] = True  # so the screen shows "Updating…" straight away
    _background(plaid.sync_all())
    return {"ok": True}


class BankMap(BaseModel):
    ledger_account_id: int


@router.post("/api/books/bank-accounts/{account_id}")
def map_bank(account_id: str, body: BankMap, db: Session = Depends(require_login)):
    b = db.get(BankAccount, account_id)
    target = db.get(LedgerAccount, body.ledger_account_id)
    if not b or not target or not is_money_account(target.type):
        raise HTTPException(422, "Pick a bank or credit card account.")
    old = b.ledger_account_id
    b.ledger_account_id = target.id
    if target.source == "quickbooks":
        b.full_history = False  # QuickBooks has the history before the start date
    db.add(b)
    others_share_old = any(x.id != b.id and x.ledger_account_id == old for x in db.exec(select(BankAccount)).all())
    if not others_share_old and old:
        for t in db.exec(select(Txn).where(Txn.source == "plaid", Txn.account_id == old)).all():
            t.account_id = target.id
            db.add(t)
        old_acct = db.get(LedgerAccount, old)
        if old_acct and old_acct.source == "bank":
            # Transfers that point at the stand-in (e.g. a card payment "from checking") follow it too.
            for t in db.exec(select(Txn).where(Txn.category_id == old)).all():
                t.category_id = target.id
                db.add(t)
            for sp in db.exec(select(TxnSplit).where(TxnSplit.category_id == old)).all():
                sp.category_id = target.id
                db.add(sp)
            for r in db.exec(select(Rule).where(Rule.category_id == old)).all():
                r.category_id = target.id
                db.add(r)
    db.commit()
    # Remove the stand-in account Savannah made when Chase was first connected, if nothing uses it now.
    old_acct = db.get(LedgerAccount, old) if old else None
    if old_acct and old_acct.source == "bank" and not others_share_old:
        used = db.exec(select(Txn).where((Txn.account_id == old) | (Txn.category_id == old))).first()
        used = used or db.exec(select(TxnSplit).where(TxnSplit.category_id == old)).first()
        if not used:
            db.delete(old_acct)
            db.commit()
    _rehide(db)
    return {"ok": True}


@router.get("/api/books/balance-check")
def balance_check(db: Session = Depends(require_login)):
    """Does Savannah's balance for each Chase account match what Chase says?"""
    from datetime import date as _date
    from . import reports

    accounts = {a.id: a for a in db.exec(select(LedgerAccount)).all()}
    debit: dict[int, int] = {}
    for _t, acct_id, d, _m in reports.ledger_lines(db, None, _date.today()):
        debit[acct_id] = debit.get(acct_id, 0) + d
    paired = {b.ledger_account_id for b in db.exec(select(BankAccount)).all()}
    out = []
    for b in db.exec(select(BankAccount)).all():
        if b.balance_cents is None or b.ledger_account_id not in accounts:
            continue
        if b.ignored:
            out.append({"bank_account_id": b.id, "name": f"{b.name} ••{b.mask}", "card": b.type == "credit", "left_out": True,
                        "ledger_name": accounts[b.ledger_account_id].name, "chase_cents": b.balance_cents, "savannah_cents": 0,
                        "difference_cents": 0, "matches": True, "balance_at": None, "suggestion": None, "full_history": False})
            continue
        card = b.type == "credit"
        chase = -b.balance_cents if card else b.balance_cents  # same sign rule as QuickBooks balances
        mine = debit.get(b.ledger_account_id, 0)
        ledger = accounts[b.ledger_account_id]
        suggestion = None
        overlap = _qb_twin(db, b, accounts) if (mine != chase or b.full_history) else None
        twice = bool(overlap and b.full_history)  # history brought in on top of QuickBooks' copy
        if overlap:
            suggestion = {"id": overlap[0].id, "name": overlap[0].name, "why": f"{overlap[1]} charges match QuickBooks"}
        if mine != chase and not suggestion:
            for a in accounts.values():
                if a.id == ledger.id or a.id in paired or not is_money_account(a.type):
                    continue
                if (a.type.lower().startswith("credit card")) != card:
                    continue
                if debit.get(a.id, 0) + mine == chase:
                    suggestion = {"id": a.id, "name": a.name}
                    break
        shown = (lambda v: -v) if card else (lambda v: v)  # cards: show what you owe as a positive number
        out.append({
            "bank_account_id": b.id, "name": f"{b.name} ••{b.mask}", "card": card,
            "ledger_name": ledger.name, "chase_cents": shown(chase), "savannah_cents": shown(mine),
            "difference_cents": shown(mine) - shown(chase), "matches": mine == chase and not twice, "counted_twice": twice,
            "balance_at": b.balance_at.isoformat() if b.balance_at else None, "suggestion": suggestion,
            "left_out": False, "full_history": b.full_history, "in_quickbooks": ledger.source == "quickbooks",
        })
    return out


def _qb_twin(db: Session, b: BankAccount, accounts: dict) -> tuple[LedgerAccount, int] | None:
    """Is this Chase account really a QuickBooks account under another name? Count Chase transactions
    (any date) that QuickBooks also has on one of its unpaired bank/card accounts: same amount, within 4 days."""
    card = b.type == "credit"
    paired = {x.ledger_account_id for x in db.exec(select(BankAccount)).all()}
    options = [a for a in accounts.values() if is_money_account(a.type) and a.id not in paired
               and a.type.lower().startswith("credit card") == card and a.source == "quickbooks"]
    if not options or b.ledger_account_id is None:
        return None
    mine = db.exec(select(Txn).where(Txn.source == "plaid", Txn.account_id == b.ledger_account_id)).all()
    if not mine:
        return None
    qb = db.exec(select(Txn).where(Txn.source == "quickbooks")).all()
    by_amount: dict[int, list[Txn]] = {}
    for q in qb:
        by_amount.setdefault(q.amount_cents, []).append(q)
    best = None
    for a in options:
        hits = 0
        for t in mine:
            near = lambda q: abs((q.date - t.date).days) <= 4  # noqa: E731
            on_account = any(q.account_id == a.id and near(q) for q in by_amount.get(t.amount_cents, []))
            # e.g. a card payment: QuickBooks has it on checking, pointing at the card (opposite sign)
            pointing = any(q.category_id == a.id and near(q) for q in by_amount.get(-t.amount_cents, []))
            if on_account or pointing:
                hits += 1
        if hits >= 5 and (best is None or hits > best[1]):
            best = (a, hits)
    return best


class LeaveOut(BaseModel):
    leave_out: bool = True


@router.post("/api/books/bank-accounts/{account_id}/leave-out")
def leave_out(account_id: str, body: LeaveOut, db: Session = Depends(require_login)):
    """A personal account: keep its transactions out of the books (or bring them back)."""
    b = db.get(BankAccount, account_id)
    if not b:
        raise HTTPException(404, "Account not found.")
    b.ignored = body.leave_out
    db.add(b)
    db.commit()
    _rehide(db)
    return {"ok": True}


@router.post("/api/books/bank-accounts/{account_id}/use-history")
async def use_history(account_id: str, db: Session = Depends(require_login)):
    """This account isn't in QuickBooks: count its Chase history, plus a starting balance so totals match Chase."""
    from datetime import timedelta as _td
    from . import reports

    b = db.get(BankAccount, account_id)
    if not b or b.ledger_account_id is None or b.balance_cents is None:
        raise HTTPException(404, "Account not found.")
    paired_to = db.get(LedgerAccount, b.ledger_account_id)
    if paired_to and paired_to.source == "quickbooks":
        raise HTTPException(409, f"QuickBooks already has the history of “{paired_to.name}”. Bringing in the bank's "
                                 "history too would count it twice.")
    twin = _qb_twin(db, b, {a.id: a for a in db.exec(select(LedgerAccount)).all()})
    if twin:
        raise HTTPException(409, f"{twin[1]} of these charges are already in QuickBooks under “{twin[0].name}”. "
                                 "Pair it with that account instead, so nothing is counted twice.")
    b.full_history, b.ignored = True, False
    db.add(b)
    db.commit()
    _rehide(db)
    txns = db.exec(select(Txn).where(Txn.source == "plaid", Txn.account_id == b.ledger_account_id, Txn.hidden == False)).all()  # noqa: E712
    # Starting balance: whatever Chase's balance has that the transactions don't explain.
    have = sum(d for _t, acct, d, _m in reports.ledger_lines(db, None, date.today()) if acct == b.ledger_account_id)
    chase = -b.balance_cents if b.type == "credit" else b.balance_cents
    gap = chase - have
    if gap:
        first = min((t.date for t in txns), default=date.today())
        equity = db.exec(select(LedgerAccount).where(LedgerAccount.name == "Opening balance equity")).first()
        if not equity:
            equity = LedgerAccount(name="Opening balance equity", type="Equity", source="you")
            db.add(equity)
            db.commit()
            db.refresh(equity)
        ob = Txn(external_id=f"open:{b.id}", source="you", date=first - _td(days=1),
                 description=f"Starting balance for {b.name} ••{b.mask}", amount_cents=gap,
                 account_id=b.ledger_account_id, category_id=equity.id, category_source="you")
        existing = db.exec(select(Txn).where(Txn.external_id == ob.external_id)).first()
        if existing:
            existing.amount_cents, existing.date = gap + existing.amount_cents, ob.date
            db.add(existing)
        else:
            db.add(ob)
        db.commit()
    ids = [t.id for t in txns if t.category_id is None and t.category_source not in ("split", "rule-split", "qb-split")]
    _background(categorize.categorize(db, ids))
    return {"ok": True, "transactions": len(txns), "starting_balance_cents": gap}


@router.post("/api/books/recategorize")
async def recategorize(db: Session = Depends(require_login)):
    ids = [
        t.id for t in db.exec(
            select(Txn).where(Txn.category_id.is_(None), Txn.hidden == False, Txn.category_source.not_in(["split", "rule-split", "qb-split"]))  # noqa: E712
        ).all()
    ]
    return await categorize.categorize(db, ids)
