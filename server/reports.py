"""Report math: Profit & Loss, Cash flow, and income still to come from bookings.

Money convention (see ledger.py): amount_cents > 0 = money in to the bank/card, < 0 = money out.
Only transactions that are part of Savannah's books count (QuickBooks history + Chase after the start date).
"""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Field, Session, SQLModel, select

from . import config
from .db import utcnow
from .ledger import LedgerAccount, Txn, is_card, is_money_account, kind, splits_for, txn_lines


class ReportView(SQLModel, table=True):
    """A saved report layout ("P&L by month with % of income", …)."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    report: str  # pl | cashflow | upcoming
    config: str = "{}"  # JSON chosen on the screen
    created_at: datetime = Field(default_factory=utcnow)


# ---------- periods ----------


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def periods(start: date, end: date, breakdown: str) -> list[tuple[str, date, date]]:
    """Split [start, end] (both inclusive) into labelled columns."""
    if breakdown not in ("month", "quarter", "year"):
        return []
    out = []
    step = {"month": 1, "quarter": 3, "year": 12}[breakdown]
    if breakdown == "month":
        cur = _month_start(start)
    elif breakdown == "quarter":
        cur = date(start.year, 3 * ((start.month - 1) // 3) + 1, 1)
    else:
        cur = date(start.year, 1, 1)
    while cur <= end and len(out) < 60:
        nxt = _add_months(cur, step)
        p_start, p_end = max(cur, start), min(nxt - timedelta(days=1), end)
        if breakdown == "month":
            label = cur.strftime("%b %Y")
        elif breakdown == "quarter":
            label = f"Q{(cur.month - 1) // 3 + 1} {cur.year}"
        else:
            label = str(cur.year)
        out.append((label, p_start, p_end))
        cur = nxt
    return out


def previous_range(start: date, end: date, compare: str) -> tuple[date, date] | None:
    if compare == "prev_year":
        try:
            return start.replace(year=start.year - 1), end.replace(year=end.year - 1)
        except ValueError:  # 29 Feb
            return start - timedelta(days=365), end - timedelta(days=365)
    if compare == "prev_period":
        length = (end - start).days + 1
        return start - timedelta(days=length), start - timedelta(days=1)
    return None


def _txns(db: Session, start: date, end: date) -> list[Txn]:
    return db.exec(
        select(Txn).where(Txn.hidden == False, Txn.date >= start, Txn.date <= end)  # noqa: E712
    ).all()


# ---------- building rows with sub-accounts ----------


def _tree_rows(amounts: dict[int, list[int]], accounts: dict[int, LedgerAccount], width: int) -> list[dict]:
    """Turn {account_id: [cents per column]} into rows, nesting 'Parent:Child' names."""
    nodes: dict[str, dict] = {}

    def node(path: str) -> dict:
        if path not in nodes:
            nodes[path] = {"path": path, "own": [0] * width, "children": set(), "account_id": None}
        return nodes[path]

    for acct_id, vals in amounts.items():
        name = accounts[acct_id].name if acct_id in accounts else "Unknown"
        parts = [p.strip() for p in name.split(":")]
        for i in range(1, len(parts)):
            node(":".join(parts[:i]))["children"].add(":".join(parts[: i + 1]))
        n = node(":".join(parts))
        n["account_id"] = acct_id
        n["own"] = [a + b for a, b in zip(n["own"], vals)]

    def total(path: str) -> list[int]:
        n = nodes[path]
        t = list(n["own"])
        for c in n["children"]:
            t = [a + b for a, b in zip(t, total(c))]
        return t

    rows: list[dict] = []

    def walk(path: str, depth: int):
        n = nodes[path]
        vals = total(path)
        if not any(vals):
            return
        kids = sorted(n["children"], key=lambda c: c.lower())
        has_kids = any(any(total(c)) for c in kids)
        rows.append({"path": path, "name": path.split(":")[-1], "depth": depth, "values": vals, "parent": has_kids})
        if has_kids:
            if any(n["own"]):
                rows.append({"path": path + ":·", "name": f"{path.split(':')[-1]} (other)", "depth": depth + 1, "values": n["own"], "parent": False})
            for c in kids:
                walk(c, depth + 1)

    for top in sorted((p for p in nodes if ":" not in p), key=str.lower):
        walk(top, 0)
    return rows


def _sum_rows(rows: list[dict], width: int) -> list[int]:
    out = [0] * width
    for r in rows:
        if r["depth"] == 0:
            out = [a + b for a, b in zip(out, r["values"])]
    return out


# ---------- Profit & Loss ----------

PL_SECTIONS = [
    ("income", "Income"),
    ("cogs", "Cost of goods sold"),
    ("expense", "Expenses"),
    ("other_income", "Other income"),
    ("other_expense", "Other expenses"),
]


def _pl_section(account_type: str) -> str | None:
    t = (account_type or "").lower()
    k = kind(account_type)
    if k == "income":
        return "other_income" if "other" in t else "income"
    if k == "expense":
        if "cost of goods" in t:
            return "cogs"
        return "other_expense" if "other" in t else "expense"
    return None


def profit_and_loss(db: Session, start: date, end: date, breakdown: str = "", compare: str = "") -> dict:
    accounts = {a.id: a for a in db.exec(select(LedgerAccount)).all()}
    cols = periods(start, end, breakdown)
    ranges = [(s, e) for _, s, e in cols] + [(start, end)]  # breakdown columns, then Total
    prev = previous_range(start, end, compare)
    if prev:
        ranges.append(prev)
    width = len(ranges)

    per_section: dict[str, dict[int, list[int]]] = {k: defaultdict(lambda: [0] * width) for k, _ in PL_SECTIONS}
    unsorted = [0, 0]  # in, out (for the "not sorted yet" note)
    lo = min(r[0] for r in ranges)
    hi = max(r[1] for r in ranges)
    txns = _txns(db, lo, hi)
    parts = splits_for(db, [t.id for t in txns])
    for t in txns:
        for cat_id, cents in txn_lines(t, parts):
            acct = accounts.get(cat_id) if cat_id else None
            if acct is None:
                if start <= t.date <= end and t.account_id is not None:
                    unsorted[0 if cents > 0 else 1] += abs(cents)
                continue
            sec = _pl_section(acct.type)
            if not sec:
                continue
            sign = 1 if sec in ("income", "other_income") else -1
            vals = per_section[sec][acct.id]
            for i, (s, e) in enumerate(ranges):
                if s <= t.date <= e:
                    vals[i] += sign * cents

    sections = []
    totals = {}
    for key, title in PL_SECTIONS:
        rows = _tree_rows(dict(per_section[key]), accounts, width)
        totals[key] = _sum_rows(rows, width)
        if rows:
            sections.append({"key": key, "title": title, "rows": rows, "total": totals[key]})

    def combine(*parts):
        out = [0] * width
        for sign, key in parts:
            out = [a + sign * b for a, b in zip(out, totals[key])]
        return out

    gross = combine((1, "income"), (-1, "cogs"))
    operating = combine((1, "income"), (-1, "cogs"), (-1, "expense"))
    net = combine((1, "income"), (-1, "cogs"), (-1, "expense"), (1, "other_income"), (-1, "other_expense"))
    return {
        "columns": [c[0] for c in cols],
        "ranges": [[a.isoformat(), b.isoformat()] for a, b in ranges],
        "has_prev": bool(prev),
        "prev_label": _range_label(*prev) if prev else "",
        "range_label": _range_label(start, end),
        "sections": sections,
        "lines": {
            "total_income": totals["income"],
            "gross_profit": gross if totals["cogs"] and any(totals["cogs"]) else None,
            "net_operating_income": operating,
            "net_income": net,
        },
        "unsorted": {"in_cents": unsorted[0], "out_cents": unsorted[1]},
    }


def _range_label(s: date, e: date) -> str:
    return f"{s.strftime('%b %-d, %Y')} – {e.strftime('%b %-d, %Y')}"


# ---------- Cash flow (what actually moved through your bank accounts) ----------

CF_SECTIONS = [
    ("operating", "From running the rentals"),
    ("investing", "Buying or selling property and equipment"),
    ("financing", "Owner money and loans"),
    ("between", "Moves between your bank accounts"),
]


def _cf_place(acct: LedgerAccount | None) -> tuple[str, str]:
    """Which section a bank transaction belongs to, and the row name."""
    if acct is None:
        return "operating", "Not sorted yet"
    t = acct.type.lower()
    k = kind(acct.type)
    if k in ("income", "expense"):
        return "operating", acct.name.split(":")[0].strip()
    if is_card(acct.type):
        return "operating", "Credit card payments"
    if is_money_account(acct.type):
        return "between", acct.name
    if "fixed asset" in t or t == "other assets":
        return "investing", acct.name.split(":")[0].strip()
    if k == "owner":
        return "financing", acct.name.split(":")[0].strip()
    if "liabilit" in t or "loan" in t:
        return "financing", acct.name.split(":")[0].strip()
    return "operating", acct.name.split(":")[0].strip()


def cash_flow(db: Session, start: date, end: date, breakdown: str = "") -> dict:
    accounts = {a.id: a for a in db.exec(select(LedgerAccount)).all()}
    banks = {a.id for a in accounts.values() if is_money_account(a.type) and not is_card(a.type)}
    cols = periods(start, end, breakdown)
    ranges = [(s, e) for _, s, e in cols] + [(start, end)]
    width = len(ranges)
    data: dict[str, dict[str, list[int]]] = {k: defaultdict(lambda: [0] * width) for k, _ in CF_SECTIONS}
    txns = [t for t in _txns(db, start, end) if t.account_id in banks]  # card purchases count when the card is paid
    parts = splits_for(db, [t.id for t in txns])
    for t in txns:
        for cat_id, cents in txn_lines(t, parts):
            sec, name = _cf_place(accounts.get(cat_id) if cat_id else None)
            vals = data[sec][name]
            for i, (s, e) in enumerate(ranges):
                if s <= t.date <= e:
                    vals[i] += cents
    sections, net = [], [0] * width
    for key, title in CF_SECTIONS:
        rows = [
            {"path": f"{key}:{n}", "name": n, "depth": 0, "values": v, "parent": False}
            for n, v in sorted(data[key].items(), key=lambda kv: -kv[1][-1])  # money in first
            if any(v)
        ]
        total = [sum(r["values"][i] for r in rows) for i in range(width)]
        net = [a + b for a, b in zip(net, total)]
        if rows:
            sections.append({"key": key, "title": title, "rows": rows, "total": total})
    return {
        "columns": [c[0] for c in cols],
        "ranges": [[a.isoformat(), b.isoformat()] for a, b in ranges],
        "range_label": _range_label(start, end),
        "sections": sections,
        "net_change": net,
        "bank_accounts": sorted(accounts[b].name for b in banks),
    }


# ---------- Coming income (future bookings from Hospitable) ----------

BOOKINGS_FILE = "bookings.json"


def money_from(v) -> int | None:
    """Read an amount from Hospitable: {'amount': 12345, 'formatted': '$123.45'}, '$123.45', or a number."""
    if v is None:
        return None
    if isinstance(v, dict):
        if v.get("formatted"):
            got = money_from(str(v["formatted"]))
            if got is not None:
                return got
        if "amount" in v:
            a = v["amount"]
            if isinstance(a, int):
                return a  # Hospitable amounts are in cents
            try:
                return round(float(a) * 100)
            except (TypeError, ValueError):
                return None
        return None
    if isinstance(v, str):
        s = v.replace("$", "").replace(",", "").strip()
        neg = s.startswith("(") or s.startswith("-")
        s = s.strip("()-")
        try:
            c = round(float(s) * 100)
        except ValueError:
            return None
        return -c if neg else c
    if isinstance(v, (int, float)):
        return round(float(v) * 100) if isinstance(v, float) else int(v)
    return None


def payout_cents(fin: dict | None) -> int | None:
    """What the host receives for a booking."""
    if not isinstance(fin, dict):
        return None
    host = fin.get("host") if isinstance(fin.get("host"), dict) else {}
    for key in ("revenue", "payout", "total_payout", "net", "total"):
        got = money_from(host.get(key))
        if got is not None:
            return got
    for key in ("host_payout", "payout", "revenue", "total"):
        got = money_from(fin.get(key))
        if got is not None:
            return got
    return None


def save_bookings(rows: list[dict], raw_sample: list[dict]) -> None:
    (config.DATA_DIR / BOOKINGS_FILE).write_text(json.dumps({
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "bookings": rows,
        "raw_financials_sample": raw_sample,  # kept so the reader can be checked against real data
    }, indent=1, default=str))


def load_bookings() -> dict | None:
    p = config.DATA_DIR / BOOKINGS_FILE
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except ValueError:
        return None


# ---------- Ledger lines: every transaction as "which account, how much" ----------


def ledger_lines(db: Session, start: date | None, end: date):
    """Yield (txn, account_id, debit_cents, is_money_side) for every line through `end`.
    Debit convention (like QuickBooks balances): what you own goes up with a debit,
    what you owe / owner equity / income go up with a credit (negative here)."""
    stmt = select(Txn).where(Txn.hidden == False, Txn.date <= end)  # noqa: E712
    if start:
        stmt = stmt.where(Txn.date >= start)
    txns = db.exec(stmt).all()
    parts = splits_for(db, [t.id for t in txns])
    for t in txns:
        if t.account_id:
            yield t, t.account_id, t.amount_cents, True
        for cat_id, cents in txn_lines(t, parts):
            if cat_id is not None:
                yield t, cat_id, -cents, False


# ---------- Balance sheet ----------

BS_GROUPS = [
    ("assets", "bank", "Bank accounts"),
    ("assets", "ar", "Money owed to you"),
    ("assets", "current", "Other current assets"),
    ("assets", "fixed", "Property and equipment"),
    ("assets", "other", "Other assets"),
    ("liabilities", "cards", "Credit cards"),
    ("liabilities", "ap", "Bills to pay"),
    ("liabilities", "current", "Other current liabilities"),
    ("liabilities", "long", "Loans and mortgages"),
    ("equity", "equity", "Owner's equity"),
]


def _bs_group(account_type: str) -> tuple[str, str] | None:
    t = " ".join((account_type or "").lower().replace("(", " ").replace(")", " ").split())
    if kind(account_type) in ("income", "expense"):
        return None
    if t.startswith("bank"):
        return "assets", "bank"
    if "receivable" in t:
        return "assets", "ar"
    if "current asset" in t:
        return "assets", "current"
    if "fixed asset" in t:
        return "assets", "fixed"
    if "asset" in t:
        return "assets", "other"
    if t.startswith("credit card"):
        return "liabilities", "cards"
    if "payable" in t:
        return "liabilities", "ap"
    if "current liabilit" in t:
        return "liabilities", "current"
    if "liabilit" in t or "loan" in t:
        return "liabilities", "long"
    if "equity" in t:
        return "equity", "equity"
    return "assets", "other"


def balance_sheet(db: Session, as_of: date, compare: str = "") -> dict:
    accounts = {a.id: a for a in db.exec(select(LedgerAccount)).all()}
    dates = [as_of]
    if compare == "prev_year":
        try:
            dates.append(as_of.replace(year=as_of.year - 1))
        except ValueError:
            dates.append(as_of - timedelta(days=365))
    elif compare == "prev_period":
        dates.append(as_of.replace(day=1) - timedelta(days=1))  # end of the month before
    width = len(dates)
    debit: dict[int, list[int]] = defaultdict(lambda: [0] * width)
    retained = [0] * width
    this_year = [0] * width
    for t, acct_id, d, _ in ledger_lines(db, None, max(dates)):
        a = accounts.get(acct_id)
        if not a:
            continue
        is_pl = kind(a.type) in ("income", "expense")
        for i, when in enumerate(dates):
            if t.date > when:
                continue
            if is_pl:  # profit so far becomes part of equity
                if t.date.year == when.year:
                    this_year[i] -= d
                else:
                    retained[i] -= d
            else:
                debit[acct_id][i] += d

    by_group: dict[tuple[str, str], dict[int, list[int]]] = defaultdict(dict)
    for acct_id, vals in debit.items():
        g = _bs_group(accounts[acct_id].type)
        if not g:
            continue
        sign = 1 if g[0] == "assets" else -1
        by_group[g][acct_id] = [sign * v for v in vals]

    sections = []
    totals = {"assets": [0] * width, "liabilities": [0] * width, "equity": [0] * width}
    for side, key, title in BS_GROUPS:
        rows = _tree_rows(by_group.get((side, key), {}), accounts, width)
        if side == "equity":
            if any(retained):
                rows.append({"path": "__retained", "name": "Profit from earlier years", "depth": 0, "values": retained, "parent": False})
            if any(this_year):
                rows.append({"path": "__net_income", "name": f"Profit this year", "depth": 0, "values": this_year, "parent": False})
        if not rows:
            continue
        total = _sum_rows(rows, width)
        totals[side] = [a + b for a, b in zip(totals[side], total)]
        sections.append({"key": f"{side}:{key}", "side": side, "title": title, "rows": rows, "total": total})
    owe_and_owner = [a + b for a, b in zip(totals["liabilities"], totals["equity"])]
    return {
        "dates": [d.isoformat() for d in dates],
        "columns": [d.strftime("%b %-d, %Y") for d in dates],
        "sections": sections,
        "totals": totals,
        "balanced": all(a == b for a, b in zip(totals["assets"], owe_and_owner)),
        "liabilities_and_equity": owe_and_owner,
    }


# ---------- What's behind a number ----------


def _other_side(t: Txn, accounts: dict, in_row) -> str:
    """Show where the money came from or went: the bank for a category row, the category for a bank row."""
    bank = accounts.get(t.account_id)
    if bank is not None and not in_row(bank):
        return bank.name
    if t.category_source in ("split", "rule-split", "qb-split"):
        return "Split"
    cat = accounts.get(t.category_id) if t.category_id else None
    return cat.name if cat else ("Journal entry" if t.source == "journal" else "No category yet")


def detail(db: Session, report: str, path: str, start: date | None, end: date, section: str = "") -> dict:
    """The transactions behind one row of a report."""
    accounts = {a.id: a for a in db.exec(select(LedgerAccount)).all()}
    own_only = path.endswith(":·")
    base = path[:-2] if own_only else path

    def in_row(a: LedgerAccount | None) -> bool:
        if a is None:
            return False
        if own_only:
            return a.name == base
        return a.name == base or a.name.startswith(base + ":")

    items = []
    if report == "cashflow":
        banks = {a.id for a in accounts.values() if is_money_account(a.type) and not is_card(a.type)}
        sec_key, _, name = path.partition(":")
        stmt = select(Txn).where(Txn.hidden == False, Txn.date >= start, Txn.date <= end)  # noqa: E712
        txns = [t for t in db.exec(stmt).all() if t.account_id in banks]
        parts = splits_for(db, [t.id for t in txns])
        for t in txns:
            for cat_id, cents in txn_lines(t, parts):
                if _cf_place(accounts.get(cat_id) if cat_id else None) == (sec_key, name):
                    items.append((t, cents))
    else:
        for t, acct_id, d, money_side in ledger_lines(db, start, end):
            a = accounts.get(acct_id)
            if not in_row(a):
                continue
            if report == "pl":
                value = -d if kind(a.type) == "income" else d
            else:  # balance sheet: what you own = debit, what you owe/owner = credit
                g = _bs_group(a.type)
                value = d if g and g[0] == "assets" else -d
            items.append((t, value))
    items.sort(key=lambda x: (x[0].date, x[0].id), reverse=True)
    total = sum(v for _, v in items)
    return {
        "count": len(items),
        "total_cents": total,
        "items": [
            {"id": t.id, "date": t.date.isoformat(), "description": t.merchant or t.description,
             "account": _other_side(t, accounts, in_row),
             "source": t.source, "cents": v}
            for t, v in items[:400]
        ],
    }
