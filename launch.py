"""Launch checklist (admin) and My account (everyone): the practical steps between a working prototype and real use."""
import json

import pandas as pd
import streamlit as st

import db
import transcribe as tr
import ui
from auth import check_pw, hash_pw, require

DEMO_USERS = {"admin", "leader", "mentor1", "mentor2", "mentor3"}


# ---------------------------------------------------------------- my account
def page_account():
    user = require("mentor", "leader", "admin")
    st.title("My account")
    ui.section("Your sign-in", "See how you are signed in and change your password. Use a password nobody else knows.")
    role = {"mentor": "Mentor", "leader": "Leadership", "admin": "Program admin"}[user["role"]]
    st.markdown(f"**Name:** {user['display_name']}  \n**Sign-in name:** {user['username']}  \n**Role:** {role}")
    msg = st.session_state.pop("flash", None)
    if msg:
        st.success(msg)
    ui.section("Change your password", "Enter your current password, then a new one of at least 8 characters. You will stay signed in.", level=3)
    with st.form("pw_form", clear_on_submit=True):
        cur = st.text_input("Current password", type="password")
        new = st.text_input("New password (at least 8 characters)", type="password")
        again = st.text_input("New password again", type="password")
        ok = st.form_submit_button("Change password", type="primary")
    if ok:
        u = db.get_user(user["username"])
        banned = {"practice123", str(db.default_password())}
        if not u or not check_pw(cur, u["pw_hash"], u["salt"]):
            st.error("The current password is not right.")
        elif len(new) < 8:
            st.error("Use at least 8 characters.")
        elif new != again:
            st.error("The two new passwords do not match.")
        elif new == cur or new in banned:
            st.error("Choose a password that is new and not one of the shared demo passwords.")
        else:
            db.update_user(u["id"], password=new)
            db.log(user["username"], "changed own password")
            st.session_state.flash = "Your password was changed."
            st.rerun()


# ---------------------------------------------------------------- launch checklist
def _auto():
    """Checks the app can make for itself. Each item: (id, group, label, done, detail)."""
    users = db.list_users()
    banned = {"practice123", str(db.default_password())}
    shared = [u["username"] for u in users if u["active"] and any(check_pw(p, u["pw_hash"], u["salt"]) for p in banned)]
    demo_on = [u["username"] for u in users if u["active"] and u["username"] in DEMO_USERS and u["username"] != "admin"]
    consent = db.get_setting("consent_text", "")
    have_p = {q["id"] for q in db.get_published("questions")[1]}
    return [
        ("a_pw", "Set up", "No one signs in with a shared demo password", not shared, ("Still using a shared password: " + ", ".join(shared)) if shared else "Every active account has its own password."),
        ("a_demo", "Set up", "Demo Mentor and leadership accounts are turned off", not demo_on, ("Still active: " + ", ".join(demo_on)) if demo_on else "Demo accounts are off."),
        ("a_db", "Set up", "The app uses a permanent database", not db.using_sqlite(), "The temporary database loses data when the app restarts." if db.using_sqlite() else "Connected to a permanent database."),
        ("a_season", "Set up", "A season is open for check-ins", bool(db.get_setting("current_season", "")), "Open one in Settings."),
        ("a_consent", "Approvals", "The consent wording is no longer marked as a draft", "Draft wording" not in consent, "Edit it in Settings once Friends of the Children has approved it."),
        ("a_pilotq", "Set up", "Pilot feedback questions are in the question set", {"P01", "P02", "P03"} <= have_p, "Add them on the Pilot year page, under Pilot feedback."),
        ("a_tr", "Set up", "Automatic transcription is set up (optional)", bool(tr.providers()), tr.status_line()),
    ]


MANUAL = [
    ("m_consent", "Approvals", "Friends of the Children approved the consent wording Mentors see"),
    ("m_data", "Approvals", "Friends of the Children approved the hosting and data handling, and there is a data agreement"),
    ("m_lead", "Approvals", "A designated support lead is named, and it is not a Mentor's supervisor"),
    ("m_safety", "Approvals", "Someone is named to receive safety and welfare flags, with a written procedure"),
    ("m_retain", "Approvals", "A rule is agreed for how long recordings and answers are kept"),
    ("m_ai", "Approvals", "Friends of the Children approved sending transcripts to Claude, and audio to the transcription service if one is used"),
    ("m_phone", "Testing", "The check-in works on a Mentor's phone, including the microphone"),
    ("m_laptop", "Testing", "The check-in works on a laptop, including the microphone"),
    ("m_usab", "Testing", "Someone who does not know the project completed a check-in and edited a question with no help"),
    ("m_backup", "Testing", "A backup was downloaded and opens correctly"),
    ("m_dbpw", "Set up", "The database password was changed from any password shared in chat or email"),
    ("m_accts", "Launch", "Mentor accounts are created on the People page, each with its own starting password"),
    ("m_brief", "Launch", "Mentors were told what the check-in is, who sees their answers, and how long it takes"),
    ("m_train", "Launch", "The support lead and leadership were shown how to read their pages"),
]


def page_launch():
    user = require("admin")
    st.title("Launch checklist")
    ui.section("Is the app ready for real Mentors?", "Work through each group. Items marked automatic update by themselves. For the rest, tick the box once it is true, so the whole team can see progress.")
    checks = {}
    try:
        checks = json.loads(db.get_setting("launch_checks", "{}"))
    except Exception:
        checks = {}
    auto = _auto()
    counted = [a for a in auto if "(optional)" not in a[2]]
    total = len(counted) + len(MANUAL)
    done_n = sum(1 for a in counted if a[3]) + sum(1 for m in MANUAL if m[0] in checks)
    st.progress(done_n / total, text=f"{done_n} of {total} done")
    if done_n < total:
        st.info("Real Mentor answers should not go in until the Approvals and Testing groups are complete.")
    else:
        st.success("Everything is done. The app is ready for a pilot with real Mentors.")
    for group in ("Approvals", "Testing", "Set up", "Launch"):
        ui.section(group, {"Approvals": "Decisions only Friends of the Children can make.", "Testing": "Proof that it works for real people on real devices.",
                          "Set up": "Settings and accounts. Items with a status are checked automatically.", "Launch": "What to do on and just before the first day."}[group], level=3)
        for a in [x for x in auto if x[1] == group]:
            st.markdown(f"{'✅' if a[3] else '⬜'} **{a[2]}** *(automatic)*" + ("" if a[3] else f"  \n<span style='color:#555'>{a[4]}</span>"), unsafe_allow_html=True)
        for m in [x for x in MANUAL if x[1] == group]:
            was = m[0] in checks
            now = st.checkbox(m[2], value=was, key=f"lc_{m[0]}",
                              help=(f"Ticked by {checks[m[0]]['by']} on {checks[m[0]]['when']}" if was else None))
            if now != was:
                if now:
                    checks[m[0]] = {"by": user["username"], "when": db.now()[:10]}
                else:
                    checks.pop(m[0], None)
                db.set_setting("launch_checks", json.dumps(checks))
                db.log(user["username"], "updated launch checklist", f"{m[0]}={now}")
                st.rerun()

    ui.section("Download a backup", "Free hosting does not back up your data. Download these files regularly and keep them somewhere safe. They include Mentors' answers, so treat them as confidential. Recordings are not included.")
    resp = pd.DataFrame(db.fetch_responses())
    sess = pd.DataFrame(db.get_sessions())
    users = pd.DataFrame(db.list_users()).drop(columns=["pw_hash", "salt"], errors="ignore")
    acts = pd.DataFrame(db.get_actions())
    c = st.columns(4)
    for col, name, frame in zip(c, ["responses", "sessions", "people", "actions"], [resp, sess, users, acts]):
        col.download_button(f"Download {name} (CSV)", frame.to_csv(index=False), file_name=f"{name}.csv", mime="text/csv", disabled=frame.empty, key=f"bk_{name}")
