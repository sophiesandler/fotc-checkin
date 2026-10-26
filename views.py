"""Screens for each role. Phase 1 and 2: sign-in, Mentor check-in, and editors for the questions and themes and rules."""
import copy
import uuid

import pandas as pd
import streamlit as st

import content as ct
import db
import seasons
import transcribe as tr
import ui
from auth import require

SECONDS = {"Rating": 15, "Spoken": 60, "Checklist": 30}


def _flash():
    msg = st.session_state.pop("flash", None)
    if msg:
        st.success(msg)


# =====================================================================  MENTOR CHECK-IN
def page_checkin():
    user = require("mentor")
    st.title(db.get_setting("app_title", "Mentor check-in"))
    ci = st.session_state.setdefault("ci", {"phase": "consent"})

    if ci["phase"] == "consent":
        fresh = db.get_user(user["username"]) or {}
        stype = fresh.get("session_type") or "Quarterly"
        season = seasons.current_label()
        quarter = seasons.number(seasons.parse(season)[0])
        ver, qs = db.get_published("questions")
        session = ct.build_session(qs, stype, quarter, bool(fresh.get("first_year")))
        minutes = max(1, round(_estimate_minutes(session)))
        before = [s for s in db.get_sessions() if s["participant_code"] == user["username"] and s["season"] == season and s["session_type"] == stype and s["completed"]]
        allow_repeat = db.get_setting("allow_repeat", "No") == "Yes"
        if before and not allow_repeat:
            st.success(f"You have already completed this season's check-in ({season}). Thank you! There is nothing more to do until the next season opens.")
            return
        if before:
            st.info(f"You have already completed the {season} check-in. Repeats are turned on for practice, so you can take it again.")
        st.markdown(f"**{ct.type_label(stype)} for {season}:** {len(session)} questions, about {minutes} minute{'s' if minutes != 1 else ''}. You can skip any question.")
        st.markdown(db.get_setting("consent_text"))
        agreed = st.checkbox("I understand and want to continue", key="ci_agree")
        if st.button("Start", type="primary", disabled=not agreed):
            st.session_state.ci = dict(phase="q", idx=0, sid=uuid.uuid4().hex[:10], ver=ver, session=session, stype=stype, quarter=quarter, season=season)
            db.start_session(st.session_state.ci["sid"], user["username"], season, stype, len(session))
            st.rerun()
        return

    if ci["phase"] == "done":
        if not ci.get("transcribed"):
            ci["transcribed"] = True
            if db.get_setting("auto_transcribe", "No") == "Yes" and tr.providers():
                with st.spinner("Saving your answers..."):
                    tr.auto_for_session(ci["sid"])
        st.subheader("Thank you")
        st.markdown(db.get_setting("thanks_text"))
        done_ = [a for a in db.get_actions() if a["status"] == "Done"][:5]
        if done_:
            st.subheader("What changed because of what Mentors said")
            for a in done_:
                st.markdown(f"- **You raised:** {a['raised']}  \n  **We did:** {a['action']}")
        if db.get_setting("allow_repeat", "No") == "Yes" and st.button("Start over (practice)"):
            st.session_state.ci = {"phase": "consent"}
            st.session_state.pop("ci_agree", None)
            st.rerun()
        return

    session, i = ci["session"], ci["idx"]
    if i >= len(session):
        ci["phase"] = "done"
        st.rerun()
    q = session[i]
    last = i == len(session) - 1
    st.progress(i / len(session), text=f"Question {i + 1} of {len(session)}")
    st.subheader(q["text"])
    k = f"{ci['sid']}_{i}"
    rating = audio = text = chosen = top = None
    if q["type"] == "Rating":
        hint = ct.scale_hint(q["options"])
        if hint:
            st.caption(hint)
        rating = st.radio("Your answer", ct.rating_choices(q["options"]), index=None, horizontal=True, key="r" + k)
    elif q["type"] == "Spoken":
        st.caption("Press the microphone to record, or type your answer below. You can also skip.")
        audio = st.audio_input("Record your answer", key="a" + k)
        text = st.text_area("Or type your answer", key="t" + k)
    else:
        st.caption("Pick all that apply, then choose the one that mattered most.")
        opts = ct.checklist_options(q["options"])
        chosen = st.multiselect("Select all that apply", opts, key="m" + k)
        top = st.selectbox("Which one mattered most?", chosen, index=None, key="s" + k)

    def save(skip):
        row = dict(session_id=ci["sid"], ts=db.now(), user_id=user["id"], participant_code=user["username"],
                   session_type=ci["stype"], quarter=ci["quarter"], season=ci["season"], question_id=q["id"], question_version=ci["ver"],
                   qtype=q["type"], rating="", text_answer="", checklist_selected="", checklist_top="", audio_blob=None,
                   audio_note="", transcript="", skipped=True, linked_themes=q.get("themes", ""))
        if not skip:
            if q["type"] == "Rating" and rating:
                row["rating"] = rating; row["skipped"] = False
            if q["type"] == "Spoken":
                if text and text.strip():
                    row["text_answer"] = text.strip(); row["skipped"] = False
                if audio is not None:
                    row["audio_blob"] = audio.getvalue(); row["audio_note"] = "recorded"; row["skipped"] = False
            if q["type"] == "Checklist" and (chosen or top):
                sel = list(chosen or [])
                if top and top not in sel:
                    sel.append(top)
                row["checklist_selected"] = "; ".join(sel); row["checklist_top"] = top or ""; row["skipped"] = False
        db.add_responses([row])
        ci["idx"] += 1
        db.update_session(ci["sid"], ci["idx"], ci["idx"] >= len(session))

    c1, c2, _ = st.columns([1, 1, 3])
    if c1.button("Finish" if last else "Next", type="primary", key="n" + k):
        save(False); st.rerun()
    if c2.button("Skip this question", key="k" + k):
        save(True); st.rerun()


# =====================================================================  LEADERSHIP OVERVIEW
def _question_text_map():
    ver, qs = db.get_published("questions")
    return {q["id"]: q["text"] for q in qs}


def page_overview():
    require("leader", "admin")
    st.title("Overview")
    st.caption("First version: counts and averages. The full dashboard (trends, themes, school-day time, support signals) is the next phase.")
    k = int(db.get_setting("min_group", "5"))
    rows = db.fetch_responses()
    if not rows:
        st.info("No check-ins yet. Sign in as a Mentor (for example `mentor1`), complete a practice check-in, and come back.")
        return
    df = pd.DataFrame(rows)
    sessions, people = df["session_id"].nunique(), df["participant_code"].nunique()
    c1, c2, c3 = st.columns(3)
    c1.metric("Check-ins completed or started", sessions if sessions >= k else f"under {k}")
    c2.metric("Mentors who took part", people if people >= k else f"under {k}")
    c3.metric("Answers skipped", f"{df['skipped'].mean() * 100:.0f}%" if len(df) >= k else f"under {k}")
    st.caption(f"Groups smaller than {k} are hidden to protect privacy. Change this in Settings.")
    r = df[(df["qtype"] == "Rating") & df["rating"].str.fullmatch(r"[1-5]", na=False)].copy()
    if r.empty:
        st.write("No rating answers yet.")
        return
    r["value"] = r["rating"].astype(int)
    qmap = _question_text_map()
    g = r.groupby("question_id")["value"].agg(["count", "mean"]).reset_index()
    g["Question"] = g["question_id"].map(qmap)
    g["Average (1 to 5)"] = [f"{m:.1f}" if c >= k else f"under {k} answers" for c, m in zip(g["count"], g["mean"])]
    g["Answers"] = [str(c) if c >= k else f"under {k}" for c in g["count"]]
    st.dataframe(g[["question_id", "Question", "Answers", "Average (1 to 5)"]].rename(columns={"question_id": "ID"}),
                 hide_index=True, width="stretch")


# =====================================================================  QUESTIONS
def _versions_tab(kind, label):
    hist = db.version_history(kind)
    ui.section("Version history", "Purpose: see every published version and who made it. How to use: restore an older version as a draft, then review and publish it.", level=3)
    st.dataframe(pd.DataFrame(hist).rename(columns={"version": "Version", "status": "Status", "note": "Note",
                                                    "created_by": "By", "created": "When (UTC)"}), hide_index=True, width="stretch")
    options = [h["version"] for h in hist if h["status"] != "published"]
    if options:
        v = st.selectbox(f"Restore an older {label} version as a draft", options, key=f"restore_{kind}")
        if st.button("Restore as draft", key=f"restore_btn_{kind}"):
            payload = db.get_published_version(kind, int(v))
            db.save_draft(kind, payload, st.session_state.user["username"])
            for key in ("qwork", "cwork"):
                st.session_state.pop(key, None)
            st.session_state.flash = f"Version {v} is now your draft. Review it, then publish to make it live."
            st.rerun()


def _gather_questions(work, stamp):
    out = []
    for q in work:
        k = f"{stamp}_{q['id']}_"
        g = lambda f, d: st.session_state.get(k + f, d)
        nq = dict(q)
        nq.update(text=str(g("text", q["text"])).strip(), type=g("type", q["type"]), wave=g("wave", q["wave"]),
                  order=int(g("order", q["order"])), options=str(g("options", q["options"])).strip(), block=g("block", q["block"]),
                  themes=str(g("themes", q["themes"])).strip(), active=bool(g("active", q.get("active", True))),
                  quarters=sorted(seasons.number(x) if isinstance(x, str) else x for x in g("quarters", q.get("quarters", []))), first_year_always=bool(g("fy", q.get("first_year_always", False))))
        out.append(nq)
    return out


def _validate_questions(qs):
    errs = []
    for q in qs:
        if not q["active"]:
            continue
        if not q["text"]:
            errs.append(f"{q['id']} has no wording.")
        if q["type"] == "Checklist" and len(ct.checklist_options(q["options"])) < 2:
            errs.append(f"{q['id']} is a checklist and needs at least two options, separated by semicolons.")
        if q["type"] == "Rating" and not q["options"]:
            errs.append(f"{q['id']} is a rating and needs a scale description, such as 1 = Strongly disagree ... 5 = Strongly agree.")
    return errs


def _unscheduled(qs):
    return [q["id"] for q in qs if q["active"] and q["block"] == "Rotating" and not q["quarters"] and not q["first_year_always"]]


def _estimate_minutes(session):
    sec = 30 + sum(SECONDS[q["type"]] for q in session)
    return round(sec / 60, 1)


def page_questions():
    user = require("leader", "admin")
    ver, pub = db.get_published("questions")
    st.title("Questions")
    _flash()
    if user["role"] != "admin":
        st.caption(f"Published version {ver}. Only the program admin can change questions.")
        df = pd.DataFrame(pub)
        df["wave"] = df["wave"].map(ct.wave_label)
        ui.section("Questions Mentors are asked", "Purpose: see exactly what Mentors are asked. How to use: Block shows how often a question appears. Only the program admin can edit.", level=3)
        st.dataframe(df[["id", "block", "type", "text", "wave", "active"]].rename(columns={"id": "ID", "block": "Block", "type": "Type", "text": "Question", "wave": "Asked in", "active": "Active"}),
                      hide_index=True, width="stretch")
        return

    if "qwork" not in st.session_state:
        d = db.get_draft("questions")
        st.session_state.qwork = copy.deepcopy(d if d is not None else pub)
        st.session_state.qstamp = st.session_state.get("qstamp", 0) + 1
        st.session_state.qhasdraft = d is not None
    work, stamp = st.session_state.qwork, st.session_state.qstamp
    st.caption(f"Live version: {ver}. " + ("You have a saved draft with unpublished changes." if st.session_state.qhasdraft else "Changes stay private until you publish."))
    t_edit, t_prev, t_ver = st.tabs(["Edit questions", "Preview", "Version history"])

    with t_edit:
        show_ret = st.checkbox("Show retired questions", key="qshowret")
        for block in ct.BLOCKS:
            group = sorted([q for q in work if q["block"] == block], key=lambda q: q.get("order", 0))
            if not group:
                continue
            st.subheader(block)
            st.caption(ct.BLOCK_HELP[block])
            for q in group:
                if not q.get("active", True) and not show_ret:
                    continue
                label = f"{q['id']}  |  {q['text'][:90]}" + ("   (retired)" if not q.get("active", True) else "")
                with st.expander(label):
                    k = f"{stamp}_{q['id']}_"
                    st.text_area("Question wording", q["text"], key=k + "text", help="Exactly what the Mentor sees.")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.selectbox("Question type", ct.TYPES, index=ct.TYPES.index(q["type"]), key=k + "type")
                    c2.selectbox("Asked in", ct.WAVES, index=ct.WAVES.index(q["wave"]), key=k + "wave", format_func=ct.wave_label)
                    c3.selectbox("Block", ct.BLOCKS, index=ct.BLOCKS.index(q["block"]), key=k + "block")
                    c4.number_input("Order", value=int(q.get("order", 0)), step=10, key=k + "order", help="Lower numbers come first within a block.")
                    st.text_area("Answer options or scale", q["options"], key=k + "options",
                                 help="Rating: describe the scale, for example 1 = Strongly disagree ... 5 = Strongly agree (or Prefer not to answer). "
                                      "Checklist: list the choices separated by semicolons.")
                    if q["block"] == "Rotating":
                        st.multiselect("Asked in seasons", seasons.SEASONS, default=[seasons.SEASONS[n - 1] for n in q.get("quarters", [])], key=k + "quarters")
                        st.checkbox("Also ask every season during a Mentor's first year", q.get("first_year_always", False), key=k + "fy")
                    st.text_input("Linked themes (for reference)", q.get("themes", ""), key=k + "themes")
                    st.checkbox("Active (untick to retire this question)", q.get("active", True), key=k + "active")
        with st.expander("Add a new question"):
            nb = st.selectbox("Block", ct.BLOCKS, key="new_block")
            nt = st.selectbox("Question type", ct.TYPES, key="new_type")
            nw = st.selectbox("Asked in", ct.WAVES, key="new_wave", format_func=ct.wave_label)
            ntext = st.text_area("Question wording", key="new_text")
            nopt = st.text_area("Answer options or scale", key="new_opts")
            if st.button("Add question"):
                if not ntext.strip():
                    st.error("Write the question first.")
                else:
                    cur = _gather_questions(work, stamp)
                    nq = dict(id=ct.next_question_id(nb, cur), order=max([q["order"] for q in cur if q["block"] == nb] + [0]) + 10,
                              block=nb, type=nt, text=ntext.strip(), options=nopt.strip(), themes="", wave=nw, active=True,
                              quarters=[], first_year_always=False)
                    st.session_state.qwork = cur + [nq]
                    st.session_state.qstamp += 1
                    st.session_state.flash = f"Added {nq['id']}. Open it under {nb} to fine-tune it."
                    st.rerun()
        st.divider()
        b1, b2, b3 = st.columns(3)
        if b1.button("Save draft"):
            st.session_state.qwork = _gather_questions(work, stamp)
            db.save_draft("questions", st.session_state.qwork, user["username"])
            st.session_state.qhasdraft = True
            db.log(user["username"], "saved question draft")
            st.success("Draft saved. Mentors still see the live version.")
        if b2.button("Discard my changes"):
            db.discard_draft("questions")
            st.session_state.pop("qwork", None)
            st.session_state.flash = "Draft discarded. You are back to the live version."
            st.rerun()
        review = b3.button("Review and publish", type="primary")
        if review or st.session_state.get("q_review"):
            st.session_state.q_review = True
            new = _gather_questions(work, stamp)
            st.subheader("Review before publishing")
            errs = _validate_questions(new)
            for e in errs:
                st.error(e)
            unsched = _unscheduled(new)
            if unsched:
                st.info("Not scheduled in any season right now (kept in reserve, so no Mentor sees them): " + ", ".join(unsched))
            changes = ct.diff_questions(pub, new)
            if not changes:
                st.info("Nothing has changed from the live version.")
            for level, m in changes:
                (st.warning if level == "warn" else st.write)(m)
            note = st.text_input("What changed and why (shown in the version history)", key="q_note")
            if st.button(f"Publish as version {ver + 1}", disabled=bool(errs) or not changes, type="primary"):
                v = db.publish("questions", new, user["username"], note)
                db.log(user["username"], "published questions", f"version {v}: {note}")
                st.session_state.pop("qwork", None); st.session_state.pop("q_review", None)
                st.session_state.flash = f"Published version {v}. Mentors now see the new questions."
                st.rerun()

    with t_prev:
        st.caption("See what a Mentor would be asked, using your current edits.")
        c1, c2, c3 = st.columns(3)
        stype = c1.selectbox("Check-in type", ["Quarterly", "Exit"], key="prev_type", format_func=ct.type_label)
        season_ = c2.selectbox("Season", seasons.SEASONS, index=seasons.number(seasons.parse(seasons.current_label())[0]) - 1, key="prev_q")
        quarter = seasons.number(season_)
        fy = c3.checkbox("First-year Mentor", key="prev_fy")
        session = ct.build_session(_gather_questions(work, stamp), stype, quarter, fy)
        st.metric("Questions", len(session))
        st.metric("Estimated time (minutes)", _estimate_minutes(session))
        st.caption("Estimate: 15 seconds per rating, 60 per spoken answer, 30 per checklist, plus 30 for the welcome screen.")
        for n, q in enumerate(session, 1):
            st.markdown(f"**{n}. {q['text']}**  \n<span style='color:gray'>{q['type']}, {q['block']}</span>", unsafe_allow_html=True)
    with t_ver:
        _versions_tab("questions", "question")


# =====================================================================  CODING KEY
def _gather_codebook(work, stamp):
    themes = []
    for t in work["themes"]:
        k = f"{stamp}_{t['id']}_"
        g = lambda f, d: st.session_state.get(k + f, d)
        nt = dict(t)
        nt.update(name=str(g("name", t["name"])).strip(), definition=str(g("definition", t["definition"])).strip(),
                  context=str(g("context", t.get("context", ""))).strip(), controllability=g("control", t.get("controllability", "Unknown")),
                  phrases=[p.strip() for p in str(g("phrases", "\n".join(t.get("phrases", [])))).split("\n") if p.strip()],
                  keywords=str(g("keywords", t.get("keywords", ""))).strip(), active=bool(g("active", t.get("active", True))))
        themes.append(nt)
    rules = []
    for i, r in enumerate(work["rules"]):
        k = f"{stamp}_rule{i}_"
        g = lambda f, d: st.session_state.get(k + f, d)
        if g("remove", False):
            continue
        rules.append(dict(name=str(g("name", r["name"])).strip(), category=str(g("category", r["category"])).strip(),
                          what=str(g("what", r["what"])).strip(), example=str(g("example", r["example"])).strip()))
    return dict(themes=themes, rules=rules)


def page_coding_key():
    user = require("leader", "admin")
    ver, pub = db.get_published("codebook")
    st.title("Themes and rules")
    st.caption("The themes (indicators) and rules used to tag what Mentors say. The tagging instructions are built from this page.")
    _flash()
    if user["role"] != "admin":
        st.caption(f"Published version {ver}. Only the program admin can change the themes and rules.")
        ui.section("Themes", "Purpose: the topics Mentors' answers are sorted into. How to use: read the definitions to know what each theme includes.", level=3)
        st.dataframe(pd.DataFrame(pub["themes"])[["id", "name", "definition", "controllability"]], hide_index=True, width="stretch")
        ui.section("Rules", "Purpose: how answers are tagged consistently. How to use: these rules are given to whoever or whatever tags the answers.", level=3)
        st.dataframe(pd.DataFrame(pub["rules"])[["name", "category", "what"]], hide_index=True, width="stretch")
        return
    if "cwork" not in st.session_state:
        d = db.get_draft("codebook")
        st.session_state.cwork = copy.deepcopy(d if d is not None else pub)
        st.session_state.cstamp = st.session_state.get("cstamp", 0) + 1
        st.session_state.chasdraft = d is not None
    work, stamp = st.session_state.cwork, st.session_state.cstamp
    st.caption(f"Live version: {ver}. " + ("You have a saved draft with unpublished changes." if st.session_state.chasdraft else "Changes stay private until you publish."))
    t_th, t_ru, t_pr, t_ver = st.tabs(["Themes", "Rules", "Tagging instructions", "Version history"])

    with t_th:
        for t in work["themes"]:
            k = f"{stamp}_{t['id']}_"
            with st.expander(f"{t['id']}  |  {t['name']}" + ("   (retired)" if not t.get("active", True) else "")):
                st.text_input("Theme name", t["name"], key=k + "name")
                st.text_area("Definition (one sentence)", t["definition"], key=k + "definition")
                st.text_area("Why it matters at Friends Chicago", t.get("context", ""), key=k + "context")
                st.selectbox("Can the program change this?", ct.CONTROL, index=ct.CONTROL.index(t.get("controllability", "Unknown")) if t.get("controllability") in ct.CONTROL else 3, key=k + "control")
                st.text_area("Example phrases a Mentor might say (one per line)", "\n".join(t.get("phrases", [])), key=k + "phrases")
                st.text_area("Keywords, separated by commas", t.get("keywords", ""), key=k + "keywords",
                             help="Hints only. A keyword alone never decides a theme.")
                st.checkbox("Active (untick to retire this theme)", t.get("active", True), key=k + "active")
        with st.expander("Add a new theme"):
            tn = st.text_input("Theme name", key="nt_name")
            td = st.text_area("Definition (one sentence)", key="nt_def")
            if st.button("Add theme"):
                if not tn.strip() or not td.strip():
                    st.error("Give the theme a name and a definition.")
                else:
                    cur = _gather_codebook(work, stamp)
                    cur["themes"].insert(len(cur["themes"]) - 1 if cur["themes"] and cur["themes"][-1]["id"] == "T99" else len(cur["themes"]),
                                         dict(id=ct.next_theme_id(cur["themes"]), name=tn.strip(), definition=td.strip(), context="",
                                              controllability="Unknown", phrases=[], keywords="", active=True))
                    st.session_state.cwork = cur; st.session_state.cstamp += 1
                    st.session_state.flash = "Theme added. Open it to add example phrases and keywords."
                    st.rerun()
    with t_ru:
        cats = sorted({r["category"] for r in work["rules"]})
        for i, r in enumerate(work["rules"]):
            k = f"{stamp}_rule{i}_"
            with st.expander(f"{r['name']}   ({r['category']})"):
                st.text_input("Rule name", r["name"], key=k + "name")
                st.text_input("Category", r["category"], key=k + "category", help="Existing categories: " + "; ".join(cats))
                st.text_area("What to do", r["what"], key=k + "what")
                st.text_area("Example", r["example"], key=k + "example")
                st.checkbox("Remove this rule", False, key=k + "remove")
        with st.expander("Add a new rule"):
            rn = st.text_input("Rule name", key="nr_name")
            rc = st.text_input("Category", value=cats[0] if cats else "How to tag", key="nr_cat")
            rw = st.text_area("What to do", key="nr_what")
            re_ = st.text_area("Example", key="nr_ex")
            if st.button("Add rule"):
                if not rn.strip() or not rw.strip():
                    st.error("Give the rule a name and say what to do.")
                else:
                    cur = _gather_codebook(work, stamp)
                    cur["rules"].append(dict(name=rn.strip(), category=rc.strip(), what=rw.strip(), example=re_.strip()))
                    st.session_state.cwork = cur; st.session_state.cstamp += 1
                    st.session_state.flash = "Rule added."
                    st.rerun()
    with t_pr:
        which = st.radio("Show instructions built from", ["Live themes and rules", "My current edits"], horizontal=True)
        text = ct.build_prompt(pub, ver) if which == "Live themes and rules" else ct.build_prompt(_gather_codebook(work, stamp), f"{ver} + unpublished edits")
        st.caption(f"About {len(text) // 4:,} words-worth of instructions (roughly {len(text) // 4:,} tokens). These are what the AI tagger is told. They rebuild automatically from this page.")
        st.download_button("Download tagging instructions (.txt)", text, file_name="tagging_instructions.txt")
        st.text_area("Tagging instructions", text, height=360, disabled=True)
    st.divider()
    b1, b2, b3 = st.columns(3)
    if b1.button("Save draft", key="c_save"):
        st.session_state.cwork = _gather_codebook(work, stamp)
        db.save_draft("codebook", st.session_state.cwork, user["username"])
        st.session_state.chasdraft = True
        db.log(user["username"], "saved themes and rules draft")
        st.success("Draft saved. The live themes and rules is unchanged.")
    if b2.button("Discard my changes", key="c_disc"):
        db.discard_draft("codebook"); st.session_state.pop("cwork", None)
        st.session_state.flash = "Draft discarded."; st.rerun()
    if b3.button("Review and publish", type="primary", key="c_rev") or st.session_state.get("c_review"):
        st.session_state.c_review = True
        new = _gather_codebook(work, stamp)
        st.subheader("Review before publishing")
        changes = ct.diff_codebook(pub, new)
        if not changes:
            st.info("Nothing has changed from the live version.")
        for level, m in changes:
            (st.warning if level == "warn" else st.write)(m)
        note = st.text_input("What changed and why (shown in the version history)", key="c_note")
        if st.button(f"Publish as version {ver + 1}", disabled=not changes, type="primary", key="c_pub"):
            v = db.publish("codebook", new, user["username"], note)
            db.log(user["username"], "published themes and rules", f"version {v}: {note}")
            st.session_state.pop("cwork", None); st.session_state.pop("c_review", None)
            st.session_state.flash = f"Published version {v}. The tagging instructions now use it."
            st.rerun()
    with t_ver:
        _versions_tab("codebook", "themes and rules")


# =====================================================================  USERS, SETTINGS, AUDIT, GUIDE
def page_users():
    me = require("admin")
    st.title("People")
    _flash()
    st.caption("Add Mentors and staff. Give each Mentor a code and an initial password; ask them to keep it private.")
    us = db.list_users()
    ui.section("Everyone with an account", "Purpose: see who can sign in and how. How to use: pick a person below to change their check-in type, first-year status, active status, or password.", level=3)
    st.dataframe(pd.DataFrame(us)[["username", "display_name", "role", "active", "session_type", "first_year"]]
                 .rename(columns={"username": "Sign-in name", "display_name": "Name", "role": "Role", "active": "Active",
                                  "session_type": "Check-in type", "first_year": "First year"}).assign(**{"Check-in type": lambda d: d["Check-in type"].map(ct.type_label)}), hide_index=True, width="stretch")
    with st.expander("Add a person"):
        un = st.text_input("Sign-in name or Mentor code (no spaces)", key="u_name")
        dn = st.text_input("Name shown in the app", key="u_disp")
        rl = st.selectbox("Role", ["mentor", "leader", "admin"], key="u_role", help="mentor: takes check-ins. leader: sees group results only. admin: sees individuals and edits content.")
        pw = st.text_input("Starting password (at least 8 characters)", type="password", key="u_pw")
        if st.button("Add person"):
            if not un.strip() or " " in un.strip() or len(pw) < 8:
                st.error("Use a sign-in name without spaces and a password of at least 8 characters.")
            elif db.get_user(un.strip()):
                st.error("That sign-in name already exists.")
            else:
                db.add_user(un.strip(), dn.strip() or un.strip(), rl, pw)
                db.log(me["username"], "added user", f"{un.strip()} ({rl})")
                st.session_state.flash = f"Added {un.strip()}."; st.rerun()
    ui.section("Change a person", "Pick a person, change their settings, and save.", level=3)
    sel = st.selectbox("Person", [u["username"] for u in us], key="u_sel")
    u = next(x for x in us if x["username"] == sel)
    c1, c2, c3 = st.columns(3)
    stype = c1.selectbox("Check-in type", ["Quarterly", "Exit"], index=0 if (u["session_type"] or "Quarterly") == "Quarterly" else 1, key=f"st_{sel}", format_func=ct.type_label)
    fy = c2.checkbox("First-year Mentor", bool(u["first_year"]), key=f"fy_{sel}")
    act = c3.checkbox("Active", bool(u["active"]), key=f"ac_{sel}")
    newpw = st.text_input("New password (leave blank to keep the current one)", type="password", key=f"pw_{sel}")
    if st.button("Save changes to this person"):
        admins = [x for x in us if x["role"] == "admin" and x["active"] and x["username"] != sel]
        if u["role"] == "admin" and not act and not admins:
            st.error("You cannot deactivate the only active admin.")
        elif newpw and len(newpw) < 8:
            st.error("Passwords need at least 8 characters.")
        else:
            fields = dict(session_type=stype, first_year=fy, active=act)
            if newpw:
                fields["password"] = newpw
            db.update_user(u["id"], **fields)
            db.log(me["username"], "updated user", sel)
            st.session_state.flash = f"Saved changes for {sel}."; st.rerun()


def page_settings():
    me = require("admin")
    st.title("Settings")
    _flash()
    title = st.text_input("App title", db.get_setting("app_title", "Mentor check-in"))
    cur_name, cur_year = seasons.parse(seasons.current_label())
    s1, s2 = st.columns(2)
    season_name = s1.selectbox("Which season is open for check-ins?", seasons.SEASONS, index=seasons.SEASONS.index(cur_name),
                               help="Check-ins are stamped with this season, and it picks which rotating questions are asked.")
    season_year = s2.number_input("Year", min_value=2024, max_value=2040, value=int(cur_year), step=1)
    stage = st.selectbox("Program stage", ["Pilot year", "Established"], index=0 if db.get_setting("program_stage", "Pilot year") == "Pilot year" else 1,
                         help="During the pilot year, leadership lands on the Pilot year page. The Dashboard and Support signals become more useful after several seasons.")
    k = st.number_input("Smallest group shown in reports (privacy)", min_value=2, max_value=50, value=int(db.get_setting("min_group", "5")))
    ui.section("Check-ins", "Rules for how Mentors take the check-in.", level=3)
    rep_ = st.selectbox("Can a Mentor take the check-in twice in the same season?", ["No", "Yes (for practice only)"], index=0 if db.get_setting("allow_repeat", "No") != "Yes" else 1,
                        help="Keep this on No for real use, so nobody answers twice by accident. Turn it on while you test.")
    ui.section("Recordings and transcription", "Choose how recorded answers become text, and how long recordings are kept. Transcripts are kept either way.", level=3)
    st.caption("Automatic transcription: " + tr.status_line())
    auto_t = st.selectbox("Transcribe automatically when a Mentor finishes?", ["No", "Yes"], index=1 if db.get_setting("auto_transcribe", "No") == "Yes" else 0,
                          help="Needs the transcription service to be set up. If it fails, the answer is saved and the admin can transcribe it on the Answers page.")
    keep = list(ct.RETENTION)
    ret = st.selectbox("What happens to recordings?", keep, index=keep.index(db.get_setting("audio_retention", "after_read")) if db.get_setting("audio_retention", "after_read") in keep else 1,
                       format_func=ct.RETENTION.get, help="The consent text says recordings are deleted after transcription. Pick the rule that matches what you promised Mentors.")
    with st.expander("How to set up automatic transcription"):
        st.markdown("**Free option (recommended to start): Groq**\n"
                    "1. Go to console.groq.com and create an account. No credit card is needed.\n"
                    "2. Open **API Keys**, create a key, and copy it.\n"
                    "3. In Streamlit, open **Manage app > Settings > Secrets** and add a line: `GROQ_API_KEY = \"your key\"`.\n"
                    "4. Save and reboot. The status above should say Ready.\n\n"
                    "The free plan has daily limits (about 8 hours of audio a day at the time of writing), which is far more than a pilot needs.\n\n"
                    "**Paid option: OpenAI.** Add `OPENAI_API_KEY = \"your key\"` the same way. It charges per minute of audio. If both keys are set, the free one is used first.\n\n"
                    "**Recordings are sent to that service, so get Friends of the Children's approval, and read the service's data terms, before using real recordings.**")
    consent = st.text_area("Welcome and consent text (Mentors see this first)", db.get_setting("consent_text"), height=260)
    thanks = st.text_area("Thank-you message", db.get_setting("thanks_text"), height=140)
    st.caption("Friends of the Children staff and legal review should approve the consent text before any real use.")
    if st.button("Save settings", type="primary"):
        for key, val in (("allow_repeat", "Yes" if rep_.startswith("Yes") else "No"), ("auto_transcribe", auto_t), ("audio_retention", ret), ("app_title", title), ("program_stage", stage), ("current_season", seasons.label(season_name, season_year)), ("current_quarter", seasons.number(season_name)), ("min_group", int(k)), ("consent_text", consent), ("thanks_text", thanks)):
            db.set_setting(key, val)
        db.log(me["username"], "changed settings")
        st.session_state.flash = "Settings saved."; st.rerun()


def page_audit():
    require("admin")
    st.title("Activity log")
    st.caption("Who signed in, viewed individual responses, played recordings, or changed content.")
    ui.section("What happened and when", "Purpose: an audit trail of sign-ins, answers viewed, and changes. How to use: check here if you need to know who saw or changed something.", level=3)
    st.dataframe(pd.DataFrame(db.recent_log()).rename(columns={"ts": "When (UTC)", "username": "Who", "action": "What", "detail": "Detail"}).drop(columns=["id"], errors="ignore"),
                 hide_index=True, width="stretch")


GUIDE = {
    "mentor": """### What this is
A short check-in about your work. The first screen tells you how many questions there are and about how long it takes. Every question can be skipped.

### How to take it
1. Read the welcome note and tick the box to start.
2. Answer each question one at a time. For spoken questions you can record your voice or type.
3. Press **Next** (or **Skip this question**). Press **Finish** on the last one.

You can complete the check-in once each season. If you try again, the app tells you that you are already done.

If you share a safety concern, a designated person will follow up so you can get help.""",
    "leader": """### What you can do
- **Pilot year** is the landing page during year one: participation, the first-season baseline, a summary of what Mentors said, and what has been done about it.
- **Dashboard** shows group results by season: trends and themes. It becomes more useful after several seasons. Groups under the minimum size are hidden.
- **Support signals** shows the share of Mentors whose answers suggest a supportive check-in, and which signals appear most. Individual Mentors are not shown to you.
- **Questions** and **Themes and rules** show what is being asked and how answers are tagged. Only the program admin can edit them.
- **My account** lets you change your password.

Use the switch at the top of each page to look at live check-ins or the clearly labeled demo data.""",
    "admin": """### Changing the questions
1. Open **Questions**, expand a question, and edit it.
2. Press **Save draft** to keep your work private, or **Review and publish** to see what changes and make it live.
3. Core questions show a warning when you change them, because trend lines restart.
4. Use **Version history** to restore an older version as a draft.

### Changing the themes and rules
Open **Themes and rules** to edit themes (indicators), example phrases, keywords, and rules. The tagging instructions rebuild from it automatically.

### Answers
Open **Answers** for everything Mentors said. For each answer: listen and check the transcript, tag its themes, read it, and star standout excerpts for leadership. Automatic transcription and tagging can do much of this for you once they are set up in **Settings**.

### Pilot year
During year one, start on **Pilot year**: check that the check-in works (participation, time, skipped questions), see what Mentors said, and record what you did about each concern under **You said, we did**.

### Dashboard and Support signals
- **Dashboard** and **Support signals** show group results by season. Open a season in **Settings** before Mentors start their check-ins.
- On **Support signals** you also see the list of Mentors who might benefit from a supportive check-in, and you can mark when one has been offered.
- **Change the indicator rules** at the bottom of Support signals. Each rule is a plain statement worth some points, and two cut-offs set High and Medium priority.

### Getting ready for real Mentors
Open **Launch checklist** to see what is still needed: approvals, testing, setup, and launch steps. You can also download a backup there.

### Looking after people and privacy
- **People**: add Mentors, set exit interviews, reset passwords.
- **Answers** shows individual answers. Opening it and playing recordings are logged under **Activity log**.
- **My account** lets you change your own password.
- Never share individual answers with a Mentor's supervisor. Use them only to offer support.""",
}


def page_guide():
    user = require("mentor", "leader", "admin")
    st.title("Guide")
    st.markdown(GUIDE[user["role"]])
