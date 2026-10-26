"""Simple username and password sign-in for the prototype. Passwords are stored as salted hashes, never as text.
For real use, replace this with sign-in through the organization's Google or Microsoft accounts."""
import hashlib
import hmac
import secrets
import time

import streamlit as st


def hash_pw(password, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000).hex()
    return h, salt


def check_pw(password, pw_hash, salt):
    h, _ = hash_pw(password, salt)
    return hmac.compare_digest(h, pw_hash)


def login_screen():
    import db
    import ui
    left, right = st.columns([1.05, 1], gap="large")
    with left:
        st.markdown("<p class='kicker'>Friends of the Children · Chicago</p>", unsafe_allow_html=True)
        st.title(db.get_setting("app_title", "Mentor check-in"))
        st.caption("Prototype with practice data only. Do not enter real information.")
        with st.form("login"):
            username = st.text_input("User name")
            password = st.text_input("Password", type="password")
            ok = st.form_submit_button("Sign in", type="primary")
        if ok:
            u = db.get_user(username.strip())
            fails = st.session_state.get("fails", 0)
            if fails >= 5:
                time.sleep(2)
            if u and u["active"] and check_pw(password, u["pw_hash"], u["salt"]):
                st.session_state.user = dict(id=u["id"], username=u["username"], display_name=u["display_name"], role=u["role"],
                                             session_type=u["session_type"] or "Quarterly", first_year=bool(u["first_year"]))
                st.session_state.fails = 0
                db.log(u["username"], "sign in")
                st.rerun()
            else:
                st.session_state.fails = fails + 1
                st.error("That user name and password do not match. Check for typing mistakes, or ask your program admin to reset your password.")
        if db.using_default_password():
            st.info("**Demo accounts** (password `practice123`): `mentor1`, `mentor2` (exit interview), `mentor3` (first-year Mentor), "
                    "`leader` (leadership view), and `admin` (program admin).")
    with right:
        ui.login_hero()


def require(*roles):
    user = st.session_state.get("user")
    if not user or user["role"] not in roles:
        st.error("You do not have access to this page.")
        st.stop()
    return user
