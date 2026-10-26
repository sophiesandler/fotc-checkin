"""Answers: one page for everything about what Mentors said. Listen, transcribe, tag themes, read, and choose standout excerpts."""
import pandas as pd
import streamlit as st

import content as ct
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


def page_answers():
    user = require("admin")
    st.title("Answers")
    ui.section("What Mentors said", "One place for every spoken answer. For each answer: listen and check the transcript, tag its themes, read it, and choose standout excerpts for leadership.")
    st.warning("Individual answers are confidential. Use them only to offer support, never to evaluate anyone. Do not share Mentor names with supervisors.")
    msg = st.session_state.pop("flash", None)
    if msg:
        st.success(msg)
    if "ans_logged" not in st.session_state:
        db.log(user["username"], "viewed individual answers")
        st.session_state.ans_logged = True

    codebook_ver, codebook = db.get_published("codebook")
    pq = db.get_published("questions")[1]
    qtexts_now = {q["id"]: q["text"] for q in pq}
    rows = db.spoken_responses()
    if not rows:
        st.info("No spoken answers yet. Sign in as a Mentor, answer a spoken question, and come back.")
        _everything(user)
        return
    done_tags = db.tagged_ids()
    esc_ids = {t["response_id"] for t in db.get_tags() if t["escalation"]}
    reviews = {r["response_id"]: r for r in db.get_reviews()}
    tag_by, auto_ids = {}, set()
    for t in db.get_tags():
        tag_by.setdefault(t["response_id"], []).append(t["theme"])
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
                         themes=", ".join(sorted({names.get(t, t) for t in tag_by.get(r["id"], [])})), esc=r["id"] in esc_ids, typed=bool((r["text_answer"] or "").strip())))
    df = pd.DataFrame(recs)

    c = st.columns(6)
    c[0].metric("Spoken answers", len(df))
    c[1].metric("Need a transcript", int((df["status"] == "Needs transcript").sum()))
    c[2].metric("Ready to tag", int((df["status"] == "Ready to tag").sum()))
    c[3].metric("Tagged", int(df["status"].isin(["Tagged", "Tagged (auto)"]).sum()))
    c[4].metric("Read", int(df["read"].sum()))
    c[5].metric("Starred", int(df["star"].sum()))

    # ---- do many at once
    ui.section("Process everything that is waiting", "Purpose: do the transcribing and tagging for all waiting answers in one click. How to use: set up the services in Settings, then click. With both turned on in Settings, this already happens by itself shortly after each Mentor finishes.", level=3)
    need_t, need_g = pl.waiting()
    st.caption(f"Transcription: {tr.status_line()}  \nTagging: {pl.tagging_status()}")
    can_do = bool(tr.providers() or pl.tagging_providers())
    if st.button(f"Process all waiting answers ({need_t} to transcribe, {need_g} to tag)", disabled=not (can_do and (need_t or need_g))):
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
    if esc_ids:
        st.error(f"{len(esc_ids)} answer(s) raised a safety or welfare flag: #" + ", #".join(str(i) for i in sorted(esc_ids))
                 + ". Follow Friends of the Children's procedure and tell the designated person. These stay out of the dashboard.")

    # ---- the list
    ui.section("All spoken answers", "Filter the list, then open one answer below. Status shows the next step for each answer.", level=3)
    f1, f2, f3 = st.columns(3)
    sf = f1.selectbox("Season", ["All"] + sorted({x for x in df["season"] if x}), key="ans_season")
    qf = f2.selectbox("Question", ["All"] + sorted(df["qid"].unique()), key="ans_q")
    stf = f3.selectbox("Show", ["All", "Needs transcript", "Ready to tag", "Tagged", "Tagged (auto)", "Not yet read", "Starred"], key="ans_status")
    v = df
    if sf != "All":
        v = v[v["season"] == sf]
    if qf != "All":
        v = v[v["qid"] == qf]
    v = {"All": v, "Needs transcript": v[v["status"] == "Needs transcript"], "Ready to tag": v[v["status"] == "Ready to tag"], "Tagged": v[v["status"].isin(["Tagged", "Tagged (auto)"])], "Tagged (auto)": v[v["status"] == "Tagged (auto)"],
         "Not yet read": v[~v["read"]], "Starred": v[v["star"]]}[stf]
    tbl = pd.DataFrame({"ID": v["id"], "Mentor": v["mentor"], "Season": v["season"], "Question": v["qid"], "Status": v["status"], "Answer": v["text"],
                        "Themes": v["themes"], "Read": v["read"].map({True: "yes", False: ""}), "Starred": v["star"].map({True: "★", False: ""})})
    colors = {"Tagged": "color:#1B5E20;font-weight:700", "Tagged (auto)": "color:#1B5E20;font-weight:700", "Ready to tag": "color:#1A74B8;font-weight:700", "Needs transcript": "color:#C94A20;font-weight:700"}
    st.dataframe(tbl.style.map(lambda x: colors.get(x, ""), subset=["Status"]), hide_index=True, width="stretch", column_config={"Answer": st.column_config.TextColumn(width="large")})
    if v.empty:
        _everything(user)
        return

    # ---- one answer, three steps
    pick = st.selectbox("Open an answer", v["id"].tolist(), format_func=lambda i: f"#{i}  {v[v['id'] == i]['mentor'].iloc[0]}  {v[v['id'] == i]['qid'].iloc[0]}  ({v[v['id'] == i]['status'].iloc[0]})", key="ans_pick")
    r = v[v["id"] == pick].iloc[0]
    rid = int(pick)
    qtext = {q["id"]: q["text"] for q in (db.get_published_version("questions", int(r["qver"])) or [])}.get(r["qid"], qtexts_now.get(r["qid"], r["qid"]))
    st.markdown(f"**Question:** {qtext}")
    if r["esc"]:
        st.error("This answer raised a safety or welfare flag. Follow Friends of the Children's procedure and tell the designated person. It stays out of the dashboard and cannot be starred.")

    ui.section("Step 1: Recording and transcript", "Listen, then check the written version against it. Fix any mistakes before tagging, because the tags are built from this text.", level=3)
    if r["audio_note"] == "recorded":
        blob = db.get_audio(rid)
        if blob:
            st.audio(bytes(blob), format="audio/wav")
            if st.session_state.get("last_audio") != rid:
                db.log(user["username"], "played audio", f"response {rid}")
                st.session_state.last_audio = rid
    elif r["audio_note"] == "deleted":
        st.caption("The recording was deleted. The transcript is kept.")
    if r["audio_note"] == "recorded" and not r["text"].strip() and not tr.providers():
        st.info("Automatic transcription is not set up, so this recording has not been written out yet. Listen to it, type what was said in the box below, and click Save transcript. "
                "To turn on automatic transcription, see Settings.")
    if r["audio_note"] in ("recorded", "deleted") or not r["typed"]:
        cur = st.text_area("Transcript", value=r["text"], key=f"tr_{rid}", height=130, placeholder="Type what was said in the recording here.",
                           help="Automatic transcripts are close but not perfect. Check names, places, and numbers.")
        t1, t2, t3 = st.columns(3)
        if t1.button("Save transcript", key=f"st_{rid}"):
            if cur.strip():
                db.set_transcript(rid, cur.strip())
                db.log(user["username"], "saved a transcript", f"response {rid}")
                st.session_state.flash = "Transcript saved."
                st.rerun()
            else:
                st.error("Type or generate the transcript first.")
        if r["audio_note"] == "recorded" and tr.providers() and t2.button("Transcribe automatically", key=f"at_{rid}"):
            with st.spinner("Transcribing..."):
                ok_, m_ = tr.transcribe_response(rid, user["username"])
            st.session_state.flash = "Transcribed. Check it against the recording." if ok_ else m_
            st.rerun()
        if r["audio_note"] == "recorded" and t3.button("Delete the recording", key=f"dr_{rid}"):
            db.delete_audio(rid)
            db.log(user["username"], "deleted audio", f"response {rid}")
            st.session_state.flash = "Recording deleted."
            st.rerun()
    else:
        st.markdown(f"**Answer (typed by the Mentor):** {r['text']}")
    text = r["text"].strip()

    ui.section("Step 2: Themes", "Tag the answer with themes from your themes and rules. Tags feed the Themes tab on the Dashboard.", level=3)
    if not text:
        st.info("Add a transcript in step 1 first.")
    else:
        mine = [t for t in db.get_tags() if t["response_id"] == rid]
        if mine:
            st.dataframe(pd.DataFrame(mine)[["theme", "valence", "quote", "aggregate_only", "escalation"]].rename(
                columns={"theme": "Theme", "valence": "Valence", "quote": "Exact words", "aggregate_only": "Counted only in totals", "escalation": "Safety flag"}),
                hide_index=True, width="stretch")
        if pl.tagging_providers() and st.button("Tag automatically" if not mine else "Tag again automatically", key=f"tc_{rid}"):
            with st.spinner("Tagging..."):
                ok_, m_ = _tag_one(rid, r["qid"], qtext, text, user["username"], codebook, codebook_ver)
            st.session_state.flash = "Tagged. Check the themes below." if ok_ else m_
            st.rerun()
        with st.expander("Tag by hand instead", expanded=not pl.tagging_providers() and not mine):
            st.caption("Open a new Claude chat. First paste the tagging instructions (Themes and rules > Tagging instructions > Download). Then paste this message and send it.")
            st.code(_message(r["qid"], qtext, rid, text), language="text")
            reply = st.text_area("Paste Claude's reply here", key=f"rp_{rid}", height=160)
            if st.button("Check and save tags", type="primary", key=f"cs_{rid}"):
                errs, tags, flags = parse_reply(reply, text, {t["id"] for t in codebook["themes"]})
                if errs:
                    for e in errs:
                        st.error(e)
                elif not tags and not flags:
                    st.warning("The reply has no themes (for example, a very short answer). Nothing was saved.")
                else:
                    db.add_tags(rid, tags, user["username"], escalation=bool(flags))
                    db.log(user["username"], "saved tags", f"response {rid}: {len(tags)} tag(s), escalation={bool(flags)}")
                    st.session_state.flash = "Saved. This answer raised a safety or welfare flag. Follow Friends of the Children's procedure." if flags else f"Saved {len(tags)} tag(s)."
                    st.rerun()

    ui.section("Step 3: Read and share", "Mark the answer as read. Star it to show a trimmed excerpt to leadership, with names removed.", level=3)
    if not text:
        st.caption("Nothing to read yet.")
    else:
        st.warning("Read before you star: remove names and any detail that could identify a Mentor or a youth.")
        excerpt = st.text_area("Excerpt for leadership", value=r["excerpt"] or text, key=f"ex_{rid}", height=100, disabled=bool(r["esc"]))
        cr, cs = st.columns(2)
        reviewed = cr.checkbox("I have read this answer", value=bool(r["read"]), key=f"rv_{rid}")
        starred = cs.checkbox("Star as a standout excerpt", value=bool(r["star"]), key=f"sr_{rid}", disabled=bool(r["esc"]))
        if st.button("Save", key=f"sv_{rid}"):
            db.upsert_review(rid, user["username"], reviewed or starred, starred and not r["esc"], excerpt.strip())
            db.log(user["username"], "reviewed an answer", f"response {rid}, starred={starred}")
            note = "Saved."
            if (reviewed or starred) and r["audio_note"] == "recorded" and tr.retention() == "after_read":
                db.delete_audio(rid)
                note = "Saved. The recording was deleted, as set in Settings."
            st.session_state.flash = note
            st.rerun()
    _everything(user)


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
