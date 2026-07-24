"""
Civic Information Desk — backend server (genailab.tcs.in / LiteLLM version)

Merged server: the richer text-chat endpoint (conversation history, greetings,
booking extraction) plus a hardened continuous voice call over /ws/call
(Deepgram speech-to-text + ElevenLabs text-to-speech).

Run:
    pip install -r requirements.txt
    Fill in the values in .env (see .env.example)
    python server.py
"""

import os
import json
import threading
import time
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
# Personas / prompts (shared by text chat and voice calls)
# ---------------------------------------------------------------------------
BASE_RULES = """You are CivicBot, a clerk at the Civic Information Desk, a public service
information chatbot. Your main job covers: permits & licenses, tax payments, and
local regulations.

Rules that never change regardless of persona:
- Give accurate, concise answers (2-4 sentences), UNLESS you need to ask a
  narrowing question first (see below).
- Greetings, small talk, and simple personal questions (e.g. "what's your name",
  "how are you", "who am I talking to") get a brief, warm, direct answer —
  never a deflection. You are CivicBot; answer as yourself. If asked the
  citizen's own name and you don't know it, say so lightly and ask what they'd
  like to be called, don't refuse to engage.
- If a question is a genuine request for help that's outside permits/tax/
  regulations (e.g. asking about an unrelated topic entirely), say so plainly
  and suggest the relevant department or the general inquiries line.
- Never invent specific fees, dates, or phone numbers — speak in general
  terms (e.g. "typically 10-15 business days") rather than fabricating figures.
- Do not break character with meta-commentary about being an AI persona.
- NARROW BEFORE YOU ANSWER: if the citizen's question is broad or missing a
  key detail you'd need to give a real answer (e.g. individual vs business,
  which type of permit, which municipality), ask ONE short clarifying
  question first instead of giving a generic answer. Once you have enough
  detail, answer directly — don't keep narrowing forever.
- USE WHAT YOU ALREADY KNOW: if the citizen already told you something earlier
  in this conversation (their name, what they're applying for, individual vs
  business, etc.), use it — never ask for the same detail twice.
- GREETING MANNERS: if the citizen greets you (hi, good morning, etc.), greet
  them back appropriately for the time of day you're given. If you have their
  name, use it naturally ("Good morning, {name}"); if you don't have a name,
  greet warmly without inventing one ("Good morning! How can I help?").
"""

MEXICO_CONTEXT = """
General reference context (Mexico) — use this as background knowledge, not as
verbatim script. These are general patterns that hold across most Mexican
municipalities; always tell the citizen to confirm exact fees/offices locally
since these vary by state and change over time:
- Driver's license (licencia de conducir): typically needs proof of identity
  (passport or residency card), CURP, proof of address (utility bill, usually
  under ~3 months old), payment of the applicable fee, and sometimes a vision
  test or written test on traffic rules. Done in person at the local
  Secretaría de Movilidad / transit licensing office.
- Traffic ticket / infraction (multa de tránsito): the citizen should receive
  a written citation — paying an officer directly at the roadside is not the
  correct channel and should never be advised. Fines are normally payable at
  the municipal traffic office / juzgado cívico, an authorized bank, or
  sometimes online, often with an early-payment discount if settled within
  1-2 weeks. Citations can usually be contested within a set window (often
  around 15 business days) at the same office that issued it.
"""

VOICE_ADDENDUM = """
This is a SPOKEN phone call, not a chat window. Extra rules for voice:
- Keep replies short and easy to say aloud — favor 1-3 sentences over lists.
- Never use markdown, bullet points, or symbols like "*" or "#" — everything
  you write is spoken directly by a text-to-speech engine.
- Unless you just asked the citizen a clarifying question yourself, end your
  turn with a brief, natural, VARIED invitation to keep going — for example
  "What else can I help you with?", "Is there anything else on your mind?",
  "Anything else today?". Don't reuse the exact same phrase twice in a row,
  and don't add one if you already asked the citizen a question in this same
  reply — never ask two questions at once.
- If the citizen is only exchanging pleasantries at the very start of the
  call (a greeting with nothing else), greet them back and ask how you can
  help — don't invent a closing question on top of that.
"""

PERSONAS = {
    "permits": BASE_RULES + MEXICO_CONTEXT + """
Voice: the Permits & Licensing clerk. Brisk, efficient, no wasted words.
Give the answer first, in short direct sentences. Skip pleasantries beyond
manners already required above.
""",
    "tax": BASE_RULES + """
Voice: the Tax & Revenue clerk. Patient and reassuring — explain things a
little more fully, and proactively mention ways to avoid a penalty. Early on,
narrow down whether this is for an individual or a business, and which tax
(property, income, etc.) — the right next step differs a lot by answer.
""",
    "regulations": BASE_RULES + MEXICO_CONTEXT + """
Voice: the Regulatory Affairs clerk. Dry, a little wry about paperwork,
but never unhelpful or sarcastic toward the citizen. Keep it brief. When a
citizen describes a situation (e.g. "I got a ticket for running a red
light"), give them a short practical roadmap: what the right channel is,
roughly how the process works, and what to do next — not just a one-line
deflection.
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
    "agendar una cita", "hacer una cita", "quiero agendar", "reservar una cita",
]

# Steps for the voice-driven booking flow. Each entry is (field_key, prompt_to_speak).
BOOKING_STEPS = [
    ("name", "Sure, let's get you booked in. Can I get your full name?"),
    ("contact", "Thanks. What's the best email or phone number to reach you?"),
    ("date", "What date would you like to come in?"),
    ("time", "And what time works best for you?"),
    ("reason", "Last thing — briefly, what's this appointment for? You can also say 'skip'."),
]

# Phrases that signal the citizen is wrapping up the call. Kept as plain
# substrings (lowercased) across the three supported languages — this is a
# lightweight heuristic, not a language model call, so it stays fast and
# doesn't add latency to every turn.
CLOSING_PHRASES = [
    # English
    "thank you, goodbye", "thanks, goodbye", "thank you goodbye",
    "goodbye", "good bye", "bye bye", "bye for now", "that's all",
    "that is all", "that will be all", "nothing else", "no that's it",
    "no, that's it", "i'm good, thanks", "i'm all set", "that's it thanks",
    "hang up", "end the call", "no more questions",
    # Spanish
    "adiós", "adios", "hasta luego", "eso es todo", "nada más",
    "nada mas", "gracias, eso es todo", "ya no necesito nada",
    "es todo gracias", "colgar", "terminar la llamada", "muchas gracias adiós",
    # Hindi (romanized, common phrasing)
    "dhanyavad", "alvida", "bas itna hi", "bas itna hi tha", "shukriya bas",
]

# Just "thank you" / "gracias" alone (no goodbye word) is treated as a soft
# signal — worth ending the turn warmly, but only closes the call if paired
# with one of the phrases above, so a citizen who says "thanks!" mid-call
# isn't hung up on before their next question.
SOFT_THANKS = ["thank you", "thanks", "gracias", "shukriya", "dhanyavad"]

# How long the call can sit idle (no finalized user speech) before the clerk
# checks in, and how long after that before it hangs up gracefully.
IDLE_CHECKIN_SECONDS = 22
IDLE_HANGUP_SECONDS = 20  # additional seconds after the check-in prompt

STILL_THERE_PROMPTS = {
    "en": "Are you still there? I'm here whenever you're ready — what else can I help with?",
    "es": "¿Sigues ahí? Aquí estoy cuando quieras — ¿en qué más te puedo ayudar?",
    "hi": "Kya aap wahin hain? Main yahin hoon, jab chahen poochh sakte hain.",
}
TIMEOUT_GOODBYE = {
    "en": "I haven't heard back, so I'll go ahead and close this call — feel free to call again anytime. Goodbye!",
    "es": "No he escuchado respuesta, así que voy a cerrar la llamada — puedes volver a llamar cuando quieras. ¡Hasta luego!",
    "hi": "Mujhe jawaab nahi mila, isliye main call band kar raha hoon — jab chahen dobara call karein. Alvida!",
}


def build_system_prompt(category, mode, language, user_name="", time_of_day="", history=None, voice=False):
    system_prompt = PERSONAS.get(category, PERSONAS["general"])
    if voice:
        system_prompt += VOICE_ADDENDUM
    if mode == "scenario":
        system_prompt += SCENARIO_SUFFIX

    lang_name = LANGUAGE_NAMES.get(language)
    if lang_name:
        system_prompt += f"\n\nRespond in {lang_name}, regardless of what language the citizen wrote in."

    system_prompt += (
        f"\n\nCitizen's name: {user_name if user_name else 'not provided — do not invent one'}."
        f"\nCurrent time of day: {time_of_day if time_of_day else 'unknown'}."
    )

    if history:
        convo_text = "\n".join(
            f"Citizen: {h.get('question', '')}\nCivicBot: {h.get('answer', '')}"
            for h in history[-6:]
        )
        system_prompt += (
            "\n\nEarlier in this same conversation:\n" + convo_text +
            "\n\nDo not ask the citizen again for anything they already told you above."
        )
    return system_prompt


def ask_llm(user_message, category, mode, language, context="", user_name="", time_of_day="", history=None, voice=False):
    system_prompt = build_system_prompt(category, mode, language, user_name, time_of_day, history, voice=voice)
    final_message = user_message
    if context:
        final_message = (
            f"The citizen has attached this document/context:\n\n{context}\n\n"
            f"Their question: {user_message}"
        )
    prompt = f"{system_prompt.strip()}\n\nUser: {final_message}"
    response = llm.invoke(prompt)
    return getattr(response, "content", str(response))


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
    resp = requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
    resp.raise_for_status()
    return resp.content


def is_closing_utterance(text):
    low = (text or "").strip().lower()
    if not low:
        return False
    if any(p in low for p in CLOSING_PHRASES):
        return True
    # "Thanks" alone, as a short whole utterance (not "thanks, and also...")
    # is treated as closing too — a longer sentence containing "thanks" that
    # goes on to ask something else should NOT trigger a hangup.
    word_count = len(low.split())
    if word_count <= 4 and any(low == p or low.startswith(p) for p in SOFT_THANKS):
        return True
    return False


# ---------------------------------------------------------------------------
# Text chat endpoints
# ---------------------------------------------------------------------------
@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True) or {}
    user_message = (data.get("message") or "").strip()
    category = data.get("category") or "general"
    mode = data.get("mode") or "chat"
    language = data.get("language") or "en"
    context = (data.get("context") or "").strip()
    user_name = (data.get("userName") or "").strip()
    time_of_day = (data.get("timeOfDay") or "").strip()
    history = data.get("history") or []

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    try:
        answer = ask_llm(user_message, category, mode, language, context, user_name, time_of_day, history)
        return jsonify({
            "answer": answer,
            "department": DEPARTMENT_NAMES.get(category, "General Inquiries Desk"),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"AI request failed: {str(e)}"}), 502


@app.route("/api/extract-booking", methods=["POST"])
def extract_booking():
    """Given the citizen's recent conversation, ask the LLM to pull out any
    booking-relevant details (name, contact, date, time, department, reason)
    it can confidently infer, so the booking form can be pre-filled instead
    of starting blank. Anything not clearly mentioned is left empty — this
    never invents values."""
    data = request.get_json(force=True) or {}
    history = data.get("history") or []
    user_name = (data.get("userName") or "").strip()
    category = data.get("category") or "general"

    if not history:
        return jsonify({"name": user_name, "contact": "", "date": "", "time": "", "department": category, "reason": ""})

    convo_text = "\n".join(
        f"Citizen: {h.get('question','')}\nClerk: {h.get('answer','')}" for h in history[-8:]
    )

    extraction_prompt = f"""You are extracting appointment-booking details from a citizen's recent
conversation with a civic help desk, so a booking form can be pre-filled.

Conversation:
{convo_text}

The citizen's known name (if any): {user_name or "unknown"}
The department window currently open: {category}

Output ONLY a single JSON object with exactly these keys — no markdown, no
explanation, no code fences:
- "name": the citizen's name if mentioned, otherwise "{user_name}"
- "contact": an email or phone number ONLY if explicitly mentioned in the conversation, otherwise ""
- "date": a specific date in YYYY-MM-DD format ONLY if one was explicitly mentioned, otherwise ""
- "time": a specific time in 24-hour HH:MM format ONLY if one was explicitly mentioned, otherwise ""
- "department": one of "permits", "tax", "regulations", "general" — best guess from the topic discussed, defaulting to "{category}"
- "reason": a short (under 8 words) plain-language reason for the visit, based on what was discussed, otherwise ""

Never invent a date, time, or contact detail that was not explicitly stated."""

    try:
        response = llm.invoke(extraction_prompt)
        raw = getattr(response, "content", str(response)).strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())
        result = {
            "name": parsed.get("name") or user_name,
            "contact": parsed.get("contact") or "",
            "date": parsed.get("date") or "",
            "time": parsed.get("time") or "",
            "department": parsed.get("department") or category,
            "reason": parsed.get("reason") or "",
        }
        return jsonify(result)
    except Exception:
        traceback.print_exc()
        return jsonify({"name": user_name, "contact": "", "date": "", "time": "", "department": category, "reason": ""})


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
#   client -> server, first text frame (JSON):
#       {"category","language","mode","userName","timeOfDay","history"}
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
#     {"type":"call_ended","reason": "goodbye"|"timeout"}  server is hanging up
#     {"type":"error","message": "..."}
#   server -> client, binary frames: mp3 audio to play (the spoken reply)
#
# Reliability notes:
#   - A background thread sends periodic Deepgram KeepAlive frames so the
#     upstream STT socket doesn't get closed by Deepgram for inactivity while
#     the clerk is talking or the citizen is thinking (this was the main
#     cause of calls dropping "out of nowhere").
#   - If the Deepgram socket drops anyway, we transparently reconnect it
#     instead of tearing down the whole call.
#   - An idle watchdog checks in ("are you still there?") before hanging up,
#     rather than just going silent.
#   - Closing phrases ("thank you", "goodbye", etc.) end the call gracefully
#     with a spoken sign-off instead of an abrupt disconnect.
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


def open_deepgram_socket(language):
    dg_lang = DEEPGRAM_LANGUAGE.get(language, "en-US")
    dg_url = (
        "wss://api.deepgram.com/v1/listen"
        f"?model=nova-2&language={dg_lang}&smart_format=true&punctuate=true"
        "&interim_results=true&endpointing=600&utterance_end_ms=1500&vad_events=true"
    )
    return create_connection(dg_url, header=[f"Authorization: Token {DEEPGRAM_API_KEY}"])


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
    user_name = (cfg.get("userName") or "").strip()
    time_of_day = (cfg.get("timeOfDay") or "").strip()
    history = cfg.get("history") or []

    state = {"language": language}

    try:
        dg_ws = open_deepgram_socket(language)
    except Exception as e:
        ws.send(json.dumps({"type": "error", "message": f"Could not connect to Deepgram: {e}"}))
        return

    booking_state = {"active": False, "step": 0, "data": {}}
    stop_flag = {"stop": False}
    ending_flag = {"ending": False}  # true once we've decided to hang up (goodbye or timeout)
    buf = {"text": ""}
    lock = threading.Lock()
    dg_lock = threading.Lock()
    dg_holder = {"ws": dg_ws}
    last_activity = {"t": time.monotonic()}
    checkin_sent = {"sent": False}

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
        send_json({"type": "assistant_text", "text": text})
        try:
            audio = synthesize_speech(text, state["language"])
            send_audio(audio)
        except Exception as e:
            send_json({"type": "error", "message": f"Text-to-speech failed: {e}"})

    def end_call(reason):
        ending_flag["ending"] = True
        send_json({"type": "call_ended", "reason": reason})
        stop_flag["stop"] = True

    def reconnect_deepgram():
        """Transparently rebuild the Deepgram socket after a drop, instead of
        killing the whole call. Returns True on success."""
        with dg_lock:
            try:
                dg_holder["ws"].close()
            except Exception:
                pass
            try:
                dg_holder["ws"] = open_deepgram_socket(state["language"])
                return True
            except Exception:
                return False

    def handle_utterance(text):
        text = (text or "").strip()
        if not text:
            return
        last_activity["t"] = time.monotonic()
        checkin_sent["sent"] = False
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
                    speak("I've filled in your booking form on screen — please review it and press confirm. What else can I help you with?")
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

        # A closing remark ends the call gracefully instead of waiting for a
        # silence timeout or just going quiet.
        if is_closing_utterance(text):
            farewell = {
                "en": "You're welcome — thanks for calling the Civic Information Desk. Goodbye!",
                "es": "Con gusto — gracias por llamar al Centro de Información Cívica. ¡Hasta luego!",
                "hi": "Aapka swagat hai — Civic Information Desk ko call karne ke liye dhanyavad. Alvida!",
            }.get(state["language"], "Thanks for calling the Civic Information Desk. Goodbye!")
            send_json({"type": "department", "department": DEPARTMENT_NAMES.get(category, "General Inquiries Desk")})
            speak(farewell)
            end_call("goodbye")
            return

        # normal Q&A (outside the lock — this can take a while)
        try:
            answer = ask_llm(text, category, mode, state["language"], "", user_name, time_of_day, history, voice=True)
            history.append({"question": text, "answer": answer})
            send_json({"type": "department", "department": DEPARTMENT_NAMES.get(category, "General Inquiries Desk")})
            speak(answer)
        except Exception as e:
            send_json({"type": "error", "message": f"AI request failed: {e}"})

    def deepgram_listener():
        while not stop_flag["stop"]:
            with dg_lock:
                current_dg = dg_holder["ws"]
            try:
                msg = current_dg.recv()
            except Exception:
                if stop_flag["stop"]:
                    break
                # The upstream socket dropped (often just an idle timeout).
                # Try to bring it back instead of ending the call.
                if reconnect_deepgram():
                    continue
                send_json({"type": "error", "message": "Lost connection to the speech service, retrying…"})
                time.sleep(1)
                continue
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

            last_activity["t"] = time.monotonic()
            checkin_sent["sent"] = False

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

    def keepalive_loop():
        """Deepgram closes a live-transcription socket if it doesn't receive
        audio for a while. During TTS playback / thinking, the browser mic is
        muted and nothing gets forwarded — send a lightweight KeepAlive frame
        every few seconds so the connection survives natural pauses."""
        while not stop_flag["stop"]:
            time.sleep(4)
            if stop_flag["stop"]:
                break
            with dg_lock:
                current_dg = dg_holder["ws"]
            try:
                current_dg.send(json.dumps({"type": "KeepAlive"}))
            except Exception:
                pass  # deepgram_listener's recv loop will notice and reconnect

    def idle_watchdog():
        while not stop_flag["stop"]:
            time.sleep(2)
            if stop_flag["stop"] or ending_flag["ending"] or booking_state["active"]:
                continue
            idle_for = time.monotonic() - last_activity["t"]
            if not checkin_sent["sent"] and idle_for >= IDLE_CHECKIN_SECONDS:
                checkin_sent["sent"] = True
                prompt = STILL_THERE_PROMPTS.get(state["language"], STILL_THERE_PROMPTS["en"])
                speak(prompt)
            elif checkin_sent["sent"] and idle_for >= (IDLE_CHECKIN_SECONDS + IDLE_HANGUP_SECONDS):
                goodbye = TIMEOUT_GOODBYE.get(state["language"], TIMEOUT_GOODBYE["en"])
                speak(goodbye)
                end_call("timeout")

    listener_thread = threading.Thread(target=deepgram_listener, daemon=True)
    listener_thread.start()
    keepalive_thread = threading.Thread(target=keepalive_loop, daemon=True)
    keepalive_thread.start()
    watchdog_thread = threading.Thread(target=idle_watchdog, daemon=True)
    watchdog_thread.start()

    send_json({"type": "ready"})
    if user_name:
        speak(f"Hi {user_name}! How can I help you today?")
    else:
        speak("Hi there! How can I help you today?")
    last_activity["t"] = time.monotonic()

    try:
        while not stop_flag["stop"]:
            # A short timeout lets this loop notice stop_flag (set by the
            # watchdog or a goodbye) promptly instead of blocking forever on
            # a client that has gone quiet.
            try:
                msg = ws.receive(timeout=1)
            except Exception:
                break
            if stop_flag["stop"]:
                break
            if msg is None:
                continue  # just a quiet moment, not a disconnect
            if isinstance(msg, (bytes, bytearray)):
                with dg_lock:
                    current_dg = dg_holder["ws"]
                try:
                    current_dg.send_binary(msg)
                except Exception:
                    if not reconnect_deepgram():
                        continue  # drop this chunk, keep the call alive
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
        with dg_lock:
            try:
                dg_holder["ws"].close()
            except Exception:
                pass


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
