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
import httpx
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import traceback

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

# Set up HTTPX client with SSL verification disabled (as in the sample code)
httpx_client = httpx.Client(verify=False)

# Build ChatOpenAI client from langchain_openai
llm = ChatOpenAI(
    base_url=BASE_URL.rstrip("/"),  # Ensure no trailing slash
    model=MODEL_NAME,
    api_key=API_KEY,
    http_client=httpx_client
)

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
        # Compose prompt: prepend system prompt, then user message (as a single string)
        prompt = f"{SYSTEM_PROMPT.strip()}\n\nUser: {user_message}"
        response = llm.invoke(prompt)
        # The LangChain result can have .content or be just a string depending on model wrapper
        answer = getattr(response, "content", str(response))
        return jsonify({"answer": answer})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"AI request failed: {str(e)}"}), 502


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
