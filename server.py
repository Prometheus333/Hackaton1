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

    system_prompt = PERSONAS.get(category, PERSONAS["general"])
    if mode == "scenario":
        system_prompt += SCENARIO_SUFFIX

    lang_name = LANGUAGE_NAMES.get(language)
    if lang_name:
        system_prompt += f"\n\nRespond in {lang_name}, regardless of what language the citizen wrote in."

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


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
