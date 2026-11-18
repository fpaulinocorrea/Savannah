"""Talking to Hospitable (public API v2).

Docs: https://developer.hospitable.com  — base URL https://public.api.hospitable.com/v2
We use: list properties, list reservations and inquiries, read messages, send a message.
"""

import asyncio
import os
import uuid
from datetime import date

import httpx

BASE_URL = os.environ.get("HOSPITABLE_BASE_URL", "https://public.api.hospitable.com/v2")


class HospitableError(Exception):
    """A problem worth showing to the person, in plain words."""


class HospitableAuthError(HospitableError):
    """The access key was refused."""


class Hospitable:
    def __init__(self, token: str, base_url: str = BASE_URL):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token.strip()}", "Accept": "application/json"},
            timeout=30,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self._client.aclose()

    # ---------- low level ----------

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        for attempt in range(5):
            try:
                res = await self._client.request(method, path, **kwargs)
            except httpx.HTTPError:
                if attempt == 4:
                    raise HospitableError("Can't reach Hospitable. Check this computer's internet connection.")
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if res.status_code == 429:  # too many requests: wait as told, then retry
                await asyncio.sleep(float(res.headers.get("Retry-After", 10)))
                continue
            if res.status_code >= 500:
                await asyncio.sleep(3 * (attempt + 1))
                continue
            if res.status_code in (401, 403):
                raise HospitableAuthError("Hospitable didn't accept this access key. Check you copied all of it, or make a new one in Hospitable.")
            if res.status_code >= 400:
                try:
                    detail = res.json().get("message", "")
                except ValueError:
                    detail = ""
                raise HospitableError(f"Hospitable said no ({res.status_code}). {detail}".strip())
            return res.json() if res.content else {}
        raise HospitableError("Hospitable is busy right now. Savannah will try again shortly.")

    async def _all_pages(self, path: str, params: list[tuple[str, str]]) -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            data = await self._request("GET", path, params=params + [("page", str(page)), ("per_page", "100")])
            items.extend(data.get("data") or [])
            meta = data.get("meta") or {}
            last = meta.get("last_page") or 1
            if page >= last or not data.get("data"):
                return items
            page += 1

    # ---------- what Savannah uses ----------

    async def properties(self) -> list[dict]:
        return await self._all_pages("/properties", [])

    async def reservations(self, property_ids: list[str], start: date, end: date, include: str = "guest,properties") -> list[dict]:
        if not property_ids:
            return []
        params = [("properties[]", pid) for pid in property_ids]
        params += [
            ("start_date", start.isoformat()),
            ("end_date", end.isoformat()),
            ("include", include),
        ]
        return await self._all_pages("/reservations", params)

    async def inquiries(self, property_ids: list[str]) -> list[dict]:
        """People asking before they book (Airbnb inquiries). Not part of /reservations."""
        props = [("properties[]", pid) for pid in property_ids]
        # Ask for the messages too; Hospitable has no separate "read inquiry messages" call.
        for params in (props + [("include", "guest,properties,messages")], props + [("include", "guest,properties")]):
            try:
                return await self._all_pages("/inquiries", params)
            except HospitableAuthError:
                raise
            except HospitableError:
                continue
        return []

    async def messages(self, reservation_id: str, inquiry: bool = False) -> list[dict]:
        kind = "inquiries" if inquiry else "reservations"
        data = await self._request("GET", f"/{kind}/{reservation_id}/messages")
        return data.get("data") or []

    async def send(self, reservation_id: str, body: str, inquiry: bool = False) -> dict:
        kind = "inquiries" if inquiry else "reservations"
        data = await self._request(
            "POST", f"/{kind}/{reservation_id}/messages", json={"body": body},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        return data.get("data") or {}


# ---------- reading reservation fields defensively ----------


def _photo(guest: dict) -> str:
    """The guest's profile picture, if Hospitable has one (public https link only)."""
    for key in ("picture_url", "thumbnail_url", "profile_picture", "picture", "avatar", "photo_url"):
        v = guest.get(key)
        if isinstance(v, dict):
            v = v.get("url") or v.get("large") or v.get("medium") or ""
        if isinstance(v, str) and v.startswith("https://"):
            return v
    return ""


def reservation_summary(res: dict, property_names: dict[str, str]) -> dict:
    guest = res.get("guest") or {}
    if isinstance(guest, dict) and isinstance(guest.get("data"), dict):
        guest = guest["data"]
    if not isinstance(guest, dict):
        guest = {}
    name = " ".join(x for x in [guest.get("first_name"), guest.get("last_name")] if x) or res.get("guest_name") or "Guest"
    props = res.get("properties") or res.get("property") or []
    if isinstance(props, dict):  # sometimes one home, sometimes a list, sometimes wrapped in "data"
        props = props.get("data", [props])
    if not isinstance(props, list):
        props = []
    first = props[0] if props and isinstance(props[0], dict) else {}
    prop_name = first.get("public_name") or first.get("name") or ""
    if not prop_name:
        prop_name = property_names.get(str(res.get("property_id") or first.get("id") or ""), "")
    status = res.get("reservation_status") or {}
    if isinstance(status, dict):
        status = (status.get("current") or {}).get("category") or ""
    return {
        "id": res.get("id", ""),
        "guest_name": name,
        "photo": _photo(guest),
        "property_name": prop_name,
        "platform": res.get("platform") or "",
        "arrival": str(res.get("arrival_date") or res.get("check_in") or "")[:10],
        "departure": str(res.get("departure_date") or res.get("check_out") or "")[:10],
        "status": str(status or res.get("status") or ""),
    }


def inquiry_summary(inq: dict, property_names: dict[str, str]) -> dict:
    s = reservation_summary(inq, property_names)
    prop = inq.get("property") or {}
    if isinstance(prop, dict) and isinstance(prop.get("data"), dict):
        prop = prop["data"]
    if not s["property_name"] and isinstance(prop, dict):
        s["property_name"] = prop.get("public_name") or prop.get("name") or property_names.get(prop.get("id", ""), "")
    ch = inq.get("channel") or ""
    s["platform"] = s["platform"] or (ch.get("name", "") if isinstance(ch, dict) else str(ch))
    if not isinstance(s["status"], str):
        s["status"] = str(s["status"])
    s["kind"] = "inquiry"
    return s


def is_cancelled(summary: dict) -> bool:
    s = summary.get("status", "").lower()
    return any(w in s for w in ("cancel", "declin", "expired", "withdr", "denied"))


def message_role(msg: dict) -> str:
    role = (msg.get("sender_role") or msg.get("sender_type") or "").lower()
    return "guest" if role == "guest" else "host"
