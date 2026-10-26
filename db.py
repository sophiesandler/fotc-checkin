"""Database layer. Works with a local SQLite file (default) or Postgres (for example Supabase) when a
DATABASE_URL secret is set. Content (questions, coding key) is stored as versioned snapshots so every
response remembers exactly which wording it answered."""
import copy
import datetime
import json
import os

import streamlit as st
from sqlalchemy import (Boolean, Column, Integer, LargeBinary, MetaData, String, Table, Text, create_engine,
                        delete, func, insert, select, update)

from auth import hash_pw

HERE = os.path.dirname(os.path.abspath(__file__))
meta = MetaData()

users = Table("users", meta,
              Column("id", Integer, primary_key=True, autoincrement=True),
              Column("username", String(80), unique=True, nullable=False),
              Column("display_name", String(120)), Column("role", String(20)),
              Column("pw_hash", String(200)), Column("salt", String(64)),
              Column("active", Boolean, default=True), Column("session_type", String(20), default="Quarterly"),
              Column("first_year", Boolean, default=False), Column("created", String(40)))
content = Table("content_versions", meta,
                Column("id", Integer, primary_key=True, autoincrement=True),
                Column("kind", String(20)), Column("version", Integer), Column("status", String(12)),
                Column("payload", Text), Column("note", Text), Column("created_by", String(80)), Column("created", String(40)))
settings = Table("settings", meta, Column("key", String(80), primary_key=True), Column("value", Text))
responses = Table("responses", meta,
                  Column("id", Integer, primary_key=True, autoincrement=True),
                  Column("session_id", String(40)), Column("ts", String(40)), Column("user_id", Integer),
                  Column("participant_code", String(80)), Column("session_type", String(20)), Column("quarter", Integer),
                  Column("question_id", String(20)), Column("question_version", Integer), Column("qtype", String(20)),
                  Column("rating", String(40)), Column("text_answer", Text), Column("checklist_selected", Text),
                  Column("checklist_top", Text), Column("audio_blob", LargeBinary), Column("audio_note", String(60)),
                  Column("transcript", Text), Column("skipped", Boolean), Column("linked_themes", Text))
audit = Table("audit_log", meta,
              Column("id", Integer, primary_key=True, autoincrement=True),
              Column("ts", String(40)), Column("username", String(80)), Column("action", String(80)), Column("detail", Text))


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def default_password():
    return _secret("DEMO_PASSWORD", "") or "practice123"


def using_default_password():
    return not _secret("DEMO_PASSWORD", "")


def _url():
    u = os.environ.get("DATABASE_URL") or _secret("DATABASE_URL", "")
    if not u:
        return "sqlite:///" + os.path.join(HERE, "fotc_local.db")
    if u.startswith("postgres://"):
        u = "postgresql://" + u[len("postgres://"):]
    if u.startswith("postgresql://"):
        u = "postgresql+psycopg2://" + u[len("postgresql://"):]
    return u


@st.cache_resource
def engine():
    e = create_engine(_url(), pool_pre_ping=True)
    meta.create_all(e)
    seed(e)
    return e


def using_sqlite():
    return _url().startswith("sqlite")


def seed(e):
    data = json.load(open(os.path.join(HERE, "seed_content.json"), encoding="utf-8"))
    with e.begin() as c:
        if c.execute(select(func.count()).select_from(users)).scalar() == 0:
            for uname, name, role, stype, fy in [("admin", "Program admin (demo)", "admin", "Quarterly", False),
                                                 ("leader", "Leadership (demo)", "leader", "Quarterly", False),
                                                 ("mentor1", "Demo Mentor 1", "mentor", "Quarterly", False),
                                                 ("mentor2", "Demo Mentor 2 (exit interview)", "mentor", "Exit", False),
                                                 ("mentor3", "Demo Mentor 3 (first year)", "mentor", "Quarterly", True)]:
                h, s = hash_pw(default_password())
                c.execute(insert(users).values(username=uname, display_name=name, role=role, pw_hash=h, salt=s, active=True,
                                               session_type=stype, first_year=fy, created=now()))
        for kind, payload in (("questions", data["questions"]), ("codebook", dict(themes=data["themes"], rules=data["rules"]))):
            if c.execute(select(func.count()).select_from(content).where(content.c.kind == kind)).scalar() == 0:
                c.execute(insert(content).values(kind=kind, version=1, status="published", payload=json.dumps(payload),
                                                 note="Starting version imported from the workbooks", created_by="system", created=now()))
        if c.execute(select(func.count()).select_from(settings)).scalar() == 0:
            for k, v in data["settings"].items():
                c.execute(insert(settings).values(key=k, value=v))


# ---------------- settings
def get_setting(key, default=""):
    with engine().connect() as c:
        r = c.execute(select(settings.c.value).where(settings.c.key == key)).scalar()
    return default if r is None else r


def set_setting(key, value):
    with engine().begin() as c:
        if c.execute(select(settings.c.key).where(settings.c.key == key)).first():
            c.execute(update(settings).where(settings.c.key == key).values(value=str(value)))
        else:
            c.execute(insert(settings).values(key=key, value=str(value)))


# ---------------- users
def get_user(username):
    with engine().connect() as c:
        r = c.execute(select(users).where(users.c.username == username)).mappings().first()
    return dict(r) if r else None


def list_users():
    with engine().connect() as c:
        return [dict(r) for r in c.execute(select(users).order_by(users.c.role, users.c.username)).mappings()]


def add_user(username, display_name, role, password):
    h, s = hash_pw(password)
    with engine().begin() as c:
        c.execute(insert(users).values(username=username, display_name=display_name, role=role, pw_hash=h, salt=s,
                                       active=True, session_type="Quarterly", first_year=False, created=now()))


def update_user(uid, **fields):
    if "password" in fields:
        pw = fields.pop("password")
        fields["pw_hash"], fields["salt"] = hash_pw(pw)
    with engine().begin() as c:
        c.execute(update(users).where(users.c.id == uid).values(**fields))


# ---------------- content versions (questions, codebook)
def _row_payload(r):
    return json.loads(r["payload"]) if r else None


def get_published(kind):
    with engine().connect() as c:
        r = c.execute(select(content).where((content.c.kind == kind) & (content.c.status == "published"))
                      .order_by(content.c.version.desc())).mappings().first()
    return (r["version"], _row_payload(r)) if r else (0, None)


def get_published_version(kind, version):
    with engine().connect() as c:
        r = c.execute(select(content).where((content.c.kind == kind) & (content.c.version == version)
                                            & (content.c.status != "draft"))).mappings().first()
    return _row_payload(r)


def get_draft(kind):
    with engine().connect() as c:
        r = c.execute(select(content).where((content.c.kind == kind) & (content.c.status == "draft"))).mappings().first()
    return _row_payload(r)


def save_draft(kind, payload, username):
    with engine().begin() as c:
        if c.execute(select(content.c.id).where((content.c.kind == kind) & (content.c.status == "draft"))).first():
            c.execute(update(content).where((content.c.kind == kind) & (content.c.status == "draft"))
                      .values(payload=json.dumps(payload), created_by=username, created=now()))
        else:
            c.execute(insert(content).values(kind=kind, version=0, status="draft", payload=json.dumps(payload),
                                             note="", created_by=username, created=now()))


def discard_draft(kind):
    with engine().begin() as c:
        c.execute(delete(content).where((content.c.kind == kind) & (content.c.status == "draft")))


def publish(kind, payload, username, note=""):
    """Save the payload as the next published version and archive the previous one. Returns the new version."""
    with engine().begin() as c:
        top = c.execute(select(func.max(content.c.version)).where(content.c.kind == kind)).scalar() or 0
        c.execute(update(content).where((content.c.kind == kind) & (content.c.status == "published")).values(status="archived"))
        c.execute(delete(content).where((content.c.kind == kind) & (content.c.status == "draft")))
        c.execute(insert(content).values(kind=kind, version=top + 1, status="published", payload=json.dumps(payload),
                                         note=note, created_by=username, created=now()))
    return top + 1


def version_history(kind):
    with engine().connect() as c:
        rows = c.execute(select(content.c.version, content.c.status, content.c.note, content.c.created_by, content.c.created)
                         .where((content.c.kind == kind) & (content.c.status != "draft")).order_by(content.c.version.desc())).mappings()
        return [dict(r) for r in rows]


# ---------------- responses
def add_responses(rows):
    with engine().begin() as c:
        c.execute(insert(responses), rows)


def fetch_responses(include_audio=False):
    cols = [c for c in responses.c if include_audio or c.name != "audio_blob"]
    with engine().connect() as c:
        return [dict(r) for r in c.execute(select(*cols).order_by(responses.c.id.desc())).mappings()]


def has_audio_count():
    with engine().connect() as c:
        return c.execute(select(func.count()).select_from(responses).where(responses.c.audio_blob.is_not(None))).scalar()


def get_audio(response_id):
    with engine().connect() as c:
        return c.execute(select(responses.c.audio_blob).where(responses.c.id == response_id)).scalar()


def delete_audio(response_id):
    with engine().begin() as c:
        c.execute(update(responses).where(responses.c.id == response_id).values(audio_blob=None, audio_note="deleted"))


# ---------------- audit log
def log(username, action, detail=""):
    with engine().begin() as c:
        c.execute(insert(audit).values(ts=now(), username=username, action=action, detail=detail))


def recent_log(n=300):
    with engine().connect() as c:
        return [dict(r) for r in c.execute(select(audit).order_by(audit.c.id.desc()).limit(n)).mappings()]
