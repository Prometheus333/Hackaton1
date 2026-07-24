# Civic Information Desk — genailab.tcs.in (LiteLLM) + live call setup

Files:
- `server.py` — Flask backend: text chat endpoint + `/ws/call` WebSocket for
  the continuous voice call (Deepgram speech-to-text + ElevenLabs
  text-to-speech)
- `civic-info-desk.html` — the webpage (still calls localhost:5000)
- `.env.example` — template for your credentials
- `requirements.txt` — Python packages needed

## ⚠️ About the previous version of this README

An earlier version of this file had real Deepgram and ElevenLabs API keys
pasted directly into it in plain text. **If those keys are still active,
revoke/regenerate them now** in the Deepgram and ElevenLabs dashboards —
anything committed to a repo or shared as a doc should be treated as
compromised. Keys belong only in your local `.env` file, never in the
README or any other tracked file.

## 1. Install Python (if you don't have it)
https://www.python.org/downloads/ — check "Add Python to PATH" during install.

## 2. Install dependencies
Open a terminal in this folder and run:
```powershell
pip install -r requirements.txt
```

## 3. Add your credentials
1. Copy `.env.example` to a new file named `.env` (same folder)
2. Fill in your real values:
```
LITELLM_BASE_URL=https://genailab.tcs.in/v1
LITELLM_API_KEY=your-actual-token
LITELLM_MODEL=your-actual-model-name

DEEPGRAM_API_KEY=your-deepgram-key
ELEVENLABS_API_KEY=your-elevenlabs-key
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
```
`.env` is already in `.gitignore` so it won't get uploaded to GitHub by accident.

> Note: the exact LiteLLM base URL path (whether it ends in `/v1`,
> `/v1/chat/completions`, or something else) depends on how your org's
> LiteLLM proxy is configured. If you get a 404, check with whoever gave you
> the endpoint for the exact base URL and model name to use.

## 4. Run the backend
```powershell
python server.py
```
Leave this terminal open — it needs to keep running.

## 5. Open the webpage
Double-click `civic-info-desk.html`, or open it with Live Server in VS Code.
The status badge should say "Connected" once it reaches the backend.

## Troubleshooting
- **404 / model not found** — double check `LITELLM_BASE_URL` and
  `LITELLM_MODEL` match exactly what you were given.
- **401 / unauthorized** — check the relevant API key has no extra spaces or
  quotes around it in the `.env` file.
- **Backend offline in the page** — make sure `python server.py` is still
  running in its terminal.
- **Call button doesn't connect** — make sure `DEEPGRAM_API_KEY` and
  `ELEVENLABS_API_KEY` are set in `.env` and the server was restarted after
  adding them. Browser mic permission must also be granted.

## What's new: the call feature

The old "Talk Mode" (browser Web Speech API push-to-talk-ish recognition +
browser TTS) and the single-shot mic button have been removed. In their
place is a single **Call** button (the wave icon next to the composer) that
starts a real, uninterrupted phone-style call:

1. Click the wave button — the browser asks for mic permission once.
2. The overlay opens and the call connects over a WebSocket to
   `/ws/call` on the backend.
3. Talk normally — there's no button to hold. Your mic streams
   continuously to the backend, which relays it to **Deepgram** for live
   transcription. When you pause (end of an utterance), the backend sends
   your question to the LLM and speaks the answer back using
   **ElevenLabs**, exactly like a phone call. The mic briefly mutes itself
   while the clerk is talking so it doesn't pick up its own voice, then
   un-mutes automatically.
4. Every exchange is also written to the Inquiry Ledger (tagged 🎙 CALL) and
   the Civic Passport, just like typed questions.
5. Say something like "I'd like to book an appointment" during the call and
   the clerk will ask you for your name, contact info, date, time, and
   reason one at a time by voice. Once you've answered them all, the
   booking form on screen is **automatically filled in** with what you said
   — you just review it and press "Book Appointment" to confirm (still a
   prototype simulation, no real appointment is created).
6. Click the ✕ in the overlay to hang up at any time.

No new setup steps beyond adding the two new keys to `.env` (step 3 above).

## Everything else (unchanged from before)

- **Visible journey** — each typed question shows an animated routing
  sequence before the answer appears.
- **Window personas** — Permits, Tax, Regulations, and General each answer
  in a distinct clerk voice (server-side `PERSONAS` dict).
- **Scenario Check mode** — toggle in the sidebar for a Verdict / Why /
  Before-you-apply structure instead of a plain answer.
- **Civic Passport** — every successfully stamped inquiry is logged and
  saved in your browser's local storage.
- **Document attach** — paperclip icon lets you attach a `.txt`/`.md` file
  as context for your next typed question.
- **Language selector** — EN/ES/HI in the top nav; also used to pick the
  Deepgram transcription language and the language the clerk replies in
  during a call.
- **Insights page**, **Help Center** — unchanged.
