"""
Civic Information Desk — backend server (genailab.tcs.in / LiteLLM version)

Run:
    pip install -r requirements.txt
    Fill in the values in .env (see .env.example)
    python server.py
"""

import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import traceback

load_dotenv()

app = Flask(__name__)
CORS(app)

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
    http_client=httpx_client
)

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
    history = data.get("history") or []  # list of {question, answer}, most recent last

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    system_prompt = PERSONAS.get(category, PERSONAS["general"])
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

    final_message = user_message
    if context:
        final_message = (
            f"The citizen has attached this document/context:\n\n{context}\n\n"
            f"Their question: {user_message}"
        )

    try:
        prompt = f"{system_prompt.strip()}\n\nUser: {final_message}"
        response = llm.invoke(prompt)
        answer = getattr(response, "content", str(response))
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
    history = data.get("history") or []  # list of {question, answer}
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
        import json as _json
        parsed = _json.loads(raw.strip())
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
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
