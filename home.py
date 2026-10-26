"""Home screen for admins and leadership: what needs attention today, plus a map of every page grouped into four sections.
Each card has an icon, a short plain-language line, and a link. Cards a role cannot use are not shown."""
import datetime

import pandas as pd
import streamlit as st

import db
import pipeline as pl
from auth import require

# key, icon, title, one-line description, roles that see it
SECTIONS = [
    ("See how it's going", "Results, trends, and who may need support.", [
        ("pilot", "🧭", "Pilot year", "Progress through the pilot at a glance.", ("leader", "admin")),
        ("dashboard", "📊", "Dashboard", "Results and trends by theme.", ("leader", "admin")),
        ("risk", "🤝", "Support signals", "Where Mentors may need extra support.", ("leader", "admin")),
        ("review", "🚩", "Review queue", "Only AI-flagged answers and anything automation missed.", ("admin",)),
    ]),
    ("Edit the tool", "Change what Mentors are asked and who has access.", [
        ("questions", "✏️", "Questions", "Change the prompts and wording.", ("leader", "admin")),
        ("users", "👥", "People", "Add Mentors and manage who can sign in.", ("admin",)),
        ("audit", "🕘", "Activity log", "See who changed what, and when.", ("admin",)),
    ]),
    ("Supporting materials", "Help, setup steps, and how answers are sorted.", [
        ("guide", "📖", "Guide", "How the tool works, step by step.", ("leader", "admin")),
        ("launch", "✅", "Launch checklist", "Steps to finish before real Mentors start.", ("admin",)),
        ("themes", "🏷️", "Themes and rules", "How answers get tagged and flagged.", ("leader", "admin")),
    ]),
    ("My account", "Your sign-in and the tool's settings.", [
        ("account", "🔑", "Account and password", "Change your password and see your profile.", ("leader", "admin")),
        ("settings", "⚙️", "Settings", "Program stage, transcription, and tagging.", ("admin",)),
    ]),
]

# Pages that have no real data during the pilot year
LATER = {"dashboard", "risk"}


def _safe(fn, default):
    """Home must never crash because one count failed."""
    try:
        return fn()
    except Exception:
        return default


# ---------------------------------------------------------------- what needs attention
def attention_items():
    """Return a list of (count, text, page key, urgent). Only items with something to do are returned.
    Transcription and tagging are automatic, so answers are never listed just for being unread."""
    items = []
    q = _safe(pl.review_items, dict(flags=[], checks=[], problems=[]))

    open_flags = [f for f in q["flags"] if not f["handled"]]
    if open_flags:
        n = len(open_flags)
        items.append((n, f"{n} answer{'s' if n != 1 else ''} flagged by the AI as needing support. Follow up.", "review", True))

    if q["problems"]:
        items.append((len(q["problems"]), "Automatic transcription or tagging is not fully working: " + q["problems"][0], "settings", True))

    if _safe(db.using_default_password, False):
        items.append((1, "The app is still using the starting practice password. Set a private one before real use.", "account", True))

    if q["checks"]:
        n = len(q["checks"])
        items.append((n, f"{n} answer{'s' if n != 1 else ''} the automatic steps could not finish, or the AI asked a person to check.", "review", False))

    def _unfinished():
        sess = pd.DataFrame(db.get_sessions())
        if sess.empty:
            return 0
        sess["completed"] = sess["completed"].astype(bool)
        done = set(map(tuple, sess[sess["completed"]][["participant_code", "season"]].values))
        open_ = sess[~sess["completed"]]
        return len({(a, b) for a, b in open_[["participant_code", "season"]].values if (a, b) not in done})

    n = _safe(_unfinished, 0)
    if n:
        items.append((n, f"{n} Mentor{'s' if n != 1 else ''} started a check-in and haven't finished.", "pilot", False))

    def _stale_actions():
        acts = pd.DataFrame(db.get_actions())
        if acts.empty:
            return 0
        age = (pd.Timestamp(datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)) - pd.to_datetime(acts["ts"], errors="coerce")).dt.days
        return int(((acts["status"] != "Done") & (age >= 90)).sum())

    n = _safe(_stale_actions, 0)
    if n:
        items.append((n, f"{n} \"you said, we did\" action{'s' if n != 1 else ''} still open after 3 months. Update the status.", "pilot", False))

    return sorted(items, key=lambda x: not x[3])


# ---------------------------------------------------------------- page
def page_home(pages, role):
    """pages: dict of key -> st.Page for pages this role can open. role: 'leader' or 'admin'."""
    user = require("leader", "admin")
    stage = db.get_setting("program_stage", "Pilot year")
    first = (user.get("display_name") or user["username"]).split(" ")[0]
    st.title("Home")
    st.caption(f"Welcome, {first}. Pick a card to open a page. Every page in the tool is on this screen.")

    if role == "admin":
        st.markdown("<div class='home-head'>Needs your attention</div>", unsafe_allow_html=True)
        items = attention_items()
        if not items:
            st.success("Nothing needs your attention right now.")
        else:
            with st.container(border=True):
                for n, text, key, urgent in items:
                    c1, c2 = st.columns([6, 1.3], vertical_alignment="center")
                    c1.markdown(f"{'🔴' if urgent else '🟠'} {text}")
                    if key in pages:
                        c2.page_link(pages[key], label="Open", icon=":material/arrow_forward:")

    for title, blurb, cards in SECTIONS:
        mine = [c for c in cards if role in c[4] and (c[0] in pages)]
        if not mine:
            continue
        st.markdown(f"<div class='home-head'>{title}<span>{blurb}</span></div>", unsafe_allow_html=True)
        cols = st.columns(4)  # same card width in every section
        for col, (key, icon, name, desc, _roles) in zip(cols, mine):
            later = stage == "Pilot year" and key in LATER
            with col.container(border=True, height=205):
                st.markdown(f"<div class='home-icon{' later' if later else ''}'>{icon}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='home-name{' later' if later else ''}'>{name}</div>", unsafe_allow_html=True)
                if later:
                    st.markdown("<div class='home-desc later'>Available after the first season.</div>", unsafe_allow_html=True)
                    st.page_link(pages[key], label="Preview with example data", icon=":material/visibility:")
                else:
                    st.markdown(f"<div class='home-desc'>{desc}</div>", unsafe_allow_html=True)
                    st.page_link(pages[key], label="Open", icon=":material/arrow_forward:")
