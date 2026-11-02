# JARVIS Setup Guide (for beginners)

This guide takes you from nothing to talking with JARVIS on your Windows laptop.
Expect about **20–30 minutes**, mostly waiting for downloads. Do the steps in order, and
**don't skip the tests in Step 5**. Each test checks one part, so if something breaks later
you'll already know which parts work.

> **How to read this guide:** text `like this` is something you type or a file name.
> "Command Prompt" is the black window where you type commands (Step 5 shows how to open it).

---

## Using a bash terminal (MSYS2 UCRT64 / Git Bash)?

If you prefer a terminal like MSYS2 or Git Bash to double-clicking files, do this instead of Steps 2, 3, and 6.
You still need **Step 1**: install Windows Python 3.12 from python.org. MSYS2's own `pacman`
Python **won't work**, because the speech packages don't support it. The setup script finds the
Windows Python for you.

```bash
# 1. Get the code (MSYS2 users: if 'git' isn't found, run  pacman -S git  first)
cd ~
git clone -b claude/robinhood-trading-ndmzv3 https://github.com/gabrielawwad9-pixel/ai-trading-.git
cd ai-trading-/jarvis

# 2. Install everything (5-10 minutes)
bash setup.sh

# 3. Add your Claude API key (Ctrl+O, Enter to save; Ctrl+X to exit)
nano .env

# 4. Close and reopen the terminal, then test each part:
jarvis check mic
jarvis check voice
jarvis check wake
jarvis check stt
jarvis check brain
jarvis check interrupt

# 5. Run it
jarvis            # voice mode: say "Jarvis"
jarvis chat       # type to JARVIS instead
```

Other commands: `jarvis memory` (what it remembers), `jarvis personality` (edit its personality),
`jarvis settings` (edit `.env`), `jarvis setup` (reinstall/update), `jarvis help`.

If `git clone` asks for a password, GitHub needs a **personal access token** rather than your
password. Or download the ZIP from GitHub in your browser instead, and `cd` into the extracted
`jarvis` folder (e.g. `cd /c/Users/Gabri/Downloads/ai-trading-.../jarvis`).

---

## What you need

- A Windows 10 or 11 laptop with a working microphone (the built-in Dell mic is fine; a headset is better).
- About 2 GB of free disk space.
- Internet for setup. After that, JARVIS can run fully offline if you choose Option B in Step 4.
- **One** of these "brains":
  - **Option A, Claude (recommended):** the smartest option. It needs an Anthropic API key, which is pay-as-you-go. A normal day of chatting usually costs a few cents.
  - **Option B, Ollama:** free and private, and runs entirely on your laptop. It's less clever and slower on laptops without a strong graphics card.

---

## Step 1: Install Python

Python is the programming language JARVIS is written in.

1. Go to <https://www.python.org/downloads/windows/> and download **Python 3.12** (the
   "Windows installer (64-bit)").
2. Run the installer. **On the very first screen, tick the box "Add python.exe to PATH".**
   This is the #1 cause of problems if you miss it.
3. Click **Install Now** and wait for it to finish.

**Test it:** press the Windows key, type `cmd`, press Enter. In the black window, type:

```
py --version
```

You should see something like `Python 3.12.7`.
**If you see "'py' is not recognized":** run the installer again, choose **Modify**, and make sure
"py launcher" and "Add Python to environment variables" are ticked.

---

## Step 2: Get the JARVIS folder

1. Download this project from GitHub (green **Code** button → **Download ZIP**).
2. Right-click the ZIP → **Extract All…** → extract to your **Documents** folder.
3. Open the extracted folder and find the **`jarvis`** folder inside it. That's JARVIS's home.
   You'll see files like `setup.bat`, `start_jarvis.bat`, and `personality.txt`.

> Tip: put the folder somewhere simple like `Documents\jarvis`. Avoid OneDrive-synced folders
> if you can, because syncing can lock files while JARVIS is using them.

---

## Step 3: Run the installer

1. Double-click **`setup.bat`**.
2. If Windows shows **"Windows protected your PC"**, click **More info** → **Run anyway**.
   (This appears for any script downloaded from the internet. `setup.bat` is a plain text file
   you can open in Notepad to see exactly what it does.)
3. Wait. Lots of text will scroll past; that's normal. It:
   - creates a private Python environment just for JARVIS (the `.venv` folder),
   - installs the packages listed in `requirements.txt`,
   - creates your settings file `.env`,
   - downloads the wake-word and speech-recognition models (~160 MB).
4. When it says **"Setup complete!"**, press any key to close it.

**If it fails**, read the message it prints. The most common causes:

| What you see | What it means | Fix |
|---|---|---|
| `I couldn't find Python 3.10-3.13` | Python isn't installed, or isn't on PATH | Redo Step 1 and tick "Add python.exe to PATH" |
| `No matching distribution found` | Your Python is too new or too old for a package | Install Python 3.12, delete the `.venv` folder, and run `setup.bat` again |
| `Microsoft Visual C++ 14.0 or greater is required` / `DLL load failed` | A Windows system component is missing | Install [Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe), restart, and run `setup.bat` again |
| Network / timeout errors | Downloads were blocked or interrupted | Check your Wi-Fi and run `setup.bat` again (it picks up where it left off) |

---

## Step 4: Give JARVIS a brain

Open the **`.env`** file with Notepad: right-click it → **Open with** → **Notepad**.
(If you don't see `.env`, in File Explorer click **View** → **Show** → tick **File name extensions**
and **Hidden items**.)

### Option A: Claude (online, smartest)

1. Go to <https://console.anthropic.com>, sign up, and add a little credit under **Billing**
   ($5 lasts a long time).
2. Go to **API Keys** → **Create Key** → copy it (it starts with `sk-ant-`).
3. In `.env`, paste it right after the `=` with no spaces or quotes:
   ```
   ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxx
   ```
4. Save the file (Ctrl+S).

> **Keep your key secret.** Never share `.env` or post it online. The project's `.gitignore`
> already stops it from being uploaded to GitHub.

### Option B: Ollama (free, runs on your laptop)

1. Install Ollama from <https://ollama.com/download>. It will sit in your system tray.
2. Open Command Prompt and download a model (about 2 GB):
   ```
   ollama pull llama3.2
   ```
3. In `.env`, change the first setting to:
   ```
   LLM_PROVIDER=ollama
   ```
4. Save the file.

You can switch between Claude and Ollama any time by changing `LLM_PROVIDER`.

While you're in `.env`, set `USER_NAME=` to what you'd like JARVIS to call you (optional).

---

## Step 5: Test each piece (one at a time)

Open Command Prompt **in the jarvis folder**: open the folder in File Explorer, click in the
address bar at the top, type `cmd`, and press Enter. Then run each test below **in order**.
Only move on when a test says **[OK]**.

### Test 1: Microphone

```
check.bat mic
```

**What happens:** it lists your audio devices, asks you to stay quiet for 2 seconds, then talk
for 5 seconds while a volume bar moves. It then plays your recording back.

**Success looks like:** the bar jumps when you talk, you hear yourself played back, and
it ends with `[OK] Microphone works!`.

**Common problems:**
- **The bar never moves / "recording silence":** your mic is muted or blocked.
  - Check the mic mute key on your Dell keyboard (often **F4**, with a little mic icon).
  - **Settings → Privacy & security → Microphone**: turn on *Microphone access*, *Let apps access
    your microphone*, **and** *Let desktop apps access your microphone*.
  - **Settings → System → Sound → Input**: pick the right mic and turn up the volume.
- **Wrong mic (e.g. a webcam in another room):** note the number in `[ ]` next to the mic you want
  in the list, and set `MIC_DEVICE=that number` in `.env`.
- The test prints a suggested `SILENCE_LEVEL`. If JARVIS later cuts you off or never stops
  listening, put that number in `.env`.

### Test 2: Voice

```
check.bat voice
```

**What happens:** JARVIS says *"Good day. All systems are online…"* and asks if you heard it.

**Common problems:**
- **"The online voice couldn't connect":** the default voice (Microsoft's "Ryan", calm and British)
  needs internet. Check your Wi-Fi, or use the offline voice:
  ```
  check.bat voice --download-piper
  ```
  then set `TTS_ENGINE=piper` in `.env`. (Once downloaded, JARVIS also falls back to Piper
  automatically if the internet drops.)
- **Generated but you heard nothing:** check the laptop volume and that headphones aren't connected,
  or set `SPEAKER_DEVICE` in `.env` to the number shown in the Test 1 list.
- **Want a different voice?** Change `EDGE_VOICE` in `.env`. Try `en-GB-ThomasNeural`,
  `en-US-GuyNeural`, `en-US-AndrewNeural`, or `en-GB-SoniaNeural` (female). Change speed with `EDGE_RATE`.

### Test 3: Wake word

```
check.bat wake
```

**What happens:** for 30 seconds, say **"Jarvis"** a few times with pauses in between. A score bar
shows how confident it is. Each time it passes the threshold you'll see `<-- JARVIS heard you!`.

**Good to know:** the free ready-made wake-word model was trained on **"Hey Jarvis"**. A clear
"Jarvis" on its own usually works too. If it misses you, try "Hey Jarvis" or lower the threshold.

**Common problems:**
- **"It almost heard you":** the test suggests a lower `WAKE_THRESHOLD` (e.g. `0.3`). Put it in
  `.env` and run the test again.
- **It triggers by itself later** (TV, music, conversation): raise `WAKE_THRESHOLD` to `0.6`–`0.7`.

### Test 4: Speech recognition

```
check.bat stt
```

**What happens:** press Enter, say a sentence, then pause. It prints what it heard and how long it took.

**Common problems:**
- **Slow (more than 3–4 seconds):** set `WHISPER_MODEL=tiny.en` in `.env` (faster, a bit less accurate).
- **Often wrong:** set `WHISPER_MODEL=small.en` (more accurate, slower), or use a headset.
- **"I didn't hear any speech":** lower `SILENCE_LEVEL` in `.env` (use the number from Test 1).

### Test 5: Brain

```
check.bat brain
```

**What happens:** JARVIS introduces itself in one sentence using Claude or Ollama.

**Common problems:**
- **"Claude rejected your API key":** re-copy the key into `.env`, with no spaces or quotes.
- **"Out of credit":** add credit at console.anthropic.com → Billing.
- **"Couldn't connect to Ollama":** open the Ollama app (check the system tray) and make sure you ran
  `ollama pull llama3.2`.

### Test 6: Interrupting

```
check.bat interrupt
```

**What happens:** JARVIS talks for a while. Stay quiet for the first 4 seconds while it measures how
loud its own voice is in your mic. When you see **TALK NOW**, interrupt it by saying
"Jarvis, stop" or just talking.

It then suggests a `VOICE_INTERRUPT_LEVEL` for `.env`.

**Good to know:** with laptop speakers, the mic hears JARVIS's own voice, and loud speakers can make
it interrupt itself. If that happens:
- use headphones (best), **or**
- turn the volume down, **or**
- set `INTERRUPT_MODE=wakeword` so only saying "Jarvis" interrupts it.

> You can also run all six tests in a row with `check.bat all`. It stops at the first problem.

---

## Step 6: Start JARVIS

Double-click **`start_jarvis.bat`**. That's the single command to start it every time.
(Or type `start_jarvis` in Command Prompt in the jarvis folder.)

You'll see each part load, then JARVIS greets you. When you see `[Waiting for 'Jarvis'...]`:

1. Say **"Jarvis"**. You'll hear a soft two-tone chime.
2. Say your request. JARVIS stops listening when you pause.
3. It answers out loud. For about 5 seconds afterwards you can ask a follow-up **without** saying
   "Jarvis" again.
4. To cut it off mid-sentence, say "Jarvis" (or just start talking, if you're on headphones).

### Things to try

| You say | What happens |
|---|---|
| "Jarvis, what time is it?" / "What's the date?" | Instant answer, no AI needed |
| "Open Spotify" / "Open YouTube" / "Open the calculator" | Opens the app or website |
| "Go to bbc dot co dot uk" | Opens that website |
| "Search for easy pasta recipes" | Opens a Google search |
| "Set a timer for 10 minutes" | Chimes and speaks when it's done |
| "Remind me to check the oven in 20 minutes" | Timer with a spoken reminder |
| "How much time is left?" / "Cancel the timer" | Checks or cancels timers |
| "Remember that my sister's name is Maya" | Saved to `memory.json` and remembered next time |
| "What do you know about me?" | Reads back what it remembers |
| "Forget my sister's name" / "Forget everything" | Deletes memories |
| Any question, like "Why is the sky blue?" | Answered by Claude or Ollama |
| "Never mind" / "That's all" | Goes back to waiting for "Jarvis" |
| "Goodbye" / "Shut down" | Closes JARVIS |

JARVIS also learns about you on its own. If you mention something lasting ("I'm a nurse", "I hate
mornings"), the AI may quietly save it to `memory.json`.

**No microphone handy?** `start_jarvis.bat --text` lets you type instead of talk.

---

## Step 7: Make it yours

- **Personality:** edit `personality.txt` in Notepad and restart JARVIS. Make it more formal,
  funnier, more concise, or whatever you like.
- **Settings:** everything is in `.env`, and each setting has a note explaining it.
- **Memory:** `memory.json` is a plain text file of facts. You can read or edit it in Notepad
  (keep the format), or delete it to start fresh.
- **Desktop shortcut:** right-click `start_jarvis.bat` → **Show more options** → **Send to** →
  **Desktop (create shortcut)**.
- **Start automatically when you log in:** press Win+R, type `shell:startup`, press Enter, and put a
  shortcut to `start_jarvis.bat` in that folder.

---

## Step 8: Trading (your Robinhood account)

JARVIS works with your stock trading bot. **It starts in paper mode**: a practice account with
$10,000 of pretend money and real prices. Play with it as much as you like; nothing real happens.

### Things to say (or type in `jarvis chat`)

| You say | What happens |
|---|---|
| "What's Tesla trading at?" / "Price of AAPL" | Current price and today's move |
| "How's my portfolio doing?" | Account value, today's gain/loss, biggest movers |
| "What do I own?" / "What's my buying power?" | Your positions / available cash |
| "Is the market open?" | Market hours (US Eastern) |
| "Buy 5 shares of Apple" / "Buy $100 of Nvidia" | Prepares the order, reads it back, waits for you |
| "Sell all my Tesla" / "Sell 2 Tesla at 300" | Market or limit sell |
| "Yes" (paper) / **"Confirm order"** (live) | Places the order you were just asked about |
| "Add AMD to my watchlist" / "How's my watchlist?" | Watchlist with live prices |
| "Alert me if Tesla goes above 300" | JARVIS speaks up when it happens (while running) |
| "Cancel my orders" / "Reset my paper account" | As it says |
| "Should I trim my Apple position?" | A real discussion using your actual holdings |

### The same things as terminal commands

```bash
jarvis portfolio          jarvis positions         jarvis cash          jarvis market
jarvis quote AAPL TSLA    jarvis buy 5 AAPL        jarvis buy '$100' NVDA
jarvis sell all TSLA      jarvis sell 2 TSLA --limit 300
jarvis watch add AMD      jarvis watch             jarvis alert TSLA above 300
jarvis dashboard          # live screen of your account + watchlist, refreshes every 15s
jarvis trades             # every order JARVIS has placed
jarvis mode               jarvis paper reset       jarvis orders cancel
```

(On Windows without bash, use `trade.bat portfolio`, `trade.bat buy 5 AAPL`, etc.)
In bash, put dollar amounts in single quotes (`'$100'`), or bash will treat `$1` as a variable.

### Connecting Robinhood

1. Put your login in `.env` (`jarvis settings`), **or** in the trading bot's `.env` one folder up.
   JARVIS reads both, so you only need it in one place:
   ```
   ROBINHOOD_USERNAME=you@example.com
   ROBINHOOD_PASSWORD=your-password
   ROBINHOOD_TOTP_SECRET=        # only if you use an authenticator app: the SETUP secret, not a 6-digit code
   ```
2. Run **`jarvis login`** in the terminal. If Robinhood texts you a code or asks you to approve the login
   in the app, do it then. Robinhood remembers the login for a while, so JARVIS can use it in voice mode.
3. Check it worked: `jarvis portfolio`. Prices now come from Robinhood (real time), but you're
   **still in paper mode**.

### Turning on real-money trading (only when you're ready)

In `.env` set:
```
TRADING_MODE=live
MAX_ORDER_USD=500        # JARVIS refuses any single order bigger than this
```

Safety rules that are always on in live mode:
- Every order is read back first. By voice you must say **"confirm order"** ("yes" isn't enough);
  in the terminal you must type **yes**. Anything else cancels it.
- Orders over `MAX_ORDER_USD` are refused, and you can't sell more shares than you own.
- An order you don't confirm within 2 minutes expires.
- **The AI can never place trades.** Only your explicit "buy…/sell…" commands can. When you discuss
  stocks with it, it can only talk.
- Every order is written to `trade_log.jsonl` (`jarvis trades` shows it).

> **Be careful:** speech recognition can mishear numbers ("fifteen" vs "fifty"). Always listen
> to the read-back before confirming. Start with tiny orders, and remember your Robinhood password sits
> in `.env` on this laptop. Keep that file private. JARVIS's opinions aren't financial advice.

---

## Privacy: what stays on your laptop?

| Part | Where it runs |
|---|---|
| Wake word ("Jarvis") | On your laptop. Audio is never sent anywhere. |
| Speech-to-text (Whisper) | On your laptop |
| Brain | **Claude:** the text of what you say (after "Jarvis") goes to Anthropic. **Ollama:** on your laptop |
| Voice | **edge-tts:** JARVIS's reply text goes to Microsoft to make the audio. **Piper:** on your laptop |
| Memory | `memory.json` on your laptop (and its contents go to the brain as context) |
| Trading | Prices come from Robinhood or Yahoo Finance. Orders go to Robinhood (live mode only). When you ask the AI about stocks, a summary of your holdings is sent to the brain |

For a **completely offline** JARVIS, use `LLM_PROVIDER=ollama` and `TTS_ENGINE=piper`.

---

## Troubleshooting

When something goes wrong, JARVIS prints a **plain-English explanation and a suggested fix**.
For the full technical details (useful if you ask someone for help), run:

```
start_jarvis.bat --debug
check.bat mic --debug
```

| Problem | Likely cause and fix |
|---|---|
| Window flashes and closes | Run it from Command Prompt instead (Step 5) so you can read the message |
| "A required Python package is missing" | Run `setup.bat` again |
| "JARVIS isn't set up yet" | You haven't run `setup.bat`, or you moved the folder. Run `setup.bat` |
| It never responds to "Jarvis" | Run `check.bat wake`. Try "Hey Jarvis", or lower `WAKE_THRESHOLD` |
| It wakes up randomly | Raise `WAKE_THRESHOLD` (0.6–0.7) |
| It cuts me off mid-sentence | Raise `END_OF_SPEECH_SECONDS` to 1.2, or lower `SILENCE_LEVEL` |
| It keeps listening after I've finished | Raise `SILENCE_LEVEL` (background noise is being mistaken for speech) |
| It interrupts itself while talking | Use headphones, lower the volume, or set `INTERRUPT_MODE=wakeword` |
| It responds to the TV after answering | Set `FOLLOW_UP_SECONDS=0` |
| Replies are slow | Use `WHISPER_MODEL=tiny.en` and/or `CLAUDE_MODEL=claude-haiku-5-5` |
| "Open X" says it can't find X | The app isn't installed, or has an unusual name. Say its name as it appears in the Start menu |
| Anything to do with the microphone | Settings → Privacy & security → Microphone → allow **desktop apps** |

---

## Updating

To get a newer version: download the new files over the old ones (your `.env` and `memory.json` are
kept), then run `setup.bat` again to install any new packages.

## For the curious: how it works

```
 mic --> wake word (openWakeWord) --> record until you pause --> Whisper speech-to-text
                                                                     |
                     quick skills (time, timers, open apps) <--------+-----> Claude / Ollama
                                                                     |        (streams reply)
 speakers <-- voice (edge-tts / Piper), sentence by sentence <-------+
     ^                                                               
     +-- while speaking, the mic keeps listening so you can interrupt
```

- `jarvis.py`: starts everything.
- `check.py`: the step-by-step tests.
- `jarvis_core/`: the parts: `audio.py` (mic), `wakeword.py`, `stt.py`, `tts.py` (voice and
  interruptions), `brain.py`, `memory.py`, `skills.py`, `assistant.py` (the main loop), and
  `errors.py` (the plain-English error messages).
- `tests/`: automated tests that don't need a mic. Run them with `.venv\Scripts\python -m unittest discover tests`.
