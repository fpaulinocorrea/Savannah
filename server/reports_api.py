"""Report routes: /api/reports/*"""

import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from . import forecast, reports
from .auth import require_login
from .db import engine, get_setting, set_setting
from .hospitable import Hospitable, HospitableError, is_cancelled, reservation_summary

router = APIRouter()


def _dates(start: str, end: str) -> tuple[date, date]:
    try:
        s, e = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise HTTPException(422, "Pick a start and end date.")
    if e < s:
        raise HTTPException(422, "The end date is before the start date.")
    return s, e


@router.get("/api/reports/pl")
def pl(start: str, end: str, breakdown: str = "", compare: str = "", db: Session = Depends(require_login)):
    s, e = _dates(start, end)
    return reports.profit_and_loss(db, s, e, breakdown, compare)


@router.get("/api/reports/cashflow")
def cashflow(start: str, end: str, breakdown: str = "", db: Session = Depends(require_login)):
    s, e = _dates(start, end)
    return reports.cash_flow(db, s, e, breakdown)


@router.get("/api/reports/balance-sheet")
def balance_sheet(as_of: str, compare: str = "", db: Session = Depends(require_login)):
    try:
        d = date.fromisoformat(as_of)
    except ValueError:
        raise HTTPException(422, "Pick a date.")
    return reports.balance_sheet(db, d, compare)


@router.get("/api/reports/detail")
def detail(report: str, path: str, end: str, start: str = "", db: Session = Depends(require_login)):
    try:
        e = date.fromisoformat(end)
        s = date.fromisoformat(start) if start else None
    except ValueError:
        raise HTTPException(422, "Pick dates.")
    if report not in ("pl", "cashflow", "bs"):
        raise HTTPException(422, "Unknown report.")
    return reports.detail(db, report, path, s, e)


@router.get("/api/reports/range")
def data_range(db: Session = Depends(require_login)):
    """First and last dates with transactions, for the 'All time' choice."""
    from sqlalchemy import func
    from .ledger import Txn
    lo, hi = db.exec(select(func.min(Txn.date), func.max(Txn.date)).where(Txn.hidden == False)).one()  # noqa: E712
    return {"first": lo.isoformat() if lo else None, "last": hi.isoformat() if hi else None}


# ---------- coming income ----------


async def _fetch_bookings(token: str) -> list[dict]:
    today = date.today()
    async with Hospitable(token) as api:
        props = await api.properties()
        names = {p.get("id", ""): p.get("public_name") or p.get("name") or "" for p in props}
        raw = await api.reservations([p["id"] for p in props if p.get("id")], today, today + timedelta(days=365), "guest,properties,financials")
    rows, sample = [], []
    for r in raw:
        summ = reservation_summary(r, names)
        if is_cancelled(summ) or not summ["arrival"] or summ["arrival"] < today.isoformat():
            continue
        status = summ["status"].lower()
        if status and status not in ("accepted", "confirmed", "booked", "checkpoint"):
            continue  # requests and inquiries aren't income yet
        fin = r.get("financials")
        if len(sample) < 3 and fin:
            sample.append({"platform": summ["platform"], "financials": fin})
        rows.append({**summ, "payout_cents": reports.payout_cents(fin), "nights": r.get("nights")})
    rows.sort(key=lambda x: x["arrival"])
    reports.save_bookings(rows, sample)
    return rows


async def _bookings(db: Session, refresh: bool) -> tuple[str | None, dict | None, str]:
    """Upcoming bookings (a 30-minute copy is kept). Returns (token, cached, error)."""
    token = get_setting(db, "hospitable_token")
    cached = reports.load_bookings()
    fresh_enough = False
    if cached:
        saved = datetime.fromisoformat(cached["saved_at"])
        fresh_enough = datetime.now(timezone.utc) - saved < timedelta(minutes=30)
    error = ""
    if token and (refresh or not fresh_enough):
        try:
            await _fetch_bookings(token)
        except HospitableError as e:
            error = str(e)
        cached = reports.load_bookings()
    return token, cached, error


@router.get("/api/reports/upcoming")
async def upcoming(refresh: bool = False, db: Session = Depends(require_login)):
    token, cached, error = await _bookings(db, refresh)
    if not token and not cached:
        raise HTTPException(409, "Connect Hospitable in Settings to see income from upcoming bookings.")
    rows = (cached or {}).get("bookings", [])
    months: dict[str, dict] = {}
    for b in rows:
        key = b["arrival"][:7]
        m = months.setdefault(key, {"month": key, "count": 0, "payout_cents": 0, "missing": 0})
        m["count"] += 1
        if b["payout_cents"] is None:
            m["missing"] += 1
        else:
            m["payout_cents"] += b["payout_cents"]
    return {
        "saved_at": (cached or {}).get("saved_at"),
        "error": error,
        "bookings": rows,
        "months": [months[k] for k in sorted(months)],
        "total_cents": sum(b["payout_cents"] or 0 for b in rows),
        "missing": sum(1 for b in rows if b["payout_cents"] is None),
    }


# ---------- cash forecast ----------

FORECAST_MIN_KEY = "forecast_min_cents"
FORECAST_MIN_DEFAULT = 100000  # $1,000 until you pick your own


@router.get("/api/reports/forecast")
async def cash_forecast(refresh: bool = False, db: Session = Depends(require_login)):
    _, cached, error = await _bookings(db, refresh)
    from . import plaid

    bills = await plaid.card_bills(db, force=refresh)
    data = forecast.build(db, date.today(), (cached or {}).get("bookings", []), bills=bills, choices=forecast.load_choices(db))
    data["bills_fetched_at"] = bills.get("fetched_at")
    saved = get_setting(db, FORECAST_MIN_KEY)
    data["min_cents"] = int(saved) if saved not in (None, "") else FORECAST_MIN_DEFAULT
    data["bookings_saved_at"] = (cached or {}).get("saved_at")
    data["bookings_error"] = error
    data["hospitable_connected"] = bool(cached)
    return data


class MinBody(BaseModel):
    cents: int


@router.post("/api/reports/forecast/minimum")
def set_forecast_min(body: MinBody, db: Session = Depends(require_login)):
    if body.cents < 0 or body.cents > 100_000_000:
        raise HTTPException(422, "Pick an amount between $0 and $1,000,000.")
    set_setting(db, FORECAST_MIN_KEY, str(body.cents))
    return {"min_cents": body.cents}


class ChoicesBody(BaseModel):
    cards: dict[str, str] = {}
    categories: dict[str, str] = {}
    cleaning: dict[str, int | None] = {}


@router.post("/api/reports/forecast/choices")
def set_forecast_choices(body: ChoicesBody, db: Session = Depends(require_login)):
    return forecast.save_choices(db, body.model_dump())


# ---------- saved layouts ----------


class ViewBody(BaseModel):
    name: str
    report: str
    config: dict


@router.get("/api/reports/views")
def views(db: Session = Depends(require_login)):
    return [
        {"id": v.id, "name": v.name, "report": v.report, "config": json.loads(v.config or "{}")}
        for v in db.exec(select(reports.ReportView).order_by(reports.ReportView.created_at)).all()
    ]


@router.post("/api/reports/views")
def save_view(body: ViewBody, db: Session = Depends(require_login)):
    name = body.name.strip()[:60]
    if not name:
        raise HTTPException(422, "Give this layout a name.")
    if body.report not in ("pl", "cashflow", "bs", "upcoming"):
        raise HTTPException(422, "Unknown report.")
    existing = db.exec(select(reports.ReportView).where(reports.ReportView.name == name, reports.ReportView.report == body.report)).first()
    v = existing or reports.ReportView(name=name, report=body.report)
    v.config = json.dumps(body.config)
    db.add(v)
    db.commit()
    db.refresh(v)
    return {"id": v.id, "name": v.name, "report": v.report, "config": body.config}


@router.delete("/api/reports/views/{view_id}")
def delete_view(view_id: int, db: Session = Depends(require_login)):
    v = db.get(reports.ReportView, view_id)
    if v:
        db.delete(v)
        db.commit()
    return {"ok": True}
