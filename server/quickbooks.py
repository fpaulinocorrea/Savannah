"""Reading QuickBooks exports (Excel or CSV).

Two reports are supported:
  • Account List              → your chart of accounts
  • Transaction List by Date  → your history (Transaction Detail by Account / General Ledger also work)

QuickBooks exports have title rows on top, section headers, "Total for …" rows and
amounts like "(1,234.56)". This file deals with all of that.
"""

import csv
import hashlib
import io
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from sqlmodel import Session, select

from .ledger import LedgerAccount, Txn, find_or_create, is_card, is_money_account, kind, to_cents


class ImportProblem(Exception):
    pass


# ---------- reading the file ----------


def read_rows(path: Path) -> list[list]:
    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return rows
    if suffix == ".csv":
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
        return [row for row in csv.reader(io.StringIO(text))]
    if suffix == ".xls":
        raise ImportProblem("This is an old .xls file. In QuickBooks, choose Export → Excel (.xlsx) or CSV instead.")
    raise ImportProblem("Savannah reads Excel (.xlsx) or CSV files.")


def _clean(v) -> str:
    return "" if v is None else str(v).strip()


def _norm(v) -> str:
    return _clean(v).lower().replace("_", " ").rstrip(":")


ACCOUNT_NAMES = {"account", "account name", "name", "full name"}
TYPE_NAMES = {"type", "account type"}
DATE_NAMES = {"date", "transaction date"}
AMOUNT_NAMES = {"amount", "debit", "credit"}


def _find_header(rows: list[list], must: list[set[str]]) -> tuple[int, list[str]]:
    """Find the header row: the first row (in the top 40) containing one name from each set."""
    for i, row in enumerate(rows[:40]):
        names = [_norm(c) for c in row]
        if all(any(n in names for n in group) for group in must):
            return i, names
    raise ImportProblem("Couldn't find the column titles in this file. Is it the right QuickBooks report?")


def _col(names: list[str], *aliases: str) -> int | None:
    for a in aliases:
        if a in names:
            return names.index(a)
    return None


def _as_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _clean(v)
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ---------- Account List ----------


def import_accounts(db: Session, path: Path) -> dict:
    rows = read_rows(path)
    h, names = _find_header(rows, [ACCOUNT_NAMES, TYPE_NAMES])
    c_name = _col(names, "account", "account name", "full name", "name")
    c_type = _col(names, "type", "account type")
    c_detail = _col(names, "detail type", "detail account type")
    c_desc = _col(names, "description")
    c_num = _col(names, "account #", "number", "account number", "acct #")

    existing = {a.name.lower(): a for a in db.exec(select(LedgerAccount)).all()}
    added = updated = 0
    for row in rows[h + 1 :]:
        name = _clean(row[c_name]) if c_name is not None and c_name < len(row) else ""
        typ = _clean(row[c_type]) if c_type is not None and c_type < len(row) else ""
        if not name or not typ or name.lower().startswith("total"):
            continue
        get = lambda c: _clean(row[c]) if c is not None and c < len(row) else ""
        acct = existing.get(name.lower())
        if acct:
            acct.type, acct.detail_type = typ, get(c_detail) or acct.detail_type
            acct.description, acct.number = get(c_desc) or acct.description, get(c_num) or acct.number
            acct.source, acct.active = "quickbooks", True
            updated += 1
        else:
            acct = LedgerAccount(name=name, type=typ, detail_type=get(c_detail), description=get(c_desc), number=get(c_num), source="quickbooks")
            existing[name.lower()] = acct
            added += 1
        db.add(acct)
    db.commit()
    if added + updated == 0:
        raise ImportProblem("No accounts found in this file. Is it the Account List report?")
    return {"added": added, "updated": updated}


# ---------- Transaction history ----------


def parse_transactions(db: Session, path: Path, flip: bool = False) -> dict:
    """Read the history file without saving. Returns rows ready to save plus a summary to preview."""
    rows = read_rows(path)
    h, names = _find_header(rows, [DATE_NAMES, AMOUNT_NAMES])
    c = {
        "date": _col(names, "date", "transaction date"),
        "type": _col(names, "transaction type", "type"),
        "num": _col(names, "num", "no.", "ref no.", "number"),
        "name": _col(names, "name", "payee", "vendor", "customer"),
        "memo": _col(names, "memo/description", "memo", "description"),
        "account": _col(names, "account", "account name", "account full name"),
        "split": _col(names, "split", "split account", "category"),
        "amount": _col(names, "amount"),
        "debit": _col(names, "debit"),
        "credit": _col(names, "credit"),
    }
    chart = {a.name.lower(): a for a in db.exec(select(LedgerAccount)).all()}
    if not any(is_money_account(a.type) for a in chart.values()):
        raise ImportProblem("Import your Account List first, so Savannah knows which accounts are Chase.")

    def lookup(name: str) -> LedgerAccount | None:
        n = name.strip().lower()
        if n in chart:
            return chart[n]
        for a in chart.values():  # match the last part of "Parent:Child"
            if a.name.split(":")[-1].strip().lower() == n:
                return a
        return None

    def cell(row, key):
        i = c[key]
        return row[i] if i is not None and i < len(row) else None

    section = ""
    out, skipped, seen = [], Counter(), Counter()
    for row in rows[h + 1 :]:
        cells = [_clean(x) for x in row]
        if not any(cells):
            continue
        d = _as_date(cell(row, "date"))
        if not d:
            first = next((x for x in cells if x), "")
            if first and not first.lower().startswith("total") and sum(1 for x in cells if x) == 1:
                section = first  # a section header like "Chase Checking (1234)"
            continue
        if c["amount"] is not None:
            amt = to_cents(cell(row, "amount"))
        else:
            deb, cred = to_cents(cell(row, "debit")) or 0, to_cents(cell(row, "credit")) or 0
            amt = deb - cred
        if amt is None or amt == 0:
            skipped["no amount"] += 1
            continue

        acct_name = _clean(cell(row, "account")) or section.split("(")[0].strip()
        split_name = _clean(cell(row, "split"))
        acct, split = lookup(acct_name), lookup(split_name) if split_name else None

        # Which side is Chase (the money account) and which side is the category?
        if acct and is_money_account(acct.type):
            money, category_name, sign = acct, split_name, 1
        elif split and is_money_account(split.type):
            money, category_name, sign = split, acct_name, -1
        else:
            skipped["not a bank or card transaction"] += 1
            continue

        # QuickBooks shows card charges as increases (positive). Savannah counts them as money out.
        direction = -1 if is_card(money.type) else 1
        cents = amt * sign * direction * (-1 if flip else 1)

        desc = " ".join(x for x in [_clean(cell(row, "name")), _clean(cell(row, "memo"))] if x) or _clean(cell(row, "type")) or "QuickBooks entry"
        key = f"{d}|{cents}|{desc}|{money.name}|{_clean(cell(row, 'num'))}"
        seen[key] += 1
        ext = "qb:" + hashlib.sha1(f"{key}|{seen[key]}".encode()).hexdigest()[:20]
        out.append({
            "external_id": ext, "date": d, "description": desc[:300], "amount_cents": cents,
            "merchant": _clean(cell(row, "name"))[:120],
            "account": money.name, "category": "" if category_name in ("", "-Split-") else category_name,
            "type": _clean(cell(row, "type")),
        })

    if not out:
        reasons = ", ".join(f"{n} {r}" for r, n in skipped.items()) or "no rows with a date"
        raise ImportProblem(f"No bank or card transactions found ({reasons}). Is it the Transaction List by Date report?")

    money_in = sum(t["amount_cents"] for t in out if t["amount_cents"] > 0)
    money_out = -sum(t["amount_cents"] for t in out if t["amount_cents"] < 0)
    by_account = Counter(t["account"] for t in out)
    samples = sorted(out, key=lambda t: t["date"], reverse=True)[:6]
    return {
        "rows": out,
        "summary": {
            "count": len(out),
            "first": min(t["date"] for t in out).isoformat(),
            "last": max(t["date"] for t in out).isoformat(),
            "money_in_cents": money_in,
            "money_out_cents": money_out,
            "accounts": [{"name": n, "count": k} for n, k in by_account.most_common()],
            "skipped": sum(skipped.values()),
            "skipped_reasons": dict(skipped),
            "samples": [{**s, "date": s["date"].isoformat()} for s in samples],
        },
    }


def save_transactions(db: Session, parsed: list[dict]) -> dict:
    existing = set(db.exec(select(Txn.external_id).where(Txn.source == "quickbooks")).all())
    chart = {a.name.lower(): a for a in db.exec(select(LedgerAccount)).all()}
    added = 0
    for t in parsed:
        if t["external_id"] in existing:
            continue
        money = chart[t["account"].lower()]
        cat_id = None
        if t["category"]:
            cat = chart.get(t["category"].lower()) or find_or_create(db, t["category"], "Income" if t["amount_cents"] > 0 else "Expense")
            chart[cat.name.lower()] = cat
            cat_id = cat.id
        db.add(Txn(
            external_id=t["external_id"], source="quickbooks", date=t["date"], description=t["description"],
            merchant=t.get("merchant", ""),
            amount_cents=t["amount_cents"], account_id=money.id, category_id=cat_id,
            category_source="quickbooks" if cat_id else "", needs_review=False,
        ))
        added += 1
    db.commit()
    return {"added": added, "already_there": len(parsed) - added}


def guess_kind(path: Path) -> str:
    """Peek at a file to label it in the screen: 'accounts', 'transactions' or ''."""
    try:
        rows = read_rows(path)[:40]
    except Exception:
        return ""
    for row in rows:
        names = set(_norm(c) for c in row)
        if names & DATE_NAMES and {"debit", "credit"} <= names and "split" not in names and "amount" not in names:
            return "journal"
        if names & DATE_NAMES and names & AMOUNT_NAMES:
            return "transactions"
        if names & ACCOUNT_NAMES and names & TYPE_NAMES:
            return "accounts"
    return ""


__all__ = ["ImportProblem", "import_accounts", "parse_transactions", "save_transactions", "guess_kind", "kind"]


# ---------- Journal report (fills in "-Split-" payments and journal entries) ----------


def parse_journal(db: Session, path: Path) -> dict:
    """Read the QuickBooks Journal report.

    Each QuickBooks transaction is a block of lines (account + debit or credit). We use two kinds:
      • a block with ONE bank/card line that matches a "-Split-" payment already imported
        → its other lines become the split parts (e.g. mortgage interest, escrow, principal)
      • a block with NO bank/card line that touches income or expenses (journal entries, invoices)
        → added as a journal entry so the P&L matches QuickBooks
    Everything else is already in Savannah from the Transaction List."""
    from .ledger import kind

    rows = read_rows(path)
    h, names = _find_header(rows, [DATE_NAMES, {"debit"}, {"credit"}])
    c = {
        "date": _col(names, "date", "transaction date"),
        "type": _col(names, "transaction type", "type"),
        "num": _col(names, "num", "no.", "ref no."),
        "name": _col(names, "name", "payee", "vendor", "customer"),
        "memo": _col(names, "memo/description", "memo", "description"),
        "account": _col(names, "account", "account name", "account full name", "full name"),
        "debit": _col(names, "debit"),
        "credit": _col(names, "credit"),
    }
    if c["account"] is None:
        raise ImportProblem("This file has no Account column. Is it the Journal report?")
    chart = {a.name.lower(): a for a in db.exec(select(LedgerAccount)).all()}

    def lookup(name: str) -> LedgerAccount | None:
        n = name.strip().lower()
        if n in chart:
            return chart[n]
        for a in chart.values():
            if a.name.split(":")[-1].strip().lower() == n:
                return a
        return None

    def cell(row, key):
        i = c[key]
        return row[i] if i is not None and i < len(row) else None

    # 1) cut the file into blocks: QuickBooks ends each one with a "Total for …" row.
    #    (Files without those rows are cut whenever the debits and credits balance.)
    has_totals = any(_clean(r[0]).lower().startswith("total for") for r in rows[h + 1 :] if r)
    blocks, cur = [], None
    for row in rows[h + 1 :]:
        acct_name = _clean(cell(row, "account"))
        d = _as_date(cell(row, "date"))
        deb, cred = to_cents(cell(row, "debit")) or 0, to_cents(cell(row, "credit")) or 0
        first = next((_clean(x) for x in row if _clean(x)), "")
        if not acct_name:
            if cur and cur["lines"]:  # a total row closes the block
                blocks.append(cur)
                cur = None
            continue
        if first.lower().startswith("total"):
            continue
        balanced = cur is not None and cur["lines"] and sum(l[1] for l in cur["lines"]) == sum(l[2] for l in cur["lines"])
        if d and (cur is None or (not has_totals and (balanced or d != cur["date"]))):
            if cur and cur["lines"]:
                blocks.append(cur)
            cur = {"date": d, "type": _clean(cell(row, "type")), "num": _clean(cell(row, "num")),
                   "name": _clean(cell(row, "name")), "memo": _clean(cell(row, "memo")), "lines": []}
        if cur is None:
            continue
        cur["lines"].append((acct_name, deb, cred, _clean(cell(row, "memo"))))
        if not cur["name"]:
            cur["name"] = _clean(cell(row, "name"))
    if cur and cur["lines"]:
        blocks.append(cur)
    if not blocks:
        raise ImportProblem("No journal lines found. Is it the Journal report?")

    # 2) the "-Split-" payments waiting for their parts, and everything already in Savannah
    waiting = {}
    for t in db.exec(select(Txn).where(Txn.source == "quickbooks", Txn.category_id.is_(None), Txn.category_source == "")).all():
        waiting.setdefault((t.date, t.account_id, t.amount_cents), []).append(t)
    present: dict[tuple, int] = {}
    for t in db.exec(select(Txn).where(Txn.source == "quickbooks")).all():
        k = (t.date, t.account_id, t.amount_cents)
        present[k] = present.get(k, 0) + 1

    fills, entries, unknown = [], [], set()
    pl_effect: dict[str, int] = {}
    existing_journal = set(db.exec(select(Txn.external_id).where(Txn.source == "journal")).all())
    seen = {}
    for b in blocks:
        resolved = []
        for acct_name, deb, cred, memo in b["lines"]:
            a = lookup(acct_name)
            if a is None:
                unknown.add(acct_name)
            resolved.append((a, deb, cred, memo))
        money = [r for r in resolved if r[0] is not None and is_money_account(r[0].type)]
        others = [r for r in resolved if r[0] is not None and not is_money_account(r[0].type)]
        touches_pl = any(kind(r[0].type) in ("income", "expense") for r in others)

        if len(money) == 1 and others:
            m = money[0]
            amount = m[1] - m[2]
            matches = waiting.get((b["date"], m[0].id, amount))
            if matches:
                t = matches.pop(0)
                parts = [(r[0].id, -(r[1] - r[2]), r[3]) for r in others]
                if sum(p[1] for p in parts) == t.amount_cents:
                    k = (b["date"], m[0].id, amount)
                    present[k] = present.get(k, 0) - 1
                    fills.append({"txn_id": t.id, "parts": parts, "date": b["date"], "name": b["name"] or t.description})
                    for r in others:
                        if kind(r[0].type) in ("income", "expense"):
                            pl_effect[r[0].name] = pl_effect.get(r[0].name, 0) + (r[1] - r[2]) * (1 if kind(r[0].type) == "expense" else -1)
                    continue

        if money:
            # Already in Savannah from the Transaction List? (same date, same bank/card, same amount)
            found = None
            for m in money:
                k = (b["date"], m[0].id, m[1] - m[2])
                if present.get(k, 0) > 0:
                    found = k
                    break
            if found:
                present[found] -= 1
                continue
            # Not there (e.g. QuickBooks journal entries that touch a bank account): add it.
            if any(r[0] is None for r in resolved) and len(money) + len(others) < 2:
                continue
            m = money[0]
            rest = money[1:] + others
            key = f"{b['date']}|{b['type']}|{b['num']}|{m[0].name}:{m[1]}:{m[2]}|" + "|".join(f"{r[0].name}:{r[1]}:{r[2]}" for r in rest)
            seen[key] = seen.get(key, 0) + 1
            ext = "jr:" + hashlib.sha1(f"{key}|{seen[key]}".encode()).hexdigest()[:20]
            if ext in existing_journal:
                continue
            entries.append({
                "external_id": ext, "date": b["date"], "account_id": m[0].id, "amount_cents": m[1] - m[2],
                "description": " ".join(x for x in [b["type"], b["num"] and f"#{b['num']}", b["name"], b["memo"]] if x)[:300] or "Journal entry",
                "parts": [(r[0].id, -(r[1] - r[2]), r[3]) for r in rest],
            })
            for r in rest:
                if kind(r[0].type) in ("income", "expense"):
                    pl_effect[r[0].name] = pl_effect.get(r[0].name, 0) + (r[1] - r[2]) * (1 if kind(r[0].type) == "expense" else -1)
            continue

        if not money and others:
            key = f"{b['date']}|{b['type']}|{b['num']}|" + "|".join(f"{r[0].name}:{r[1]}:{r[2]}" for r in others)
            seen[key] = seen.get(key, 0) + 1
            ext = "jr:" + hashlib.sha1(f"{key}|{seen[key]}".encode()).hexdigest()[:20]
            if ext in existing_journal:
                continue
            entries.append({
                "external_id": ext, "date": b["date"],
                "description": " ".join(x for x in [b["type"], b["num"] and f"#{b['num']}", b["name"], b["memo"]] if x)[:300] or "Journal entry",
                "parts": [(r[0].id, -(r[1] - r[2]), r[3]) for r in others],
            })
            for r in others:
                if kind(r[0].type) in ("income", "expense"):
                    pl_effect[r[0].name] = pl_effect.get(r[0].name, 0) + (r[1] - r[2]) * (1 if kind(r[0].type) == "expense" else -1)

    still_waiting = sum(len(v) for v in waiting.values())
    top = sorted(pl_effect.items(), key=lambda kv: -abs(kv[1]))[:8]
    return {
        "fills": fills,
        "entries": entries,
        "summary": {
            "blocks": len(blocks),
            "splits_filled": len(fills),
            "splits_still_missing": still_waiting,
            "journal_entries": len(entries),
            "unknown_accounts": sorted(unknown)[:10],
            "pl_effect": [{"name": n, "cents": abs(v), "label": _effect_label(n, v, chart)} for n, v in top],
            "samples": [
                {"date": f["date"].isoformat(), "name": f["name"],
                 "parts": [{"category": next((a.name for a in chart.values() if a.id == p[0]), "?"), "cents": p[1]} for p in f["parts"]]}
                for f in fills[:3]
            ],
        },
    }


def save_journal(db: Session, parsed: dict) -> dict:
    from .ledger import set_splits

    filled = 0
    for f in parsed["fills"]:
        t = db.get(Txn, f["txn_id"])
        if t and t.category_id is None:
            set_splits(db, t, f["parts"], source="qb-split")
            filled += 1
    added = 0
    for e in parsed["entries"]:
        t = Txn(external_id=e["external_id"], source="journal", date=e["date"], description=e["description"],
                amount_cents=e.get("amount_cents", 0), account_id=e.get("account_id"), needs_review=False)
        db.add(t)
        db.commit()
        db.refresh(t)
        set_splits(db, t, e["parts"], source="qb-split")
        added += 1
    return {"splits_filled": filled, "journal_entries": added}


def _effect_label(name: str, v: int, chart: dict) -> str:
    """v > 0 means more expense or less income (it lowers profit)."""
    from .ledger import kind

    a = chart.get(name.lower())
    is_income = a is not None and kind(a.type) == "income"
    if is_income:
        return "less income" if v > 0 else "more income"
    return "more expense" if v > 0 else "less expense"
