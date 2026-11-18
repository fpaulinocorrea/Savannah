"""Cash forecast: where your checking balance is heading over the next 13 weeks.

Four kinds of future money movements, each one a layer you can switch off on the screen:
  income    payouts from confirmed Hospitable bookings (the day after check-in)
  card      credit card bills: the bank's own next bill (statement balance or minimum, your pick per card)
            on its due date; later months and cards without bank data use the average of the last 3 payments
  fixed     loan payments such as the mortgage (latest payment, same day each month)
  cost      cleaning: your price per checkout for each house, on the checkout day
            everything else paid straight from checking, per category, your pick:
            same weeks last year (default) · last 3 months · leave out.
            A category that is new since last year uses the last 13 weeks.

Only money that moves through checking counts. Card purchases show up when the card is paid,
so a category that is now paid by card (e.g. water) is left out of 'cost' to avoid counting it twice.
Owner money, transfers and equipment purchases are left out: they don't follow a pattern.
"""

from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from sqlmodel import Session, select

from .ledger import BankAccount, LedgerAccount, Txn, is_card, is_money_account, kind, splits_for, txn_lines

CARD_MODES = ("statement", "minimum", "average")
CATEGORY_MODES = ("last_year", "recent", "off")
CHOICES_KEY = "forecast_choices"  # {"cards": {bank_account_id: mode}, "categories": {category_id: mode}, "cleaning": {property: cents}}


def load_choices(db: Session) -> dict:
    import json

    from .db import get_setting

    try:
        c = json.loads(get_setting(db, CHOICES_KEY) or "{}")
    except ValueError:
        c = {}
    return {"cards": c.get("cards") or {}, "categories": c.get("categories") or {}, "cleaning": c.get("cleaning") or {}}


def save_choices(db: Session, patch: dict) -> dict:
    import json

    from .db import set_setting

    c = load_choices(db)
    for k, v in (patch.get("cards") or {}).items():
        if v in CARD_MODES:
            c["cards"][k] = v
    for k, v in (patch.get("categories") or {}).items():
        if v in CATEGORY_MODES:
            c["categories"][str(k)] = v
    for k, v in (patch.get("cleaning") or {}).items():
        if v is None or v == "":
            c["cleaning"].pop(k, None)
        elif isinstance(v, int) and 0 <= v <= 10_000_00:
            c["cleaning"][k] = v
    set_setting(db, CHOICES_KEY, json.dumps(c))
    return c


def is_cleaning(a: LedgerAccount) -> bool:
    return "cleaning" in a.name.split(":")[-1].lower()

WEEKS = 13
HISTORY_DAYS = 28
RECENT_DAYS = 91  # "the last 3 months"


def _year_back(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year - 1, day=28)


def _year_ahead(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        return d.replace(year=d.year + 1, day=28)


def _month_day(y: int, m: int, day: int) -> date:
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return date(y, m, min(day, (nxt - timedelta(days=1)).day))


def _monthly(day: int, after: date, end: date) -> list[date]:
    """Every <day> of the month in (after, end]."""
    out, y, m = [], after.year, after.month
    while True:
        d = _month_day(y, m, day)
        if d > end:
            return out
        if d > after:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _is_loan(a: LedgerAccount | None) -> bool:
    if a is None:
        return False
    t = a.type.lower()
    return ("liabilit" in t or "loan" in t) and not is_card(a.type) and "current" not in t


def _short(name: str) -> str:
    return name.replace(":", ": ")


def build(db: Session, today: date, bookings: list[dict], weeks: int = WEEKS, bills: dict | None = None, choices: dict | None = None) -> dict:
    bills = bills or {}
    choices = choices or {"cards": {}, "categories": {}, "cleaning": {}}
    end = today + timedelta(days=7 * weeks)
    accounts = {a.id: a for a in db.exec(select(LedgerAccount)).all()}
    bank_accts = db.exec(select(BankAccount)).all()

    # Checking accounts with a live balance from Chase: the line starts here.
    checking = [b for b in bank_accts if b.type != "credit" and not b.ignored and b.ledger_account_id and b.balance_cents is not None]
    checking_ids = {b.ledger_account_id for b in checking}
    start_cents = sum(b.balance_cents or 0 for b in checking)
    as_of = max((b.balance_at for b in checking if b.balance_at), default=None)
    # Every bank account in the books (old closed ones too), for last year's history.
    all_banks = {a.id for a in accounts.values() if is_money_account(a.type) and not is_card(a.type)}

    lo = _year_back(today) - timedelta(days=7)
    txns = db.exec(select(Txn).where(Txn.hidden == False, Txn.date >= min(lo, today - timedelta(days=400)))).all()  # noqa: E712
    parts = splits_for(db, [t.id for t in txns])
    bank_txns = [t for t in txns if t.account_id in all_banks]

    events: list[dict] = []

    # ---- actual balance, last 4 weeks (worked backwards from today's Chase balance) ----
    history = []
    if checking_ids:
        later = defaultdict(int)
        for t in txns:
            if t.account_id in checking_ids and t.date > today - timedelta(days=HISTORY_DAYS):
                later[t.date] += t.amount_cents
        bal = start_cents
        for i in range(0, HISTORY_DAYS + 1):
            d = today - timedelta(days=i)
            history.append({"date": d.isoformat(), "cents": bal})
            bal -= later.get(d, 0)
        history.reverse()

    # ---- 1. payouts from bookings ----
    paid_in = 0
    counted = 0
    for b in bookings:
        if not b.get("arrival") or b.get("payout_cents") in (None, 0):
            continue
        arrival = date.fromisoformat(b["arrival"][:10])
        pay = arrival + timedelta(days=1)
        if arrival < today or pay > end:
            continue
        counted += 1
        paid_in += b["payout_cents"]
        events.append({"date": pay.isoformat(), "kind": "income", "label": f"{b.get('guest_name') or 'Guest'} · {b.get('property_name') or ''}".strip(" ·"), "cents": b["payout_cents"]})

    # ---- 2. credit card bills ----
    recent_from = today - timedelta(days=100)
    cards_out = []
    for card in [b for b in bank_accts if b.type == "credit" and not b.ignored and b.ledger_account_id]:
        pays = []
        for t in bank_txns:
            if t.date < recent_from or t.amount_cents >= 0:
                continue
            for cat, cents in txn_lines(t, parts):
                if cat == card.ledger_account_id and cents < 0:
                    pays.append((t.date, -cents))
        pays.sort()
        last3 = pays[-3:]
        name = f"{card.name} ({card.mask})" if card.mask else card.name
        mode = choices["cards"].get(card.id, "statement")
        bill = (bills.get("cards") or {}).get(card.id)
        item = (bills.get("items") or {}).get(card.item_id) or {}
        avg = round(sum(c for _, c in last3) / len(last3)) if last3 else None
        avg_day = int(median(d.day for d, _ in last3)) if last3 else None
        info = {"id": card.id, "item_id": card.item_id, "name": name, "balance_cents": card.balance_cents, "mode": mode,
                "average_cents": avg, "day": avg_day, "bill": bill,
                "bill_problem": None if item.get("ok", True) else {"kind": item.get("kind"), "message": item.get("message")},
                "last_payments": [{"date": d.isoformat(), "cents": c} for d, c in last3], "schedule": []}

        def add(d: date, cents: int, why: str):
            events.append({"date": d.isoformat(), "kind": "card", "label": f"{name} · {why}", "cents": -cents})
            info["schedule"].append({"date": d.isoformat(), "cents": cents, "why": why})

        due = date.fromisoformat(bill["due_date"]) if bill and bill.get("due_date") else None
        first = None
        if mode != "average" and due:
            amount = bill.get("statement_cents") if mode == "statement" else bill.get("minimum_cents")
            stmt = date.fromisoformat(bill["statement_date"]) if bill.get("statement_date") else due - timedelta(days=25)
            paid = sum(c for d, c in pays if d > stmt)  # already paid toward this bill
            if amount is not None and due > today:
                left = amount - paid
                if left > 0 and due <= end:
                    add(due, left, "statement balance" if mode == "statement" else "minimum payment")
                first = due
            elif due <= today:
                first = due  # this bill's date has passed; following months below
        if first:
            later = bill.get("minimum_cents") if mode == "minimum" else avg
            if later:
                for d in _monthly(first.day, max(first, today), end):
                    add(d, later, "minimum payment" if mode == "minimum" else "average of last 3 payments")
        elif avg:
            for d in _monthly(avg_day, today, end):
                if any(0 <= (d - p).days <= 20 for p, _ in pays):
                    continue  # already paid this cycle
                add(d, avg, "average of last 3 payments")
        cards_out.append(info)

    # ---- 3. loan payments (mortgage) ----
    loan_txn_ids: set[int] = set()
    loans: dict[int, list[Txn]] = defaultdict(list)
    for t in bank_txns:
        loan_cats = {cat for cat, _ in txn_lines(t, parts) if _is_loan(accounts.get(cat))}
        if loan_cats:
            loan_txn_ids.add(t.id)
            if t.date >= recent_from:
                loans[min(loan_cats)].append(t)
    fixed_out = []
    loan_amounts = set()
    for acct_id, ts in loans.items():
        ts.sort(key=lambda t: t.date)
        last = ts[-1]
        amount = -last.amount_cents
        loan_amounts.add(amount)
        name = accounts[acct_id].name
        label = "Mortgage" if "mortgage" in name.lower() else _short(name)
        # Usual day from the last 3 (a weekend can push one by a day or two).
        # A payment that lands at the end of the month (e.g. May 30) is really the next month's 1st.
        days = [1 if t.date.day >= 25 else t.date.day for t in ts[-3:]]
        day = min(int(median(days)), 28)
        fixed_out.append({"label": label, "cents": amount, "day": day})
        # Same-amount payments that aren't split yet (e.g. this month's) count as paid too.
        same = [t.date for t in bank_txns if t.amount_cents == -amount]
        for d in _monthly(day, today, end):
            if any(0 <= (d - p).days <= 20 for p in same + [x.date for x in ts]):
                continue
            events.append({"date": d.isoformat(), "kind": "fixed", "label": label, "cents": -amount})
    for t in bank_txns:  # unsplit copies of a loan payment shouldn't count as a cost
        if -t.amount_cents in loan_amounts:
            loan_txn_ids.add(t.id)

    # ---- 4. other costs, per category ----
    def cost_lines(t: Txn):
        if t.id in loan_txn_ids:
            return []
        out = []
        for cat, cents in txn_lines(t, parts):
            a = accounts.get(cat) if cat else None
            if a is not None and kind(a.type) == "expense":
                out.append((cat, cents))
        return out

    ly_start, ly_end = _year_back(today) + timedelta(days=1), _year_back(end)
    recent_start = today - timedelta(days=RECENT_DAYS)
    card_ids = {a.id for a in accounts.values() if is_card(a.type)}

    last_year = defaultdict(list)  # cat -> [(date, cents)]
    recent_bank = defaultdict(list)
    ever_before = set()  # categories paid from a bank in the year before the recent window
    for t in bank_txns:
        for cat, cents in cost_lines(t):
            if ly_start <= t.date <= ly_end:
                last_year[cat].append((t.date, cents))
            if t.date > recent_start and t.date <= today:
                recent_bank[cat].append((t.date, cents))
            if recent_start - timedelta(days=365) <= t.date <= recent_start:
                ever_before.add(cat)
    on_card_recently = set()
    for t in txns:
        if t.account_id in card_ids and t.date > recent_start:
            for cat, _ in txn_lines(t, parts):
                if cat:
                    on_card_recently.add(cat)

    # Cleaning: your price per checkout for each house, on the checkout day.
    cleaning_out = []
    cleaning_cats = {c for c in set(last_year) | set(recent_bank) if is_cleaning(accounts[c])}
    if choices["cleaning"]:
        per_house: dict[str, dict] = {}
        for b in bookings:
            prop = b.get("property_name") or ""
            dep = b.get("departure")
            if not dep or not b.get("arrival") or b["arrival"][:10] < today.isoformat():
                continue
            d = date.fromisoformat(dep[:10])
            price = choices["cleaning"].get(prop)
            h = per_house.setdefault(prop, {"property": prop, "cents": price, "count": 0, "total_cents": 0})
            if price is None or not (today < d <= end):
                continue
            h["count"] += 1
            h["total_cents"] += price
            events.append({"date": d.isoformat(), "kind": "cost", "label": f"Cleaning · {prop.split('|')[0].strip()}", "cents": -price})
        for prop, price in choices["cleaning"].items():
            per_house.setdefault(prop, {"property": prop, "cents": price, "count": 0, "total_cents": 0})
        cleaning_out = sorted(per_house.values(), key=lambda h: h["property"])

    costs_out, moved = [], []
    for cat in sorted(set(last_year) | set(recent_bank), key=lambda c: accounts[c].name.lower()):
        if cat in cleaning_cats and choices["cleaning"]:
            continue  # counted per checkout above
        name = _short(accounts[cat].name)
        if cat in last_year and cat not in recent_bank and cat in on_card_recently:
            moved.append(name)  # was paid from checking last year, now paid by card
            continue
        is_new = cat not in last_year and cat not in ever_before
        mode = choices["categories"].get(str(cat)) or ("recent" if is_new else "last_year")
        if mode == "recent":
            rows = [(d + timedelta(days=7 * weeks), c) for d, c in recent_bank.get(cat, [])]
        elif mode == "last_year":
            rows = [(_year_ahead(d), c) for d, c in last_year.get(cat, [])]
        else:
            rows = []
        rows = [(d, c) for d, c in rows if today < d <= end]
        total = sum(c for _, c in rows)
        if mode != "off":
            for d, c in rows:
                events.append({"date": d.isoformat(), "kind": "cost", "label": name, "cents": c})
        costs_out.append({"id": cat, "name": name, "cents": max(-total, 0), "mode": mode, "new": is_new, "count": len(rows)})
    costs_out.sort(key=lambda c: (c["mode"] == "off", -c["cents"]))

    events.sort(key=lambda e: (e["date"], -e["cents"]))
    return {
        "today": today.isoformat(),
        "end": end.isoformat(),
        "weeks": weeks,
        "as_of": as_of.isoformat() if as_of else None,
        "start_cents": start_cents,
        "accounts": [f"{b.name} ({b.mask})" if b.mask else b.name for b in checking],
        "history": history,
        "events": events,
        "last_year_range": [ly_start.isoformat(), ly_end.isoformat()],
        "sources": {
            "income": {"count": counted, "cents": paid_in},
            "cards": cards_out,
            "fixed": fixed_out,
            "costs": costs_out,
            "cleaning": cleaning_out,
            "moved_to_card": moved,
        },
    }
