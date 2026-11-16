"""Pilot year: one page for the first year, before there is enough data for trends. Four sections: Pilot targets (including the
feedback on the check-in itself), Mentor ratings against the baseline, What we heard (standout excerpts with a leadership
"addressed" box and comment), and Our response (you said, we did). A single "data readiness" figure sits at the top."""
import numpy as np
import pandas as pd
import streamlit as st

import content as ct
import dashboard as dash
import db
import risk
import seasons
from auth import require

CORE = risk.CORE
SHORT = dash.SHORT
FEEDBACK = {"P01": "This check-in was easy to use", "P02": "I felt comfortable answering honestly", "P05": "I am satisfied with this check-in"}
TARGETS = {"completion": 0.80, "minutes": 8.0, "skip": 0.10, "feedback": 4.0}
SRC = ["Live pilot data", "Example (synthetic)"]
STATUS_COLORS = {"Done": "background-color:#D6EFD9;color:#1B5E20;font-weight:700", "In progress": "background-color:#FFD9A0;color:#282828;font-weight:700",
                 "Planned": "background-color:#E3F1FB;color:#1A74B8;font-weight:700"}


# ---------------------------------------------------------------- data
def _empty_sessions():
    return pd.DataFrame(columns=["session_id", "participant_code", "mentor", "season", "session_type", "n_questions", "started", "last_ts", "last_idx", "completed", "minutes"])


def live_pilot():
    sess = pd.DataFrame(db.get_sessions())
    if sess.empty:
        sess = _empty_sessions()
    else:
        sess["minutes"] = (pd.to_datetime(sess["last_ts"]) - pd.to_datetime(sess["started"])).dt.total_seconds() / 60
        sess["completed"] = sess["completed"].astype(bool)
        sess["mentor"] = sess["participant_code"]
        # a Mentor who submits again in the same season still counts once (a finished check-in wins, then the latest)
        sess = sess.sort_values(["completed", "started"], ascending=[False, False]).drop_duplicates(["participant_code", "season", "session_type"], keep="first")
    rows = db.fetch_responses()
    resp = pd.DataFrame(rows)
    pq = db.get_published("questions")[1]
    qtext = {q["id"]: ct.plain(q["text"]) for q in pq}
    qblock = {q["id"]: q["block"] for q in pq}
    qorder = {q["id"]: i for i, q in enumerate(pq)}
    ratings = pd.DataFrame(columns=["mentor", "season", "qid", "value"])
    qstats = pd.DataFrame(columns=["season", "qid", "reached", "skipped"])
    if not resp.empty:
        resp["season"] = [dash.season_of(r) for r in rows]
        resp["skipped"] = resp["skipped"].astype(bool)
        r = resp[(resp["qtype"] == "Rating") & resp["question_id"].isin(CORE + list(FEEDBACK))].copy()
        r["value"] = pd.to_numeric(r["rating"], errors="coerce")
        ratings = r.dropna(subset=["value"]).rename(columns={"participant_code": "mentor", "question_id": "qid"})[["mentor", "season", "qid", "value"]]
        qstats = resp.groupby(["season", "question_id"]).agg(reached=("id", "count"), skipped=("skipped", "sum")).reset_index().rename(columns={"question_id": "qid"})
    sp = db.spoken_responses()
    tag_rows = db.get_tags()
    tag_by = {}
    esc = set()
    for t in tag_rows:
        tag_by.setdefault(t["response_id"], []).append(dash.THEME_SHORT.get(t["theme"], t["theme"]))
        if t["escalation"]:
            esc.add(t["response_id"])
    rev = {x["response_id"]: x for x in db.get_reviews()}
    lnotes = {x["response_id"]: x for x in db.get_leader_notes()}
    ans = []
    for r in sp:
        text = (r["transcript"] or r["text_answer"] or "").strip()
        has_audio = r["audio_note"] in ("recorded", "deleted")
        if not text:
            text = "(recording, not yet typed up)" if has_audio else ""
        rv = rev.get(r["id"], {})
        ans.append(dict(id=r["id"], mentor=r["participant_code"], season=dash.season_of(r), qid=r["question_id"], qtext=qtext.get(r["question_id"], r["question_id"]),
                        text=text, audio=bool(has_audio), reviewed=bool(rv.get("reviewed")), starred=bool(rv.get("starred")), excerpt=rv.get("excerpt", ""),
                        themes=", ".join(sorted(set(tag_by.get(r["id"], [])))), escalated=r["id"] in esc,
                        addressed=bool(lnotes.get(r["id"], {}).get("addressed")), lnote=lnotes.get(r["id"], {}).get("note") or "",
                        lby=lnotes.get(r["id"], {}).get("by_user") or "", lts=lnotes.get(r["id"], {}).get("ts") or ""))
    answers = pd.DataFrame(ans, columns=["id", "mentor", "season", "qid", "qtext", "text", "audio", "reviewed", "starred", "excerpt", "themes", "escalated",
                                         "addressed", "lnote", "lby", "lts"])
    acts = pd.DataFrame(db.get_actions(), columns=["id", "ts", "season", "raised", "action", "status", "owner", "result", "note", "by_user"])
    return dict(example=False, invited=int(db.count_active_mentors()), sessions=sess, qstats=qstats, ratings=ratings, answers=answers, actions=acts,
                qtext=qtext, qblock=qblock, qorder=qorder)


def example_pilot():
    d = dash.demo_checkins()
    waves = seasons.ordered(list(d["wave"].unique()))          # every synthetic season, past and current
    pq = db.get_published("questions")[1]
    qtext = {q["id"]: ct.plain(q["text"]) for q in pq}
    qblock = {q["id"]: q["block"] for q in pq}
    qorder = {q["id"]: i for i, q in enumerate(pq)}
    n_q = 12
    skip = {"C01": .02, "C02": .03, "C03": .03, "C04": .05, "C07": .04, "C10": .08, "C11": .10, "C12": .12, "Z01": .35,
            "P01": .02, "P02": .03, "P05": .02}
    tg_all = dash.demo_tags()
    sess, qs, ratings, answers = [], [], [], []
    for si, season in enumerate(waves):
        rng = np.random.default_rng(7 + si)
        first = d[d["wave"] == season]
        mentors = sorted(first["mentor"].unique())[:28]
        n = len(mentors)
        done_n = min(n, [24, 25, 25, 26, 26, 27][si % 6])
        for i, m in enumerate(mentors):
            done = i < done_n
            sess.append(dict(session_id=f"ex{si}_{i}", participant_code=m, mentor=m, season=season, session_type="Quarterly", n_questions=n_q,
                             last_idx=n_q if done else int(rng.integers(4, 12)), completed=done,
                             minutes=float(np.clip(rng.normal(7.4 - 0.15 * si, 1.9), 3.2, 13)) if done else float(abs(rng.normal(3.5, 1.2)))))
        for j_, (q, rate) in enumerate(skip.items()):
            reached = n - min(j_ // 3, 4)
            qs.append(dict(season=season, qid=q, reached=reached, skipped=int(round(reached * rate))))
        for m in mentors[:done_n]:
            row = first[first["mentor"] == m].iloc[0]
            for c in ("C01", "C02", "C03", "C04", "C07"):                  # the five ratings still asked every season
                if not pd.isna(row[c]):
                    ratings.append(dict(mentor=m, season=season, qid=c, value=float(row[c])))
            for qid, p in (("P01", [.0, .02, .08, .35, .55]), ("P02", [.02, .06, .22, .40, .30]), ("P05", [.02, .06, .24, .42, .26])):
                p = np.array(p, dtype=float)
                if qid != "P01":                                   # trust and ease creep up a little each season
                    p[2] -= 0.015 * si
                    p[4] += 0.015 * si
                ratings.append(dict(mentor=m, season=season, qid=qid, value=float(rng.choice([1, 2, 3, 4, 5], p=p / p.sum()))))
        tg = tg_all[(tg_all["wave"] == season) & tg_all["mentor"].isin(mentors) & (tg_all["quote"] != "")].head(26)
        for i, r in enumerate(tg.itertuples(index=False)):
            answers.append(dict(id=1000 + si * 100 + i, mentor=r.mentor, season=season, qid=r.question, qtext=qtext.get(r.question, r.question), text=r.quote, audio=bool(i % 2 == 0),
                                reviewed=i % 3 != 0, starred=i in (1, 4, 9), excerpt="", themes=dash.THEME_SHORT.get(r.theme, r.theme), escalated=False,
                            addressed=i == 4, lnote="Shared with the Program Director." if i == 4 else "", lby="", lts=""))
    first_season = waves[0] if waves else "Summer 2025"
    spread = waves[1:4] + [first_season] * 3                          # spread the example actions over the first seasons
    acts = pd.DataFrame([
        dict(id=1, ts="", season=first_season, raised="Portfolio gets overwhelming when a youth is in crisis", action="Set up a backup Mentor rota for crisis weeks", status="Done", owner="Program Director", result="Helped", note="", by_user=""),
        dict(id=2, ts="", season=spread[0], raised="Time when youth are away feels aimless", action="Pilot a shared planning block on Tuesdays", status="Done", owner="Program team", result="Unsure", note="", by_user=""),
        dict(id=3, ts="", season=spread[1], raised="Training did not cover home visits", action="Add shadowing to onboarding", status="In progress", owner="HR Specialist", result="", note="", by_user=""),
        dict(id=4, ts="", season=spread[2], raised="The check-in felt long", action="Review optional questions with FOTC leadership", status="Planned", owner="Program team", result="", note="", by_user=""),
    ])
    return dict(example=True, invited=30, sessions=pd.DataFrame(sess), qstats=pd.DataFrame(qs), ratings=pd.DataFrame(ratings), answers=pd.DataFrame(answers), actions=acts,
                qtext=qtext, qblock=qblock, qorder=qorder)


# ---------------------------------------------------------------- page
SECTIONS = [("Pilot targets", "pilot-targets"), ("Mentor ratings", "mentor-ratings"), ("What we heard", "what-we-heard"), ("Our response", "our-response")]
NO_NAMES = "Do not include names or details that could identify a Mentor."


def _heading(title, anchor, line):
    st.subheader(title, anchor=anchor)
    st.caption(line)


def page_pilot():
    user = require("leader", "admin")
    admin = user["role"] == "admin"
    k = dash._k()
    st.title("Pilot year")
    st.caption("Is the check-in working, what are Mentors telling us, and what are we doing about it?")
    if "pilot_src" not in st.session_state:
        live_done = sum(1 for s_ in db.get_sessions() if s_["completed"])
        st.session_state.pilot_src = SRC[0] if live_done >= k else SRC[1]
    c_src, c_sea = st.columns([3, 2])
    choice = c_src.radio("Data shown", SRC, index=SRC.index(st.session_state.pilot_src), horizontal=True, key="pilot_radio",
                         on_change=lambda: st.session_state.update(pilot_src=st.session_state.pilot_radio))
    data = example_pilot() if choice == SRC[1] else live_pilot()
    example = data["example"]
    if example:
        st.warning("Example data: a made-up pilot of up to 28 Mentors in each of six seasons, with illustrative answers. Nobody here is real, and you cannot save changes in this view.")
    sess, ratings, answers, acts = data["sessions"], data["ratings"], data["answers"], data["actions"]
    all_seasons = seasons.ordered(list(sess["season"]) + list(ratings["season"]) + list(answers["season"]) + list(acts["season"].dropna()))
    cur_label = seasons.current_label()
    if not all_seasons:
        st.info("No check-ins yet. Sign in as a Mentor and complete a check-in, or switch to the example data above.")
        return
    sel = c_sea.selectbox("Season", list(reversed(all_seasons)), index=0)
    msg = st.session_state.pop("flash", None)
    if msg:
        st.success(msg)

    # work everything out first, so the summary at the top can use the real numbers
    goals, funnel = _goal_rows(data, sel, k, admin)
    rating_tbl, baseline, changes = _rating_rows(data, sel, k)
    ready_tbl, ready_pct = _readiness(data, all_seasons, k)
    heard = _excerpts(data, sel, k, admin)

    _checklist(goals, funnel, heard, ready_tbl, ready_pct)
    st.markdown("Jump to:  " + "  ·  ".join(f"[{t}](#{a})" for t, a in SECTIONS))

    _targets(goals, funnel, k, admin, user)
    _ratings(rating_tbl, baseline, sel, k)
    _heard(heard, sel, k, admin, user, example)
    _response(data, sel, cur_label, admin, user, example)


# ---------------------------------------------------------------- 1. pilot targets
def _goal_rows(data, sel, k, admin):
    sess, rt = data["sessions"], data["ratings"]
    s_sel = sess[(sess["season"] == sel) & (sess["session_type"] == "Quarterly")]
    started, completed, invited = len(s_sel), int(s_sel["completed"].sum()), data["invited"]
    med = float(s_sel[s_sel["completed"]]["minutes"].median()) if completed else None
    qs = data["qstats"][data["qstats"]["season"] == sel].copy()
    qs["rate"] = qs["skipped"] / qs["reached"].where(qs["reached"] > 0)
    core_skip = qs[qs["qid"].isin(CORE) & (qs["reached"] >= k)]["rate"].max() if not qs.empty else None
    if pd.isna(core_skip):
        core_skip = None

    def avg(qid):
        s_ = rt[(rt["season"] == sel) & (rt["qid"] == qid)]["value"]
        return float(s_.mean()) if len(s_) >= k else None

    rows = []

    def judge(value, ok, label, short, shown):
        rows.append({"Goal": label, "Now": shown, "Status": "Not enough data" if value is None else ("Met" if ok else "Not yet"), "short": short})

    shown_ok = admin or completed >= k
    rate = completed / invited if invited and shown_ok else None
    judge(rate, rate is not None and rate >= TARGETS["completion"], f"At least {TARGETS['completion']:.0%} of Mentors finish", "finishing the check-in", f"{rate:.0%}" if rate is not None else "-")
    t = med if shown_ok else None
    judge(t, t is not None and t <= TARGETS["minutes"], f"Typical time is {TARGETS['minutes']:.0f} minutes or less", "time to finish", f"{t:.1f} min" if t is not None else "-")
    judge(core_skip, core_skip is not None and core_skip <= TARGETS["skip"], f"No core question skipped by more than {TARGETS['skip']:.0%}", "skipped questions", f"{core_skip:.0%} at most" if core_skip is not None else "-")
    for qid, label, short in (("P01", "Mentors find the check-in easy to use", "ease of use"), ("P02", "Mentors feel comfortable answering honestly", "comfort answering honestly"),
                              ("P05", "Mentors are satisfied with the check-in", "satisfaction")):
        v = avg(qid)
        judge(v, v is not None and v >= TARGETS["feedback"], f"{label} (average {TARGETS['feedback']:.1f} or higher)", short, f"{v:.1f}" if v is not None else "-")
    funnel = dict(invited=invited, started=started, completed=completed, med=med, show=admin or started >= k)
    return pd.DataFrame(rows), funnel


def _targets(goals, funnel, k, admin, user):
    _heading("Pilot targets", "pilot-targets", "Orange rows are targets not yet met. These targets are suggestions to agree with Friends of the Children.")
    colors = {"Met": "background-color:#D6EFD9;color:#1B5E20;font-weight:700", "Not yet": "background-color:#FFD9A0;color:#282828;font-weight:700"}
    st.dataframe(goals.drop(columns=["short"]).style.map(lambda x: colors.get(x, ""), subset=["Status"]), hide_index=True, width="stretch",
                 column_config={"Goal": st.column_config.TextColumn(width="large"), "Now": st.column_config.TextColumn(width="small"), "Status": st.column_config.TextColumn(width="small")})
    if funnel["show"]:
        st.caption(f"{funnel['invited']} invited, {funnel['started']} started, {funnel['completed']} finished.")
    else:
        st.caption(f"Fewer than {k} Mentors started a check-in this season, so the details are hidden to protect privacy.")
    _feedback_setup(admin, user)


def _feedback_setup(admin, user):
    """If the three pilot feedback questions are missing from the question set, an admin can add them here."""
    have = {q["id"] for q in db.get_published("questions")[1]}
    if set(FEEDBACK) <= have:
        return
    if not admin:
        st.info("The pilot feedback questions have not been added yet.")
        return
    st.info("The pilot feedback questions are not in your question set yet. They ask Mentors whether the check-in was easy, whether they felt comfortable answering honestly, and how satisfied they are.")
    if st.button("Add the standard pilot feedback questions", type="primary"):
        if db.get_draft("questions") is not None:
            st.error("You have unpublished question edits. Publish or discard them on the Questions page first.")
        else:
            ver, pub = db.get_published("questions")
            have_ids = {q["id"] for q in pub}
            new = pub + [q for q in ct.PILOT_QUESTIONS if q["id"] not in have_ids]
            v = db.publish("questions", new, user["username"], "Added the standard pilot feedback questions")
            db.log(user["username"], "added pilot feedback questions", f"version {v}")
            st.session_state.flash = f"Added. Mentors will see them in their next check-in (question version {v})."
            st.rerun()


# ---------------------------------------------------------------- 2. mentor ratings
def _rating_rows(data, sel, k):
    """One row per question still being asked. Returns the table, the baseline season, and the numeric changes (for the summary)."""
    rt = data["ratings"]
    asked = {q["id"] for q in db.get_published("questions")[1] if q.get("active", True)}
    areas = [c for c in CORE if c in asked] or [c for c in CORE if c in set(rt["qid"])]
    rated_seasons = seasons.ordered(list(rt["season"].unique())) if not rt.empty else []
    baseline = rated_seasons[0] if rated_seasons else sel
    comparing = sel != baseline

    def stats(season, qid):
        s_ = rt[(rt["season"] == season) & (rt["qid"] == qid)]["value"]
        return (float(s_.mean()), float((s_ >= 4).mean())) if len(s_) >= k else (None, None)

    rows, changes = [], []
    for c in areas:
        now_avg, now_hi = stats(sel, c)
        row = {"Question": dash.LONG[c]}
        if comparing:
            base_avg, _ = stats(baseline, c)
            row[f"Baseline ({baseline})"] = f"{base_avg:.1f}" if base_avg is not None else f"under {k} answers"
        row[f"This season ({sel})"] = f"{now_avg:.1f}" if now_avg is not None else f"under {k} answers"
        if comparing:
            if now_avg is not None and base_avg is not None:
                d = now_avg - base_avg
                changes.append((dash.SHORT[c], d))
                row["Change"] = "no change" if abs(d) < 0.05 else (f"▲ +{d:.1f}" if d > 0 else f"▼ −{abs(d):.1f}")
            else:
                row["Change"] = "-"
        row["Rated 4 or 5"] = f"{now_hi:.0%}" if now_hi is not None else "-"
        rows.append(row)
    return pd.DataFrame(rows), baseline, changes


def _ratings(tbl, baseline, sel, k):
    _heading("Mentor ratings", "mentor-ratings", "Average answer from 1 (low) to 5 (high), from the Mentors who answered. Higher is better.")
    if tbl.empty:
        st.info(f"Each question needs at least {k} answers to be shown.")
        return
    st.dataframe(tbl, hide_index=True, width="stretch", column_config={"Question": st.column_config.TextColumn(width="large")})
    if sel == baseline:
        st.caption(f"{baseline} is the baseline season. From the next season, this table shows how each rating has changed.")
    else:
        st.caption(f"Change compares {sel} with the baseline season, {baseline}. \"Rated 4 or 5\" is the share of Mentors who gave a high rating this season.")


# ---------------------------------------------------------------- 3. what we heard
def _excerpts(data, sel, k, admin):
    a = data["answers"][data["answers"]["season"] == sel].copy()
    enough = admin or a["mentor"].nunique() >= k
    stars = a[a["starred"] & ~a["escalated"]] if enough else a.iloc[0:0]
    return dict(all=a, stars=stars, enough=enough, n_answers=len(a), n_stars=len(stars), n_addressed=int(stars["addressed"].sum()) if len(stars) else 0)


def _heard(h, sel, k, admin, user, example):
    _heading("What we heard", "what-we-heard", "Standout excerpts the admin chose to share, with names removed. Tick Addressed once leadership has responded, and add a comment if you like. "
             "Mentors never see these notes.")
    if h["n_answers"] == 0:
        st.info("No spoken answers this season yet.")
        return
    if not h["enough"]:
        st.info(f"Fewer than {k} Mentors have spoken answers this season, so excerpts are hidden to protect privacy.")
        return
    st.caption(f"{h['n_answers']} spoken answers this season. {h['n_stars']} standout excerpt{'s' if h['n_stars'] != 1 else ''}, {h['n_addressed']} marked addressed.")
    if h["stars"].empty:
        st.caption("No excerpts have been chosen yet." + (" Choose them in the Review queue." if admin else " The program admin chooses them."))
        return
    for _, r in h["stars"].iterrows():
        rid = int(r["id"])
        body = (r["excerpt"] or r["text"])[:400]
        st.markdown(f"> “{body}”  \n> <span style='color:#555'>{r['season']}</span>", unsafe_allow_html=True)
        with st.form(f"heard_{rid}", border=False):
            c1, c2, c3 = st.columns([1.2, 4, 1.2], vertical_alignment="bottom")
            addressed = c1.checkbox("Addressed", value=bool(r["addressed"]), disabled=example)
            note = c2.text_input("Leadership comment", value=r["lnote"], placeholder="What was done or decided", help=NO_NAMES, disabled=example, max_chars=300)
            saved = c3.form_submit_button("Save", disabled=example)
        if r["lby"]:
            st.caption(f"Last updated by {r['lby']} on {str(r['lts'])[:10]}. {NO_NAMES}")
        if saved:
            db.upsert_leader_note(rid, user["username"], addressed, note)
            db.log(user["username"], "updated a leadership note", f"excerpt {rid}: {'addressed' if addressed else 'open'}")
            st.session_state.flash = "Saved."
            st.rerun()


# ---------------------------------------------------------------- 4. our response
def _response(data, sel, cur_label, admin, user, example):
    _heading("Our response", "our-response", "What was done about what Mentors raised. Add an item when you act, update its status as it moves, and record whether it helped. "
             "Finished items appear on the Mentor thank-you screen as \"You said, we did\".")
    acts = data["actions"].copy()
    if acts.empty:
        st.info("Nothing logged yet." + (" Add the first item below." if admin else ""))
    else:
        tbl = pd.DataFrame({"Season": acts["season"], "What Mentors raised": acts["raised"], "What we did": acts["action"], "Status": acts["status"],
                            "Who": acts["owner"], "Did it help?": acts["result"].replace("", "Not yet known")})
        st.dataframe(tbl.style.map(lambda x: STATUS_COLORS.get(x, ""), subset=["Status"]), hide_index=True, width="stretch",
                     column_config={"Season": st.column_config.TextColumn(width="small"), "What Mentors raised": st.column_config.TextColumn(width="medium"),
                                    "What we did": st.column_config.TextColumn(width="medium"), "Status": st.column_config.TextColumn(width="small"),
                                    "Who": st.column_config.TextColumn(width="small"), "Did it help?": st.column_config.TextColumn(width="small")})
    if not admin:
        return
    with st.expander("Add an item"):
        raised = st.text_area("What Mentors raised (in general terms, no names)", key="ac_raised", height=80)
        did = st.text_area("What we did or will do", key="ac_did", height=80)
        c1, c2, c3 = st.columns(3)
        status = c1.selectbox("Status", ["Planned", "In progress", "Done"], key="ac_status")
        owner = c2.text_input("Who is responsible", key="ac_owner")
        season = c3.selectbox("Season", list(reversed(seasons.ordered([sel, cur_label]))), key="ac_season")
        if st.button("Add to the list", disabled=example):
            if not raised.strip() or not did.strip():
                st.error("Fill in what was raised and what you did.")
            else:
                db.add_action(season, raised.strip(), did.strip(), status, owner.strip(), user["username"])
                db.log(user["username"], "added an action", did.strip()[:80])
                st.session_state.flash = "Added."
                st.rerun()
    if not acts.empty:
        with st.expander("Update an item"):
            aid = st.selectbox("Item", acts["id"].tolist(), format_func=lambda i: f"{acts[acts['id'] == i]['action'].iloc[0][:70]}", key="ac_pick")
            row = acts[acts["id"] == aid].iloc[0]
            c1, c2 = st.columns(2)
            new_status = c1.selectbox("Status", ["Planned", "In progress", "Done"], index=["Planned", "In progress", "Done"].index(row["status"]) if row["status"] in ("Planned", "In progress", "Done") else 0, key=f"us_{aid}")
            res_opts = ["", "Helped", "Not yet", "Unsure"]
            new_res = c2.selectbox("Did it help?", res_opts, index=res_opts.index(row["result"]) if row["result"] in res_opts else 0, key=f"ur_{aid}")
            if st.button("Save changes", disabled=example, key=f"ub_{aid}"):
                db.update_action(int(aid), status=new_status, result=new_res)
                db.log(user["username"], "updated an action", f"id {aid}")
                st.session_state.flash = "Updated."
                st.rerun()


# ---------------------------------------------------------------- checklist and readiness
def _checklist(goals, funnel, heard, ready_tbl, ready_pct):
    """The top of the page: two plain checklists. Left: is the pilot on track? Right: what can the data support yet?"""
    icon = {"Met": "✅", "Not yet": "🟠", "Not enough data": "⚪"}
    judged = goals[goals["Status"] != "Not enough data"]
    met = int((goals["Status"] == "Met").sum())
    left, right = st.columns([3, 2])
    with left.container(border=True):
        st.markdown(f"#### Pilot checklist: {met} of {len(goals)} targets met")
        lines = []
        for _, r in goals.iterrows():
            now = f"**{r['Now']}**" if r["Status"] != "Not enough data" else "not enough data yet"
            lines.append(f"{icon[r['Status']]} {r['Goal']}: {now}")
        if heard["enough"] and heard["n_stars"]:
            done = heard["n_addressed"] == heard["n_stars"]
            lines.append(f"{'✅' if done else '⬜'} Standout Mentor comments addressed: **{heard['n_addressed']} of {heard['n_stars']}**")
        st.markdown("\n\n".join(lines))
        if funnel["show"] and funnel["invited"]:
            st.caption(f"{funnel['completed']} of {funnel['invited']} invited Mentors finished this season.")
        if len(judged) < len(goals):
            st.caption("⚪ means fewer Mentors have answered than the privacy minimum, or no one has yet.")
    with right.container(border=True):
        st.markdown(f"#### Data readiness: {ready_pct}%")
        st.progress(ready_pct / 100)
        lines = []
        for _, r in ready_tbl.iterrows():
            if r["Status"] == "Ready":
                lines.append(f"✅ {r['What it unlocks']}")
            elif r["Status"] == "Building":
                lines.append(f"🔄 {r['What it unlocks']} ({r['Progress']:.0%}). Needs: {r['What is needed'][0].lower() + r['What is needed'][1:]}")
            else:
                lines.append(f"⏳ {r['What it unlocks']}. Needs: {r['What is needed'][0].lower() + r['What is needed'][1:]}")
        st.markdown("\n\n".join(lines))
        st.caption("Ready means enough data to rely on. This is about the data, not a grade for the pilot.")


def _readiness(data, all_seasons, k):
    """What the data can support yet. Returns the table and one overall percentage (the average progress across the items)."""
    sess = data["sessions"]
    per = {s: int(sess[(sess["season"] == s) & sess["completed"] & (sess["session_type"] == "Quarterly")]["mentor"].nunique()) for s in all_seasons}
    ok_seasons = sum(1 for n in per.values() if n >= k)
    latest = per.get(all_seasons[-1], 0)
    tg = dash.demo_tags() if data["example"] else dash.live_tags()
    tagged = int(tg[tg["wave"] == all_seasons[-1]]["mentor"].nunique()) if not tg.empty else 0
    exits = int(sess[(sess["session_type"] == "Exit") & sess["completed"]]["mentor"].nunique()) if not sess.empty else 0
    items = [
        ("Group averages for one season", "At least %d Mentors finish" % k, latest, k),
        ("Up and down arrows between seasons", "2 seasons with %d+ Mentors each" % k, ok_seasons, 2),
        ("Patterns over a full year", "4 seasons with %d+ Mentors each" % k, ok_seasons, 4),
        ("Theme explorer", "%d+ Mentors with tagged answers in a season" % k, tagged, k),
        ("Checking the risk rules against real departures", "A full year and 10 exit interviews", min(ok_seasons / 4, exits / 10) * 10, 10),
        ("Comparing groups (for example, time as a Mentor)", "%d+ Mentors in each group, and group details collected" % k, 0, k),
    ]
    out = []
    for name, need, have, target in items:
        prog = max(0.0, min(1.0, have / target)) if target else 0.0
        out.append({"What it unlocks": name, "What is needed": need, "Progress": prog, "Status": "Ready" if prog >= 1 else ("Building" if prog > 0 else "Later")})
    tbl = pd.DataFrame(out)
    return tbl, int(round(tbl["Progress"].mean() * 100))
