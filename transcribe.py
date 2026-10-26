"""Automatic transcription of recorded answers.

Providers (the first one that is set up is used, in this order):
  groq    a free online speech-to-text service (rate limited). Needs GROQ_API_KEY in the app's secrets. Audio leaves this app, so
          Friends of the Children must approve it before real recordings are sent.
  openai  a paid online speech-to-text service. Needs OPENAI_API_KEY in the app's secrets. Pay per use. Same approval needed.
  local   the free faster-whisper library, if it is installed on the server. Audio never leaves the app. It does not install on the
          free Streamlit hosting, so it is mainly for self-hosting or testing on a laptop.
Error messages here never include keys or audio."""
import io
import os

import requests
import streamlit as st

import db

VOCAB = "Professional Mentor, portfolio, Clubhouse, Friends of the Children, caregivers, youth, program team, supervisor."


def _secret(name, default=""):
    v = os.environ.get(name)
    if v:
        return v
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def providers():
    out = []
    if _secret("GROQ_API_KEY"):
        out.append("groq")
    if _secret("OPENAI_API_KEY"):
        out.append("openai")
    try:
        import faster_whisper  # noqa: F401
        out.append("local")
    except Exception:
        pass
    return out


def status_line():
    p = providers()
    if not p:
        return "Not set up. Add a GROQ_API_KEY (free) or OPENAI_API_KEY secret to turn it on (see Settings)."
    return "Ready (" + ", ".join({"groq": "free online service", "openai": "paid online service", "local": "this server"}[x] for x in p) + ")"


@st.cache_resource
def _local_model():
    from faster_whisper import WhisperModel
    return WhisperModel(_secret("WHISPER_MODEL", "base"), device="cpu", compute_type="int8")


def transcribe(audio, provider=None):
    """Returns (text, error). Exactly one of them is empty."""
    provs = providers()
    if not provs:
        return "", "Automatic transcription is not set up yet."
    provider = provider if provider in provs else provs[0]
    if provider == "groq":
        return _compatible("https://api.groq.com/openai/v1/audio/transcriptions", _secret("GROQ_API_KEY"),
                           [m for m in (_secret("GROQ_TRANSCRIBE_MODEL"), "whisper-large-v3-turbo", "whisper-large-v3") if m], "Groq", audio)
    if provider == "openai":
        # OpenAI is replacing whisper-1 with newer models, so try the newer one first and fall back to the older one.
        return _compatible("https://api.openai.com/v1/audio/transcriptions", _secret("OPENAI_API_KEY"),
                           [m for m in (_secret("TRANSCRIBE_MODEL"), "gpt-transcribe", "whisper-1") if m], "OpenAI", audio)
    try:
        model = _local_model()
        segs, _ = model.transcribe(io.BytesIO(audio), language="en", vad_filter=True, initial_prompt=VOCAB)
        return " ".join(s.text.strip() for s in segs).strip(), ""
    except Exception as e:
        return "", f"Local transcription failed ({type(e).__name__})."


def _compatible(url, key, models, name, audio):
    """Call a speech-to-text service that follows OpenAI's request format. Tries each model in turn. Returns (text, error)."""
    seen, last = [], f"The {name} transcription service did not accept the request."
    for m in models:
        if m in seen:
            continue
        seen.append(m)
        data = {"model": m}
        if m.startswith("whisper") or m.startswith("gpt-4o"):
            data.update(language="en", prompt=VOCAB)
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {key}"}, files={"file": ("answer.wav", audio, "audio/wav")}, data=data, timeout=120)
        except Exception as e:
            return "", f"Could not reach the {name} service ({type(e).__name__})."
        if r.status_code == 200:
            try:
                text = (r.json().get("text") or "").strip()
            except Exception:
                return "", f"The {name} service sent a reply this app could not read."
            if text:
                return text, ""
            last = "The service returned no words. The recording may be silent."
            continue
        if r.status_code in (400, 404, 422):      # this model is not available or does not accept the settings: try the next one
            last = f"The {name} service refused the request (code {r.status_code})."
            continue
        if r.status_code == 401:
            return "", f"The {name} key was not accepted (code 401). Check the key in your secrets."
        if r.status_code == 429:
            return "", f"The {name} service says a limit was reached (code 429). Wait a while and try again, or check the account's limits and billing."
        return "", f"The {name} service returned an error (code {r.status_code})."
    return "", last


def retention():
    return db.get_setting("audio_retention", "after_read")


def transcribe_response(rid, username):
    """Transcribe one stored recording and apply the recording-retention rule. Returns (ok, message)."""
    blob = db.get_audio(int(rid))
    if not blob:
        return False, "There is no recording to transcribe."
    text, err = transcribe(bytes(blob))
    if err:
        db.log(username, "transcription failed", f"response {rid}")
        return False, err
    if not text:
        return False, "The service returned no words. The recording may be silent."
    db.set_transcript(int(rid), text)
    db.log(username, "transcribed a recording", f"response {rid}")
    if retention() == "after_transcript":
        db.delete_audio(int(rid))
    return True, "Transcribed."


def pending_ids():
    """Responses with a recording but no transcript."""
    return [r["id"] for r in db.spoken_responses() if r["audio_note"] == "recorded" and not (r["transcript"] or "").strip()]


def auto_for_session(sid):
    """Called when a Mentor finishes. Never blocks or errors for the Mentor."""
    if db.get_setting("auto_transcribe", "No") != "Yes" or not providers():
        return 0
    n = 0
    try:
        ids = {r["id"] for r in db.spoken_responses() if r["audio_note"] == "recorded" and not (r["transcript"] or "").strip()}
        for r in db.fetch_responses():
            if r["session_id"] == sid and r["id"] in ids:
                ok, _ = transcribe_response(r["id"], "system")
                n += 1 if ok else 0
    except Exception:
        pass
    return n
