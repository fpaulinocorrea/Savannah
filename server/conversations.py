"""The conversations folder: one file per reservation, in data/conversations/.

This folder is Savannah's memory. Every past chat and every reply you send lands here,
so drafts keep getting closer to how you write.
"""

import json
import math
import re
from collections import Counter

from . import config
from .hospitable import message_role


def _path(reservation_id: str):
    safe = re.sub(r"[^A-Za-z0-9_-]", "", reservation_id)
    return config.CONVERSATIONS_DIR / f"{safe}.json"


def clean_messages(raw: list[dict]) -> list[dict]:
    msgs = []
    for m in raw:
        body = (m.get("body") or "").strip()
        if not body:
            continue
        msgs.append({"id": str(m.get("id", "")), "role": message_role(m), "body": body, "at": m.get("created_at") or ""})
    msgs.sort(key=lambda m: m["at"])
    return msgs


def save(reservation: dict, messages: list[dict]) -> None:
    config.CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)
    _path(reservation["id"]).write_text(
        json.dumps({"reservation": reservation, "messages": messages}, indent=2, ensure_ascii=False)
    )


def load(reservation_id: str) -> dict | None:
    p = _path(reservation_id)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def append_message(reservation_id: str, message: dict) -> None:
    convo = load(reservation_id)
    if not convo:
        return
    if not any(m["id"] == message["id"] for m in convo["messages"]):
        convo["messages"].append(message)
    save(convo["reservation"], convo["messages"])


def load_all() -> list[dict]:
    if not config.CONVERSATIONS_DIR.exists():
        return []
    out = []
    for p in config.CONVERSATIONS_DIR.glob("*.json"):
        try:
            out.append(json.loads(p.read_text()))
        except (ValueError, OSError):
            continue
    return out


# ---------- turning history into examples of how you reply ----------


def _turns(messages: list[dict]) -> list[tuple[str, str]]:
    """Group back-to-back messages from the same side into one turn."""
    turns: list[tuple[str, str]] = []
    for m in messages:
        if turns and turns[-1][0] == m["role"]:
            turns[-1] = (m["role"], turns[-1][1] + "\n" + m["body"])
        else:
            turns.append((m["role"], m["body"]))
    return turns


def examples() -> list[dict]:
    """Every (guest wrote → you replied) pair across all conversations."""
    pairs = []
    for convo in load_all():
        turns = _turns(convo.get("messages", []))
        prop = convo.get("reservation", {}).get("property_name", "")
        for (r1, guest), (r2, host) in zip(turns, turns[1:]):
            if r1 == "guest" and r2 == "host":
                pairs.append({"guest": guest[:1500], "host": host[:1500], "property": prop})
    return pairs


def stats() -> dict:
    convos = load_all()
    return {"conversations": len(convos), "examples": len(examples()) if convos else 0}


_WORD = re.compile(r"[a-zà-ÿ0-9']+")
_STOP = set("the a an and or to of in on for is it i you we my your our be are was this that with at as do can have has me us so if just".split())


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


def similar(question: str, property_name: str, k: int = 6) -> list[dict]:
    """Past exchanges most like this new guest message (simple word-overlap scoring)."""
    pairs = examples()
    if not pairs:
        return []
    docs = [Counter(_tokens(p["guest"])) for p in pairs]
    df = Counter(w for d in docs for w in d)
    n = len(docs)
    idf = {w: math.log((n + 1) / (c + 1)) + 1 for w, c in df.items()}
    q = Counter(_tokens(question))

    def vec_norm(d):
        return math.sqrt(sum((c * idf.get(w, 1)) ** 2 for w, c in d.items())) or 1

    qn = vec_norm(q)
    scored = []
    for p, d in zip(pairs, docs):
        dot = sum(c * idf.get(w, 1) * d.get(w, 0) * idf.get(w, 1) for w, c in q.items())
        score = dot / (qn * vec_norm(d))
        if property_name and p["property"] == property_name:
            score *= 1.25  # same home: its details are more likely right
        scored.append((score, p))
    scored.sort(key=lambda s: s[0], reverse=True)
    top = [p for s, p in scored[:k] if s > 0]
    # Always show a few examples of your voice, even if nothing matches closely.
    if len(top) < 3:
        top += [p for _, p in scored[len(top) : len(top) + (3 - len(top))]]
    return top
