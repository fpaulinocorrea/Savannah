"""Chase (or any bank) through Plaid.

Flow: Savannah asks Plaid for a "link token" → the Connect button opens Plaid's window →
you sign in to Chase there (Savannah never sees your bank password) → Plaid gives Savannah
a key for reading transactions → Savannah syncs every 6 hours.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timezone

import httpx
from sqlmodel import Session, select

from . import categorize
from .db import engine, get_setting, utcnow
from .ledger import BankAccount, BankLink, LedgerAccount, Txn, is_money_account
from .ledger import is_card as ledger_is_card

log = logging.getLogger("savannah.plaid")

HOSTS = {"production": "https://production.plaid.com", "sandbox": "https://sandbox.plaid.com"}
SYNC_EVERY_HOURS = 6
HISTORY_DAYS = 730  # ask Chase for two years the first time

state = {"syncing": False, "last_sync_at": None, "last_error": "", "last_result": None}
_lock = asyncio.Lock()


class PlaidError(Exception):
    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


FRIENDLY = {
    "INVALID_API_KEYS": "Plaid didn't accept the client ID or secret. Check you copied the Production secret.",
    "INVALID_ACCESS_TOKEN": "This bank connection is no longer valid. Connect the bank again.",
    "ITEM_LOGIN_REQUIRED": "Chase needs you to sign in again. Press Reconnect.",
    "INSTITUTION_DOWN": "Chase isn't answering right now. Savannah will try again later.",
    "INSTITUTION_NOT_RESPONDING": "Chase isn't answering right now. Savannah will try again later.",
    "PRODUCTS_NOT_SUPPORTED": "This account doesn't share transactions through Plaid.",
}


def base_url() -> str:
    return os.environ.get("PLAID_BASE_URL") or HOSTS.get(os.environ.get("PLAID_ENV", "production"), HOSTS["production"])


def keys(db: Session) -> tuple[str | None, str | None]:
    return get_setting(db, "plaid_client_id"), get_setting(db, "plaid_secret")


async def call(client_id: str, secret: str, path: str, body: dict) -> dict:
    payload = {"client_id": client_id, "secret": secret, **body}
    try:
        async with httpx.AsyncClient(base_url=base_url(), timeout=60) as c:
            res = await c.post(path, json=payload)
    except httpx.HTTPError:
        raise PlaidError("Can't reach Plaid. Check this computer's internet connection.")
    data = res.json() if res.content else {}
    if res.status_code >= 400:
        code = data.get("error_code", "")
        msg = FRIENDLY.get(code) or data.get("display_message") or data.get("error_message") or f"Plaid said no ({res.status_code})."
        raise PlaidError(msg, code)
    return data


async def link_token(client_id: str, secret: str, access_token: str | None = None) -> str:
    body = {
        "user": {"client_user_id": "savannah-owner"},
        "client_name": "Savannah",
        "country_codes": ["US"],
        "language": "en",
    }
    if access_token:  # "update mode": sign in to the bank again
        body["access_token"] = access_token
    else:
        body["products"] = ["transactions"]
        body["transactions"] = {"days_requested": HISTORY_DAYS}
    data = await call(client_id, secret, "/link/token/create", body)
    return data["link_token"]


# ---------- connecting ----------


GENERIC_WORDS = {"bank", "card", "credit", "account", "checking", "savings", "business", "rewards", "the", "of",
                 "online", "consumer", "personal", "visa", "mastercard", "amex", "american", "express", "llc", "inc"}


def _words(text: str) -> set[str]:
    import re as _re

    return {w for w in _re.findall(r"[a-z0-9]+", (text or "").lower().replace("'", "")) if w not in GENERIC_WORDS and len(w) > 2}


def _match_ledger(db: Session, acct: dict, institution: str) -> int:
    """Pair a Plaid account with a bank/card account in your chart (or make one).
    Tries: last 4 digits in the name → shared store/bank name ("Home Depot") → the only unpaired one."""
    is_card = acct.get("type") == "credit"
    mask = acct.get("mask") or ""
    already = {b.ledger_account_id for b in db.exec(select(BankAccount)).all()}
    candidates = [
        a for a in db.exec(select(LedgerAccount)).all()
        if is_money_account(a.type) and ledger_is_card(a.type) == is_card and a.active and a.id not in already
    ]
    for a in candidates:
        if mask and mask in a.name:
            return a.id
    plaid_words = _words(" ".join([institution, acct.get("name") or "", acct.get("official_name") or ""]))
    by_name = [a for a in candidates if _words(a.name) & plaid_words]
    if len(by_name) == 1:
        return by_name[0].id
    if len(candidates) == 1:
        return candidates[0].id
    name = f"{institution or 'Bank'} {acct.get('name') or ('Card' if is_card else 'Checking')} ({mask})".strip()
    new = LedgerAccount(name=name, type="Credit Card" if is_card else "Bank", source="bank")
    db.add(new)
    db.commit()
    db.refresh(new)
    return new.id


def _save_accounts(db: Session, item_id: str, accounts: list[dict], institution: str) -> None:
    for a in accounts:
        row = db.get(BankAccount, a["account_id"])
        if not row:
            row = BankAccount(id=a["account_id"], item_id=item_id)
            row.ledger_account_id = _match_ledger(db, a, institution)
        row.name = a.get("name") or a.get("official_name") or ""
        row.mask = a.get("mask") or ""
        row.type, row.subtype = a.get("type") or "", a.get("subtype") or ""
        bal = (a.get("balances") or {}).get("current")
        if bal is not None:
            row.balance_cents, row.balance_at = round(bal * 100), utcnow()
        db.add(row)
    db.commit()


FREE_ITEMS = 10  # Plaid Trial plan: 10 bank logins, ever (removing one doesn't give it back)


def items_used(db: Session) -> int:
    from .db import get_setting

    stored = int(get_setting(db, "plaid_items_used") or 0)
    return max(stored, len(db.exec(select(BankLink)).all()))


def item_limit(db: Session) -> int:
    from .db import get_setting

    return int(get_setting(db, "plaid_item_limit") or FREE_ITEMS)


async def connect(public_token: str, institution: str) -> None:
    from .db import set_setting

    with Session(engine) as db:
        client_id, secret = keys(db)
        data = await call(client_id, secret, "/item/public_token/exchange", {"public_token": public_token})
        item_id, access_token = data["item_id"], data["access_token"]
        if not db.get(BankLink, item_id):
            set_setting(db, "plaid_items_used", str(items_used(db) + 1))
        link = db.get(BankLink, item_id) or BankLink(item_id=item_id, access_token=access_token)
        link.access_token, link.institution, link.error = access_token, institution, ""
        db.add(link)
        db.commit()
        accts = await call(client_id, secret, "/accounts/get", {"access_token": access_token})
        _save_accounts(db, item_id, accts.get("accounts", []), institution)


# ---------- syncing ----------


def _start_date(db: Session) -> date | None:
    s = get_setting(db, "books_start_date")
    return date.fromisoformat(s) if s else None


async def _sync_link(db: Session, link: BankLink, client_id: str, secret: str) -> list[int]:
    added, modified, removed = [], [], []
    cursor = link.cursor
    for attempt in range(3):
        added, modified, removed, c = [], [], [], cursor
        try:
            while True:
                data = await call(client_id, secret, "/transactions/sync", {"access_token": link.access_token, "cursor": c, "count": 500})
                added += data.get("added", [])
                modified += data.get("modified", [])
                removed += data.get("removed", [])
                c = data.get("next_cursor", c)
                if data.get("accounts"):
                    _save_accounts(db, link.item_id, data["accounts"], link.institution)
                if not data.get("has_more"):
                    break
            break
        except PlaidError as e:
            if e.code == "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" and attempt < 2:
                continue  # start over from the saved cursor
            raise

    accounts = {b.id: b for b in db.exec(select(BankAccount).where(BankAccount.item_id == link.item_id)).all()}
    start = _start_date(db)
    new_ids = []
    for t in added + modified:
        if t.get("pending"):
            continue  # only real, posted transactions go in the books
        ext = f"plaid:{t['transaction_id']}"
        acct = accounts.get(t.get("account_id"))
        d = date.fromisoformat(t["date"])
        row = db.exec(select(Txn).where(Txn.external_id == ext)).first()
        is_new = row is None
        row = row or Txn(external_id=ext, source="plaid", date=d)
        row.date = d
        row.description = t.get("name") or t.get("original_description") or ""
        row.merchant = t.get("merchant_name") or ""
        row.amount_cents = -round(float(t["amount"]) * 100)  # Plaid: positive = money out
        row.account_id = acct.ledger_account_id if acct else None
        pfc = t.get("personal_finance_category") or {}
        row.bank_category = (pfc.get("detailed") or pfc.get("primary") or "").replace("_", " ").lower()
        row.hidden = bool(acct and acct.ignored) or bool(start and d < start and not (acct and acct.full_history))
        db.add(row)
        db.commit()
        db.refresh(row)
        if is_new and not row.hidden:
            new_ids.append(row.id)
    for r in removed:
        row = db.exec(select(Txn).where(Txn.external_id == f"plaid:{r['transaction_id']}")).first()
        if row:
            db.delete(row)
    link.cursor, link.last_sync_at, link.error = c, utcnow(), ""
    db.add(link)
    db.commit()
    return new_ids


async def sync_all() -> dict | None:
    if _lock.locked():
        return None
    async with _lock:
        state["syncing"] = True
        result = {"new": 0, "rule": 0, "learned": 0, "ai": 0, "unsure": 0}
        try:
            with Session(engine) as db:
                client_id, secret = keys(db)
                if not (client_id and secret):
                    return None
                errors = []
                for link in db.exec(select(BankLink)).all():
                    try:
                        ids = await _sync_link(db, link, client_id, secret)
                        result["new"] += len(ids)
                        if ids:
                            for k, v in (await categorize.categorize(db, ids)).items():
                                result[k] += v
                    except PlaidError as e:
                        link.error = str(e)
                        db.add(link)
                        db.commit()
                        errors.append(str(e))
                state["last_error"] = errors[0] if errors else ""
                state["last_result"] = result
            return result
        except Exception as e:
            log.exception("sync failed")
            state["last_error"] = f"Bank sync failed ({type(e).__name__}). Savannah will try again."
            return None
        finally:
            state["syncing"] = False
            state["last_sync_at"] = datetime.now(timezone.utc).isoformat()


async def watcher() -> None:
    await asyncio.sleep(20)
    while True:
        try:
            await sync_all()
        except Exception:
            log.exception("bank watcher")
        await asyncio.sleep(SYNC_EVERY_HOURS * 3600)
