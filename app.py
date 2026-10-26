"""Mentor check-in: prototype web app. Run with: streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="Mentor check-in (prototype)", layout="wide")

import db
import ui
import views
import dashboard
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

PAGES = {
    "mentor": [st.Page(views.page_checkin, title="Check-in", url_path="checkin", default=True),
               st.Page(views.page_guide, title="Guide", url_path="guide")],
    "leader": [st.Page(dashboard.page_dashboard, title="Dashboard", url_path="dashboard", default=True),
               st.Page(dashboard.page_risk, title="Risk tracker", url_path="risk"),
               st.Page(views.page_questions, title="Questions", url_path="questions"),
               st.Page(views.page_coding_key, title="Coding key", url_path="coding-key"),
               st.Page(views.page_guide, title="Guide", url_path="guide")],
    "admin": [st.Page(dashboard.page_dashboard, title="Dashboard", url_path="dashboard", default=True),
              st.Page(dashboard.page_risk, title="Risk tracker", url_path="risk"),
              st.Page(views.page_responses, title="Responses", url_path="responses"),
              st.Page(views.page_questions, title="Questions", url_path="questions"),
              st.Page(views.page_coding_key, title="Coding key", url_path="coding-key"),
              st.Page(views.page_users, title="People", url_path="people"),
              st.Page(views.page_settings, title="Settings", url_path="settings"),
              st.Page(views.page_audit, title="Activity log", url_path="activity"),
              st.Page(views.page_guide, title="Guide", url_path="guide")],
}
nav = st.navigation(PAGES[user["role"]])
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
