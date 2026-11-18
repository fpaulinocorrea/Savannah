"""Putting each transaction in the right category, in three steps:

  1. Your rules        ("AIRBNB" → Rental income)                    → done, no review
  2. Learned patterns  (same merchant was always "Cleaning" before)  → done, no review
  3. Claude's guess    (for anything new)                            → shown in "To review"
"""

import json
import logging
import re
from collections import Counter, defaultdict

import anthropic
from sqlmodel import Session, select

from . import drafting
from .db import get_setting
from .ledger import LedgerAccount, Rule, Txn, kind, set_splits

log = logging.getLogger("savannah.categorize")

_NOISE = {
    "pos", "debit", "credit", "purchase", "card", "ach", "ppd", "ccd", "web", "id", "des", "indn", "co",
    "recurring", "checkcard", "visa", "mastercard", "online", "transfer", "xx", "xxxx", "inc", "llc", "the",
}


_ACH = re.compile(r"orig co name:\s*(.+?)\s+orig id", re.I)        # Chase ACH: "ORIG CO NAME:AIRBNB PAYMENTS ORIG ID:…"
_ZELLE = re.compile(r"\bzelle (payment|transfer) (to|from) (.+)", re.I)  # "Zelle payment to Maria Andujo 123…"


def payee(text: str) -> str:
    """Pull the useful part out of a bank description.
    'ORIG CO NAME:AIRBNB PAYMENTS ORIG ID:…' → 'AIRBNB PAYMENTS'
    'Zelle payment to Maria Andujo 2738…'    → 'Zelle payment to Maria Andujo'"""
    text = text or ""
    m = _ACH.search(text)
    if m:
        return m.group(1)
    m = _ZELLE.search(text)
    if m:
        name = [w for w in m.group(3).split() if not any(ch.isdigit() for ch in w)][:3]
        return f"Zelle {m.group(1).lower()} {m.group(2).lower()} " + " ".join(name)
    return text


def normalize(text: str) -> str:
    """Lower-case words only, without bank noise: used to compare rules and descriptions."""
    words = re.sub(r"[^a-z ]", " ", (text or "").lower()).split()
    return " ".join(w for w in words if w not in _NOISE and len(w) > 1)


def merchant_key(text: str) -> str:
    """The short name Savannah suggests for a rule and learns from.
    'POS PURCHASE ACE HARDWARE #123 TUCSON AZ' → 'ace hardware tucson'"""
    p = payee(text)
    words = normalize(p).split()
    if words[:1] == ["zelle"]:
        return " ".join(words[:6])  # keep the person's name: "zelle payment to maria andujo"
    return " ".join(words[:3])


def merchant_keys(text: str) -> list[str]:
    """Longest first: 'ace hardware tucson', 'ace hardware', 'ace'."""
    words = merchant_key(text).split()
    if words[:1] == ["zelle"]:
        return [" ".join(words)] if len(words) > 3 else []  # "zelle payment to" alone means nothing
    keys = [" ".join(words[:n]) for n in (3, 2, 1) if len(words) >= n]
    return list(dict.fromkeys(k for k in keys if len(k) >= 3))


def _direction(cents: int) -> str:
    return "in" if cents > 0 else "out"


def rule_matches(rule: Rule, t: Txn) -> bool:
    """A rule matches when its words appear, in order, in the description (punctuation and bank noise ignored)."""
    want = normalize(rule.match)
    if not want or rule.direction not in ("any", _direction(t.amount_cents)):
        return False
    return f" {want} " in f" {normalize(t.description)} {normalize(t.merchant)} "


def apply_rules(db: Session, txns: list[Txn]) -> int:
    """Auto rules file a transaction by themselves; suggest rules fill in the category but leave it in "To review"."""
    rules = db.exec(select(Rule)).all()
    done = 0
    for t in txns:
        for r in rules:
            if rule_matches(r, t):
                review = r.mode == "suggest"
                if r.split_json:
                    if t.category_source not in ("rule-split", "split", "qb-split"):
                        split_by_rule(db, t, r, review)
                        r.times_used += 1
                        db.add(r)
                        done += 1
                    break
                if t.category_source == "rule" and t.category_id == r.category_id and review:
                    break  # already suggested (or already filed before you switched it to suggest)
                if (t.category_id, t.category_source, t.needs_review) != (r.category_id, "rule", review):
                    r.times_used += 1
                    db.add(r)
                    done += 1
                t.category_id, t.category_source, t.needs_review = r.category_id, "rule", review
                break
        db.add(t)
    db.commit()
    return done


def split_by_rule(db: Session, t: Txn, rule: Rule, review: bool = True) -> None:
    """Split this transaction the way you split a similar one before (same proportions).
    Amounts like mortgage interest change each month, so by default it goes to 'To review' to check."""
    parts = json.loads(rule.split_json)
    lines, left = [], t.amount_cents
    for i, p in enumerate(parts):
        cents = left if i == len(parts) - 1 else round(t.amount_cents * float(p["share"]))
        left -= cents
        lines.append((p["category_id"], cents, ""))
    set_splits(db, t, lines, source="rule-split")
    t.needs_review = review
    db.add(t)


def make_split_rule(db: Session, match: str, lines: list[tuple[int | None, int]], direction: str, mode: str = "suggest") -> Rule:
    total = sum(c for _, c in lines) or 1
    parts = [{"category_id": cat, "share": round(c / total, 6)} for cat, c in lines if cat]
    biggest = max(lines, key=lambda x: abs(x[1]))[0]
    match = match.strip().lower()
    rule = db.exec(select(Rule).where(Rule.match == match, Rule.direction == direction)).first() or Rule(
        match=match, direction=direction, category_id=biggest
    )
    rule.category_id, rule.split_json, rule.mode = biggest, json.dumps(parts), mode
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def run_rules_everywhere(db: Session) -> int:
    """Re-apply your rules to every current transaction you haven't sorted by hand."""
    txns = db.exec(
        select(Txn).where(
            Txn.hidden == False, Txn.source == "plaid", Txn.category_source.not_in(["you", "split", "qb-split"])  # noqa: E712
        )
    ).all()
    before = {t.id: (t.category_id, t.needs_review) for t in txns}
    apply_rules(db, txns)
    return sum(1 for t in txns if (t.category_id, t.needs_review) != before[t.id])


def _learned_index(db: Session) -> dict[tuple[str, str], Counter]:
    idx: dict[tuple[str, str], Counter] = defaultdict(Counter)
    rows = db.exec(
        select(Txn).where(Txn.category_id.is_not(None), Txn.category_source.in_(["quickbooks", "you", "rule"]))
    ).all()
    for t in rows:
        weight = 2 if t.category_source == "you" else 1
        for key in merchant_keys(t.merchant or t.description):
            idx[(key, _direction(t.amount_cents))][t.category_id] += weight
    return idx


def apply_learned(db: Session, txns: list[Txn]) -> int:
    idx = _learned_index(db)
    done = 0
    for t in txns:
        for key in merchant_keys(t.merchant or t.description):
            counts = idx.get((key, _direction(t.amount_cents)))
            if not counts:
                continue
            cat, n = counts.most_common(1)[0]
            total = sum(counts.values())
            # Shorter keys ("cox") need a stronger track record than longer ones.
            need = 0.8 if len(key.split()) > 1 else 0.9
            if n >= 2 and n / total >= need:
                t.category_id, t.category_source, t.needs_review = cat, "learned", False
                db.add(t)
                done += 1
            break  # only trust the most specific key that has any history
    db.commit()
    return done


async def apply_ai(db: Session, txns: list[Txn]) -> int:
    """Ask Claude for a best guess. Guesses always go to 'To review'."""
    key = get_setting(db, "claude_key")
    if not key or not txns:
        return 0
    cats = [a for a in db.exec(select(LedgerAccount).where(LedgerAccount.active == True)).all()]  # noqa: E712
    by_name = {a.name.lower(): a for a in cats}
    cat_lines = "\n".join(f"- {a.name} ({kind(a.type)})" for a in cats)

    # A few real examples of how you categorize.
    idx = _learned_index(db)
    names = {a.id: a.name for a in cats}
    examples = sorted(idx.items(), key=lambda kv: -sum(kv[1].values()))[:40]
    ex_lines = "\n".join(f"- \"{k[0]}\" (money {k[1]}) → {names.get(c.most_common(1)[0][0], '?')}" for k, c in examples)

    done = 0
    client = anthropic.AsyncAnthropic(api_key=key)
    try:
        for start in range(0, len(txns), 40):
            batch = txns[start : start + 40]
            lines = "\n".join(
                f'{t.id}: "{t.description}" {"+" if t.amount_cents > 0 else "-"}${abs(t.amount_cents) / 100:.2f}'
                + (f" (bank says: {t.bank_category})" if t.bank_category else "")
                for t in batch
            )
            prompt = f"""You categorize transactions for a short-term rental business (Airbnb/Vrbo) owned by one person.
"+" means money came in, "-" means money went out.

Categories you may use (use the exact name):
{cat_lines}

How the owner categorized similar things before:
{ex_lines or '(no history yet)'}

Transactions:
{lines}

Reply with only a JSON object mapping each transaction number to a category name, e.g. {{"12": "Cleaning"}}.
Payments to the credit card or moves between the owner's own accounts go to that bank or card account.
If you can't tell, use null."""
            res = await client.messages.create(
                model=drafting.MODEL, max_tokens=2000, messages=[{"role": "user", "content": prompt}]
            )
            text = "".join(b.text for b in res.content if getattr(b, "type", "") == "text")
            m = re.search(r"\{.*\}", text, re.S)
            guesses = json.loads(m.group(0)) if m else {}
            for t in batch:
                name = guesses.get(str(t.id))
                cat = by_name.get(str(name).lower()) if name else None
                if cat and not db.get(LedgerAccount, cat.id):
                    cat = None  # removed while Claude was thinking
                if cat:
                    t.category_id, t.category_source = cat.id, "ai"
                t.needs_review = True
                db.add(t)
                done += 1 if cat else 0
            db.commit()
    except (anthropic.APIError, ValueError) as e:
        log.warning("AI categorizing skipped: %s", e)
    finally:
        await client.close()
    return done


async def categorize(db: Session, txn_ids: list[int]) -> dict:
    txns = [
        t for t in (db.get(Txn, i) for i in txn_ids)
        if t and not t.hidden and t.category_id is None and t.category_source not in ("split", "rule-split", "qb-split")
    ]
    by_rule = apply_rules(db, txns)
    left = [t for t in txns if t.category_id is None]
    learned = apply_learned(db, left)
    left = [t for t in left if t.category_id is None]
    for t in left:
        t.needs_review = True
        db.add(t)
    db.commit()
    ai = await apply_ai(db, left)
    return {"rule": by_rule, "learned": learned, "ai": ai, "unsure": len(left) - ai}


def make_rule(db: Session, match: str, category_id: int, direction: str = "any", mode: str = "auto") -> Rule:
    match = match.strip().lower()
    rule = db.exec(select(Rule).where(Rule.match == match, Rule.direction == direction)).first()
    if rule:
        rule.category_id, rule.split_json, rule.mode = category_id, "", mode
    else:
        rule = Rule(match=match, category_id=category_id, direction=direction, mode=mode)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    use_on_waiting(db, rule)
    return rule


def use_on_waiting(db: Session, rule: Rule) -> int:
    """Use a rule right away on everything still waiting in "To review" (except splits you're checking)."""
    waiting = db.exec(select(Txn).where(Txn.needs_review == True, Txn.hidden == False)).all()  # noqa: E712
    done = 0
    for t in waiting:
        if rule.split_json or t.category_source in ("split", "rule-split", "qb-split") or not rule_matches(rule, t):
            continue
        t.category_id, t.category_source, t.needs_review = rule.category_id, "rule", rule.mode == "suggest"
        rule.times_used += 1
        done += 1
        db.add(t)
    db.add(rule)
    db.commit()
    return done
