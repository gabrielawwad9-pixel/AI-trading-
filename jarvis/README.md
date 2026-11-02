# JARVIS: a voice assistant for your Windows laptop

Say **"Jarvis"**, ask anything, and hear a calm, natural voice reply.

- **Wake word:** openWakeWord, offline
- **Speech-to-text:** faster-whisper, offline
- **Brain:** Claude API (key in `.env`), or a local model through Ollama
- **Voice:** edge-tts (natural online voice) or Piper (offline)
- **Memory:** remembers the conversation during a session, and saves facts about you to `memory.json`
- **Interruptible:** say "Jarvis" (or just talk) while it's speaking
- **Skills:** time and date, open apps and websites, web search, timers and reminders, answering questions
- **Personality:** loaded from `personality.txt`
- **Trading:** prices, your Robinhood portfolio, a paper-trading practice account, watchlist,
  price alerts, a live terminal dashboard, and voice/terminal orders with confirmations and safety limits
- **Terminal command:** `jarvis`, `jarvis chat`, `jarvis portfolio`, `jarvis buy 5 AAPL`, `jarvis dashboard` and more

## Quick start

1. Install Python 3.12 (tick **"Add python.exe to PATH"**).
2. Double-click `setup.bat`.
3. Put your Claude API key in `.env` (or set `LLM_PROVIDER=ollama`).
4. Test each part: `check.bat mic`, `voice`, `wake`, `stt`, `brain`, `interrupt`.
5. Start it: **`start_jarvis.bat`** (or `jarvis` in a bash terminal after `bash setup.sh`).
6. Trading: `jarvis portfolio`, `jarvis quote TSLA`, `jarvis buy 5 AAPL` (paper money by default).
   To link Robinhood, run `jarvis connect` (details in Step 8 of the guide).

**New to this? Follow [SETUP_GUIDE.md](SETUP_GUIDE.md).** It walks through every step,
with a test after each one and fixes for common errors.
