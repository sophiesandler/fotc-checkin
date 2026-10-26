"""The automatic pipeline: recording -> transcript -> themes. Runs in the background after a Mentor finishes, and on demand from the
Review queue. Tagging uses Claude (paid, best quality) or a free Groq-hosted model. Every tag must pass the same checks as a hand-made
tag: valid theme, and a quote that is an exact excerpt of the answer. Nothing here ever shows keys or answer text in error messages."""
import json
import os
import re
import datetime
import threading
import time

import requests

import content as ct
import db
import transcribe as tr

VALENCE = {"Positive", "Negative", "Mixed/Neutral"}
ESC = {"personal_safety", "harassment_discrimination", "child_welfare", "self_harm_or_crisis"}
norm = lambda s: re.sub(r"\s+", " ", (s or "").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')).strip()


# ---------------------------------------------------------------- checking a reply
def extract_json(text):
    s = (text or "").strip()
    i, j = s.find("{"), s.rfind("}")
    return s[i:j + 1] if i != -1 and j > i else s


def parse_reply(reply, source_text, theme_ids):
    """Check a tagger's reply. Returns (errors, tag rows, escalation flags)."""
    errs, rows, flags = [], [], []
    try:
        data = json.loads(extract_json(re.sub(r"^```(?:json)?|```$", "", reply.strip(), flags=re.MULTILINE)))
    except Exception:
        return ["That does not look like the JSON reply. Copy the whole reply, starting with { and ending with }."], [], []
    text = norm(source_text)
    if not isinstance(data, dict) or "segments" not in data:
        return ["The reply is missing the segments list."], [], []
    for sg in data.get("segments", []):
        for f in ("primary_theme", "secondary_theme"):
            v = sg.get(f)
            if v is not None and v not in theme_ids:
                errs.append(f"Segment {sg.get('segment_id')}: {v} is not a theme in the themes and rules.")
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


def ai_review_note(reply):
    """Did the tagger ask a person to check this answer? Returns (needs_review, short reason, flag category names)."""
    try:
        data = json.loads(extract_json(re.sub(r"^```(?:json)?|```$", "", (reply or "").strip(), flags=re.MULTILINE)))
    except Exception:
        return False, "", []
    cats = [str(e.get("category", "")).replace("_", " ") for e in (data.get("escalation_flags") or []) if isinstance(e, dict)]
    return bool(data.get("needs_human_review")), str(data.get("review_reason") or "")[:200], cats


def message(qid, qtext, rid, text):
    return f'<question id="{qid}">{qtext}</question>\n<transcript id="R{rid}">{text}</transcript>\nTag this transcript according to the instructions. Return JSON only.'


# ---------------------------------------------------------------- the taggers
def tagging_providers():
    out = []
    if tr._secret("ANTHROPIC_API_KEY"):
        out.append("claude")
    if tr._secret("GROQ_API_KEY"):
        out.append("groq")
    return out


def tagging_status():
    p = tagging_providers()
    if not p:
        return "Not set up. Add an ANTHROPIC_API_KEY (paid, best quality) or use the free GROQ_API_KEY (see Settings)."
    return "Ready (" + ", ".join({"claude": "Claude", "groq": "free Groq model"}[x] for x in p) + ")"


def _call_claude(system, user):
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": tr._secret("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          json={"model": tr._secret("ANTHROPIC_MODEL", "claude-sonnet-5-5"), "max_tokens": 2000, "system": system,
                                "messages": [{"role": "user", "content": user}]}, timeout=120)
    except Exception as e:
        return "", f"Could not reach Claude ({type(e).__name__})."
    if r.status_code == 401:
        return "", "The Claude key was not accepted (code 401). Check the key in your secrets."
    if r.status_code == 429:
        return "", "Claude says a limit was reached (code 429). Wait a while and try again, or check the account's balance."
    if r.status_code != 200:
        return "", f"Claude refused the request (code {r.status_code}). Check the key and the account balance."
    try:
        return r.json()["content"][0]["text"], ""
    except Exception:
        return "", "Claude's reply could not be read."


def _call_groq(system, user):
    key = tr._secret("GROQ_API_KEY")
    models = []
    for m in (tr._secret("GROQ_TAG_MODEL"), "openai/gpt-oss-120b", "openai/gpt-oss-20b"):
        if m and m not in models:
            models.append(m)
    last = "The Groq service did not accept the request."
    for m in models:
        for json_mode in (True, False):
            body = {"model": m, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0, "max_tokens": 1500}
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            try:
                r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
            except Exception as e:
                return "", f"Could not reach the Groq service ({type(e).__name__})."
            if r.status_code == 200:
                try:
                    return r.json()["choices"][0]["message"]["content"] or "", ""
                except Exception:
                    return "", "The Groq service sent a reply this app could not read."
            if r.status_code == 401:
                return "", "The Groq key was not accepted (code 401). Check the key in your secrets."
            if r.status_code == 429:
                wait = (getattr(r, "headers", {}) or {}).get("retry-after", "")
                return "", "The Groq service says a limit was reached (code 429)" + (f"; try again in about {wait} seconds." if wait else ". Wait a minute and try again.")
            last = f"The Groq service refused the request (code {r.status_code})."
            if r.status_code != 400:
                break          # not a settings problem: try the next model
    return "", last


def tag_one(rid, qid, qtext, text, who, codebook, ver, provider=None):
    """Tag one answer. Returns (ok, message)."""
    provs = tagging_providers()
    if not provs:
        return False, "Automatic tagging is not set up."
    provider = provider if provider in provs else provs[0]
    system = ct.build_prompt(codebook, ver, compact=(provider == "groq"))
    ids = {t["id"] for t in codebook["themes"]}
    msg, last = message(qid, qtext, rid, text), "The tagger did not return a usable reply."
    for attempt in range(2):
        reply, err = (_call_claude if provider == "claude" else _call_groq)(system, msg)
        if err:
            _record_failure(rid, "tag", err)
            return False, err
        errs, tags, flags = parse_reply(reply, text, ids)
        if not errs:
            if not tags and not flags:
                db.set_proc(int(rid), "tag", "no_themes", "No themes found (a very short answer, perhaps).")
                return False, "No themes found (a very short answer, perhaps)."
            db.add_tags(int(rid), tags, f"auto:{provider}", escalation=bool(flags))
            db.log(who, "tagged an answer automatically", f"response {rid} by {provider}: {len(tags)} tag(s), escalation={bool(flags)}")
            needs, why, cats = ai_review_note(reply)
            if flags:
                db.set_proc(int(rid), "tag", "flag", ", ".join(c for c in cats if c) or "safety or support concern")
            elif needs:
                db.set_proc(int(rid), "tag", "review", why or "The tagger asked for a person to check this answer.")
            else:
                db.clear_proc(int(rid))
            return True, "Tagged."
        last = errs[0]
        msg = message(qid, qtext, rid, text) + f"\nYour previous reply had a problem: {errs[0]} Copy quotes exactly from the transcript. Return corrected JSON only."
    _record_failure(rid, "tag", last)
    return False, last


# ---------------------------------------------------------------- the pipeline
def _record_failure(rid, stage, message_):
    """Remember that automatic processing could not finish this answer. Rate limits are temporary and are retried later."""
    transient = "limit was reached" in message_ or "Could not reach" in message_
    db.set_proc(int(rid), stage, "retry" if transient else "failed", message_, count_attempt=not transient)


def _find(rid):
    return next((r for r in db.spoken_responses() if r["id"] == rid), None)


def process_response(rid, who="system", do_transcribe=True, do_tag=True):
    """Transcribe if needed, then tag if needed. Returns a list of short messages (empty if nothing to do)."""
    out = []
    r = _find(rid)
    if not r:
        return out
    text = (r["transcript"] or r["text_answer"] or "").strip()
    if not text and r["audio_note"] == "recorded" and do_transcribe and tr.providers():
        ok, m = tr.transcribe_response(rid, who)
        out.append(m if not ok else "Transcribed.")
        if not ok:
            _record_failure(rid, "transcribe", m)
            return out
        db.clear_proc(rid)
        r = _find(rid)
        text = (r["transcript"] or "").strip()
    if text and do_tag and tagging_providers() and rid not in db.tagged_ids():
        qs = db.get_published_version("questions", int(r["question_version"] or 1)) or db.get_published("questions")[1]
        qtext = {q["id"]: q["text"] for q in qs}.get(r["question_id"], r["question_id"])
        cv, cb = db.get_published("codebook")
        ok, m = tag_one(rid, r["question_id"], qtext, text, who, cb, cv)
        out.append(m)
    return out


def process_session(sid):
    """Everything that can be done automatically for one finished check-in. Never raises."""
    do_tr = db.get_setting("auto_transcribe", "No") == "Yes"
    do_tag = db.get_setting("auto_tag", "No") == "Yes"
    try:
        for r in db.spoken_responses():
            if r["session_id"] != sid:
                continue
            msgs = process_response(r["id"], "system", do_transcribe=do_tr, do_tag=do_tag)
            if any("limit was reached" in m for m in msgs):          # free services have rate limits: wait once and retry
                time.sleep(30)
                process_response(r["id"], "system", do_transcribe=do_tr, do_tag=do_tag)
    except Exception as e:
        try:
            db.log("system", "automatic processing failed", type(e).__name__)
        except Exception:
            pass


def start_background(sid):
    """Run process_session without making the Mentor wait."""
    if os.environ.get("FOTC_SYNC") == "1":
        process_session(sid)
        return
    threading.Thread(target=process_session, args=(sid,), daemon=True).start()


def _text_of(r):
    return (r["transcript"] or r["text_answer"] or "").strip()


def waiting():
    """Counts of answers that still need a step: (needs transcript, needs tags). Answers with nothing to tag are not counted."""
    done = db.tagged_ids()
    skip = {p["response_id"] for p in db.get_proc() if p["result"] in ("no_themes", "dismissed")}
    need_t = need_g = 0
    for r in db.spoken_responses():
        text = _text_of(r)
        if not text and r["audio_note"] == "recorded" and r["id"] not in skip:
            need_t += 1
        elif text and r["id"] not in done and r["id"] not in skip:
            need_g += 1
    return need_t, need_g


# ---------------------------------------------------------------- is the automation working?
def automation_problems():
    """Plain-language reasons the automatic steps are not running. An empty list means transcription and tagging are both on and ready."""
    out = []
    if db.get_setting("auto_transcribe", "No") != "Yes":
        out.append("Automatic transcription is turned off in Settings.")
    elif not tr.providers():
        out.append("Automatic transcription has no service set up (add a GROQ_API_KEY or OPENAI_API_KEY secret).")
    if db.get_setting("auto_tag", "No") != "Yes":
        out.append("Automatic tagging is turned off in Settings.")
    elif not tagging_providers():
        out.append("Automatic tagging has no service set up (add a GROQ_API_KEY or ANTHROPIC_API_KEY secret).")
    return out


def _age_minutes(ts):
    try:
        t = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds() / 60
    except Exception:
        return 0


# ---------------------------------------------------------------- the review queue
def review_items(grace=10):
    """Everything a person needs to look at. Nothing else is ever put in front of the admin.
    flags:  the AI found a safety, welfare, or support concern (needs follow-up)
    checks: the AI asked for a person to check, or the automation could not finish the answer
    problems: why the automation itself is not working (shown once, not once per answer)"""
    rows = db.spoken_responses()
    proc = {p["response_id"]: p for p in db.get_proc()}
    tagged = db.tagged_ids()
    handled = {r["response_id"] for r in db.get_reviews() if r["reviewed"]}
    esc = {t["response_id"] for t in db.get_tags() if t["escalation"]}
    problems = automation_problems()
    tr_on = db.get_setting("auto_transcribe", "No") == "Yes" and bool(tr.providers())
    tag_on = db.get_setting("auto_tag", "No") == "Yes" and bool(tagging_providers())
    flags, checks = [], []
    for r in rows:
        rid = r["id"]
        p = proc.get(rid) or {}
        base = dict(id=rid, mentor=r["participant_code"], season=r["season"] or "", qid=r["question_id"], row=r)
        text = _text_of(r)
        age = _age_minutes(r["ts"])
        if rid in esc:
            flags.append(dict(base, handled=rid in handled, detail=p.get("detail", "") if p.get("result") == "flag" else "safety or support concern"))
            continue
        if p.get("result") == "review":
            if rid not in handled:
                checks.append(dict(base, kind="The AI asked a person to check this answer", detail=p.get("detail", "")))
            continue
        if p.get("result") in ("no_themes", "dismissed"):
            continue
        if not text and r["audio_note"] == "recorded":
            if p.get("result") == "failed":
                checks.append(dict(base, kind="Transcription failed", detail=p.get("detail", "")))
            elif tr_on and age > grace:
                checks.append(dict(base, kind="Still not transcribed", detail="It has been waiting more than %d minutes." % grace))
        elif text and rid not in tagged:
            if p.get("result") == "failed":
                checks.append(dict(base, kind="Tagging failed", detail=p.get("detail", "")))
            elif tag_on and age > grace:
                checks.append(dict(base, kind="Still not tagged", detail="It has been waiting more than %d minutes." % grace))
    flags.sort(key=lambda x: x["handled"])
    return dict(flags=flags, checks=checks, problems=problems)


# ---------------------------------------------------------------- self-healing: retry what got stuck
def sweep(who="system"):
    """Finish anything the automatic steps missed (a restart, a rate limit). Never raises. Skips answers that keep failing."""
    try:
        do_tr = db.get_setting("auto_transcribe", "No") == "Yes"
        do_tag = db.get_setting("auto_tag", "No") == "Yes"
        if not (do_tr or do_tag):
            return
        proc = {p["response_id"]: p for p in db.get_proc()}
        tagged = db.tagged_ids()
        for r in db.spoken_responses():
            rid = r["id"]
            p = proc.get(rid) or {}
            if p.get("result") in ("no_themes", "dismissed") or (p.get("result") == "failed" and (p.get("attempts") or 0) >= 3):
                continue
            if _age_minutes(r["ts"]) < 3:
                continue                                  # the check-in's own background step is probably still running
            text = _text_of(r)
            needs = (not text and r["audio_note"] == "recorded" and do_tr) or (text and rid not in tagged and do_tag)
            if not needs:
                continue
            msgs = process_response(rid, who, do_transcribe=do_tr, do_tag=do_tag)
            if any("limit was reached" in m for m in msgs):
                break                                     # try again at the next sweep
    except Exception as e:
        try:
            db.log("system", "automatic retry failed", type(e).__name__)
        except Exception:
            pass


def maybe_sweep(every_minutes=10):
    """Called when anyone signs in. At most one retry pass every few minutes, in the background."""
    try:
        last = db.get_setting("last_sweep", "")
        if last and _age_minutes(last) < every_minutes:
            return
        db.set_setting("last_sweep", db.now())
        if os.environ.get("FOTC_SYNC") == "1":
            sweep()
        else:
            threading.Thread(target=sweep, daemon=True).start()
    except Exception:
        pass
