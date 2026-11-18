"""Instant alerts: Hospitable calls this the moment a guest writes.

Only /hooks/... is reachable from the internet (through the Cloudflare tunnel).
The link carries a long secret, so nobody can guess it.
"""

import asyncio
import hmac
import json
import logging
import secrets
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from . import config, conversations, sync
from .auth import require_login
from .db import engine, get_setting, set_setting

log = logging.getLogger("savannah.hooks")
router = APIRouter()

state = {"last_at": None, "last_action": "", "count": 0}
_tasks: set[asyncio.Task] = set()
_again = {"pending": False}


def _secret(db: Session) -> str:
    s = get_setting(db, "hook_secret")
    if not s:
        s = secrets.token_urlsafe(24)
        set_setting(db, "hook_secret", s)
    return s


def _link(db: Session) -> str:
    host = (get_setting(db, "hook_host") or "").strip()
    if not host:
        return ""
    scheme = "http" if host.startswith(("localhost", "127.0.0.1")) else "https"  # http only for testing at home
    return f"{scheme}://{host}/hooks/hospitable/{_secret(db)}"


def _find_ids(data: dict) -> list[str]:
    """Reservation or inquiry ids mentioned in the alert, whatever shape it comes in."""
    ids = []
    for key in ("reservation_id", "inquiry_id", "conversation_id", "reservation_uuid", "inquiry_uuid"):
        v = data.get(key)
        if isinstance(v, str) and v:
            ids.append(v)
    for key in ("reservation", "inquiry"):
        v = data.get(key)
        if isinstance(v, dict) and isinstance(v.get("id"), str):
            ids.append(v["id"])
    if isinstance(data.get("id"), str):
        ids.append(data["id"])
    return ids


async def _check_soon() -> None:
    """Run a full check; if one is already running, run once more right after."""
    if sync._lock.locked():
        _again["pending"] = True
        return
    await sync.check_now()
    while _again["pending"]:
        _again["pending"] = False
        await sync.check_now()


async def _handle(action: str, data: dict) -> None:
    try:
        known = [i for i in _find_ids(data) if conversations.load(i)]
        if known and action.startswith("message"):
            draft_id = await sync.refresh_one(known[0])
            if draft_id:
                await sync.draft_for(draft_id)
        else:
            await _check_soon()  # a new guest or new booking: look at everything
    except Exception:
        log.exception("instant alert")


@router.post("/hooks/hospitable/{key}")
async def receive(key: str, request: Request):
    with Session(engine) as db:
        secret = get_setting(db, "hook_secret") or ""
    if not secret or not hmac.compare_digest(key, secret):
        raise HTTPException(404, "Not found.")
    try:
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        body = {}
    action = str(body.get("action") or body.get("event") or "")
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    state.update(last_at=datetime.now(timezone.utc).isoformat(), last_action=action, count=state["count"] + 1)
    try:  # what arrived (field names only, no message text), to see the shape if something's off
        (config.DATA_DIR / "last-alert.json").write_text(json.dumps(
            {"at": state["last_at"], "action": action, "fields": sorted(data.keys()), "ids": _find_ids(data)}, indent=1))
    except OSError:
        pass
    if action != "savannah.test":
        t = asyncio.create_task(_handle(action, data))
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)
    return {"ok": True}


@router.get("/hooks")
@router.get("/hooks/{rest:path}")
def no_browsing(rest: str = ""):
    """The alert door only takes deliveries; there's nothing to look at."""
    raise HTTPException(404, "Not found.")


# ---------- Settings ----------


def _info(db: Session) -> dict:
    return {"host": get_setting(db, "hook_host") or "", "link": _link(db), **state}


@router.get("/api/hooks")
def hooks_info(db: Session = Depends(require_login)):
    return _info(db)


class HostBody(BaseModel):
    host: str


@router.post("/api/hooks")
def set_host(body: HostBody, db: Session = Depends(require_login)):
    host = body.host.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0]
    if host and (" " in host or ("." not in host and not host.startswith("localhost"))):
        raise HTTPException(422, "Type just the address, like hooks.sproutly-app.com")
    set_setting(db, "hook_host", host)
    return _info(db)


@router.post("/api/hooks/test")
async def test(db: Session = Depends(require_login)):
    """Knock on our own door from the internet side, through the tunnel."""
    link = _link(db)
    if not link:
        raise HTTPException(409, "Type your tunnel address first.")
    before = state["count"]
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(link, json={"action": "savannah.test", "data": {}})
    except httpx.ConnectError:
        return {"ok": False, "message": "This computer can't look up that address yet. That's normal for a few hours after setting up a new domain, and Hospitable may already reach it fine. If step 3 turns green when a guest writes, it works."}
    except httpx.HTTPError:
        return {"ok": False, "message": "Couldn't reach that address. Check the tunnel is running and the address is right."}
    if r.status_code == 200 and state["count"] > before:
        return {"ok": True, "message": "Working! Hospitable can reach Savannah."}
    if r.status_code in (404, 403) and state["count"] == before:
        return {"ok": False, "message": f"The address answered ({r.status_code}) but didn't reach Savannah. Check the tunnel's Path is hooks and the URL is localhost:8800."}
    return {"ok": False, "message": f"Something answered with {r.status_code}, but not Savannah. Check the tunnel settings."}
