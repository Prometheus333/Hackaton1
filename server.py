"""
Civic Information Desk — backend server (genailab.tcs.in / LiteLLM version)

LiteLLM proxies usually expose an OpenAI-compatible API, so we use the
`openai` Python client but point it at your TCS endpoint instead of
OpenAI's servers.

Run:
    pip install -r requirements.txt
    Fill in the values in .env (see .env.example)
    python server.py
"""

import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()  # reads variables from a local .env file if present

app = Flask(__name__)
CORS(app)

BASE_URL = os.environ.get("LITELLM_BASE_URL")   # e.g. https://genailab.tcs.in/v1
API_KEY = os.environ.get("LITELLM_API_KEY")
MODEL_NAME = os.environ.get("LITELLM_MODEL")     # e.g. the model string your team was given

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

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

SYSTEM_PROMPT = """You are the Civic Information Desk assistant, a conversational AI chatbot
for public service information access. You help citizens with questions about:
- Permits & licenses (building permits, business licenses, parking permits)
- Tax payments (property tax, payment methods, penalties, filing)
- Local regulations (noise ordinances, waste disposal, zoning)

Guidelines:
- Give clear, accurate, concise answers (2-4 sentences).
- If a question is outside these topics, politely say so and suggest
  visiting the relevant department or calling the general inquiries line.
- Use plain language — avoid bureaucratic jargon.
- Never invent specific fees, dates, or phone numbers you don't actually know;
  speak in general terms (e.g. "typically processed within 10-15 business days")
  rather than fabricating exact figures.
"""


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    user_message = (data or {}).get("message", "").strip()

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            max_tokens=300,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        answer = response.choices[0].message.content
        return jsonify({"answer": answer})

    except Exception as e:
        return jsonify({"error": f"LiteLLM request failed: {str(e)}"}), 502


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
