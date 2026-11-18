"""The database: one file, data/savannah.db."""

from datetime import datetime, timezone

from sqlmodel import Field, Session, SQLModel, create_engine, select

from . import config


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Setting(SQLModel, table=True):
    """Simple key/value settings (owner name, password hash, ...)."""

    key: str = Field(primary_key=True)
    value: str


class LoginSession(SQLModel, table=True):
    """One row per signed-in device."""

    token: str = Field(primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
    device: str = ""


class Draft(SQLModel, table=True):
    """A suggested reply waiting for you (or already handled)."""

    id: int | None = Field(default=None, primary_key=True)
    reservation_id: str = Field(index=True)
    guest_message_id: str = Field(index=True, unique=True)  # the guest message this answers
    guest_name: str = ""
    property_name: str = ""
    platform: str = ""
    arrival: str = ""
    departure: str = ""
    guest_message: str = ""
    draft_text: str = ""
    # drafting → ready → sent   (or: skipped, replaced, answered_elsewhere, error)
    status: str = Field(default="drafting", index=True)
    error: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    sent_at: datetime | None = None


class ConvoState(SQLModel, table=True):
    """What you decided about a conversation in Savannah's inbox."""

    reservation_id: str = Field(primary_key=True)
    archived_at: datetime | None = None  # hidden from the inbox (comes back if the guest writes again)
    handled_message_id: str = ""  # the guest message you marked as "already replied"
    updated_at: datetime = Field(default_factory=utcnow)


engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    from . import ledger, reports  # noqa: F401  (registers the bookkeeping and report tables)

    config.ensure_folders()
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()
    from . import fixups

    fixups.run_pending()


def _add_missing_columns() -> None:
    """Older databases get new fields added in place (nothing is removed or rewritten)."""
    from sqlalchemy import inspect, text

    wanted = {
        "rule": [("split_json", "VARCHAR DEFAULT ''"), ("mode", "VARCHAR DEFAULT 'auto'")],
        "bankaccount": [("ignored", "BOOLEAN DEFAULT 0"), ("full_history", "BOOLEAN DEFAULT 0")],
    }
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    if (table, name) == ("rule", "mode"):
                        # Split rules always asked you to check the amounts: keep them that way.
                        conn.execute(text("UPDATE rule SET mode = 'suggest' WHERE split_json != ''"))


def get_setting(session: Session, key: str) -> str | None:
    row = session.get(Setting, key)
    return row.value if row else None


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))
    session.commit()


def delete_setting(session: Session, key: str) -> None:
    row = session.get(Setting, key)
    if row:
        session.delete(row)
        session.commit()


__all__ = [
    "Session", "select", "engine", "init_db", "get_setting", "set_setting", "delete_setting",
    "Setting", "LoginSession", "Draft", "ConvoState", "utcnow",
]
