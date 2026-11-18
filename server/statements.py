"""Read a mortgage statement (PDF or photo) and fill in a payment's split: principal, interest, escrow, fees.

Claude reads the statement (any lender's layout). We then pick the right numbers for the
payment you're splitting:
  1. a payment listed in the statement's "Transaction Activity" with the same amount and a close date, or
  2. the "Explanation of Amount Due" when the payment's date is near the statement's due date.
A copy of each statement is kept in data/statements/ for your records.
"""

import base64
import datetime as dt
import json
import re

import anthropic
from sqlmodel import Session, select

from . import categorize, config, drafting
from .db import get_setting
from .ledger import LedgerAccount, Rule, Txn, TxnSplit, kind

PARTS = ("principal", "interest", "escrow", "fees")
LABELS = {"principal": "Principal", "interest": "Interest", "escrow": "Escrow (taxes & insurance)", "fees": "Fees & late charges"}

PROMPT = """This is a mortgage (home loan) statement. Read it and reply with only this JSON (amounts as plain numbers in dollars, dates as YYYY-MM-DD, null when not shown):

{
 "lender": "...",
 "loan_number_last4": "1234",
 "property": "street address",
 "statement_date": "YYYY-MM-DD",
 "due_date": "YYYY-MM-DD",
 "amount_due": 0.00,
 "due_breakdown": {"principal": 0.00, "interest": 0.00, "escrow": 0.00, "fees": 0.00},
 "payments": [
   {"date": "YYYY-MM-DD", "amount": 0.00, "principal": 0.00, "interest": 0.00, "escrow": 0.00, "fees": 0.00}
 ]
}

- "due_breakdown" is the upcoming regular payment (often called "Explanation of Amount Due"). Fees = late charges + other fees due.
- "payments" are payments the lender received during the statement period (often in "Transaction Activity"). Only include actual payments, not insurance or tax disbursements.
"""


class StatementError(Exception):
    pass


def _media(name: str, data: bytes) -> tuple[str, str]:
    n = name.lower()
    if n.endswith(".pdf") or data[:4] == b"%PDF":
        return "document", "application/pdf"
    if n.endswith((".jpg", ".jpeg")):
        return "image", "image/jpeg"
    if n.endswith(".png"):
        return "image", "image/png"
    if n.endswith(".webp"):
        return "image", "image/webp"
    raise StatementError("Upload the statement as a PDF or a photo (JPG or PNG).")


async def read_statement(api_key: str, name: str, data: bytes) -> dict:
    block_type, media = _media(name, data)
    block = {"type": block_type, "source": {"type": "base64", "media_type": media, "data": base64.b64encode(data).decode()}}
    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        res = await client.messages.create(
            model=drafting.MODEL, max_tokens=1500,
            messages=[{"role": "user", "content": [block, {"type": "text", "text": PROMPT}]}],
        )
    except anthropic.AuthenticationError:
        raise StatementError("Claude didn't accept the key. Check it in Settings → Connections.")
    except anthropic.APIError as e:
        raise StatementError(f"Couldn't read the statement right now ({type(e).__name__}). Try again in a minute.")
    finally:
        await client.close()
    text = "".join(b.text for b in res.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    try:
        info = json.loads(m.group(0)) if m else None
    except ValueError:
        info = None
    if not isinstance(info, dict):
        raise StatementError("That doesn't look like a mortgage statement Savannah can read.")
    return info


def _cents(v) -> int:
    try:
        return round(float(str(v).replace("$", "").replace(",", "")) * 100)
    except (TypeError, ValueError):
        return 0


def _date(v) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def pick_numbers(info: dict, t: Txn) -> dict:
    """Which breakdown fits this payment? Returns {parts: {principal: cents, …}, where: '…', exact: bool}."""
    amount = abs(t.amount_cents)

    def parts_of(row: dict) -> dict[str, int]:
        return {p: abs(_cents(row.get(p))) for p in PARTS}

    # 1. A payment the lender received, same amount, within a week.
    best = None
    for row in info.get("payments") or []:
        d = _date(row.get("date"))
        if abs(_cents(row.get("amount"))) == amount and d and abs((d - t.date).days) <= 7:
            if best is None or abs((d - t.date).days) < abs((_date(best.get("date")) - t.date).days):
                best = row
    if best:
        p = parts_of(best)
        return {"parts": p, "where": f"payment received {_date(best['date']):%b %-d}", "exact": sum(p.values()) == amount}

    # 2. The amount due, if this payment is for that due date.
    due = _date(info.get("due_date"))
    breakdown = info.get("due_breakdown") or {}
    if breakdown:
        p = parts_of(breakdown)
        near = due is not None and abs((due - t.date).days) <= 20
        return {
            "parts": p,
            "where": f"amount due {due:%b %-d}" if due else "amount due",
            "exact": near and sum(p.values()) == amount,
        }
    raise StatementError("Couldn't find the payment breakdown on that statement.")


def _candidates(db: Session, t: Txn) -> list[LedgerAccount]:
    """Categories you've used for this payment before (this one, its split rule, similar past splits)."""
    ids: list[int] = [s.category_id for s in db.exec(select(TxnSplit).where(TxnSplit.txn_id == t.id)).all() if s.category_id]
    for r in db.exec(select(Rule).where(Rule.split_json != "")).all():
        if categorize.rule_matches(r, t):
            ids += [p["category_id"] for p in json.loads(r.split_json)]
    keys = set(categorize.merchant_keys(t.merchant or t.description))
    split_txns = db.exec(
        select(Txn).where(Txn.category_source.in_(["split", "qb-split", "rule-split"]), Txn.id != t.id).order_by(Txn.date.desc()).limit(300)
    ).all()
    for o in split_txns:
        if keys & set(categorize.merchant_keys(o.merchant or o.description)):
            ids += [s.category_id for s in db.exec(select(TxnSplit).where(TxnSplit.txn_id == o.id)).all() if s.category_id]
            break
    out, seen = [], set()
    for i in ids:
        a = db.get(LedgerAccount, i)
        if a and i not in seen:
            seen.add(i)
            out.append(a)
    return out


def _pick(accounts: list[LedgerAccount], part: str) -> LedgerAccount | None:
    def score(a: LedgerAccount) -> int:
        n, k = a.name.lower(), kind(a.type)
        typ = (a.type or "").lower()
        if part == "interest":
            return 3 if "mortgage interest" in n else 2 if "interest" in n and k == "expense" else 0
        if part == "escrow":
            return 3 if "escrow" in n else 1 if ("tax" in n and "insurance" in n) else 0
        if part == "principal":
            if "interest" in n or "escrow" in n:
                return 0
            return 3 if "liabilit" in typ and ("mortgage" in n or "loan" in n) else 2 if "liabilit" in typ else 0
        if part == "fees":
            return 3 if "late" in n else 2 if "fee" in n and k == "expense" else 0
        return 0
    best = max(accounts, key=score, default=None)
    return best if best and score(best) > 0 else None


def fill_split(db: Session, t: Txn, info: dict) -> dict:
    nums = pick_numbers(info, t)
    used = _candidates(db, t)
    everything = db.exec(select(LedgerAccount).where(LedgerAccount.active == True)).all()  # noqa: E712
    lines = []
    for part in PARTS:
        cents = nums["parts"][part]
        if not cents:
            continue
        cat = _pick(used, part) or _pick(everything, part)
        lines.append({"part": part, "label": LABELS[part], "category_id": cat.id if cat else None, "amount_cents": cents})
    total = sum(ln["amount_cents"] for ln in lines)
    gap = abs(t.amount_cents) - total
    warning = ""
    if gap:
        warning = (f"The statement adds up to ${total / 100:,.2f}, but this payment is ${abs(t.amount_cents) / 100:,.2f}. "
                   "Check that it's the right month's statement.")
    elif not nums["exact"]:
        warning = "This statement's due date is far from this payment's date. Check that it's the right month."
    return {
        "lines": lines,
        "where": nums["where"],
        "statement_date": info.get("statement_date") or "",
        "lender": info.get("lender") or "",
        "warning": warning,
    }


def keep_copy(info: dict, name: str, data: bytes) -> None:
    """Save the statement in data/statements/ (e.g. 'Freedom Mortgage 2371 2026-09-01.pdf')."""
    folder = config.DATA_DIR / "statements"
    folder.mkdir(parents=True, exist_ok=True)
    ext = ".pdf" if data[:4] == b"%PDF" else "." + name.rsplit(".", 1)[-1].lower()[:5]
    label = " ".join(str(x) for x in (info.get("lender"), info.get("loan_number_last4"), info.get("statement_date")) if x)
    label = re.sub(r"[^\w .-]", "", label).strip() or "statement"
    (folder / f"{label}{ext}").write_bytes(data)


async def split_from_statement(db: Session, t: Txn, name: str, data: bytes) -> dict:
    key = get_setting(db, "claude_key")
    if not key:
        raise StatementError("Add your Claude key in Settings first. Savannah uses it to read statements.")
    if len(data) > 20 * 1024 * 1024:
        raise StatementError("That file is too big. Statements are usually under 1 MB.")
    info = await read_statement(key, name, data)
    result = fill_split(db, t, info)
    try:
        keep_copy(info, name, data)
    except OSError:
        pass
    return result
