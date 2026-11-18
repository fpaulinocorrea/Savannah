"""The background watcher.

Every few minutes: look at current and upcoming reservations in Hospitable, save each
conversation to the folder, and when a guest is waiting on a reply, draft one.
"""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from . import conversations, drafting
from .db import Draft, engine, get_setting, utcnow
from . import config
from .hospitable import Hospitable, HospitableAuthError, HospitableError, inquiry_summary, is_cancelled, reservation_summary

log = logging.getLogger("savannah.sync")

CHECK_EVERY_MINUTES = 3
WINDOW_BACK_DAYS = 45  # long stays and stays that ended recently can still get messages
WINDOW_AHEAD_DAYS = 400  # people book (and write) up to a year ahead
INQUIRY_DAYS = 30  # inquiries asked in the last month
HISTORY_DAYS = 730  # "learn from past conversations" looks back two years

state = {
    "last_check_at": None,
    "last_error": "",
    "checking": False,
    "import": {"running": False, "done": 0, "total": 0, "finished_at": None, "error": ""},
}
_lock = asyncio.Lock()


def keys(db: Session) -> tuple[str | None, str | None, str]:
    return get_setting(db, "hospitable_token"), get_setting(db, "claude_key"), get_setting(db, "owner_name") or ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _reservations(api: Hospitable, start: date, end: date, with_inquiries: bool = False) -> list[dict]:
    props = await api.properties()
    names = {p.get("id", ""): p.get("public_name") or p.get("name") or "" for p in props}
    raw = await api.reservations([p["id"] for p in props if p.get("id")], start, end)
    summaries = [reservation_summary(r, names) for r in raw]
    found = [s for s in summaries if s["id"] and not is_cancelled(s)]
    last_check["reservations"] = len(found)
    if with_inquiries:
        found += await _inquiries(api, [p["id"] for p in props if p.get("id")], names)
    return found


async def _inquiries(api: Hospitable, property_ids: list[str], names: dict[str, str]) -> list[dict]:
    """Recent inquiries. If Hospitable won't share them, the reservations still work."""
    try:
        raw = await api.inquiries(property_ids)
    except HospitableAuthError:
        raise
    except Exception as e:  # inquiries must never stop the bookings from being checked
        last_check["inquiries_error"] = f"{type(e).__name__}: {e}"[:300]
        return []
    if raw:  # the shape of one inquiry (field names and types only), to spot surprises
        last_check["inquiry_shape"] = {k: type(v).__name__ for k, v in raw[0].items()}
    since = (datetime.now(timezone.utc) - timedelta(days=INQUIRY_DAYS)).isoformat()
    out = []
    without_messages = 0
    for r in raw:
        try:
            s = inquiry_summary(r, names)
            when = str(r.get("last_message_at") or r.get("updated_at") or r.get("inquiry_date") or r.get("created_at") or "")
            msgs = r.get("messages")
            if isinstance(msgs, dict):
                msgs = msgs.get("data")
        except Exception as e:
            last_check["inquiries_error"] = f"{type(e).__name__}: {e}"[:300]
            continue
        if not (s["id"] and not is_cancelled(s) and (not when or when[:10] >= since[:10])):
            continue
        if not isinstance(msgs, list):
            without_messages += 1  # Hospitable didn't share this one's messages: nothing to show
            continue
        _inquiry_messages[s["id"]] = msgs
        out.append(s)
    if without_messages:
        last_check["inquiries_note"] = f"{without_messages} recent inquiries came without messages (Hospitable doesn't share them)."
    last_check["inquiries"] = len(out)
    last_check.setdefault("inquiries_error", "")
    return out


_inquiry_messages: dict[str, list] = {}  # inquiry id → messages that came with the inquiry list


async def _messages(api: Hospitable, summary: dict) -> list[dict]:
    if summary.get("kind") == "inquiry":
        # Hospitable can't GET inquiry messages one by one; they come with the list (or not at all).
        return conversations.clean_messages(_inquiry_messages.get(summary["id"], []))
    return conversations.clean_messages(await api.messages(summary["id"]))


def is_inquiry(reservation_id: str) -> bool:
    convo = conversations.load(reservation_id)
    return bool(convo and convo["reservation"].get("kind") == "inquiry")


# What the last check found, saved to data/last-check.json (no message text) so problems are easy to see.
last_check: dict = {}


def _save_last_check() -> None:
    try:
        (config.DATA_DIR / "last-check.json").write_text(json.dumps(last_check, indent=1, default=str))
    except OSError:
        pass


# ---------- drafting ----------


async def draft_for(draft_id: int, adjust: str = "") -> None:
    """(Re)write the reply for one draft."""
    with Session(engine) as db:
        d = db.get(Draft, draft_id)
        if not d:
            return
        _, claude_key, host = keys(db)
        convo = conversations.load(d.reservation_id)
        if not claude_key:
            d.status, d.error = "error", "Add your Claude key in Settings so Savannah can write drafts."
        elif not convo or not convo["messages"]:
            d.status, d.error = "error", "Couldn't find this conversation. Press Check now."
        else:
            d.status, d.error = "drafting", ""
        d.updated_at = utcnow()
        db.add(d)
        db.commit()
        if d.status == "error":
            return
    try:
        text = await drafting.write_reply(claude_key, host, convo["reservation"], convo["messages"], adjust)
        status, error = "ready", ""
    except drafting.DraftError as e:
        text, status, error = "", "error", str(e)
    except Exception as e:  # never let one draft stop the watcher
        log.exception("draft failed")
        text, status, error = "", "error", f"Something went wrong writing this draft ({type(e).__name__}). Try Rewrite."
    with Session(engine) as db:
        d = db.get(Draft, draft_id)
        if d and d.status == "drafting":
            if text:
                d.draft_text = text
            d.status, d.error, d.updated_at = status, error, utcnow()
            db.add(d)
            db.commit()


def _open_draft(db: Session, reservation_id: str) -> Draft | None:
    return db.exec(
        select(Draft).where(Draft.reservation_id == reservation_id, Draft.status.in_(["drafting", "ready", "error"]))
    ).first()


async def _handle_conversation(summary: dict, messages: list[dict]) -> int | None:
    """Save the conversation; return a draft id if a new reply needs writing."""
    conversations.save(summary, messages)
    if not messages:
        return None
    last = messages[-1]
    with Session(engine) as db:
        open_draft = _open_draft(db, summary["id"])
        if last["role"] == "host":
            # You (or an automated message) already replied: retire any waiting draft.
            if open_draft:
                open_draft.status, open_draft.updated_at = "answered_elsewhere", utcnow()
                db.add(open_draft)
                db.commit()
            return None
        if db.exec(select(Draft).where(Draft.guest_message_id == last["id"])).first():
            return None  # already drafted for this message
        from .db import ConvoState

        st = db.get(ConvoState, summary["id"])
        if st and st.handled_message_id == last["id"]:
            return None  # you marked this one as already replied
        if open_draft:
            open_draft.status, open_draft.updated_at = "replaced", utcnow()
            db.add(open_draft)
        # Everything the guest said since your last reply.
        waiting = []
        for m in reversed(messages):
            if m["role"] != "guest":
                break
            waiting.append(m["body"])
        d = Draft(
            reservation_id=summary["id"],
            guest_message_id=last["id"],
            guest_name=summary["guest_name"],
            property_name=summary["property_name"],
            platform=summary["platform"],
            arrival=summary["arrival"],
            departure=summary["departure"],
            guest_message="\n\n".join(reversed(waiting)),
        )
        db.add(d)
        db.commit()
        db.refresh(d)
        return d.id


async def refresh_one(reservation_id: str) -> int | None:
    """Fetch one conversation fresh from Hospitable (used when you open it). Returns a new draft id, if any."""
    with Session(engine) as db:
        token, _, _ = keys(db)
    convo = conversations.load(reservation_id)
    if not token or not convo:
        return None
    if convo["reservation"].get("kind") == "inquiry" and convo["reservation"]["id"] not in _inquiry_messages:
        return None  # nothing newer to fetch for an inquiry outside a full check
    async with Hospitable(token) as api:
        msgs = await _messages(api, convo["reservation"])
    return await _handle_conversation(convo["reservation"], msgs)


def draft_on_request(reservation_id: str) -> int | None:
    """You pressed 'Suggest a reply': make (or reuse) a draft for the guest's latest message."""
    convo = conversations.load(reservation_id)
    if not convo:
        return None
    msgs = convo["messages"]
    guest_msgs = [m for m in msgs if m["role"] == "guest"]
    if not guest_msgs:
        return None
    last_guest = guest_msgs[-1]
    r = convo["reservation"]
    with Session(engine) as db:
        open_draft = _open_draft(db, reservation_id)
        if open_draft:
            return open_draft.id
        d = db.exec(select(Draft).where(Draft.guest_message_id == last_guest["id"])).first()
        if d:
            d.status, d.error, d.updated_at = "ready", "", utcnow()  # bring an old one back
        else:
            d = Draft(
                reservation_id=reservation_id, guest_message_id=last_guest["id"], guest_name=r["guest_name"],
                property_name=r["property_name"], platform=r["platform"], arrival=r["arrival"],
                departure=r["departure"], guest_message=last_guest["body"],
            )
        db.add(d)
        db.commit()
        db.refresh(d)
        return d.id


def open_draft_for(reservation_id: str) -> Draft | None:
    with Session(engine) as db:
        return _open_draft(db, reservation_id)


# ---------- the two jobs ----------


async def check_now() -> None:
    """Look for guests waiting on a reply."""
    if _lock.locked():
        return
    async with _lock:
        with Session(engine) as db:
            token, _, _ = keys(db)
        if not token:
            return
        state["checking"] = True
        last_check.clear()
        last_check.update(started=_now_iso(), conversations=[], skipped=[])
        try:
            today = date.today()
            new_drafts = []
            async with Hospitable(token) as api:
                start, end = today - timedelta(days=WINDOW_BACK_DAYS), today + timedelta(days=WINDOW_AHEAD_DAYS)
                last_check["window"] = [start.isoformat(), end.isoformat()]
                for summary in await _reservations(api, start, end, with_inquiries=True):
                    try:
                        msgs = await _messages(api, summary)
                    except HospitableAuthError:
                        raise
                    except Exception as e:
                        # One conversation that won't open shouldn't hide all the others.
                        last_check["skipped"].append({"guest": summary["guest_name"], "kind": summary.get("kind", "stay"), "why": f"{type(e).__name__}: {e}"[:200]})
                        continue
                    last_check["conversations"].append({
                        "guest": summary["guest_name"], "kind": summary.get("kind", "stay"), "arrival": summary["arrival"],
                        "messages": len(msgs), "newest": msgs[-1]["at"] if msgs else "", "from": msgs[-1]["role"] if msgs else "",
                    })
                    draft_id = await _handle_conversation(summary, msgs)
                    if draft_id:
                        new_drafts.append(draft_id)
            for draft_id in new_drafts:
                await draft_for(draft_id)
            state["last_error"] = ""
        except HospitableError as e:
            state["last_error"] = str(e)
        except Exception as e:
            log.exception("check failed")
            import traceback
            last_check["trace"] = traceback.format_exc()[-1500:]
            state["last_error"] = f"Checking Hospitable failed ({type(e).__name__}). Savannah will try again."
        finally:
            state["checking"] = False
            state["last_check_at"] = _now_iso()
            last_check["finished"] = state["last_check_at"]
            last_check["error"] = state["last_error"]
            last_check["conversations"].sort(key=lambda c: c["newest"], reverse=True)
            _save_last_check()


async def import_history() -> None:
    """Copy the last two years of conversations into the folder so drafts sound like you."""
    imp = state["import"]
    if imp["running"]:
        return
    with Session(engine) as db:
        token, _, _ = keys(db)
    if not token:
        imp["error"] = "Connect Hospitable in Settings first."
        return
    imp.update(running=True, done=0, total=0, error="", finished_at=None)
    try:
        today = date.today()
        async with Hospitable(token) as api:
            reservations = await _reservations(api, today - timedelta(days=HISTORY_DAYS), today + timedelta(days=WINDOW_AHEAD_DAYS))
            imp["total"] = len(reservations)
            for summary in reservations:
                msgs = await _messages(api, summary)
                conversations.save(summary, msgs)
                imp["done"] += 1
                await asyncio.sleep(0.2)  # be gentle with Hospitable
    except HospitableError as e:
        imp["error"] = str(e)
    except Exception as e:
        log.exception("import failed")
        imp["error"] = f"Learning stopped early ({type(e).__name__}). Press the button to continue."
    finally:
        imp["running"] = False
        imp["finished_at"] = _now_iso()


async def watcher() -> None:
    await asyncio.sleep(5)
    while True:
        try:
            await check_now()
        except Exception:
            log.exception("watcher")
        await asyncio.sleep(CHECK_EVERY_MINUTES * 60)
