# Civic Information Desk — genailab.tcs.in (LiteLLM) setup

Files:
- `server.py` — Flask backend that calls your TCS genailab.tcs.in LiteLLM endpoint
- `civic-info-desk.html` — the webpage (unchanged — still just calls localhost:5000)
- `.env.example` — template for your credentials
- `requirements.txt` — Python packages needed

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
```
`.env` is already in `.gitignore` so it won't get uploaded to GitHub by accident.

> Note: the exact base URL path (whether it ends in `/v1`, `/v1/chat/completions`,
> or something else) depends on how your org's LiteLLM proxy is configured.
> If you get a 404, check with whoever gave you the endpoint for the exact
> base URL and model name to use.

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
- **401 / unauthorized** — check `LITELLM_API_KEY` has no extra spaces or
  quotes around it in the `.env` file.
- **Backend offline in the page** — make sure `python server.py` is still
  running in its terminal.

## What's new: the four features

1. **Visible journey** — each question now shows an animated routing sequence
   (Inquiry received → Routed to [department] → Reviewing → Response stamped)
   before the answer appears.
2. **Window personas** — Permits, Tax, Regulations, and General each answer in
   a distinct clerk voice (set server-side in `server.py`'s `PERSONAS` dict),
   while staying strictly factual.
3. **Scenario Check mode** — toggle the checkbox in the sidebar, then describe
   something you're planning (e.g. "add a second floor"). The bot returns a
   Verdict / Why / Before-you-apply structure instead of a plain answer.
4. **Civic Passport** — every successfully stamped inquiry is logged in the
   right-hand panel and saved in your browser's local storage, so it persists
   across visits (per browser, not shared between people).

No new setup steps — same `.env`, same `pip install -r requirements.txt`,
same `python server.py`.

## Latest additions

- **Voice input** — mic icon in the composer (Chrome/Edge best support; falls
  back to an alert if the browser doesn't support Web Speech API).
- **Document attach** — paperclip icon lets you attach a `.txt`/`.md` file;
  its content is sent to the AI as context for your next question, then cleared.
- **Language selector** — EN/ES/HI in the top nav; the AI's answer comes back
  in the selected language (UI chrome itself stays in English).
- **Insights page** — replaces the old "My Requests" page: a bar chart of
  inquiries per department plus the full history table, both computed live
  from your saved local data.
- **Help Center** — a static, searchable FAQ page, separate from the AI
  assistant (no backend call — instant answers for common questions).

No new setup steps — same `.env`, same `requirements.txt`, same `python server.py`.
`server.py` now also reads `language` and `context` from each request.

## New: Call the Desk (simulated phone call)

A phone icon next to the mic button in the Assistant composer opens a
push-to-talk call modal:

1. Hold the mic button and speak, release to send.
2. Your clip is transcribed by **Deepgram** (`/v1/listen`, `nova-2` model).
3. The transcript is answered by the same persona/scenario logic as the
   text chat.
4. The reply is spoken back with **ElevenLabs** TTS and plays automatically.
5. Each turn is logged as a Civic Passport stamp, same as text chat.

### Extra setup for this feature
Add two more values to your `.env` (see `.env.example`):
```
DEEPGRAM_API_KEY=your-deepgram-key
ELEVENLABS_API_KEY=your-elevenlabs-key
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM   # optional, defaults to "Rachel"
```
- Get a Deepgram key at https://console.deepgram.com/
- Get an ElevenLabs key at https://elevenlabs.io/app/settings/api-keys
- No new pip packages needed — both are called with plain HTTPS requests via
  the `httpx` client already in `server.py`. (`requirements.txt` has also
  been corrected to include `httpx` and `langchain-openai`, which `server.py`
  imports but which were missing from the original file.)
- The browser needs mic permission and `MediaRecorder` support (Chrome/Edge/
  Firefox all work; Safari support varies by version).
- If you see "Recording not supported in this browser," try Chrome or Edge.
- If a call turn fails with a 502 mentioning Deepgram or ElevenLabs, double
  check the corresponding API key in `.env` and that your account has
  remaining credits.
