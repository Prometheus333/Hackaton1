import os
import json
import threading
import traceback
from datetime import datetime

import httpx
import requests
from dateutil import parser as dateparser
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_sock import Sock
from langchain_openai import ChatOpenAI
from websocket import create_connection
import ssl

import re
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

app = Flask(__name__)
CORS(app)
sock = Sock(app)

# ---------------------------------------------------------------------------
# LiteLLM / chat model config
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("LITELLM_BASE_URL")
API_KEY = os.environ.get("LITELLM_API_KEY")
MODEL_NAME = os.environ.get("LITELLM_MODEL")

missing = [name for name, val in [
    ("LITELLM_BASE_URL", BASE_URL),
    ("LITELLM_API_KEY", API_KEY),
    ("LITELLM_MODEL", MODEL_NAME),
] if not val]

if missing:
    raise RuntimeError(
        f"Missing required environment variable(s): {', '.join(missing)}. "
        "Set them in a .env file (see .env.example) before running this server."
    )

httpx_client = httpx.Client(verify=False)

llm = ChatOpenAI(
    base_url=BASE_URL.rstrip("/"),
    model=MODEL_NAME,
    api_key=API_KEY,
    http_client=httpx_client,
)

# ---------------------------------------------------------------------------
# Voice provider config (Deepgram = speech-to-text, ElevenLabs = text-to-speech)
# ---------------------------------------------------------------------------
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")

DEEPGRAM_LANGUAGE = {"en": "en-US", "es": "es", "hi": "hi"}

# ---------------------------------------------------------------------------
# Personas / prompts
# ---------------------------------------------------------------------------
BASE_RULES = """You are a clerk at the Civic Information Desk, a public service
information chatbot. You only cover: permits & licenses, tax payments, and
local regulations.

Rules that never change regardless of persona:
- Give accurate, concise answers (2-4 sentences).
- If a question is outside these topics, say so plainly and suggest the
  relevant department or the general inquiries line.
- Never invent specific fees, dates, or phone numbers — speak in general
  terms (e.g. "typically 10-15 business days") rather than fabricating figures.
- Do not break character with meta-commentary about being an AI persona.
- This is a spoken conversation, so keep replies short and easy to say aloud
  when the conversation is happening over voice.
"""

PERSONAS = {
    "permits": BASE_RULES + """
Voice: the Permits & Licensing clerk. Brisk, efficient, no wasted words.
Give the answer first, in short direct sentences. Skip pleasantries.
""",
    "tax": BASE_RULES + """
Voice: the Tax & Revenue clerk. Patient and reassuring — explain things a
little more fully, and proactively mention ways to avoid a penalty.
""",
    "regulations": BASE_RULES + """
Voice: the Regulatory Affairs clerk. Dry, a little wry about paperwork,
but never unhelpful or sarcastic toward the citizen. Keep it brief.
""",
    "general": BASE_RULES + """
Voice: the General Inquiries clerk at the front desk. Warm and welcoming,
helps people figure out which window they actually need.
""",
}

SCENARIO_SUFFIX = """

You are now in SCENARIO CHECK mode. The citizen is describing something
they're planning to do and wants to know if it's likely to require a permit
or run into a regulation, BEFORE they file anything.

Respond in this structure:
1. **Verdict:** one of "Likely requires a permit/approval", "Likely fine as-is",
   or "Depends on details".
2. **Why:** 1-2 sentences of reasoning in general terms.
3. **Before you apply:** one practical next step.
"""

LANGUAGE_NAMES = {"en": None, "es": "Spanish", "hi": "Hindi"}

DEPARTMENT_NAMES = {
    "permits": "Permits & Licensing Office",
    "tax": "Tax & Revenue Office",
    "regulations": "Regulatory Affairs Office",
    "general": "General Inquiries Desk",
}

BOOKING_PHRASES = [
    "book an appointment", "schedule an appointment", "make an appointment",
    "book appointment", "set up an appointment", "i want to book",
    "i'd like to book", "i would like to book",
]

# Steps for the voice-driven booking flow. Each entry is (field_key, prompt_to_speak).
BOOKING_STEPS = [
    ("name", "Sure, let's get you booked in. Can I get your full name?"),
    ("contact", "Thanks. What's the best email or phone number to reach you?"),
    ("date", "What date would you like to come in?"),
    ("time", "And what time works best for you?"),
    ("reason", "Last thing — briefly, what's this appointment for? You can also say 'skip'."),
]


def build_system_prompt(category, mode, language):
    system_prompt = PERSONAS.get(category, PERSONAS["general"])
    if mode == "scenario":
        system_prompt += SCENARIO_SUFFIX
    lang_name = LANGUAGE_NAMES.get(language)
    if lang_name:
        system_prompt += f"\n\nRespond in {lang_name}, regardless of what language the citizen wrote in."
    return system_prompt


def ask_llm(user_message, category, mode, language, context=""):
    system_prompt = build_system_prompt(category, mode, language)
    final_message = user_message
    if context:
        final_message = (
            f"The citizen has attached this document/context:\n\n{context}\n\n"
            f"Their question: {user_message}"
        )
    prompt = f"{system_prompt.strip()}\n\nUser: {final_message}"
    response = llm.invoke(prompt)
    return getattr(response, "content", str(response))


_elevenlabs_session = requests.Session()
_elevenlabs_session.verify = False


def synthesize_speech(text, language):
    """Calls ElevenLabs TTS and returns raw mp3 bytes."""
    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.75},
    }
    resp = _elevenlabs_session.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.content


def split_into_speech_chunks(text, min_words=6):
    """Splits a reply into speakable chunks so TTS/audio can start streaming
    before the whole reply has been synthesized, without cutting it into
    choppy one-or-two-word fragments.

    Consecutive short sentences are merged until a chunk has at least
    `min_words` words (the last chunk is kept as-is however short)."""
    sentences = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return []

    chunks = []
    current = ""
    for sentence in sentences:
        current = f"{current} {sentence}".strip() if current else sentence
        if len(current.split()) >= min_words:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True) or {}
    user_message = (data.get("message") or "").strip()
    category = data.get("category") or "general"
    mode = data.get("mode") or "chat"
    language = data.get("language") or "en"
    context = (data.get("context") or "").strip()

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    try:
        answer = ask_llm(user_message, category, mode, language, context)
        return jsonify({
            "answer": answer,
            "department": DEPARTMENT_NAMES.get(category, "General Inquiries Desk"),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"AI request failed: {str(e)}"}), 502


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "voice_enabled": bool(DEEPGRAM_API_KEY and ELEVENLABS_API_KEY),
    })


# ---------------------------------------------------------------------------
# Continuous voice call — /ws/call
#
# Protocol (client <-> server, over one WebSocket connection):
#   client -> server, first text frame (JSON): {"category","language","mode"}
#   client -> server, binary frames: raw mic audio chunks (webm/opus)
#   client -> server, text frame: {"type":"hangup"} to end the call,
#                      or {"type":"category_update","category":...}
#
#   server -> client, text frames (JSON):
#     {"type":"ready"}
#     {"type":"interim","text": "..."}                 partial transcript
#     {"type":"user_transcript","text": "..."}          finalized transcript
#     {"type":"department","department": "..."}
#     {"type":"assistant_text","text": "..."}           what the clerk is saying
#     {"type":"booking_fill","data": {...}}             fields to fill the booking form with
#     {"type":"error","message": "..."}
#   server -> client, binary frames: mp3 audio to play (the spoken reply)
# ---------------------------------------------------------------------------

def parse_spoken_date(text):
    try:
        dt = dateparser.parse(text, fuzzy=True, default=datetime.now())
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return text


def parse_spoken_time(text):
    try:
        dt = dateparser.parse(text, fuzzy=True, default=datetime.now())
        return dt.strftime("%H:%M")
    except Exception:
        return text


@sock.route("/ws/call")
def call_socket(ws):
    if not DEEPGRAM_API_KEY:
        ws.send(json.dumps({"type": "error", "message": "DEEPGRAM_API_KEY is not set on the server."}))
        return
    if not ELEVENLABS_API_KEY:
        ws.send(json.dumps({"type": "error", "message": "ELEVENLABS_API_KEY is not set on the server."}))
        return

    # --- read initial config from the client ---
    try:
        first = ws.receive(timeout=10)
        cfg = json.loads(first) if first else {}
    except Exception:
        cfg = {}

    category = cfg.get("category", "general")
    language = cfg.get("language", "en")
    mode = cfg.get("mode", "chat")

    dg_lang = DEEPGRAM_LANGUAGE.get(language, "en-US")
    dg_url = (
        "wss://api.deepgram.com/v1/listen"
        f"?model=nova-2&language={dg_lang}&smart_format=true&punctuate=true"
        "&interim_results=true&endpointing=500&utterance_end_ms=1200&vad_events=true"
    )

    try:
        dg_ws = create_connection(dg_url, header=[f"Authorization: Token {DEEPGRAM_API_KEY}"])
    except Exception as e:
        ws.send(json.dumps({"type": "error", "message": f"Could not connect to Deepgram: {e}"}))
        return

    booking_state = {"active": False, "step": 0, "data": {}}
    stop_flag = {"stop": False}
    buf = {"text": ""}
    lock = threading.Lock()

    def send_json(obj):
        try:
            ws.send(json.dumps(obj))
        except Exception:
            stop_flag["stop"] = True

    def send_audio(mp3_bytes):
        try:
            ws.send(mp3_bytes)
        except Exception:
            stop_flag["stop"] = True

    def speak(text):
        # Send the full caption once, immediately, for the on-screen
        # transcript/ledger — this doesn't wait on TTS at all.
        send_json({"type": "assistant_text", "text": text})

        chunks = split_into_speech_chunks(text) or [text]
        for chunk in chunks:
            if stop_flag["stop"]:
                return
            try:
                audio = synthesize_speech(chunk, language)
                send_audio(audio)
            except Exception as e:
                send_json({"type": "error", "message": f"Text-to-speech failed: {e}"})
                return

    def handle_utterance(text):
        text = (text or "").strip()
        if not text:
            return
        send_json({"type": "user_transcript", "text": text})

        with lock:
            if booking_state["active"]:
                field, _ = BOOKING_STEPS[booking_state["step"]]
                value = text
                if field == "date":
                    value = parse_spoken_date(text)
                elif field == "time":
                    value = parse_spoken_time(text)
                elif field == "reason" and text.strip().lower() in ("skip", "no", "none", "nothing"):
                    value = ""
                booking_state["data"][field] = value
                booking_state["step"] += 1

                if booking_state["step"] >= len(BOOKING_STEPS):
                    booking_state["data"]["department"] = category
                    send_json({"type": "booking_fill", "data": booking_state["data"]})
                    booking_state["active"] = False
                    booking_state["step"] = 0
                    booking_state["data"] = {}
                    speak("I've filled in your booking form on screen — please review it and press confirm.")
                else:
                    _, next_prompt = BOOKING_STEPS[booking_state["step"]]
                    speak(next_prompt)
                return

            low = text.lower()
            if any(p in low for p in BOOKING_PHRASES):
                booking_state["active"] = True
                booking_state["step"] = 0
                speak(BOOKING_STEPS[0][1])
                return

        # normal Q&A (outside the lock — this can take a while)
        try:
            answer = ask_llm(text, category, mode, language)
            send_json({"type": "department", "department": DEPARTMENT_NAMES.get(category, "General Inquiries Desk")})
            speak(answer)
        except Exception as e:
            send_json({"type": "error", "message": f"AI request failed: {e}"})

    def deepgram_listener():
        while not stop_flag["stop"]:
            try:
                msg = dg_ws.recv()
            except Exception:
                break
            if not msg:
                continue
            try:
                data = json.loads(msg)
            except Exception:
                continue

            msg_type = data.get("type")

            if msg_type == "UtteranceEnd":
                with lock:
                    pending = buf["text"]
                    buf["text"] = ""
                if pending:
                    handle_utterance(pending)
                continue

            # Other event types (Metadata, SpeechStarted, etc.) don't carry a
            # transcript in the shape we expect — skip them.
            if msg_type != "Results":
                continue

            channel = data.get("channel")
            if not isinstance(channel, dict):
                continue
            alts = channel.get("alternatives") or [{}]
            if not alts or not isinstance(alts[0], dict):
                continue
            text = alts[0].get("transcript", "")
            if not text:
                continue

            if data.get("is_final"):
                pending = None
                with lock:
                    buf["text"] = (buf["text"] + " " + text).strip()
                    if data.get("speech_final"):
                        pending = buf["text"]
                        buf["text"] = ""
                if pending:
                    handle_utterance(pending)
            else:
                send_json({"type": "interim", "text": text})

    listener_thread = threading.Thread(target=deepgram_listener, daemon=True)
    listener_thread.start()

    send_json({"type": "ready"})

    try:
        while not stop_flag["stop"]:
            msg = ws.receive()
            if msg is None:
                break
            if isinstance(msg, (bytes, bytearray)):
                try:
                    dg_ws.send_binary(msg)
                except Exception:
                    break
            else:
                try:
                    ctrl = json.loads(msg)
                except Exception:
                    continue
                if ctrl.get("type") == "hangup":
                    break
                if ctrl.get("type") == "category_update":
                    category = ctrl.get("category", category)
    except Exception:
        pass
    finally:
        stop_flag["stop"] = True
        try:
            dg_ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)