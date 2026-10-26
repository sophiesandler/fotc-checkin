"""Review queue. Transcription and tagging run on their own. This page shows only what needs a person:
answers the AI flagged for support or asked a person to check, and answers the automation could not finish.
The full list of answers is still here, but tucked away as an optional lookup."""
import pandas as pd
import streamlit as st

import db
import transcribe as tr
import ui
from auth import require

import pipeline as pl
from pipeline import message as _message, parse_reply, tag_one as _tag_one_impl  # noqa: F401  (parse_reply is also used by tests)


def claude_available():
    return bool(pl.tagging_providers())


def _tag_one(rid, qid, qtext, text, user, codebook, ver):
    return pl.tag_one(rid, qid, qtext, text, user, codebook, ver)


def _flash(msg):
    st.session_state.flash = msg
    st.rerun()


def _link(key, label, icon=":material/arrow_forward:"):
    pg = (st.session_state.get("_pages") or {}).get(key)
    if pg is not None:
        st.page_link(pg, label=label, icon=icon)


# ---------------------------------------------------------------- data
def _records(rows, codebook):
    done_tags = db.tagged_ids()
    reviews = {r["response_id"]: r for r in db.get_reviews()}
    tag_by, auto_ids, esc_ids = {}, set(), set()
    for t in db.get_tags():
        tag_by.setdefault(t["response_id"], []).append(t["theme"])
        if t["escalation"]:
            esc_ids.add(t["response_id"])
        if str(t.get("by_user", "")).startswith("auto:"):
            auto_ids.add(t["response_id"])
    names = {t["id"]: t["name"] for t in codebook["themes"]}
    recs = []
    for r in rows:
        text = (r["transcript"] or r["text_answer"] or "").strip()
        rv = reviews.get(r["id"], {})
        status = ("Tagged (auto)" if r["id"] in auto_ids else "Tagged") if r["id"] in done_tags else ("Ready to tag" if text else "Needs transcript")
        recs.append(dict(id=r["id"], mentor=r["participant_code"], season=r["season"] or "", qid=r["question_id"], text=text, audio_note=r["audio_note"] or "",
                         qver=r["question_version"], status=status, read=bool(rv.get("reviewed")), star=bool(rv.get("starred")), excerpt=rv.get("excerpt", ""),
                         themes=", ".join(sorted({names.get(t, t) for t in tag_by.get(r["id"], [])})), esc=r["id"] in esc_ids,
                         typed=bool((r["text_answer"] or "").strip())))
    return pd.DataFrame(recs, columns=["id", "mentor", "season", "qid", "text", "audio_note", "qver", "status", "read", "star", "excerpt", "themes", "esc", "typed"])


def _qtext(r, qtexts_now):
    return {q["id"]: q["text"] for q in (db.get_published_version("questions", int(r["qver"])) or [])}.get(r["qid"], qtexts_now.get(r["qid"], r["qid"]))


# ---------------------------------------------------------------- pieces of one answer
def _recording_and_transcript(r, user, kp):
    """Listen and check the written version. Fixing it here is the 'transcription validation' step."""
    rid = int(r["id"])
    if r["audio_note"] == "recorded":
        blob = db.get_audio(rid)
        if blob:
            st.audio(bytes(blob), format="audio/wav")
            if st.session_state.get("last_audio") != rid:
                db.log(user["username"], "played audio", f"response {rid}")
                st.session_state.last_audio = rid
    elif r["audio_note"] == "deleted":
        st.caption("The recording was deleted. The transcript is kept.")
    if r["audio_note"] in ("recorded", "deleted") or not r["typed"]:
        cur = st.text_area("Transcript", value=r["text"], key=f"{kp}tr_{rid}", height=120, placeholder="Type what was said in the recording here.",
                           help="Automatic transcripts are close but not perfect. Check names, places, and numbers.")
        t1, t2, t3 = st.columns(3)
        if t1.button("Save transcript", key=f"{kp}st_{rid}"):
            if cur.strip():
                db.set_transcript(rid, cur.strip())
                if rid not in db.tagged_ids():
                    db.clear_proc(rid)
                db.log(user["username"], "saved a transcript", f"response {rid}")
                if rid not in db.tagged_ids() and pl.tagging_providers():
                    with st.spinner("Tagging..."):
                        pl.process_response(rid, user["username"], do_transcribe=False)
                _flash("Transcript saved.")
            else:
                st.error("Type or generate the transcript first.")
        if r["audio_note"] == "recorded" and tr.providers() and t2.button("Transcribe again", key=f"{kp}at_{rid}"):
            with st.spinner("Transcribing..."):
                ok_, m_ = tr.transcribe_response(rid, user["username"])
            if ok_:
                db.clear_proc(rid)
            _flash("Transcribed. Check it against the recording." if ok_ else m_)
        if r["audio_note"] == "recorded" and t3.button("Delete the recording", key=f"{kp}dr_{rid}"):
            db.delete_audio(rid)
            db.log(user["username"], "deleted audio", f"response {rid}")
            _flash("Recording deleted.")
    else:
        st.markdown(f"**Answer (typed by the Mentor):** {r['text']}")


def _themes(r, qtext, codebook, codebook_ver, user, kp):
    rid = int(r["id"])
    text = r["text"].strip()
    if not text:
        st.info("This answer needs a transcript before it can be tagged.")
        return
    mine = [t for t in db.get_tags() if t["response_id"] == rid]
    if mine:
        st.dataframe(pd.DataFrame(mine)[["theme", "valence", "quote", "aggregate_only", "escalation"]].rename(
            columns={"theme": "Theme", "valence": "Valence", "quote": "Exact words", "aggregate_only": "Counted only in totals", "escalation": "Safety flag"}),
            hide_index=True, width="stretch")
    if pl.tagging_providers() and st.button("Tag automatically" if not mine else "Tag again automatically", key=f"{kp}tc_{rid}"):
        with st.spinner("Tagging..."):
            ok_, m_ = _tag_one(rid, r["qid"], qtext, text, user["username"], codebook, codebook_ver)
        _flash("Tagged. Check the themes below." if ok_ else m_)
    with st.expander("Tag by hand instead", expanded=False):
        st.caption("Open a new Claude chat. First paste the tagging instructions (Themes and rules > Tagging instructions > Download). Then paste this message and send it.")
        st.code(_message(r["qid"], qtext, rid, text), language="text")
        reply = st.text_area("Paste Claude's reply here", key=f"{kp}rp_{rid}", height=140)
        if st.button("Check and save tags", type="primary", key=f"{kp}cs_{rid}"):
            errs, tags, flags = parse_reply(reply, text, {t["id"] for t in codebook["themes"]})
            if errs:
                for e in errs:
                    st.error(e)
            elif not tags and not flags:
                st.warning("The reply has no themes (for example, a very short answer). Nothing was saved.")
            else:
                db.add_tags(rid, tags, user["username"], escalation=bool(flags))
                if flags:
                    db.set_proc(rid, "tag", "flag", ", ".join(str(f.get("category", "")).replace("_", " ") for f in flags))
                else:
                    db.clear_proc(rid)
                db.log(user["username"], "saved tags", f"response {rid}: {len(tags)} tag(s), escalation={bool(flags)}")
                _flash("Saved. This answer raised a safety or welfare flag. Follow Friends of the Children's procedure." if flags else f"Saved {len(tags)} tag(s).")


def _share(r, user, kp):
    rid = int(r["id"])
    if not r["text"].strip():
        st.caption("Nothing to read yet.")
        return
    st.warning("Read before you star: remove names and any detail that could identify a Mentor or a youth.")
    excerpt = st.text_area("Excerpt for leadership", value=r["excerpt"] or r["text"], key=f"{kp}ex_{rid}", height=100, disabled=bool(r["esc"]))
    cr, cs = st.columns(2)
    reviewed = cr.checkbox("I have read this answer", value=bool(r["read"]), key=f"{kp}rv_{rid}")
    starred = cs.checkbox("Star as a standout excerpt", value=bool(r["star"]), key=f"{kp}sr_{rid}", disabled=bool(r["esc"]))
    if st.button("Save", key=f"{kp}sv_{rid}"):
        db.upsert_review(rid, user["username"], reviewed or starred, starred and not r["esc"], excerpt.strip())
        db.log(user["username"], "reviewed an answer", f"response {rid}, starred={starred}")
        note = "Saved."
        if (reviewed or starred) and r["audio_note"] == "recorded" and tr.retention() == "after_read":
            db.delete_audio(rid)
            note = "Saved. The recording was deleted, as set in Settings."
        _flash(note)


def _quote(text):
    return "> " + (text or "(no transcript yet)").replace("\n", "\n> ")


# ---------------------------------------------------------------- queue cards
def _flag_card(f, r, qtext, codebook, ver, user):
    rid = int(r["id"])
    with st.container(border=True):
        st.markdown(f"🔴 **Support flag: {f['detail']}**  \n<span style='color:#555'>{r['mentor']} · {r['season']} · {r['qid']} · answer #{rid}</span>", unsafe_allow_html=True)
        st.caption(qtext)
        st.markdown(_quote(r["text"]))
        with st.expander("Check the transcript against the recording"):
            _recording_and_transcript(r, user, "q_")
        st.caption("Follow Friends of the Children's procedure and tell the designated person. This answer stays out of the dashboard.")
        if st.button("Mark as followed up", key=f"q_fu_{rid}", type="primary"):
            db.upsert_review(rid, user["username"], True, False, "")
            db.log(user["username"], "followed up a support flag", f"response {rid}")
            _flash("Marked as followed up.")


def _check_card(c, r, qtext, codebook, ver, user):
    rid = int(r["id"])
    ai = c["kind"].startswith("The AI")
    with st.container(border=True):
        st.markdown(f"{'🟠' if ai else '🛠️'} **{c['kind']}**  \n<span style='color:#555'>{r['mentor']} · {r['season']} · {r['qid']} · answer #{rid}</span>", unsafe_allow_html=True)
        if c["detail"]:
            st.caption(c["detail"])
        st.caption(qtext)
        if r["text"]:
            st.markdown(_quote(r["text"]))
        _recording_and_transcript(r, user, "q_")
        if r["text"]:
            st.markdown("**Themes**")
            _themes(r, qtext, codebook, ver, user, "q_")
        b1, b2 = st.columns(2)
        if not ai and b1.button("Try the automatic steps again", key=f"q_rt_{rid}"):
            with st.spinner("Working..."):
                msgs = pl.process_response(rid, user["username"])
            _flash(" ".join(msgs) if msgs else "Nothing left to do for this answer.")
        label = "Mark as checked" if ai else "Nothing more to do (dismiss)"
        if b2.button(label, key=f"q_ok_{rid}"):
            if ai:
                db.upsert_review(rid, user["username"], True, False, "")
            else:
                db.set_proc(rid, "tag" if r["text"] else "transcribe", "dismissed", "Checked by a person")
            db.log(user["username"], "cleared a review item", f"response {rid}")
            _flash("Cleared.")


# ---------------------------------------------------------------- page
def page_review():
    user = require("admin")
    st.title("Review queue")
    ui.section("Only what needs a person", "Every answer is transcribed and tagged automatically. This page shows only answers the AI flagged for support, and anything the automatic steps could not finish.")
    st.warning("Individual answers are confidential. Use them only to offer support, never to evaluate anyone. Do not share Mentor names with supervisors.")
    msg = st.session_state.pop("flash", None)
    if msg:
        st.success(msg)
    if "ans_logged" not in st.session_state:
        db.log(user["username"], "viewed the review queue")
        st.session_state.ans_logged = True

    codebook_ver, codebook = db.get_published("codebook")
    pq = db.get_published("questions")[1]
    qtexts_now = {q["id"]: q["text"] for q in pq}
    rows = db.spoken_responses()
    df = _records(rows, codebook)
    by_id = {int(r.id): r for r in df.itertuples(index=False)}
    q = pl.review_items()
    open_flags = [f for f in q["flags"] if not f["handled"]]
    done_flags = [f for f in q["flags"] if f["handled"]]
    n_done = int(df["status"].isin(["Tagged", "Tagged (auto)"]).sum()) if len(df) else 0

    c = st.columns(3)
    c[0].metric("Support flags to follow up", len(open_flags))
    c[1].metric("Need a quick check", len(q["checks"]))
    c[2].metric("Processed automatically", f"{n_done} of {len(df)}")

    # ---- is the automation itself working?
    if q["problems"]:
        st.error("Automatic processing is not fully working, so answers may pile up here.  \n" + "  \n".join(q["problems"]))
        _link("settings", "Open Settings", ":material/settings:")
    if len(rows) and not q["problems"] and not open_flags and not q["checks"]:
        st.success("Nothing needs a person right now. The automatic steps are working.")
    elif not rows:
        st.info("No spoken answers yet. They will be processed automatically as Mentors finish check-ins.")

    # ---- support flags
    ui.section("Support flags", "Purpose: the AI found a safety, welfare, harassment, or crisis concern. How to use: read the answer, check the transcript against the recording if needed, follow the procedure, then mark it followed up.", level=3)
    if not open_flags:
        st.caption("No open flags.")
    for f in open_flags:
        r = by_id[f["id"]]._asdict()
        _flag_card(f, r, _qtext(r, qtexts_now), codebook, codebook_ver, user)
    if done_flags:
        with st.expander(f"Followed up ({len(done_flags)})"):
            st.dataframe(pd.DataFrame([dict(ID=f["id"], Mentor=f["mentor"], Season=f["season"], Question=f["qid"], Concern=f["detail"]) for f in done_flags]), hide_index=True, width="stretch")

    # ---- things the automation could not do
    ui.section("Needs a quick check", "Purpose: answers where the AI asked a person to look, or where transcription or tagging did not finish. How to use: fix or confirm each one. It leaves this list once it is done.", level=3)
    if not q["checks"]:
        st.caption("Nothing to check.")
    for ck in q["checks"]:
        r = by_id[ck["id"]]._asdict()
        _check_card(ck, r, _qtext(r, qtexts_now), codebook, codebook_ver, user)

    # ---- retry everything now
    with st.expander("Retry the automatic steps now"):
        st.caption("This also happens by itself every few minutes while anyone is signed in. Use it after you fix something in Settings.")
        need_t, need_g = pl.waiting()
        st.caption(f"Transcription: {tr.status_line()}  \nTagging: {pl.tagging_status()}")
        can_do = bool(tr.providers() or pl.tagging_providers())
        if st.button(f"Retry all waiting answers ({need_t} to transcribe, {need_g} to tag)", disabled=not (can_do and (need_t or need_g))):
            todo = [r["id"] for r in db.spoken_responses()]
            done_n, problems = 0, []
            prog = st.progress(0.0)
            for i, rid_ in enumerate(todo):
                msgs = pl.process_response(rid_, user["username"])
                done_n += 1 if msgs and all(("Tagged." == m or "Transcribed." == m) for m in msgs) else 0
                problems += [f"#{rid_}: {m}" for m in msgs if m not in ("Tagged.", "Transcribed.")]
                prog.progress((i + 1) / len(todo))
                if any("limit was reached" in m for m in msgs):
                    problems.append("A free-plan limit was reached. Wait a minute and click again to continue.")
                    break
            st.session_state.flash = f"Processed {done_n} answer(s)." + (f" First problem: {problems[0]}" if problems else "")
            st.rerun()

    # ---- optional: look up any answer
    ui.section("Look up any answer (optional)", "You do not need this for day-to-day use. Open it to find one Mentor's answer, correct a tag, or choose standout excerpts for leadership.", level=3)
    if st.toggle("Show the full list of answers", key="rv_lookup"):
        _lookup(df, user, codebook, codebook_ver, qtexts_now)
    _everything(user)


def _lookup(df, user, codebook, codebook_ver, qtexts_now):
    if df.empty:
        st.info("No spoken answers yet.")
        return
    f1, f2, f3 = st.columns(3)
    sf = f1.selectbox("Season", ["All"] + sorted({x for x in df["season"] if x}), key="ans_season")
    qf = f2.selectbox("Question", ["All"] + sorted(df["qid"].unique()), key="ans_q")
    stf = f3.selectbox("Show", ["All", "Needs transcript", "Ready to tag", "Tagged", "Tagged (auto)", "Not yet read", "Starred"], key="ans_status")
    v = df
    if sf != "All":
        v = v[v["season"] == sf]
    if qf != "All":
        v = v[v["qid"] == qf]
    v = {"All": v, "Needs transcript": v[v["status"] == "Needs transcript"], "Ready to tag": v[v["status"] == "Ready to tag"], "Tagged": v[v["status"].isin(["Tagged", "Tagged (auto)"])],
         "Tagged (auto)": v[v["status"] == "Tagged (auto)"], "Not yet read": v[~v["read"]], "Starred": v[v["star"]]}[stf]
    tbl = pd.DataFrame({"ID": v["id"], "Mentor": v["mentor"], "Season": v["season"], "Question": v["qid"], "Status": v["status"], "Answer": v["text"],
                        "Themes": v["themes"], "Read": v["read"].map({True: "yes", False: ""}), "Starred": v["star"].map({True: "★", False: ""})})
    colors = {"Tagged": "color:#1B5E20;font-weight:700", "Tagged (auto)": "color:#1B5E20;font-weight:700", "Ready to tag": "color:#1A74B8;font-weight:700", "Needs transcript": "color:#C94A20;font-weight:700"}
    st.dataframe(tbl.style.map(lambda x: colors.get(x, ""), subset=["Status"]), hide_index=True, width="stretch", column_config={"Answer": st.column_config.TextColumn(width="large")})
    if v.empty:
        return
    pick = st.selectbox("Open an answer", v["id"].tolist(), format_func=lambda i: f"#{i}  {v[v['id'] == i]['mentor'].iloc[0]}  {v[v['id'] == i]['qid'].iloc[0]}  ({v[v['id'] == i]['status'].iloc[0]})", key="ans_pick")
    r = v[v["id"] == pick].iloc[0].to_dict()
    qtext = _qtext(r, qtexts_now)
    st.markdown(f"**Question:** {qtext}")
    if r["esc"]:
        st.error("This answer raised a safety or welfare flag. It stays out of the dashboard and cannot be starred.")
    ui.section("Recording and transcript", "Listen, then check the written version against it.", level=4)
    _recording_and_transcript(r, user, "lk_")
    ui.section("Themes", "Tags feed the Themes tab on the Dashboard.", level=4)
    _themes(r, qtext, codebook, codebook_ver, user, "lk_")
    ui.section("Read and share", "Star an answer to show a trimmed excerpt to leadership, with names removed.", level=4)
    _share(r, user, "lk_")


def _everything(user):
    with st.expander("Everything people answered (ratings too)"):
        ui.section("All responses", "Every answer to every question, including ratings. Use it to look up one Mentor or one question.", level=3)
        rows = db.fetch_responses()
        if not rows:
            st.info("No responses yet.")
            return
        df = pd.DataFrame(rows)
        texts = {}
        for ver in sorted(df["question_version"].dropna().unique()):
            texts[int(ver)] = {q["id"]: q["text"] for q in (db.get_published_version("questions", int(ver)) or [])}
        df["Question"] = [texts.get(int(ver), {}).get(qid, "") for ver, qid in zip(df["question_version"], df["question_id"])]
        df["Answer"] = df["rating"].fillna("") + df["text_answer"].fillna("") + df["transcript"].fillna("") + df["checklist_selected"].fillna("")
        c1, c2 = st.columns(2)
        who = c1.selectbox("Mentor code", ["All"] + sorted(df["participant_code"].unique()), key="all_who")
        qsel = c2.selectbox("Question", ["All"] + sorted(df["question_id"].unique()), key="all_q")
        if who != "All":
            df = df[df["participant_code"] == who]
        if qsel != "All":
            df = df[df["question_id"] == qsel]
        st.dataframe(df[["id", "ts", "participant_code", "season", "question_id", "Question", "Answer", "audio_note", "skipped"]].rename(
            columns={"id": "ID", "ts": "Time (UTC)", "participant_code": "Mentor", "season": "Season", "question_id": "Q", "audio_note": "Recording", "skipped": "Skipped"}),
            hide_index=True, width="stretch")


# kept so older links and tests that call the old name still work
page_answers = page_review
