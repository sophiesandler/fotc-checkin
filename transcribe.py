"""Automatic transcription of recorded answers.

Providers (the first one that is set up is used):
  openai  an online speech-to-text service. Needs OPENAI_API_KEY in the app's secrets. Pay per use. Audio leaves this app, so
          Friends of the Children must approve it before real recordings are sent.
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
        return "Not set up. Add an OPENAI_API_KEY secret to turn it on (see Settings)."
    return "Ready (" + ", ".join({"openai": "online service", "local": "this server"}[x] for x in p) + ")"


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
    if provider == "openai":
        try:
            r = requests.post("https://api.openai.com/v1/audio/transcriptions", headers={"Authorization": f"Bearer {_secret('OPENAI_API_KEY')}"},
                              files={"file": ("answer.wav", audio, "audio/wav")},
                              data={"model": _secret("TRANSCRIBE_MODEL", "whisper-1"), "language": "en", "prompt": VOCAB}, timeout=120)
        except Exception as e:
            return "", f"Could not reach the transcription service ({type(e).__name__})."
        if r.status_code != 200:
            return "", f"The transcription service refused the request (code {r.status_code}). Check the key and the account balance."
        try:
            return (r.json().get("text") or "").strip(), ""
        except Exception:
            return "", "The transcription service sent a reply this app could not read."
    try:
        model = _local_model()
        segs, _ = model.transcribe(io.BytesIO(audio), language="en", vad_filter=True, initial_prompt=VOCAB)
        return " ".join(s.text.strip() for s in segs).strip(), ""
    except Exception as e:
        return "", f"Local transcription failed ({type(e).__name__})."


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
