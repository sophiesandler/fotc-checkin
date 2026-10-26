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
                  Column("transcript", Text), Column("skipped", Boolean), Column("linked_themes", Text), Column("season", String(20)))
tags = Table("tags", meta,
             Column("id", Integer, primary_key=True, autoincrement=True),
             Column("response_id", Integer), Column("ts", String(40)), Column("theme", String(10)), Column("valence", String(20)),
             Column("quote", Text), Column("aggregate_only", Boolean), Column("confidence", String(10)),
             Column("escalation", Boolean), Column("by_user", String(80)))
sessions = Table("sessions", meta,
                 Column("session_id", String(40), primary_key=True), Column("participant_code", String(80)), Column("season", String(20)),
                 Column("session_type", String(20)), Column("n_questions", Integer), Column("started", String(40)), Column("last_ts", String(40)),
                 Column("last_idx", Integer), Column("completed", Boolean))
reviews = Table("reviews", meta,
                Column("response_id", Integer, primary_key=True), Column("by_user", String(80)), Column("ts", String(40)),
                Column("reviewed", Boolean), Column("starred", Boolean), Column("excerpt", Text))
proc = Table("processing", meta,
             Column("response_id", Integer, primary_key=True), Column("ts", String(40)), Column("stage", String(12)),
             Column("result", String(12)), Column("detail", Text), Column("attempts", Integer))
actions = Table("actions", meta,
                Column("id", Integer, primary_key=True, autoincrement=True), Column("ts", String(40)), Column("season", String(20)),
                Column("raised", Text), Column("action", Text), Column("status", String(20)), Column("owner", String(80)),
                Column("result", String(20)), Column("note", Text), Column("by_user", String(80)))
support = Table("support_actions", meta,
                Column("id", Integer, primary_key=True, autoincrement=True),
                Column("ts", String(40)), Column("source", String(10)), Column("mentor", String(80)),
                Column("wave", String(40)), Column("by_user", String(80)), Column("note", Text))
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
    migrate(e)
    seed(e)
    return e


def migrate(e):
    """Add columns that newer versions of the app need to tables that already exist."""
    from sqlalchemy import inspect, text
    cols = [c["name"] for c in inspect(e).get_columns("responses")]
    if "season" not in cols:
        with e.begin() as c:
            c.execute(text("ALTER TABLE responses ADD COLUMN season VARCHAR(20)"))


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


# ---------------- support check-ins offered (risk tracker)
_ensured = set()


def _ensure(table):
    """Create a table if it is missing. Protects against a running app that started before the table was added."""
    if table.name not in _ensured:
        table.create(engine(), checkfirst=True)
        _ensured.add(table.name)


def add_support_actions(source, mentors, wave, by_user, note=""):
    _ensure(support)
    with engine().begin() as c:
        for m in mentors:
            c.execute(insert(support).values(ts=now(), source=source, mentor=m, wave=wave, by_user=by_user, note=note))


def support_actions(source):
    _ensure(support)
    with engine().connect() as c:
        return [dict(r) for r in c.execute(select(support).where(support.c.source == source).order_by(support.c.id.desc())).mappings()]


# ---------------- transcripts and tags (theme explorer)
def spoken_responses():
    cols = [responses.c.id, responses.c.session_id, responses.c.ts, responses.c.participant_code, responses.c.season, responses.c.question_id,
            responses.c.question_version, responses.c.text_answer, responses.c.transcript, responses.c.audio_note, responses.c.skipped]
    with engine().connect() as c:
        rows = c.execute(select(*cols).where((responses.c.qtype == "Spoken") & (responses.c.skipped == False)).order_by(responses.c.id.desc())).mappings()  # noqa: E712
        return [dict(r) for r in rows]


def set_transcript(response_id, text_):
    with engine().begin() as c:
        c.execute(update(responses).where(responses.c.id == response_id).values(transcript=text_))


def tagged_ids():
    _ensure(tags)
    with engine().connect() as c:
        return {r[0] for r in c.execute(select(tags.c.response_id).distinct())}


def add_tags(response_id, rows, username, escalation=False):
    _ensure(tags)
    with engine().begin() as c:
        c.execute(delete(tags).where(tags.c.response_id == response_id))
        for t in rows:
            c.execute(insert(tags).values(response_id=response_id, ts=now(), theme=t["theme"], valence=t["valence"], quote=t.get("quote", ""),
                                          aggregate_only=bool(t.get("aggregate_only")), confidence=t.get("confidence", ""),
                                          escalation=bool(escalation), by_user=username))


def get_tags():
    _ensure(tags)
    cols = [tags.c.id, tags.c.response_id, tags.c.theme, tags.c.valence, tags.c.quote, tags.c.aggregate_only, tags.c.escalation, tags.c.by_user,
            responses.c.participant_code, responses.c.season, responses.c.ts, responses.c.question_id]
    with engine().connect() as c:
        rows = c.execute(select(*cols).select_from(tags.join(responses, tags.c.response_id == responses.c.id))).mappings()
        return [dict(r) for r in rows]


# ---------------- pilot year: sessions, answer reviews, and the "you said, we did" log
def start_session(sid, code, season, stype, n_questions):
    _ensure(sessions)
    with engine().begin() as c:
        c.execute(insert(sessions).values(session_id=sid, participant_code=code, season=season, session_type=stype, n_questions=n_questions,
                                          started=now(), last_ts=now(), last_idx=0, completed=False))


def update_session(sid, last_idx, completed):
    _ensure(sessions)
    with engine().begin() as c:
        c.execute(update(sessions).where(sessions.c.session_id == sid).values(last_idx=last_idx, last_ts=now(), completed=bool(completed)))


def get_sessions():
    _ensure(sessions)
    with engine().connect() as c:
        return [dict(r) for r in c.execute(select(sessions)).mappings()]


def count_active_mentors():
    with engine().connect() as c:
        return c.execute(select(func.count()).select_from(users).where((users.c.role == "mentor") & (users.c.active == True))).scalar()  # noqa: E712


def upsert_review(response_id, user, reviewed, starred, excerpt):
    _ensure(reviews)
    with engine().begin() as c:
        vals = dict(by_user=user, ts=now(), reviewed=bool(reviewed), starred=bool(starred), excerpt=excerpt or "")
        if c.execute(select(reviews.c.response_id).where(reviews.c.response_id == response_id)).first():
            c.execute(update(reviews).where(reviews.c.response_id == response_id).values(**vals))
        else:
            c.execute(insert(reviews).values(response_id=response_id, **vals))


def get_reviews():
    _ensure(reviews)
    with engine().connect() as c:
        return [dict(r) for r in c.execute(select(reviews)).mappings()]


def add_action(season, raised, action, status, owner, by_user):
    _ensure(actions)
    with engine().begin() as c:
        c.execute(insert(actions).values(ts=now(), season=season, raised=raised, action=action, status=status, owner=owner, result="", note="", by_user=by_user))


def update_action(aid, **fields):
    _ensure(actions)
    with engine().begin() as c:
        c.execute(update(actions).where(actions.c.id == aid).values(**fields))


def get_actions():
    _ensure(actions)
    with engine().connect() as c:
        return [dict(r) for r in c.execute(select(actions).order_by(actions.c.id.desc())).mappings()]


# ---------------- automatic processing outcomes (what the pipeline did with each answer)
# result: flag (AI found a safety or support concern), review (AI asked a person to check), failed, retry (try again later),
#         no_themes (nothing to tag), dismissed (a person checked it and nothing more is needed)
def set_proc(response_id, stage, result, detail="", count_attempt=False):
    _ensure(proc)
    with engine().begin() as c:
        old = c.execute(select(proc.c.attempts).where(proc.c.response_id == response_id)).first()
        n = (old[0] or 0) if old else 0
        vals = dict(ts=now(), stage=stage, result=result, detail=(detail or "")[:300], attempts=n + (1 if count_attempt else 0))
        if old:
            c.execute(update(proc).where(proc.c.response_id == response_id).values(**vals))
        else:
            c.execute(insert(proc).values(response_id=response_id, **vals))


def get_proc():
    _ensure(proc)
    with engine().connect() as c:
        return [dict(r) for r in c.execute(select(proc)).mappings()]


def clear_proc(response_id):
    _ensure(proc)
    with engine().begin() as c:
        c.execute(delete(proc).where(proc.c.response_id == response_id))
