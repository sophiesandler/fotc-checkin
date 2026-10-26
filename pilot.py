"""Pilot year: what is useful before there is enough data for trends. Participation, a baseline, reading what Mentors said,
what was done about it, feedback on the check-in itself, and what the data can support yet."""
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

import content as ct
import dashboard as dash
import db
import risk
import seasons
import ui
from auth import require

CORE = risk.CORE
SHORT = dash.SHORT
FEEDBACK = {"P01": "It was easy to use this check-in", "P02": "I felt comfortable answering honestly", "P03": "I trust my answers will be used to support Mentors"}
TARGETS = {"completion": 0.80, "minutes": 8.0, "skip": 0.10, "trust": 4.0}
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
    rows = db.fetch_responses()
    resp = pd.DataFrame(rows)
    pq = db.get_published("questions")[1]
    qtext = {q["id"]: q["text"] for q in pq}
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
    ans = []
    for r in sp:
        text = (r["transcript"] or r["text_answer"] or "").strip()
        has_audio = r["audio_note"] in ("recorded", "deleted")
        if not text:
            text = "(recording, not yet typed up)" if has_audio else ""
        rv = rev.get(r["id"], {})
        ans.append(dict(id=r["id"], mentor=r["participant_code"], season=dash.season_of(r), qid=r["question_id"], qtext=qtext.get(r["question_id"], r["question_id"]),
                        text=text, audio=bool(has_audio), reviewed=bool(rv.get("reviewed")), starred=bool(rv.get("starred")), excerpt=rv.get("excerpt", ""),
                        themes=", ".join(sorted(set(tag_by.get(r["id"], [])))), escalated=r["id"] in esc))
    answers = pd.DataFrame(ans, columns=["id", "mentor", "season", "qid", "qtext", "text", "audio", "reviewed", "starred", "excerpt", "themes", "escalated"])
    acts = pd.DataFrame(db.get_actions(), columns=["id", "ts", "season", "raised", "action", "status", "owner", "result", "note", "by_user"])
    return dict(example=False, invited=int(db.count_active_mentors()), sessions=sess, qstats=qstats, ratings=ratings, answers=answers, actions=acts,
                qtext=qtext, qblock=qblock, qorder=qorder)


def example_pilot():
    rng = np.random.default_rng(7)
    d = dash.demo_checkins()
    first = d[d["wave"] == "Summer 2025"]
    mentors = sorted(first["mentor"].unique())[:28]
    season = "Summer 2025"
    pq = db.get_published("questions")[1]
    qtext = {q["id"]: q["text"] for q in pq}
    qblock = {q["id"]: q["block"] for q in pq}
    qorder = {q["id"]: i for i, q in enumerate(pq)}
    n_q = 18
    sess = []
    for i, m in enumerate(mentors):
        done = i < 24
        sess.append(dict(session_id=f"ex{i}", participant_code=m, mentor=m, season=season, session_type="Quarterly", n_questions=n_q,
                         last_idx=n_q if done else int(rng.integers(4, 12)), completed=done,
                         minutes=float(np.clip(rng.normal(7.2, 1.9), 3.2, 13)) if done else float(abs(rng.normal(3.5, 1.2)))))
    sess = pd.DataFrame(sess)
    skip = {"C01": .02, "C02": .03, "C03": .03, "C04": .05, "C05": .12, "C06": .05, "C07": .04, "C08": .06, "C09": .09, "R01": .04, "R02": .05, "S01": .17,
            "P01": .02, "P02": .03, "P03": .07, "P04": .29, "Z01": .35, "O01": .58}
    qs = []
    for j, (q, rate) in enumerate(skip.items()):
        reached = 28 - min(j // 3, 4)
        qs.append(dict(season=season, qid=q, reached=reached, skipped=int(round(reached * rate))))
    ratings = []
    for m in mentors[:24]:
        row = first[first["mentor"] == m].iloc[0]
        for c in CORE:
            if not pd.isna(row[c]):
                ratings.append(dict(mentor=m, season=season, qid=c, value=float(row[c])))
        for qid, p in (("P01", [.0, .02, .08, .35, .55]), ("P02", [.02, .06, .22, .40, .30]), ("P03", [.04, .10, .30, .36, .20])):
            ratings.append(dict(mentor=m, season=season, qid=qid, value=float(rng.choice([1, 2, 3, 4, 5], p=p))))
    tg = dash.demo_tags()
    tg = tg[(tg["wave"] == season) & tg["mentor"].isin(mentors) & (tg["quote"] != "")].head(26)
    answers = []
    for i, r in enumerate(tg.itertuples(index=False)):
        answers.append(dict(id=1000 + i, mentor=r.mentor, season=season, qid=r.question, qtext=qtext.get(r.question, r.question), text=r.quote, audio=bool(i % 2 == 0),
                            reviewed=i % 3 != 0, starred=i in (1, 4, 9), excerpt="", themes=dash.THEME_SHORT.get(r.theme, r.theme), escalated=False))
    for i, text in enumerate(["The record button was easy to find.", "I wasn't sure whether my supervisor could hear this.", "I would rather type than speak some days.",
                              "It took longer than I expected.", "I liked that I could skip questions.", "The wording of the question about time when youth are away confused me."]):
        answers.append(dict(id=2000 + i, mentor=mentors[i], season=season, qid="P04", qtext=qtext.get("P04", "What would make this check-in better?"), text=text, audio=False,
                            reviewed=False, starred=False, excerpt="", themes="About the check-in", escalated=False))
    acts = pd.DataFrame([
        dict(id=1, ts="", season=season, raised="Portfolio gets overwhelming when a youth is in crisis", action="Set up a backup Mentor rota for crisis weeks", status="Done", owner="Program Director", result="Helped", note="", by_user=""),
        dict(id=2, ts="", season=season, raised="Time when youth are away feels aimless", action="Pilot a shared planning block on Tuesdays", status="In progress", owner="Program team", result="", note="", by_user=""),
        dict(id=3, ts="", season=season, raised="Training did not cover home visits", action="Add shadowing to onboarding", status="Planned", owner="HR Specialist", result="", note="", by_user=""),
    ])
    return dict(example=True, invited=30, sessions=sess, qstats=pd.DataFrame(qs), ratings=pd.DataFrame(ratings), answers=pd.DataFrame(answers), actions=acts,
                qtext=qtext, qblock=qblock, qorder=qorder)


# ---------------------------------------------------------------- page
def page_pilot():
    user = require("leader", "admin")
    admin = user["role"] == "admin"
    k = dash._k()
    st.title("Pilot year")
    st.caption("In the first year there is not enough data for trends, so this page focuses on whether the check-in works, what Mentors are saying, and what is being done about it.")
    if "pilot_src" not in st.session_state:
        live_done = sum(1 for s_ in db.get_sessions() if s_["completed"])
        st.session_state.pilot_src = SRC[0] if live_done >= k else SRC[1]
    choice = st.radio("Data shown", SRC, index=SRC.index(st.session_state.pilot_src), horizontal=True, key="pilot_radio",
                      on_change=lambda: st.session_state.update(pilot_src=st.session_state.pilot_radio))
    data = example_pilot() if choice == SRC[1] else live_pilot()
    example = data["example"]
    if example:
        st.warning("Example data: a made-up pilot of 28 Mentors, with illustrative answers. Nobody here is real, and you cannot save changes in this view.")
    sess, ratings, answers, acts = data["sessions"], data["ratings"], data["answers"], data["actions"]
    all_seasons = seasons.ordered(list(sess["season"]) + list(ratings["season"]) + list(answers["season"]) + list(acts["season"].dropna()))
    cur_label = seasons.current_label()
    if not all_seasons:
        st.info("No check-ins yet. Sign in as a Mentor and complete a check-in, or switch to the example data above.")
        return
    sel = st.selectbox("Season", list(reversed(all_seasons)), index=0)
    s_sel = sess[(sess["season"] == sel) & (sess["session_type"] == "Quarterly")]
    started, completed = len(s_sel), int(s_sel["completed"].sum())
    invited = data["invited"]
    fmt = lambda n: n if (admin or n >= k) else f"under {k}"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mentors invited", invited, help="Active Mentor accounts.")
    c2.metric("Finished this season", fmt(completed))
    c3.metric("Completion rate", f"{completed / invited * 100:.0f}%" if invited and (admin or completed >= k) else f"under {k}", help="Finished check-ins divided by Mentors invited.")
    med = float(s_sel[s_sel["completed"]]["minutes"].median()) if completed else None
    c4.metric("Typical time", f"{med:.1f} min" if med is not None and (admin or completed >= k) else "n/a", help="Middle time among finished check-ins. It includes time away from the screen.")

    tabs = st.tabs(["Pilot health", "Baseline", "What Mentors said", "You said, we did", "Pilot feedback", "Readiness"])
    with tabs[0]:
        _health(data, sel, s_sel, started, completed, invited, med, k, admin)
    with tabs[1]:
        _baseline(data, all_seasons, sel, k)
    with tabs[2]:
        _said(data, sel, k, admin)
    with tabs[3]:
        _actions(data, sel, cur_label, admin, user, example)
    with tabs[4]:
        _feedback(data, sel, k, admin, user, example)
    with tabs[5]:
        _readiness(data, all_seasons, k)


# ---------------------------------------------------------------- tabs
def _health(data, sel, s_sel, started, completed, invited, med, k, admin):
    qs = data["qstats"][data["qstats"]["season"] == sel].copy()
    qs["rate"] = qs["skipped"] / qs["reached"].where(qs["reached"] > 0)
    qs["optional"] = qs["qid"].map(lambda q: data["qblock"].get(q) in ("Optional", "Closing"))
    core_skip = qs[qs["qid"].isin(CORE) & (qs["reached"] >= k)]["rate"].max() if not qs.empty else None
    trust = data["ratings"][(data["ratings"]["season"] == sel) & (data["ratings"]["qid"] == "P03")]["value"]
    trust_m = float(trust.mean()) if len(trust) >= k else None
    ui.section("How is the pilot going?", "Purpose: check whether the check-in is working. How to use: look for orange rows, which are goals not yet met. These targets are suggestions to agree with Friends of the Children.")
    rows = []
    def judge(value, ok, label, shown):
        rows.append({"Goal": label, "Now": shown, "Status": "Not enough data" if value is None else ("Met" if ok else "Not yet")})
    rate = completed / invited if invited and (admin or completed >= k) else None
    judge(rate, rate is not None and rate >= TARGETS["completion"], f"At least {TARGETS['completion']:.0%} of Mentors finish", f"{rate:.0%}" if rate is not None else "-")
    judge(med if (admin or completed >= k) else None, med is not None and med <= TARGETS["minutes"], f"Typical time is {TARGETS['minutes']:.0f} minutes or less", f"{med:.1f} min" if med is not None else "-")
    judge(core_skip, core_skip is not None and core_skip <= TARGETS["skip"], f"No core question skipped by more than {TARGETS['skip']:.0%}", f"{core_skip:.0%} at most" if core_skip is not None else "-")
    judge(trust_m, trust_m is not None and trust_m >= TARGETS["trust"], f"Mentors trust it (average {TARGETS['trust']:.1f} or higher)", f"{trust_m:.1f}" if trust_m is not None else "-")
    goals = pd.DataFrame(rows)
    st.dataframe(goals.style.map(lambda x: {"Met": "background-color:#D6EFD9;color:#1B5E20;font-weight:700", "Not yet": "background-color:#FFD9A0;color:#282828;font-weight:700"}.get(x, ""), subset=["Status"]),
                 hide_index=True, width="stretch")

    ui.section("Who took part", "Purpose: see how many Mentors were invited, started, and finished. How to use: a big drop between steps shows where to follow up.")
    if not (admin or started >= k):
        st.info(f"Fewer than {k} Mentors started a check-in this season, so the details are hidden to protect privacy.")
    else:
        fun = pd.DataFrame({"Step": ["Invited", "Started", "Finished"], "Mentors": [invited, started, completed]})
        b = alt.Chart(fun).mark_bar(color=dash.ORANGE_).encode(x=alt.X("Mentors:Q", title=None), y=alt.Y("Step:N", sort=["Invited", "Started", "Finished"], title=None))
        dash.plot(b + b.mark_text(align="left", dx=4, color="#282828").encode(text="Mentors:Q"), 160)
        sp = data["answers"][(data["answers"]["season"] == sel)]
        if len(sp) >= k:
            audio_n, typed_n = int(sp["audio"].sum()), int((~sp["audio"]).sum())
            st.caption(f"Spoken questions: {audio_n} answered by recording and {typed_n} by typing.")

    ui.section("Questions that may need a new look", "Purpose: find questions many Mentors skip. How to use: reword flagged questions on the Questions page. Optional questions are not flagged.")
    if qs.empty:
        st.info("No answers yet this season.")
        return
    flagged = qs[(qs["reached"] >= k) & (qs["rate"] >= 0.20) & (~qs["optional"])]
    if flagged.empty:
        st.success("No required question was skipped by 1 in 5 Mentors or more.")
    else:
        for _, r in flagged.iterrows():
            st.markdown(f"- **{r['qid']}**: {data['qtext'].get(r['qid'], '')} ({r['rate']:.0%} skipped)")
        st.caption("A question many Mentors skip may be unclear, too personal, or too long. Reword it on the Questions page.")
    if admin:
        qs = qs.assign(order=qs["qid"].map(lambda q: data["qorder"].get(q, 99))).sort_values("order")
        tbl = pd.DataFrame({"ID": qs["qid"], "Question": qs["qid"].map(lambda q: data["qtext"].get(q, "")), "Mentors who reached it": qs["reached"],
                            "Skipped": qs["rate"].fillna(0), "Optional": qs["optional"].map({True: "optional", False: ""})})
        with st.expander("All questions"):
            st.caption("Every question this season, with how many Mentors reached it and how many skipped it.")
            st.dataframe(tbl, hide_index=True, width="stretch", column_config={"Skipped": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent")})
        stopped = s_sel[~s_sel["completed"]]
        ui.section("Where people stopped", "Purpose: find where unfinished check-ins ended. How to use: a spike at one question number suggests that question, or the overall length, is a problem.")
        if stopped.empty:
            st.caption("Everyone who started has finished.")
        else:
            dd = stopped.assign(Question=stopped["last_idx"].astype(int) + 1).groupby("Question").size().reset_index(name="Mentors")
            b = alt.Chart(dd).mark_bar(color=dash.BLUE_).encode(x=alt.X("Question:O", title="Question number where they stopped", axis=alt.Axis(labelAngle=0)),
                                                                 y=alt.Y("Mentors:Q", title=None, axis=alt.Axis(tickMinStep=1)))
            dash.plot(b, 200)
            st.caption("Bars are check-ins that were started but not finished. A spike means something around that question needs attention.")


def _baseline(data, all_seasons, sel, k):
    ui.section("Your starting line", "Purpose: record where things stand before anything changes. How to use: this season is the baseline. Next season the Dashboard shows arrows against it.")
    if sel != all_seasons[0]:
        st.caption(f"The baseline season is {all_seasons[0]}. You are looking at {sel}.")
    r = data["ratings"][(data["ratings"]["season"] == sel) & data["ratings"]["qid"].isin(CORE)]
    rows, mix = [], []
    for c in CORE:
        s_ = r[r["qid"] == c]["value"]
        if len(s_) < k:
            rows.append({"Area": dash.LONG[c], "Answers": f"under {k}", "Average (1 to 5)": None, "Rated 4 or 5": None, "Rated 1 or 2": None})
            continue
        rows.append({"Area": dash.LONG[c], "Answers": str(len(s_)), "Average (1 to 5)": round(float(s_.mean()), 1), "Rated 4 or 5": float((s_ >= 4).mean()), "Rated 1 or 2": float((s_ <= 2).mean())})
        for score in range(1, 6):
            mix.append({"Area": SHORT[c], "Score": str(score), "Share": float((s_ == score).mean())})
    ui.section("Average answers this season", "How many Mentors answered, the average, and the share who rated each area high (4 or 5) or low (1 or 2).", level=3)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Average (1 to 5)": st.column_config.NumberColumn(format="%.1f"),
                                "Rated 4 or 5": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent"),
                                "Rated 1 or 2": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent")})
    if mix:
        ui.section("How answers were spread", "The whole range of answers for each area. Orange segments are low scores and blue segments are high scores.", level=3)
        dash.plot(alt.Chart(pd.DataFrame(mix)).mark_bar().encode(
            x=alt.X("Share:Q", axis=alt.Axis(format="%"), title=None, stack="zero"), y=alt.Y("Area:N", sort=[SHORT[c] for c in CORE], title=None),
            color=alt.Color("Score:N", scale=alt.Scale(domain=["1", "2", "3", "4", "5"], range=[ui.SCALE[i] for i in range(1, 6)]),
                            legend=alt.Legend(title="Score (1 low, 5 high)", orient="bottom", direction="horizontal")), order=alt.Order("Score:N")), 300)
    else:
        st.info(f"Each area needs at least {k} answers to be shown.")


def _said(data, sel, k, admin):
    a = data["answers"][data["answers"]["season"] == sel].copy()
    ui.section("What Mentors said", "A summary of the spoken answers this season, with excerpts the admin chose for leadership. Names are removed. "
               + ("To look up an individual answer or choose excerpts, open the Review queue and use the optional lookup." if admin else "The program admin reads every answer and chooses which excerpts to share."))
    if a.empty:
        st.info("No spoken answers this season yet.")
        return
    enough = admin or a["mentor"].nunique() >= k
    m1, m2, m3 = st.columns(3)
    m1.metric("Spoken answers", len(a) if enough else f"under {k}")
    m2.metric("Read by the admin", f"{a['read' if 'read' in a else 'reviewed'].mean() * 100:.0f}%" if enough else f"under {k}")
    m3.metric("Standout excerpts", int(a["starred"].sum()) if enough else f"under {k}")
    if not enough:
        st.info(f"Fewer than {k} Mentors have spoken answers this season, so excerpts are hidden to protect privacy.")
        return
    ui.section("Standout excerpts", "Quotes the admin chose to share. Use them to put a human voice next to the numbers.", level=3)
    stars = a[a["starred"] & ~a["escalated"]]
    if stars.empty:
        st.caption("No excerpts have been chosen yet.")
    for _, r in stars.iterrows():
        body = (r["excerpt"] or r["text"])[:400]
        st.markdown(f"> “{body}”  \n> <span style='color:#555'>{r['season']}</span>", unsafe_allow_html=True)


def _actions(data, sel, cur_label, admin, user, example):
    ui.section("You said, we did", "Purpose: show Mentors and leadership what was done about what they raised. How to use: add an item when you act on a concern, update its status as it moves, and record whether it helped. Finished items appear on the Mentor thank-you screen.")
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
    msg = st.session_state.pop("flash", None)
    if msg:
        st.success(msg)


def _feedback(data, sel, k, admin, user, example):
    ui.section("Feedback on the check-in itself", "Purpose: learn whether Mentors find the check-in easy and trustworthy. How to use: bars past the dashed line meet the target. Orange bars do not.")
    have = {q["id"] for q in db.get_published("questions")[1]}
    if not set(FEEDBACK) <= have:
        if admin:
            st.info("The pilot feedback questions are not in your question set yet. They ask Mentors whether the check-in was easy, whether they felt comfortable, and whether they trust it.")
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
        else:
            st.info("The pilot feedback questions have not been added yet.")
    msg = st.session_state.pop("flash", None)
    if msg:
        st.success(msg)
    r = data["ratings"][(data["ratings"]["season"] == sel) & data["ratings"]["qid"].isin(FEEDBACK)]
    rows = []
    for q, label in FEEDBACK.items():
        s_ = r[r["qid"] == q]["value"]
        rows.append({"Statement": label, "Average (1 to 5)": float(s_.mean()) if len(s_) >= k else None, "Answers": len(s_) if len(s_) >= k else None})
    d = pd.DataFrame(rows)
    if d["Average (1 to 5)"].notna().any():
        b = alt.Chart(d.dropna()).mark_bar().encode(
            x=alt.X("Average (1 to 5):Q", scale=alt.Scale(domain=[1, 5]), title="Average (1 to 5)"), y=alt.Y("Statement:N", sort=list(FEEDBACK.values()), title=None, axis=alt.Axis(labelLimit=360)),
            color=alt.condition(alt.datum["Average (1 to 5)"] >= TARGETS["trust"], alt.value(dash.BLUE_), alt.value(dash.ORANGE_)))
        target = alt.Chart(pd.DataFrame({"x": [TARGETS["trust"]]})).mark_rule(color="#282828", strokeDash=[6, 4], strokeWidth=2).encode(x="x:Q")
        dash.plot(b + target + b.mark_text(align="left", dx=4, color="#282828").encode(text=alt.Text("Average (1 to 5):Q", format=".1f")), 200)
        st.caption(f"The dashed line is the suggested target ({TARGETS['trust']:.1f}). Blue meets it, orange does not. Trust matters most: if Mentors do not trust the check-in, they will stop answering honestly.")
    else:
        st.info(f"Each statement needs at least {k} answers to be shown.")
    if admin:
        st.caption("Read comments about the check-in in the Review queue's optional lookup by choosing question P04.")


def _readiness(data, all_seasons, k):
    ui.section("What the data can support yet", "Purpose: show what you can rely on now and what to wait for. How to use: Ready means enough data; Building means partly there; Later means not yet. Share this table when someone asks why a chart is empty.")
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
        ("Comparing groups (for example, time as a Mentor)", "%d+ Mentors in each group, and group details collected" % k, 0 if not data["example"] else 0, k),
    ]
    out = []
    for name, need, have, target in items:
        prog = max(0.0, min(1.0, have / target)) if target else 0.0
        status = "Ready" if prog >= 1 else ("Building" if prog > 0 else "Later")
        out.append({"What it unlocks": name, "What is needed": need, "Progress": prog, "Status": status})
    tbl = pd.DataFrame(out)
    colors = {"Ready": "background-color:#D6EFD9;color:#1B5E20;font-weight:700", "Building": "background-color:#FFD9A0;color:#282828;font-weight:700", "Later": "background-color:#E9E9E9;color:#555;font-weight:700"}
    st.dataframe(tbl.style.map(lambda x: colors.get(x, ""), subset=["Status"]), hide_index=True, width="stretch",
                 column_config={"Progress": st.column_config.ProgressColumn(min_value=0, max_value=1, format="percent")})
    st.caption("A statistical risk model needs far more departures than a single chapter usually has, so this app uses plain indicator rules that people can read and change.")
