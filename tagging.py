"""Tag answers: turn spoken answers into themes. A short manual step for now (copy a message into a Claude chat, paste the
reply back). The Dashboard's Themes tab reads what is saved here."""
import json
import re

import pandas as pd
import streamlit as st

import db
from auth import require

VALENCE = {"Positive", "Negative", "Mixed/Neutral"}
ESC = {"personal_safety", "harassment_discrimination", "child_welfare", "self_harm_or_crisis"}
norm = lambda s: re.sub(r"\s+", " ", (s or "").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')).strip()


def parse_reply(reply, source_text, theme_ids):
    """Check Claude's reply. Returns (errors, tag rows, escalation flags)."""
    errs, rows, flags = [], [], []
    try:
        data = json.loads(re.sub(r"^```(?:json)?|```$", "", reply.strip(), flags=re.MULTILINE).strip())
    except Exception:
        return ["That does not look like the JSON reply. Copy Claude's whole reply, starting with { and ending with }."], [], []
    text = norm(source_text)
    if not isinstance(data, dict) or "segments" not in data:
        return ["The reply is missing the segments list."], [], []
    for sg in data.get("segments", []):
        for f in ("primary_theme", "secondary_theme"):
            v = sg.get(f)
            if v is not None and v not in theme_ids:
                errs.append(f"Segment {sg.get('segment_id')}: {v} is not a theme in the coding key.")
        if sg.get("valence") not in VALENCE:
            errs.append(f"Segment {sg.get('segment_id')}: valence must be Positive, Negative, or Mixed/Neutral.")
        if norm(sg.get("supporting_quote")) not in text:
            errs.append(f"Segment {sg.get('segment_id')}: the quote is not an exact excerpt of the answer, so it was not accepted.")
        rows.append(dict(theme=sg.get("primary_theme"), valence=sg.get("valence"), quote=sg.get("supporting_quote", ""),
                         aggregate_only=bool(sg.get("aggregate_only")) or sg.get("primary_theme") == "T10", confidence=sg.get("confidence", "")))
    for e in data.get("escalation_flags", []) or []:
        if e.get("category") not in ESC:
            errs.append("An escalation flag has an unknown category.")
        flags.append(e)
    return errs, rows, flags


def page_tag_answers():
    user = require("admin")
    st.title("Tag answers")
    st.caption("Turn spoken answers into themes. Practice data only until Friends of the Children approves the data handling.")
    msg = st.session_state.pop("flash", None)
    if msg:
        st.success(msg)
    rows = db.spoken_responses()
    if not rows:
        st.info("No spoken answers yet. Sign in as a Mentor, answer a spoken question, and come back.")
        return
    codebook = db.get_published("codebook")[1]
    theme_ids = {t["id"] for t in codebook["themes"]}
    done = db.tagged_ids()
    df = pd.DataFrame(rows)
    df["Text"] = df["transcript"].fillna("").where(df["transcript"].fillna("") != "", df["text_answer"].fillna(""))
    df["Status"] = ["Tagged" if i in done else ("Ready to tag" if t.strip() else "Needs transcript") for i, t in zip(df["id"], df["Text"])]
    st.dataframe(df[["id", "participant_code", "season", "question_id", "Status", "Text"]].rename(
        columns={"id": "ID", "participant_code": "Mentor", "season": "Season", "question_id": "Question"}), hide_index=True, width="stretch")
    rid = st.selectbox("Choose an answer", df["id"].tolist(), format_func=lambda i: f"#{i}  {df[df['id'] == i]['participant_code'].iloc[0]}  {df[df['id'] == i]['question_id'].iloc[0]}  ({df[df['id'] == i]['Status'].iloc[0]})")
    r = df[df["id"] == rid].iloc[0]
    qtexts = {q["id"]: q["text"] for q in (db.get_published_version("questions", int(r["question_version"])) or [])}
    qtext = qtexts.get(r["question_id"], r["question_id"])
    st.markdown(f"**Question:** {qtext}")
    text = r["Text"].strip()

    if r["audio_note"] == "recorded" and not r["transcript"]:
        st.warning("This answer was recorded. Play it, then type what was said. Automatic transcription is the next phase.")
        blob = db.get_audio(int(rid))
        if blob:
            st.audio(bytes(blob), format="audio/wav")
        typed = st.text_area("What was said (a transcript)", key=f"tr_{rid}", height=140)
        if st.button("Save transcript"):
            if typed.strip():
                db.set_transcript(int(rid), typed.strip())
                db.log(user["username"], "saved a transcript", f"response {rid}")
                st.session_state.flash = "Transcript saved."
                st.rerun()
            else:
                st.error("Type the transcript first.")
        return
    if not text:
        st.info("This answer has no text.")
        return
    st.markdown(f"**Answer:** {text}")
    st.subheader("Step 1: ask Claude")
    st.caption("Open a new Claude chat. First paste the tagging instructions (Coding key > Tagging instructions > Download). Then paste this message and send it.")
    st.code(f'<question id="{r["question_id"]}">{qtext}</question>\n<transcript id="R{rid}">{text}</transcript>\nTag this transcript according to the instructions. Return JSON only.', language="text")
    st.subheader("Step 2: paste Claude's reply")
    reply = st.text_area("Claude's reply", key=f"rp_{rid}", height=180)
    if st.button("Check and save tags", type="primary"):
        errs, tags, flags = parse_reply(reply, text, theme_ids)
        if errs:
            for e in errs:
                st.error(e)
        elif not tags and not flags:
            st.warning("The reply has no themes (for example, a very short answer). Nothing was saved.")
        else:
            db.add_tags(int(rid), tags, user["username"], escalation=bool(flags))
            db.log(user["username"], "saved tags", f"response {rid}: {len(tags)} tag(s), escalation={bool(flags)}")
            if flags:
                st.session_state.flash = ("Saved. This answer raised a safety or welfare flag. Follow Friends of the Children's procedure and tell the designated person. "
                                          "It is kept out of the dashboard.")
            else:
                st.session_state.flash = f"Saved {len(tags)} tag(s). They now appear on the Dashboard under Themes."
            st.rerun()
    mine = [t for t in db.get_tags() if t["response_id"] == int(rid)]
    if mine:
        st.subheader("Saved tags for this answer")
        st.dataframe(pd.DataFrame(mine)[["theme", "valence", "quote", "aggregate_only", "escalation"]], hide_index=True, width="stretch")
