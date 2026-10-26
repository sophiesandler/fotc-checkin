"""Mentor check-in: prototype web app. Run with: streamlit run app.py"""
import streamlit as st

st.set_page_config(page_title="Mentor check-in (prototype)", layout="wide")

import db
import views
from auth import login_screen

try:
    db.engine()
except Exception as e:  # show a plain message instead of a stack trace
    st.error("The app could not connect to its database. Check the DATABASE_URL setting, or ask the person who set up the app.")
    st.caption(f"Technical detail: {type(e).__name__}")
    st.stop()

user = st.session_state.get("user")
if not user:
    login_screen()
    st.stop()

PAGES = {
    "mentor": [st.Page(views.page_checkin, title="Check-in", url_path="checkin", default=True),
               st.Page(views.page_guide, title="Guide", url_path="guide")],
    "leader": [st.Page(views.page_overview, title="Overview", url_path="overview", default=True),
               st.Page(views.page_questions, title="Questions", url_path="questions"),
               st.Page(views.page_coding_key, title="Coding key", url_path="coding-key"),
               st.Page(views.page_guide, title="Guide", url_path="guide")],
    "admin": [st.Page(views.page_overview, title="Overview", url_path="overview", default=True),
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
    st.caption(f"Signed in as **{user['display_name']}**")
    st.caption("Prototype with practice data only.")
    if st.button("Sign out"):
        db.log(user["username"], "sign out")
        st.session_state.clear()
        st.rerun()
nav.run()
