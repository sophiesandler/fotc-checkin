"""Mentor check-in: prototype web app. Run with: streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="Mentor check-in (prototype)", layout="wide")

import db
import ui
import views
import dashboard
import answers
import launch
import pilot
import home
import pipeline
from auth import login_screen


def explain_db_error(e):
    """Plain-language hint for common connection problems. Never shows the error text itself (it can contain secrets)."""
    msg = str(e).lower()
    if "password authentication failed" in msg:
        return ("The database password in your DATABASE_URL secret does not match the password Supabase has. "
                "In Supabase, open Database settings and use Reset password to set the same one, wait about five minutes, then reboot the app.")
    if "tenant or user not found" in msg:
        return ("Supabase did not recognize the host or user name. Copy the Session pooler string again from Supabase (Connect > Session pooler). "
                "The user should look like postgres.yourprojectid and the host should end in pooler.supabase.com.")
    if "could not translate host name" in msg or "name or service not known" in msg or "nodename nor servname" in msg:
        return "The host name in the DATABASE_URL secret could not be found. Check it for typing mistakes."
    if "network is unreachable" in msg or "cannot assign requested address" in msg:
        return ("Streamlit could not reach that address. Use the Session pooler string (host ends in pooler.supabase.com), not the Direct connection string.")
    if "timeout" in msg or "timed out" in msg or "connection refused" in msg:
        return "The database did not answer. Check that the Supabase project is not paused (open it in Supabase and click Resume if you see a paused notice), then reboot."
    if "ssl" in msg:
        return "The secure connection failed. Copy the Session pooler string again from Supabase."
    if "could not parse" in msg or "invalid" in msg and "url" in msg or "invalid port" in msg:
        return ("The DATABASE_URL secret could not be read. If the password contains symbols such as @ or #, reset it to letters and numbers only, "
                "and make sure the whole value is inside double quotation marks.")
    return "Check the DATABASE_URL secret for typing mistakes, and that the Supabase project is running."


ui.inject_css()

try:
    db.engine()
except Exception as e:  # show a plain message instead of a stack trace
    st.error("The app could not connect to its database.")
    st.write(explain_db_error(e))
    st.caption(f"Error type: {type(e).__name__}")
    st.stop()

user = st.session_state.get("user")
if not user:
    login_screen()
    if db.using_sqlite():
        st.warning("This app is using a temporary database, so anything you save will be lost when it restarts. "
                   "Add a DATABASE_URL secret to keep your data.")
    st.stop()

stage = db.get_setting("program_stage", "Pilot year")
role = user["role"]
pipeline.maybe_sweep()      # quietly finish anything automatic processing missed (at most every 10 minutes)


def _page(fn, title, path):
    return st.Page(fn, title=title, url_path=path)


# every page, keyed so the Home screen can link to it
P = {
    "pilot": _page(pilot.page_pilot, "Pilot year", "pilot"),
    "dashboard": _page(dashboard.page_dashboard, "Dashboard", "dashboard"),
    "risk": _page(dashboard.page_risk, "Support signals", "support-signals"),
    "review": _page(answers.page_review, "Review queue", "review"),
    "questions": _page(views.page_questions, "Questions", "questions"),
    "users": _page(views.page_users, "People", "people"),
    "audit": _page(views.page_audit, "Activity log", "activity"),
    "guide": _page(views.page_guide, "Guide", "guide"),
    "launch": _page(launch.page_launch, "Launch checklist", "launch-checklist"),
    "themes": _page(views.page_coding_key, "Themes and rules", "themes-and-rules"),
    "account": _page(launch.page_account, "My account", "my-account"),
    "settings": _page(views.page_settings, "Settings", "settings"),
}

if role == "mentor":
    PAGES = [st.Page(views.page_checkin, title="Check-in", url_path="checkin", default=True), P["account"], P["guide"]]
else:
    # pages this person can open (Home links only to these)
    allowed = {"leader": ["pilot", "dashboard", "risk", "questions", "guide", "themes", "account"],
               "admin": list(P)}[role]
    mine = {k: P[k] for k in allowed}

    def _home():
        home.page_home(mine, role)

    st.session_state["_pages"] = mine   # lets pages link to each other
    pg_home = st.Page(_home, title="Home", url_path="home", default=True, icon=":material/home:")
    PAGES = {
        "": [pg_home],
        "See how it's going": [mine[k] for k in ("pilot", "dashboard", "risk", "review") if k in mine],
        "Edit the tool": [mine[k] for k in ("questions", "users", "audit") if k in mine],
        "Supporting materials": [mine[k] for k in ("guide", "launch", "themes") if k in mine],
        "My account": [mine[k] for k in ("account", "settings") if k in mine],
    }
nav = st.navigation(PAGES)
with st.sidebar:
    ui.sidebar_brand()
    st.caption(f"Signed in as **{user['display_name']}**")
    st.caption("Prototype with practice data only.")
    if db.using_sqlite():
        st.warning("Temporary database: your changes will be lost when the app restarts.")
    if st.button("Sign out"):
        db.log(user["username"], "sign out")
        st.session_state.clear()
        st.rerun()
nav.run()
