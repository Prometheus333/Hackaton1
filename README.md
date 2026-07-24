# Civic Information Desk — genailab.tcs.in (LiteLLM) + live call setup

Files:
- `server.py` — Flask backend: text chat endpoint + `/ws/call` WebSocket for
  the continuous voice call (Deepgram speech-to-text + ElevenLabs
  text-to-speech)
- `civic-info-desk.html` — the webpage (calls localhost:5000)
- `.env.example` — template for your credentials
- `requirements.txt` — Python packages needed

## ⚠️ About exposed API keys

Earlier versions of this repo had real Deepgram/ElevenLabs/LiteLLM keys
pasted directly into `.env` and/or `README.md` in plain text. If you haven't
already, **revoke/regenerate every key that was ever committed** in the
Deepgram, ElevenLabs, and LiteLLM dashboards — anything pushed to a public
repo should be treated as compromised, even after the file is deleted,
because it still lives in the git history. Keys belong only in your local
`.env` file, which is already in `.gitignore`.

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
- **Call falls back to "Simulated" mode** — that badge means the browser
  couldn't reach `/ws/call` within a few seconds (backend not running, wrong
  `BACKEND_URL`, or a firewall blocking WebSockets). Check the terminal
  running `server.py` for errors.

## The call feature

A single **Call** button (the wave icon next to the composer) starts a real,
uninterrupted phone-style call:

1. Click the wave button — the browser asks for mic permission once.
2. The overlay opens and connects over a WebSocket to `/ws/call` on the
   backend, sending your name and recent conversation history so the clerk
   doesn't start from zero.
3. The clerk greets you first ("Hi \<name>! How can I help you today?") and
   then listens. Talk normally — there's no button to hold. Your mic streams
   continuously to the backend, which relays it to **Deepgram** for live
   transcription. When you pause, the backend sends your question to the LLM
   and speaks the answer back using **ElevenLabs**. The mic mutes itself
   while the clerk is talking so it doesn't pick up its own voice.
4. After answering, the clerk naturally invites you to keep going ("What
   else can I help with?", varied each time) instead of just going silent —
   unless it just asked you a clarifying question itself.
5. If you go quiet for a while, the clerk checks in once ("Are you still
   there?"); if there's still no response after that, it signs off politely
   and ends the call — it won't just hang there forever, and it won't cut
   out without saying anything either.
6. Say something like "I'd like to book an appointment" during the call and
   the clerk will ask you for your name, contact info, date, time, and
   reason one at a time by voice, then fill in the booking form on screen.
7. Saying something like "thank you, goodbye" or "that's all" ends the call
   gracefully with a spoken sign-off, instead of you having to hit the ✕.
8. Every exchange is also written to the Inquiry Ledger (tagged 🎙 CALL) and
   the Civic Passport, just like typed questions.
9. Click the ✕ in the overlay to hang up manually at any time, or the pause
   button to mute without ending the call.

### Why calls used to drop unexpectedly

Deepgram closes its speech-recognition socket if it doesn't receive audio
for a stretch of time — which happens naturally while the clerk is talking
or you're thinking, since the mic is muted then. The backend now sends
periodic keepalive pings to Deepgram during those quiet moments, and
transparently reconnects if the upstream socket drops anyway, instead of
ending your whole call. The client and server also exchange an explicit
`call_ended` message on a graceful hangup (goodbye phrase or timeout) so the
call always ends with a spoken sign-off rather than going silent.

## Everything else

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
