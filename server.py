"""
Civic Information Desk — backend server
Receives a citizen's question from the webpage, sends it to Claude
along with the civic knowledge base as context, and returns the answer.

Run:
    pip install -r requirements.txt
    set ANTHROPIC_API_KEY=your-key-here   (Windows PowerShell: $env:ANTHROPIC_API_KEY="your-key-here")
    python server.py
"""

import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)  # allows the HTML page (opened as a local file or from Live Server) to call this server

API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not API_KEY:
    raise RuntimeError(
        "ANTHROPIC_API_KEY environment variable is not set. "
        "See the README for how to set it before running this server."
    )

client = anthropic.Anthropic(api_key=API_KEY)

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
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        answer = "".join(
            block.text for block in response.content if block.type == "text"
        )
        return jsonify({"answer": answer})

    except anthropic.APIError as e:
        return jsonify({"error": f"Claude API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": f"Server error: {str(e)}"}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
