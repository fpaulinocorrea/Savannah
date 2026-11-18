"""Savannah's web server: the API under /api and the screens everywhere else."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from . import VERSION, books_api, config, conversations, drafting, hooks, plaid, reports_api, sync
from .auth import (
    COOKIE,
    MIN_PASSWORD,
    check_password,
    get_db,
    is_set_up,
    require_login,
    save_password,
    session_is_valid,
    slow_down,
    start_session,
)
from .db import Draft, LoginSession, delete_setting, get_setting, init_db, set_setting, utcnow
from .hospitable import Hospitable, HospitableAuthError, HospitableError
from .netinfo import phone_urls


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    tasks = [asyncio.create_task(sync.watcher()), asyncio.create_task(plaid.watcher())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Savannah", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(books_api.router)
app.include_router(reports_api.router)
app.include_router(hooks.router)


def set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=config.SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
    )


# ---------- Signing in ----------


class SetupBody(BaseModel):
    name: str
    password: str


class LoginBody(BaseModel):
    password: str


class PasswordBody(BaseModel):
    current: str
    new: str


@app.get("/api/status")
def status(db: Session = Depends(get_db), savannah_session: str | None = Cookie(default=None)):
    return {
        "set_up": is_set_up(db),
        "signed_in": session_is_valid(db, savannah_session),
        "name": get_setting(db, "owner_name") or "",
        "version": VERSION,
    }


@app.post("/api/setup")
def setup(body: SetupBody, request: Request, response: Response, db: Session = Depends(get_db)):
    if is_set_up(db):
        raise HTTPException(409, "Savannah is already set up. Sign in instead.")
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Enter your first name.")
    if len(body.password) < MIN_PASSWORD:
        raise HTTPException(422, f"Use at least {MIN_PASSWORD} characters for your password.")
    set_setting(db, "owner_name", name[:60])
    save_password(db, body.password)
    set_cookie(response, start_session(db, request))
    return {"ok": True}


@app.post("/api/login")
async def login(body: LoginBody, request: Request, response: Response, db: Session = Depends(get_db)):
    stored = get_setting(db, "password_hash")
    if not stored:
        raise HTTPException(409, "Savannah isn't set up yet.")
    if not check_password(body.password, stored):
        await slow_down()
        raise HTTPException(401, "That password doesn't match. Try again.")
    set_cookie(response, start_session(db, request))
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response, db: Session = Depends(get_db), savannah_session: str | None = Cookie(default=None)):
    if savannah_session:
        row = db.get(LoginSession, savannah_session)
        if row:
            db.delete(row)
            db.commit()
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.post("/api/password")
async def change_password(body: PasswordBody, db: Session = Depends(require_login)):
    if not check_password(body.current, get_setting(db, "password_hash") or ""):
        await slow_down()
        raise HTTPException(401, "Your current password doesn't match.")
    if len(body.new) < MIN_PASSWORD:
        raise HTTPException(422, f"Use at least {MIN_PASSWORD} characters for your new password.")
    save_password(db, body.new)
    return {"ok": True}


# ---------- About this computer ----------


@app.get("/api/system")
def system(db: Session = Depends(require_login)):
    return {
        "version": VERSION,
        "phone_urls": phone_urls(config.PORT),
        "data_folder": str(config.DATA_DIR),
        "conversations_folder": str(config.CONVERSATIONS_DIR),
    }


# ---------- Connections (Hospitable + Claude keys) ----------

KEY_NAMES = {"hospitable": "hospitable_token", "claude": "claude_key"}


class KeyBody(BaseModel):
    key: str


def _key_info(db: Session, name: str) -> dict:
    value = get_setting(db, KEY_NAMES[name]) or ""
    return {"saved": bool(value), "ending": value[-4:] if value else ""}


@app.get("/api/connections")
def connections(db: Session = Depends(require_login)):
    info = {name: _key_info(db, name) for name in KEY_NAMES}
    cid = get_setting(db, "plaid_client_id") or ""
    info["plaid"] = {"saved": bool(cid and get_setting(db, "plaid_secret")), "ending": cid[-4:]}
    return info


@app.post("/api/connections/{name}")
async def save_connection(name: str, body: KeyBody, background: BackgroundTasks, db: Session = Depends(require_login)):
    if name not in KEY_NAMES:
        raise HTTPException(404, "Unknown connection.")
    key = body.key.strip()
    if len(key) < 20:
        raise HTTPException(422, "That key looks too short. Copy the whole thing and paste it again.")
    if name == "claude" and not key.startswith("sk-ant-"):
        raise HTTPException(422, "Claude keys start with sk-ant-. Check you copied the right one.")
    result = await _test(name, key)
    if result.pop("rejected", False):
        return result  # a refused key is never saved, so a working one isn't replaced
    set_setting(db, KEY_NAMES[name], key)
    if not result["ok"]:
        result["message"] = "Saved, but couldn't check it right now: " + result["message"]
    if result["ok"] and name == "hospitable":
        background.add_task(_first_sync)
    if result["ok"] and name == "claude":
        background.add_task(_redraft_errors)
    return result


async def _first_sync() -> None:
    """Right after connecting: learn from history first (if not done yet), then look for waiting guests."""
    if conversations.stats()["conversations"] < 3:
        await sync.import_history()
    await sync.check_now()


async def _redraft_errors() -> None:
    with Session(sync.engine) as s:
        ids = [d.id for d in s.exec(select(Draft).where(Draft.status == "error")).all()]
    for draft_id in ids:
        await sync.draft_for(draft_id)


@app.post("/api/connections/{name}/test")
async def test_connection(name: str, db: Session = Depends(require_login)):
    if name not in KEY_NAMES:
        raise HTTPException(404, "Unknown connection.")
    key = get_setting(db, KEY_NAMES[name])
    if not key:
        return {"ok": False, "message": "No key saved yet."}
    result = await _test(name, key)
    result.pop("rejected", None)
    return result


@app.delete("/api/connections/{name}")
def remove_connection(name: str, db: Session = Depends(require_login)):
    if name not in KEY_NAMES:
        raise HTTPException(404, "Unknown connection.")
    delete_setting(db, KEY_NAMES[name])
    return {"ok": True}


async def _test(name: str, key: str) -> dict:
    try:
        if name == "hospitable":
            async with Hospitable(key) as api:
                props = await api.properties()
            names = [p.get("public_name") or p.get("name") or "Unnamed" for p in props]
            return {"ok": True, "message": f"Connected. {len(props)} home{'s' if len(props) != 1 else ''} found.", "homes": names}
        await drafting.test_key(key)
        return {"ok": True, "message": "Connected. Savannah can write drafts."}
    except (HospitableAuthError, drafting.KeyRejected) as e:
        return {"ok": False, "message": str(e), "rejected": True}
    except (HospitableError, drafting.DraftError) as e:
        return {"ok": False, "message": str(e)}


# ---------- Guests: drafts waiting for you ----------


def _draft_json(d: Draft) -> dict:
    return {
        "id": d.id,
        "reservation_id": d.reservation_id,
        "guest_name": d.guest_name,
        "property_name": d.property_name,
        "platform": d.platform,
        "arrival": d.arrival,
        "departure": d.departure,
        "guest_message": d.guest_message,
        "draft_text": d.draft_text,
        "status": d.status,
        "error": d.error,
        "created_at": d.created_at.isoformat(),
        "sent_at": d.sent_at.isoformat() if d.sent_at else None,
    }


@app.get("/api/guests")
def guests(db: Session = Depends(require_login)):
    open_drafts = db.exec(
        select(Draft).where(Draft.status.in_(["drafting", "ready", "error"])).order_by(Draft.created_at.desc())
    ).all()
    since = utcnow() - timedelta(days=2)
    sent = db.exec(
        select(Draft).where(Draft.status == "sent", Draft.sent_at >= since).order_by(Draft.sent_at.desc())
    ).all()
    return {
        "hospitable_connected": bool(get_setting(db, "hospitable_token")),
        "claude_connected": bool(get_setting(db, "claude_key")),
        "mode": "suggest",
        "last_check_at": sync.state["last_check_at"],
        "checking": sync.state["checking"],
        "last_error": sync.state["last_error"],
        "import": sync.state["import"],
        "memory": conversations.stats(),
        "waiting": [_draft_json(d) for d in open_drafts],
        "sent": [_draft_json(d) for d in sent],
    }


_tasks: set[asyncio.Task] = set()


def _background(coro) -> None:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def _when(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


@app.get("/api/guests/inbox")
def inbox(view: str = "all", q: str = "", offset: int = 0, db: Session = Depends(require_login)):
    """Every conversation, newest message first (like Hospitable's inbox)."""
    open_drafts = {
        d.reservation_id: d
        for d in db.exec(select(Draft).where(Draft.status.in_(["drafting", "ready", "error"]))).all()
    }
    rows = []
    for convo in conversations.load_all():
        msgs = convo.get("messages") or []
        if not msgs:
            continue
        r = convo["reservation"]
        last = msgs[-1]
        d = open_drafts.get(r["id"])
        rows.append({
            "reservation_id": r["id"], "guest_name": r.get("guest_name", ""), "photo": r.get("photo", ""), "property_name": r.get("property_name", ""),
            "platform": r.get("platform", ""), "arrival": r.get("arrival", ""), "departure": r.get("departure", ""),
            "last_role": last["role"], "last_body": last["body"][:160], "last_at": last["at"],
            "needs_reply": last["role"] == "guest", "draft_status": d.status if d else "", "kind": r.get("kind", "stay"),
        })
    waiting = sum(1 for x in rows if x["needs_reply"])
    if view == "waiting":
        rows = [x for x in rows if x["needs_reply"]]
    if q:
        ql = q.lower()
        rows = [x for x in rows if ql in x["guest_name"].lower() or ql in x["property_name"].lower()]
    rows.sort(key=lambda x: _when(x["last_at"]), reverse=True)
    return {"total": len(rows), "waiting": waiting, "items": rows[offset : offset + 60]}


def _conversation_json(reservation_id: str) -> dict:
    convo = conversations.load(reservation_id)
    if not convo:
        raise HTTPException(404, "Conversation not found.")
    d = sync.open_draft_for(reservation_id)
    return {
        "reservation": convo["reservation"],
        "messages": convo["messages"][-200:],
        "draft": _draft_json(d) if d else None,
    }


@app.get("/api/guests/conversation/{reservation_id}")
async def conversation(reservation_id: str, fresh: bool = False, db: Session = Depends(require_login)):
    if fresh:  # opening a conversation: get the latest from Hospitable first
        try:
            draft_id = await asyncio.wait_for(sync.refresh_one(reservation_id), timeout=15)
            if draft_id:
                _background(sync.draft_for(draft_id))
        except (HospitableError, asyncio.TimeoutError):
            pass  # show what's saved; the watcher will catch up
    return _conversation_json(reservation_id)


class ReplyBody(BaseModel):
    text: str


@app.post("/api/guests/conversation/{reservation_id}/send")
async def send_reply(reservation_id: str, body: ReplyBody, db: Session = Depends(require_login)):
    """Send a reply you wrote yourself (or edited from a suggestion)."""
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Write a reply before sending.")
    if "[ADD:" in text.upper():
        raise HTTPException(422, "Fill in the [ADD: …] part before sending.")
    token = get_setting(db, "hospitable_token")
    if not token:
        raise HTTPException(409, "Connect Hospitable in Settings first.")
    if not conversations.load(reservation_id):
        raise HTTPException(404, "Conversation not found.")
    try:
        async with Hospitable(token) as api:
            sent = await api.send(reservation_id, text, inquiry=sync.is_inquiry(reservation_id))
    except HospitableError as e:
        raise HTTPException(502, str(e))
    d = sync.open_draft_for(reservation_id)
    if d:
        d = db.get(Draft, d.id)
        d.draft_text, d.status, d.sent_at, d.updated_at = text, "sent", utcnow(), utcnow()
        db.add(d)
        db.commit()
    conversations.append_message(
        reservation_id,
        {"id": str(sent.get("id") or f"sent-{utcnow().timestamp()}"), "role": "host", "body": text,
         "at": sent.get("created_at") or utcnow().isoformat()},
    )
    return _conversation_json(reservation_id)


class ImproveBody(BaseModel):
    text: str
    adjust: str = ""


@app.post("/api/guests/conversation/{reservation_id}/improve")
async def improve(reservation_id: str, body: ImproveBody, db: Session = Depends(require_login)):
    """Rewrite what you typed into a better version (keeps your meaning)."""
    key = get_setting(db, "claude_key")
    if not key:
        raise HTTPException(409, "Add your Claude key in Settings first.")
    typed = body.text.strip()
    if not typed:
        raise HTTPException(422, "Type something first.")
    convo = conversations.load(reservation_id)
    if not convo:
        raise HTTPException(404, "Conversation not found.")
    try:
        text = await drafting.improve_reply(key, get_setting(db, "owner_name") or "", convo["reservation"], convo["messages"], typed, body.adjust)
    except drafting.DraftError as e:
        raise HTTPException(502, str(e))
    return {"text": text}


@app.post("/api/guests/conversation/{reservation_id}/suggest")
def suggest(reservation_id: str, db: Session = Depends(require_login)):
    if not get_setting(db, "claude_key"):
        raise HTTPException(409, "Add your Claude key in Settings first.")
    draft_id = sync.draft_on_request(reservation_id)
    if not draft_id:
        raise HTTPException(422, "There's no guest message to reply to yet.")
    _background(sync.draft_for(draft_id))
    return {"ok": True, "draft_id": draft_id}


@app.post("/api/guests/check")
async def check(db: Session = Depends(require_login)):
    """Check Hospitable now and answer when done, so the inbox can refresh straight away."""
    if not get_setting(db, "hospitable_token"):
        raise HTTPException(409, "Connect Hospitable in Settings first.")
    await sync.check_now()
    return {"ok": True, "error": sync.state["last_error"]}


@app.post("/api/guests/learn")
def learn(background: BackgroundTasks, db: Session = Depends(require_login)):
    if not get_setting(db, "hospitable_token"):
        raise HTTPException(409, "Connect Hospitable in Settings first.")
    background.add_task(sync.import_history)
    return {"ok": True}


class SendBody(BaseModel):
    text: str


class RewriteBody(BaseModel):
    adjust: str = ""


def _get_draft(db: Session, draft_id: int) -> Draft:
    d = db.get(Draft, draft_id)
    if not d:
        raise HTTPException(404, "That draft is gone. Refresh the page.")
    return d


@app.post("/api/drafts/{draft_id}/send")
async def send_draft(draft_id: int, body: SendBody, db: Session = Depends(require_login)):
    d = _get_draft(db, draft_id)
    if d.status == "sent":
        raise HTTPException(409, "This reply was already sent.")
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Write a reply before sending.")
    if "[ADD:" in text.upper():
        raise HTTPException(422, "Fill in the [ADD: …] part before sending.")
    token = get_setting(db, "hospitable_token")
    if not token:
        raise HTTPException(409, "Connect Hospitable in Settings first.")
    try:
        async with Hospitable(token) as api:
            sent = await api.send(d.reservation_id, text, inquiry=sync.is_inquiry(d.reservation_id))
    except HospitableError as e:
        raise HTTPException(502, str(e))
    d.draft_text, d.status, d.sent_at, d.updated_at = text, "sent", utcnow(), utcnow()
    db.add(d)
    db.commit()
    # Remember it: every reply you send teaches the next draft.
    conversations.append_message(
        d.reservation_id,
        {"id": str(sent.get("id") or f"sent-{d.id}"), "role": "host", "body": text, "at": sent.get("created_at") or utcnow().isoformat()},
    )
    return {"ok": True}


@app.post("/api/drafts/{draft_id}/rewrite")
async def rewrite_draft(draft_id: int, body: RewriteBody, db: Session = Depends(require_login)):
    d = _get_draft(db, draft_id)
    if d.status not in ("ready", "error"):
        raise HTTPException(409, "This draft can't be rewritten now.")
    task = asyncio.create_task(sync.draft_for(draft_id, body.adjust))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return {"ok": True}


_running: set[asyncio.Task] = set()


@app.post("/api/drafts/{draft_id}/skip")
def skip_draft(draft_id: int, db: Session = Depends(require_login)):
    d = _get_draft(db, draft_id)
    d.status, d.updated_at = "skipped", utcnow()
    db.add(d)
    db.commit()
    return {"ok": True}


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def api_not_found(rest: str):
    return JSONResponse({"detail": "Not found."}, status_code=404)


# ---------- The screens ----------


@app.get("/{path:path}")
def screens(path: str):
    index = config.WEB_DIR / "index.html"
    if not index.exists():
        return JSONResponse(
            {"detail": "The screens aren't built yet. Run: cd web && npm install && npm run build"},
            status_code=503,
        )
    target = (config.WEB_DIR / path).resolve()
    if path and target.is_file() and config.WEB_DIR.resolve() in target.parents:
        headers = {"Cache-Control": "no-cache"} if target.name in ("sw.js", "manifest.webmanifest") else None
        return FileResponse(target, headers=headers)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
