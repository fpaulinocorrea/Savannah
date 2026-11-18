"""One-time changes to your books, run once when Savannah starts (each is remembered in settings).

Each fixup checks that things look exactly as expected before changing anything, so it can't
touch the wrong transaction.
"""

import logging

from sqlmodel import Session, select

from .db import engine, get_setting, set_setting  # noqa: F401
from .ledger import LedgerAccount, Txn, TxnSplit

log = logging.getLogger("savannah.fixups")


def _account(db: Session, name: str, type_: str, detail: str) -> LedgerAccount:
    a = db.exec(select(LedgerAccount).where(LedgerAccount.name == name)).first()
    if not a:
        a = LedgerAccount(name=name, type=type_, detail_type=detail, source="you")
        db.add(a)
        db.commit()
        db.refresh(a)
    return a


def _debit(db: Session, account_id: int) -> int:
    """An account's balance exactly as the balance sheet sees it (debit = what you own goes up)."""
    import datetime as _dt

    from . import reports

    return sum(d for _t, a, d, _m in reports.ledger_lines(db, None, _dt.date(2100, 1, 1)) if a == account_id)


def card_3572_is_qb_card_2026_11(db: Session) -> str:
    """Card 3572 (F. CORREA) is the same card as QuickBooks' "Chase Business Credit Card".
    It had been added with its full Chase history, so May–Oct charges were in the books twice.
    Pair it with the QuickBooks account, count QuickBooks history before the start date, and keep
    only the Chase charges QuickBooks never recorded."""
    import datetime as _dt

    from . import books_api
    from .ledger import BankAccount

    qb_card = db.exec(select(LedgerAccount).where(LedgerAccount.name == "Chase Business Credit Card")).first()
    checking = db.exec(select(LedgerAccount).where(LedgerAccount.name == "Chase Business Checking Account")).first()
    card = next((b for b in db.exec(select(BankAccount)).all() if b.mask == "3572" or b.name == "F. CORREA"), None)
    start_s = get_setting(db, "books_start_date")
    if not (qb_card and card and start_s):
        return "skipped: accounts not as expected"
    start = _dt.date.fromisoformat(start_s)
    if card.ledger_account_id != qb_card.id:
        books_api.map_bank(card.id, books_api.BankMap(ledger_account_id=qb_card.id), db)
    card = db.get(BankAccount, card.id)
    card.full_history = False
    db.add(card)
    db.commit()
    books_api._rehide(db)

    # Card payments that pointed at the old checking stand-in (deleted when checking was paired).
    if checking:
        known = {a.id for a in db.exec(select(LedgerAccount)).all()}
        for t in db.exec(select(Txn).where(Txn.category_id.is_not(None))).all():
            if t.category_id not in known:
                t.category_id = checking.id
                db.add(t)
        db.commit()

    # Chase charges before the start date that QuickBooks never recorded: keep them.
    qb = db.exec(select(Txn).where(Txn.source == "quickbooks")).all()

    def in_qb(t: Txn) -> bool:
        return any(
            abs((q.date - t.date).days) <= 4
            and ((q.account_id == qb_card.id and q.amount_cents == t.amount_cents)
                 or (q.category_id == qb_card.id and q.amount_cents == -t.amount_cents))
            for q in qb
        )

    kept = 0
    early = db.exec(select(Txn).where(Txn.account_id == qb_card.id, Txn.source == "plaid", Txn.date < start)).all()
    for t in early:
        if in_qb(t) or db.exec(select(Txn).where(Txn.external_id == f"kept:{t.external_id}")).first():
            continue
        db.add(Txn(
            external_id=f"kept:{t.external_id}", source="you", date=t.date, description=t.description,
            merchant=t.merchant, amount_cents=t.amount_cents, account_id=qb_card.id,
            category_id=None, category_source="", needs_review=True, bank_category=t.bank_category,
        ))
        kept += 1
    db.commit()
    return f"done: paired with {qb_card.name}, kept {kept} charges QuickBooks didn't have"


def heat_pump_2026_11(db: Session) -> str:
    """Jetson Home heat pump installation ($9,722.88, Jul 31 2026, card 3572) is a building
    improvement: record it as a fixed asset, not an expense (and not the mortgage)."""
    _account(db, "Fixed Assets", "Fixed Assets", "Buildings")
    target = _account(db, "Fixed Assets:Building Improvements", "Fixed Assets", "Leasehold Improvements")
    hits = db.exec(
        select(Txn).where(Txn.amount_cents == -972288, Txn.description.contains("JETSON"), Txn.hidden == False)  # noqa: E712
    ).all()
    if len(hits) != 1:
        return f"skipped: found {len(hits)} matching transactions"
    t = hits[0]
    if db.exec(select(TxnSplit).where(TxnSplit.txn_id == t.id)).first():
        return "skipped: the transaction is split"
    t.category_id, t.category_source, t.needs_review = target.id, "you", False
    db.add(t)
    db.commit()
    return f"done: transaction {t.id} → {target.name}"


def journal_reimport_2026_11(db: Session) -> str:
    """Bring in the 15 QuickBooks journal entries that were still missing (building, mortgage, old checking…).
    Same as Books → Setup → step 3; entries already in the books are skipped."""
    from . import config, quickbooks

    files = sorted(config.IMPORTS_DIR.glob("*ournal*.xlsx"), key=lambda p: -p.stat().st_mtime) if config.IMPORTS_DIR.exists() else []
    if not files:
        return "skipped: no QuickBooks journal file in imports/"
    result = quickbooks.save_journal(db, quickbooks.parse_journal(db, files[0]))
    return f"done: {result}"


def close_lowes_card_2026_11(db: Session) -> str:
    """Lowe's Business Rewards card (closed). QuickBooks booked the 2026 payments to it as Supplies,
    so purchases already on the card were counted twice and the card never reached $0.
    Payments become transfers to the card; Apr–Jun purchases QuickBooks never recorded go to Supplies once."""
    import datetime as _dt

    card = db.exec(select(LedgerAccount).where(LedgerAccount.name.startswith("Lowe's Business Rewards Card"))).first()
    supplies = db.exec(select(LedgerAccount).where(LedgerAccount.name == "Supplies:Supplies & materials")).first()
    if not (card and supplies):
        return "skipped: accounts not as expected"
    pays = [
        t for t in db.exec(select(Txn).where(Txn.source == "quickbooks", Txn.amount_cents < 0, Txn.hidden == False)).all()  # noqa: E712
        if t.date.year == 2026 and ("LOWES AMEX" in t.description.upper() or "SYF PAYMNT LOWES" in t.description.upper())
        and t.category_id != card.id
    ]
    for t in pays:
        t.category_id, t.category_source, t.needs_review = card.id, "you", False
        db.add(t)
    db.commit()

    def owed() -> int:
        return _debit(db, card.id)  # negative = you owe; positive = paid more than the books show was bought

    extra = owed()
    if extra > 0 and not db.exec(select(Txn).where(Txn.external_id == "fixup:lowes-unrecorded-2026")).first():
        db.add(Txn(
            external_id="fixup:lowes-unrecorded-2026", source="you", date=_dt.date(2026, 6, 15),
            description="Lowe's card purchases Apr–Jun 2026 not recorded in QuickBooks (adjustment)",
            amount_cents=-extra, account_id=card.id, category_id=supplies.id, category_source="you",
        ))
        db.commit()
    left = owed()
    if left == 0:
        card.active = False  # closed card: keep its history, hide it from lists
        db.add(card)
        db.commit()
    return f"done: {len(pays)} payments now pay the card, ${extra / 100:,.2f} of purchases added, card balance ${-left / 100:,.2f}"


def close_old_checking_2026_11(db: Session) -> str:
    """AcquaReal Checking (FirstBank 6238), closed in May 2026. Its last $35.61 (sent from Chase on May 22)
    left with the closing and was never recorded; book it as a bank charge so the account ends at $0."""
    import datetime as _dt

    acct = db.exec(select(LedgerAccount).where(LedgerAccount.name.startswith("AcquaReal Checking (6238)"))).first()
    fees = db.exec(select(LedgerAccount).where(LedgerAccount.name == "General business expenses:Bank fees & service charges")).first()
    if not (acct and fees):
        return "skipped: accounts not as expected"

    def balance() -> int:
        return _debit(db, acct.id)

    bal = balance()
    if bal == 3561 and not db.exec(select(Txn).where(Txn.external_id == "fixup:firstbank-closing-2026")).first():
        db.add(Txn(
            external_id="fixup:firstbank-closing-2026", source="you", date=_dt.date(2026, 5, 22),
            description="FirstBank account 6238 closed: final balance not recorded in QuickBooks",
            amount_cents=-bal, account_id=acct.id, category_id=fees.id, category_source="you",
        ))
        db.commit()
    elif bal not in (0, 3561):
        return f"skipped: balance is ${bal / 100:,.2f}, not the expected $35.61"
    if balance() == 0:
        acct.active = False
        db.add(acct)
        db.commit()
    return f"done: account closed at $0 (was ${bal / 100:,.2f})"


def home_depot_card_2026_11(db: Session) -> str:
    """Home Depot card (Citi 8997), connected Nov 15 and paired with QuickBooks' "Home Depot Credit Card".
    QuickBooks already has its purchases, so its older bank history must NOT be brought in again. Instead:
    1. payments from checking that QuickBooks booked as Supplies now pay the card (purchases were already expenses),
    2. the Oct 24 payment seen on the card side is carried by the checking side (it was also put on the Lowe's card),
    3. the Jul 30 interest charge QuickBooks never recorded is added."""
    import datetime as _dt

    from .ledger import BankAccount

    hd = db.exec(select(LedgerAccount).where(LedgerAccount.name == "Home Depot Credit Card")).first()
    interest = db.exec(select(LedgerAccount).where(LedgerAccount.name == "Interest paid:Credit card interest")).first()
    bank = db.exec(select(BankAccount).where(BankAccount.ledger_account_id == (hd.id if hd else -1))).first()
    if not (hd and interest and bank):
        return "skipped: Home Depot card not connected or accounts not as expected"
    money_ids = {a.id for a in db.exec(select(LedgerAccount)).all() if (a.type or "").lower().startswith("bank")}
    on_card = db.exec(select(Txn).where(Txn.account_id == hd.id, Txn.hidden == False)).all()  # noqa: E712

    # 1. Checking → Home Depot payments booked as an expense, unless the card side already records that payment.
    fixed = 0
    for q in db.exec(select(Txn).where(Txn.amount_cents < 0, Txn.hidden == False)).all():  # noqa: E712
        if (q.date.year == 2026 and q.account_id in money_ids and "HOME DEPOT" in q.description.upper()
                and q.category_id != hd.id and not any(c.amount_cents == -q.amount_cents and abs((c.date - q.date).days) <= 4 and c.source == "quickbooks" for c in on_card)):
            q.category_id, q.category_source, q.needs_review = hd.id, "you", False
            db.add(q)
            fixed += 1
    # 2. Bank-side copies of payments on the card: the checking side carries them.
    neutral = 0
    for t in on_card:
        if t.source == "plaid" and t.amount_cents > 0 and t.category_id != hd.id:
            t.category_id, t.category_source, t.needs_review = hd.id, "you", False
            db.add(t)
            neutral += 1
    # 3. Interest charge QuickBooks never recorded.
    added = 0
    for t in db.exec(select(Txn).where(Txn.account_id == hd.id, Txn.source == "plaid", Txn.hidden == True)).all():  # noqa: E712
        if "INTEREST CHARGE" in t.description.upper() and t.amount_cents < 0:
            in_qb = any(c.amount_cents == t.amount_cents and abs((c.date - t.date).days) <= 4 for c in on_card if c.source == "quickbooks")
            if not in_qb and not db.exec(select(Txn).where(Txn.external_id == f"kept:{t.external_id}")).first():
                db.add(Txn(external_id=f"kept:{t.external_id}", source="you", date=t.date, description=t.description,
                           amount_cents=t.amount_cents, account_id=hd.id, category_id=interest.id, category_source="you"))
                added += 1
    db.commit()
    owed = -_debit(db, hd.id)
    bank_owes = bank.balance_cents or 0
    return (f"done: {fixed} payments now pay the card, {neutral} card-side payment(s) neutral, {added} interest charge(s) added; "
            f"Savannah ${owed / 100:,.2f} vs bank ${bank_owes / 100:,.2f}")


def appliances_may_2026(db: Session) -> str:
    """Home Depot order WH30146841 (May 1 2026, $2,239.72 on the Home Depot card): side-by-side refrigerator
    and dishwasher for 3234 S Pearl St, with delivery, install parts and sales tax. Appliances in a rental
    are fixed assets (depreciated), not supplies. Invoice: data/receipts/Home Depot WH30146841 2026-05-01.pdf"""
    target = db.exec(select(LedgerAccount).where(LedgerAccount.name == "Real Estate Owned:5 Furniture:Appliances")).first()
    hd = db.exec(select(LedgerAccount).where(LedgerAccount.name == "Home Depot Credit Card")).first()
    if not (target and hd):
        return "skipped: accounts not as expected"
    hits = [t for t in db.exec(select(Txn).where(Txn.amount_cents == -223972, Txn.account_id == hd.id, Txn.hidden == False)).all()  # noqa: E712
            if str(t.date) == "2026-05-01"]
    if len(hits) != 1:
        return f"skipped: found {len(hits)} matching transactions"
    t = hits[0]
    t.category_id, t.category_source, t.needs_review = target.id, "you", False
    db.add(t)
    db.commit()
    return f"done: transaction {t.id} → {target.name}"


def best_buy_range_2026(db: Session) -> str:
    """Best Buy order BBY01-807173497606 (Apr 30 2026, $1,353.52): Whirlpool gas range for 3234 S Pearl St,
    with install parts and tax. Paid on the Lowe's Amex card, whose Apr–Jun purchases were booked as one
    Supplies adjustment. Move the range out of that lump into Appliances (fixed asset), dated the purchase day.
    Receipt: data/receipts/Best Buy BBY01-807173497606 2026-04-30.pdf"""
    import datetime as _dt

    lump = db.exec(select(Txn).where(Txn.external_id == "fixup:lowes-unrecorded-2026")).first()
    target = db.exec(select(LedgerAccount).where(LedgerAccount.name == "Real Estate Owned:5 Furniture:Appliances")).first()
    if not (lump and target):
        return "skipped: Lowe's adjustment or Appliances account not found"
    if db.exec(select(Txn).where(Txn.external_id == "fixup:bestbuy-range-2026")).first():
        return "skipped: already moved"
    if lump.amount_cents > -135352:
        return f"skipped: the Lowe's adjustment (${-lump.amount_cents / 100:,.2f}) is smaller than the range"
    lump.amount_cents += 135352
    lump.description = "Lowe's card purchases Apr–Jun 2026 not recorded in QuickBooks (adjustment, Best Buy range moved out)"
    db.add(lump)
    db.add(Txn(
        external_id="fixup:bestbuy-range-2026", source="you", date=_dt.date(2026, 4, 30),
        description="Best Buy: Whirlpool 30 in. gas range, order BBY01-807173497606 (Lowe's Amex)",
        amount_cents=-135352, account_id=lump.account_id, category_id=target.id, category_source="you",
    ))
    db.commit()
    return f"done: $1,353.52 → {target.name}; Lowe's lump now ${-lump.amount_cents / 100:,.2f}"


def jetson_deposit_2026(db: Session) -> str:
    """Jetson Home $500 (Feb 19 2026, Lowe's card), booked as Contract labor by QuickBooks: part of the
    heat pump project, so it joins the installation in Fixed Assets:Building Improvements (total $10,222.88)."""
    target = db.exec(select(LedgerAccount).where(LedgerAccount.name == "Fixed Assets:Building Improvements")).first()
    if not target:
        return "skipped: Building Improvements account not found"
    hits = [t for t in db.exec(select(Txn).where(Txn.amount_cents == -50000, Txn.hidden == False)).all()  # noqa: E712
            if "JETSON" in t.description.upper() and str(t.date) == "2026-02-19"]
    if len(hits) != 1:
        return f"skipped: found {len(hits)} matching transactions"
    t = hits[0]
    t.category_id, t.category_source, t.needs_review = target.id, "you", False
    db.add(t)
    db.commit()
    return f"done: transaction {t.id} → {target.name}"


def forecast_choices_2026_11(db: Session) -> str:
    """Cash forecast choices Felipe made on Nov 17, 2026:
    cleaning $200 per checkout at The Craftsman House, $110 at the Cottage; Chase card = statement balance,
    Home Depot card = minimum payment; leave out general repairs and bank fees."""
    import json

    from . import forecast, reports
    from .ledger import BankAccount

    if get_setting(db, forecast.CHOICES_KEY):
        return "skipped: choices already saved"
    choices = {"cards": {}, "categories": {}, "cleaning": {}}
    for b in db.exec(select(BankAccount)).all():
        if b.type == "credit":
            if b.mask == "3572":
                choices["cards"][b.id] = "statement"
            elif b.mask == "8997" or "home depot" in b.name.lower():
                choices["cards"][b.id] = "minimum"
    for a in db.exec(select(LedgerAccount)).all():
        leaf = a.name.split(":")[-1].strip().lower()
        if a.name.strip().lower() == "repairs & maintenance" or "bank fee" in leaf:
            choices["categories"][str(a.id)] = "off"
    props = {b.get("property_name", "") for b in (reports.load_bookings() or {}).get("bookings", [])}
    for p in props:
        if "craftsman" in p.lower():
            choices["cleaning"][p] = 20000
        elif "cottage" in p.lower():
            choices["cleaning"][p] = 11000
    set_setting(db, forecast.CHOICES_KEY, json.dumps(choices))
    return f"done: {len(choices['cards'])} cards, {len(choices['categories'])} left out, {len(choices['cleaning'])} houses"


FIXUPS = [
    ("card_3572_is_qb_card_2026_11", card_3572_is_qb_card_2026_11),  # first: the heat pump charge moves
    ("heat_pump_2026_11", heat_pump_2026_11),
    ("journal_reimport_2026_11", journal_reimport_2026_11),  # before closing the old checking
    ("close_lowes_card_2026_11", close_lowes_card_2026_11),
    ("close_old_checking_2026_11", close_old_checking_2026_11),
    ("home_depot_card_2026_11", home_depot_card_2026_11),
    ("appliances_may_2026", appliances_may_2026),
    ("best_buy_range_2026", best_buy_range_2026),
    ("jetson_deposit_2026", jetson_deposit_2026),
    ("forecast_choices_2026_11", forecast_choices_2026_11),
]


def run_pending() -> None:
    with Session(engine) as db:
        for key, fn in FIXUPS:
            if get_setting(db, f"fixup:{key}"):
                continue
            try:
                result = fn(db)
            except Exception as e:  # never stop Savannah from starting
                log.exception("fixup %s", key)
                result = f"failed: {type(e).__name__}"
                db.rollback()
            set_setting(db, f"fixup:{key}", result)
            log.info("fixup %s: %s", key, result)
