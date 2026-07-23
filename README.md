# Civic Information Desk — Claude-powered setup

Two files here:
- `server.py` — a small Python backend that talks to Claude (keeps your API key safe)
- `civic-info-desk.html` — the webpage, now calling that backend for real AI answers

## 1. Get a Claude API key
1. Go to https://console.anthropic.com
2. Sign up / log in
3. Go to **API Keys** → **Create Key**
4. Copy the key (starts with `sk-ant-...`)

## 2. Install Python (if you don't have it)
Download from https://www.python.org/downloads/ and install.
During install, check the box **"Add Python to PATH"**.

## 3. Set up the project
Open a terminal (PowerShell) in the folder containing these two files, then run:

```powershell
pip install -r requirements.txt
```

## 4. Set your API key
In the same PowerShell window:

```powershell
$env:ANTHROPIC_API_KEY="sk-ant-your-key-here"
```

(This only lasts for the current terminal session — you'll need to set it again if you close and reopen the terminal.)

## 5. Run the backend
```powershell
python server.py
```

You should see something like:
```
 * Running on http://127.0.0.1:5000
```
Leave this terminal window open — it needs to keep running.

## 6. Open the webpage
Double-click `civic-info-desk.html`, or right-click it in VS Code and choose
**Open with Live Server**. The status badge in the top right should say
**"Connected"** once it can reach the backend.

Now type a question — it goes to the backend, which sends it to Claude,
and the answer comes back into the chat.

## Troubleshooting
- **"Backend offline" / can't reach backend** — make sure `python server.py`
  is still running in its terminal window.
- **401 / authentication error** — double check the API key was pasted
  correctly and has no extra spaces.
- **CORS error in browser console** — make sure `flask-cors` installed
  correctly (`pip install flask-cors`).
