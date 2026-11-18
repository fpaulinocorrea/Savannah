"""Bookkeeping tables: your chart of accounts, bank connections, transactions and rules.

Money convention: amount_cents is positive when money comes IN to the bank/card account,
negative when money goes OUT (a purchase on the card is negative, paying the card is positive).
"""

import datetime as dt
from datetime import datetime

from sqlmodel import Field, Session, SQLModel, select

from .db import utcnow


class LedgerAccount(SQLModel, table=True):
    """One line in your chart of accounts (a category, or a bank/card account)."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)  # full name, e.g. "Utilities:Internet"
    type: str = "Expense"  # QuickBooks account type
    detail_type: str = ""
    description: str = ""
    number: str = ""
    active: bool = True
    source: str = "starter"  # starter | quickbooks | you | bank


class BankLink(SQLModel, table=True):
    """A bank login connected through Plaid (e.g. Chase)."""

    item_id: str = Field(primary_key=True)
    access_token: str
    institution: str = ""
    cursor: str = ""
    last_sync_at: datetime | None = None
    error: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class BankAccount(SQLModel, table=True):
    """A checking account or card inside a BankLink."""

    id: str = Field(primary_key=True)  # Plaid account_id
    item_id: str = Field(index=True)
    name: str = ""
    mask: str = ""
    type: str = ""  # depository | credit
    subtype: str = ""  # checking | credit card | ...
    ledger_account_id: int | None = None
    balance_cents: int | None = None
    balance_at: datetime | None = None
    ignored: bool = False  # personal account: kept out of the books
    full_history: bool = False  # not in QuickBooks: Chase history counts even before the start date


class Txn(SQLModel, table=True):
    """One money movement in a bank or card account."""

    id: int | None = Field(default=None, primary_key=True)
    external_id: str = Field(index=True, unique=True)  # plaid:<id> or qb:<hash>
    source: str = "plaid"  # plaid | quickbooks | you
    date: dt.date = Field(index=True)
    description: str = ""
    merchant: str = ""
    amount_cents: int = 0
    account_id: int | None = Field(default=None, index=True)  # the bank/card LedgerAccount
    category_id: int | None = Field(default=None, index=True)  # where it belongs
    category_source: str = ""  # quickbooks | rule | learned | ai | you
    needs_review: bool = Field(default=False, index=True)
    hidden: bool = False  # before Savannah's start date (QuickBooks history covers it)
    bank_category: str = ""  # Plaid's own guess, used as a hint
    created_at: datetime = Field(default_factory=utcnow)


class TxnSplit(SQLModel, table=True):
    """One part of a split transaction (e.g. a mortgage payment → interest + escrow + principal).
    Same money convention as Txn; the parts add up to the transaction's amount."""

    id: int | None = Field(default=None, primary_key=True)
    txn_id: int = Field(index=True)
    category_id: int | None = None
    amount_cents: int = 0
    memo: str = ""


class Rule(SQLModel, table=True):
    """'Whenever the description contains X, use category Y' (or split it the same way as last time)."""

    id: int | None = Field(default=None, primary_key=True)
    match: str  # lower-case text to look for
    direction: str = "any"  # any | in | out
    category_id: int  # for a split rule: the biggest part
    times_used: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    split_json: str = ""  # [{"category_id": 5, "share": 0.62}, …] when the rule splits
    mode: str = "auto"  # auto = file it by itself · suggest = fill in the category, wait in "To review" for your OK


# ---------- account types ----------

def _t(account_type: str) -> str:
    return " ".join((account_type or "").strip().lower().replace("_", " ").split())


def kind(account_type: str) -> str:
    """Group QuickBooks account types. QuickBooks writes them several ways:
    'Expense', 'Expenses', 'Other Expense', 'Cost of Goods Sold', 'Other Current Assets'…"""
    t = _t(account_type)
    if "income" in t:
        return "income"
    if "expense" in t or "cost of goods" in t:
        return "expense"
    if "equity" in t:
        return "owner"
    return "transfer"  # bank, card, loans, assets: money moving between your own accounts


def is_money_account(account_type: str) -> bool:
    t = _t(account_type)
    return t in ("bank", "banks") or t.startswith("credit card")


def is_card(account_type: str) -> bool:
    return _t(account_type).startswith("credit card")


STARTER_CHART = [
    ("Rental income", "Income"),
    ("Cleaning fee income", "Income"),
    ("Other income", "Other Income"),
    ("Cleaning", "Expense"),
    ("Supplies", "Expense"),
    ("Repairs and maintenance", "Expense"),
    ("Utilities", "Expense"),
    ("Internet and TV", "Expense"),
    ("Platform and booking fees", "Expense"),
    ("Insurance", "Expense"),
    ("Mortgage interest", "Expense"),
    ("Property taxes", "Expense"),
    ("HOA fees", "Expense"),
    ("Furnishings", "Expense"),
    ("Software and subscriptions", "Expense"),
    ("Bank fees", "Expense"),
    ("Advertising", "Expense"),
    ("Travel", "Expense"),
    ("Meals", "Expense"),
    ("Owner draw", "Equity"),
    ("Owner contribution", "Equity"),
]


def add_starter_chart(db: Session) -> int:
    existing = {a.name.lower() for a in db.exec(select(LedgerAccount)).all()}
    added = 0
    for name, typ in STARTER_CHART:
        if name.lower() not in existing:
            db.add(LedgerAccount(name=name, type=typ, source="starter"))
            added += 1
    db.commit()
    return added


def find_or_create(db: Session, name: str, type_if_new: str, source: str = "quickbooks") -> LedgerAccount:
    name = name.strip()
    acct = db.exec(select(LedgerAccount).where(LedgerAccount.name == name)).first()
    if acct:
        return acct
    # QuickBooks sometimes shows only the last part of a sub-account ("Internet" for "Utilities:Internet").
    for a in db.exec(select(LedgerAccount)).all():
        if a.name.split(":")[-1].strip().lower() == name.lower():
            return a
    acct = LedgerAccount(name=name, type=type_if_new, source=source)
    db.add(acct)
    db.commit()
    db.refresh(acct)
    return acct


def to_cents(value) -> int | None:
    """'$1,234.56', '(12.00)', -5, 3.2 → cents."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return round(float(value) * 100)
    s = str(value).strip().replace("$", "").replace(",", "").replace(" ", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    if s.startswith("-"):
        neg, s = not neg, s[1:]
    try:
        cents = round(float(s) * 100)
    except ValueError:
        return None
    return -cents if neg else cents


def splits_for(db: Session, txn_ids: list[int]) -> dict[int, list[TxnSplit]]:
    """All split parts for these transactions, grouped by transaction."""
    out: dict[int, list[TxnSplit]] = {}
    if not txn_ids:
        return out
    for i in range(0, len(txn_ids), 800):
        for sp in db.exec(select(TxnSplit).where(TxnSplit.txn_id.in_(txn_ids[i : i + 800]))).all():
            out.setdefault(sp.txn_id, []).append(sp)
    return out


def set_splits(db: Session, t: "Txn", lines: list[tuple[int | None, int, str]], source: str = "split") -> None:
    """Replace a transaction's split parts. lines = [(category_id, amount_cents, memo)]."""
    for old in db.exec(select(TxnSplit).where(TxnSplit.txn_id == t.id)).all():
        db.delete(old)
    for cat, cents, memo in lines:
        db.add(TxnSplit(txn_id=t.id, category_id=cat, amount_cents=cents, memo=memo))
    t.category_id = None
    t.category_source = source if lines else ""
    db.add(t)
    db.commit()


def txn_lines(t: "Txn", parts: dict[int, list[TxnSplit]]) -> list[tuple[int | None, int]]:
    """Where a transaction's money went: its split parts, or the whole amount in one category."""
    if t.id in parts:
        return [(sp.category_id, sp.amount_cents) for sp in parts[t.id]]
    return [(t.category_id, t.amount_cents)]
