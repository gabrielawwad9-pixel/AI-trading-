"""Built-in skills that run instantly on your laptop (no AI needed):
time, date, timers, opening apps/websites, web search, and memory commands.
"""

import datetime as dt
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

from .memory import to_second_person, to_third_person

IS_WINDOWS = sys.platform.startswith("win")

# ---------------------------------------------------------------------------
# Number / duration parsing ("five minutes", "1 hour 30 minutes", "half an hour")
# ---------------------------------------------------------------------------
_NUM_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90,
    "a couple of": 2, "a couple": 2, "couple of": 2, "a few": 3, "few": 3,
}
_UNIT_SECONDS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600}
_NUM_PATTERN = r"(\d+(?:\.\d+)?|(?:twenty|thirty|forty|fifty)[- ](?:one|two|three|four|five|six|seven|eight|nine)|" \
               + "|".join(sorted((re.escape(k) for k in _NUM_WORDS), key=len, reverse=True)) + ")"
_DURATION_RE = re.compile(r"\b" + _NUM_PATTERN + r"\s*(?:and a half\s+)?(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b"
                          r"(\s+and a half)?")


def _word_to_number(w: str) -> float:
    w = w.lower().strip()
    try:
        return float(w)
    except ValueError:
        pass
    if w in _NUM_WORDS:
        return _NUM_WORDS[w]
    parts = re.split(r"[- ]", w)
    if len(parts) == 2 and parts[0] in _NUM_WORDS and parts[1] in _NUM_WORDS:
        return _NUM_WORDS[parts[0]] + _NUM_WORDS[parts[1]]
    return 0


def parse_duration(text: str) -> int:
    """Return the number of seconds mentioned in text, or 0 if none."""
    t = text.lower()
    total = 0.0
    if re.search(r"\bhalf an? hour\b", t):
        total += 1800
        t = re.sub(r"\bhalf an? hour\b", " ", t)
    if re.search(r"\b(?:a )?quarter of an hour\b", t):
        total += 900
        t = re.sub(r"\b(?:a )?quarter of an hour\b", " ", t)
    for m in _DURATION_RE.finditer(t):
        n = _word_to_number(m.group(1))
        unit = m.group(2).rstrip("s")          # "minutes" -> "minute", "hrs" -> "hr"
        secs = _UNIT_SECONDS.get(unit, 0)
        if "and a half" in m.group(0):
            n += 0.5
        total += n * secs
    return int(round(total))


def describe_duration(seconds: int) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    if m:
        parts.append(f"{m} minute{'s' if m != 1 else ''}")
    if s and not h:
        parts.append(f"{s} second{'s' if s != 1 else ''}")
    if not parts:
        return "less than a second"
    return " and ".join(parts) if len(parts) <= 2 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def spoken_time(now=None) -> str:
    now = now or dt.datetime.now()
    h = now.hour % 12 or 12
    return f"{h}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}"


def spoken_date(now=None) -> str:
    now = now or dt.datetime.now()
    return f"{now.strftime('%A')}, {now.strftime('%B')} {_ordinal(now.day)}, {now.year}"


# ---------------------------------------------------------------------------
# Timers
# ---------------------------------------------------------------------------
class Timers:
    """Countdown timers. When one finishes, a message is put on `announcements`."""

    def __init__(self):
        self.announcements: "queue.Queue[str]" = queue.Queue()
        self._timers = {}   # id -> (end_time, label, threading.Timer, seconds)
        self._lock = threading.Lock()
        self._next_id = 1

    def add(self, seconds: int, label: str = "") -> int:
        with self._lock:
            tid = self._next_id
            self._next_id += 1
            t = threading.Timer(seconds, self._fire, args=(tid,))
            t.daemon = True
            self._timers[tid] = (time.time() + seconds, label, t, seconds)
            t.start()
            return tid

    def _fire(self, tid):
        with self._lock:
            item = self._timers.pop(tid, None)
        if item:
            _, label, _, seconds = item
            if label:
                self.announcements.put(f"Time's up. This is your reminder to {label}.")
            else:
                self.announcements.put(f"Your {describe_duration(seconds)} timer is done.")

    def cancel_all(self) -> int:
        with self._lock:
            n = len(self._timers)
            for _, _, t, _ in self._timers.values():
                t.cancel()
            self._timers.clear()
            return n

    def status(self) -> str:
        with self._lock:
            items = sorted(self._timers.values(), key=lambda x: x[0])
        if not items:
            return "You don't have any timers running."
        bits = []
        for end, label, _, _ in items:
            left = describe_duration(max(1, end - time.time()))
            bits.append(f"{left} left" + (f" on your reminder to {label}" if label else ""))
        if len(bits) == 1:
            return f"There's {bits[0]}."
        return f"You have {len(bits)} timers: " + "; ".join(bits) + "."


# ---------------------------------------------------------------------------
# Opening apps and websites
# ---------------------------------------------------------------------------
SITES = {
    "youtube": "https://www.youtube.com", "google": "https://www.google.com",
    "gmail": "https://mail.google.com", "my email": "https://mail.google.com", "email": "https://mail.google.com",
    "google maps": "https://maps.google.com", "maps": "https://maps.google.com",
    "google drive": "https://drive.google.com", "drive": "https://drive.google.com",
    "google docs": "https://docs.google.com", "calendar": "https://calendar.google.com",
    "google calendar": "https://calendar.google.com",
    "github": "https://github.com", "netflix": "https://www.netflix.com", "reddit": "https://www.reddit.com",
    "wikipedia": "https://www.wikipedia.org", "amazon": "https://www.amazon.com",
    "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com",
    "twitter": "https://x.com", "x": "https://x.com", "linkedin": "https://www.linkedin.com",
    "twitch": "https://www.twitch.tv", "news": "https://news.google.com", "weather": "https://weather.com",
    "claude": "https://claude.ai", "chatgpt": "https://chatgpt.com", "whatsapp": "https://web.whatsapp.com",
    "outlook web": "https://outlook.live.com", "spotify web": "https://open.spotify.com",
    "robinhood": "https://robinhood.com",
}

# name -> things to try in order (a Windows command, a URI like "spotify:", or a website)
APPS = {
    "notepad": ["notepad"], "calculator": ["calc"], "calc": ["calc"],
    "file explorer": ["explorer"], "explorer": ["explorer"], "files": ["explorer"], "my files": ["explorer"],
    "settings": ["ms-settings:"], "windows settings": ["ms-settings:"],
    "task manager": ["taskmgr"], "command prompt": ["cmd"], "cmd": ["cmd"],
    "terminal": ["wt", "powershell"], "powershell": ["powershell"],
    "paint": ["mspaint"], "snipping tool": ["snippingtool", "ms-screenclip:"],
    "chrome": ["chrome"], "google chrome": ["chrome"], "edge": ["msedge"], "microsoft edge": ["msedge"],
    "firefox": ["firefox"], "brave": ["brave"],
    "word": ["winword"], "microsoft word": ["winword"], "excel": ["excel"], "microsoft excel": ["excel"],
    "powerpoint": ["powerpnt"], "outlook": ["outlook", "ms-outlook:", "https://outlook.live.com"],
    "onenote": ["onenote"],
    "spotify": ["spotify:", "spotify", "https://open.spotify.com"],
    "teams": ["msteams:", "ms-teams", "https://teams.microsoft.com"],
    "microsoft teams": ["msteams:", "ms-teams", "https://teams.microsoft.com"],
    "discord": ["discord:", "https://discord.com/app"], "steam": ["steam:"], "zoom": ["zoommtg:", "zoom"],
    "vs code": ["code"], "vscode": ["code"], "visual studio code": ["code"], "code": ["code"],
    "camera": ["microsoft.windows.camera:"], "photos": ["ms-photos:"], "clock": ["ms-clock:"],
    "alarms": ["ms-clock:"], "microsoft store": ["ms-windows-store:"], "store": ["ms-windows-store:"],
    "control panel": ["control"], "mail": ["outlookmail:", "https://mail.google.com"],
    "calendar app": ["outlookcal:"], "maps app": ["bingmaps:"], "xbox": ["xbox:"],
    "whatsapp app": ["whatsapp:"], "vlc": ["vlc"], "obs": ["obs64", "obs"],
}

_FILLER = re.compile(r"\b(the|my|app|application|program|website|web site|site|page|please|for me|up)\b")


def _looks_like_url(t: str):
    t = re.sub(r"\s+dot\s+", ".", t.strip().lower())
    t = t.replace(" ", "")
    if re.fullmatch(r"(https?://)?[\w-]+(\.[\w-]+)+(/\S*)?", t):
        return t if t.startswith("http") else "https://" + t
    return None


def _launch_one(candidate: str) -> bool:
    """Try to start one thing. Returns True if it seemed to work."""
    try:
        if candidate.startswith(("http://", "https://")):
            return webbrowser.open(candidate)
        if IS_WINDOWS:
            if re.fullmatch(r"[a-z.\-]+:", candidate):          # URI like spotify: or ms-settings:
                os.startfile(candidate)
                return True
            path = shutil.which(candidate) or _app_paths_lookup(candidate)
            if path:
                subprocess.Popen([path], close_fds=True)
                return True
            return False
        # macOS / Linux (useful for testing)
        path = shutil.which(candidate)
        if path:
            subprocess.Popen([path], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        return False
    except OSError:
        return False


def _app_paths_lookup(exe: str):
    """Windows keeps a registry list of installed apps' locations ('App Paths')."""
    try:
        import winreg
    except ImportError:
        return None
    name = exe if exe.lower().endswith(".exe") else exe + ".exe"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}") as k:
                value, _ = winreg.QueryValueEx(k, None)
                value = os.path.expandvars(value.strip('"'))
                if os.path.exists(value):
                    return value
        except OSError:
            continue
    return None


def _start_menu_lookup(name: str):
    """Find a Start Menu shortcut whose name matches what you said (e.g. 'spotify' -> Spotify.lnk)."""
    if not IS_WINDOWS:
        return None
    roots = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
        Path.home() / "Desktop",
        Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "Desktop",
    ]
    words = [w for w in re.findall(r"[a-z0-9]+", name.lower()) if w]
    if not words:
        return None
    best, best_score = None, 0
    for root in roots:
        if not root.exists():
            continue
        for lnk in root.rglob("*"):
            if lnk.suffix.lower() not in (".lnk", ".url", ".appref-ms"):
                continue
            stem = lnk.stem.lower()
            if "uninstall" in stem:
                continue
            if not all(w in stem for w in words):
                continue
            score = 100 - len(stem) + (50 if stem == name.lower() else 0)
            if score > best_score:
                best, best_score = lnk, score
    return best


def open_target(spoken: str, launcher=None):
    """Open an app or website by name. Returns (success, friendly_name)."""
    launch = launcher or _launch_one
    raw = spoken.strip().strip(".!?").lower()
    name = re.sub(r"\s+", " ", _FILLER.sub(" ", raw)).strip() or raw

    url = _looks_like_url(raw)
    if url:
        return launch(url), url.split("//", 1)[-1].rstrip("/")
    for key in (raw, name):
        if key in SITES:
            return launch(SITES[key]), key
    for key in (raw, name):
        if key in APPS:
            for cand in APPS[key]:
                if launch(cand):
                    return True, key
            break
    if launcher is None:
        if _launch_one(name):
            return True, name
        lnk = _start_menu_lookup(name)
        if lnk is not None:
            try:
                os.startfile(str(lnk))
                return True, lnk.stem
            except OSError:
                pass
    return False, name


def web_search(query: str, launcher=None):
    url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)
    return (launcher or _launch_one)(url)


# ---------------------------------------------------------------------------
# The skill router
# ---------------------------------------------------------------------------
_POLITE = r"^(?:(?:hey|ok|okay|yo)\s+)?(?:jarvis[,.!]?\s+)?(?:(?:please|can you|could you|would you|will you|i want you to|i'd like you to)\s+)*"

_TIME_RE = re.compile(r"\bwhat(?:'s| is)? (?:the )?(?:current )?time\b|\bwhat time is it\b|\btell me the time\b|^time\??$")
_DATE_RE = re.compile(r"\bwhat(?:'s| is)? (?:the |today's )?date\b|\bwhat day is (?:it|today)\b|\btoday's date\b|"
                      r"\bwhat'?s today\b|\bwhich day is it\b")
_TIMER_SET_RE = re.compile(r"\b(?:set|start|create|make|put on)\b.*\b(?:timer|alarm|countdown)\b|\btimer for\b|"
                           r"\bremind me in\b|\bremind me to .+ in\b|\bwake me (?:up )?in\b|^\w+ (?:minute|second|hour)s? timer\b")
_TIMER_CANCEL_RE = re.compile(r"\b(?:cancel|stop|clear|delete|remove)\b.*\b(?:timers?|alarms?|reminders?)\b")
_TIMER_STATUS_RE = re.compile(r"\bhow (?:much|long) (?:time )?(?:is )?(?:left|remaining)\b|\btimer status\b|"
                              r"\bhow long (?:until|till|on) (?:the|my) timer\b|\bany timers\b|\bwhat timers\b")
_OPEN_RE = re.compile(r"^(?:open|launch|start|run|pull up|bring up|fire up|load|go to|show me)\s+(?:up\s+)?(.+?)(?:\s+for me)?$")
_SEARCH_RE = re.compile(r"^(?:search|google|look up|search the web|search google)\s+(?:for\s+|up\s+)?(.+)$")
_REMEMBER_RE = re.compile(r"^(?:remember|note|don't forget|make a note)\s+(?:that\s+)?(.+)$")
_RECALL_RE = re.compile(r"\bwhat do you (?:know|remember) about me\b|\bwhat have you remembered\b|"
                        r"\bwhat do you remember\b|\bwhat facts do you have\b")
_FORGET_ALL_RE = re.compile(r"^forget (?:everything|all of it|all)(?: about me| you know)?$|^(?:clear|erase|wipe) (?:your |my )?memory$")
_FORGET_RE = re.compile(r"^forget (?:that |about )?(.+)$")
_YES_RE = re.compile(r"^(?:yes|yeah|yep|sure|please|go ahead|do it|ok|okay|yes please)\b")
_NO_RE = re.compile(r"^(?:no|nope|nah|don't|never mind|cancel)\b")


def normalize(text: str) -> str:
    t = text.strip().lower()
    t = t.replace("\u2019", "'")
    t = re.sub(_POLITE, "", t)
    t = re.sub(r"[.!?,]+$", "", t).strip()
    return t


class Skills:
    def __init__(self, memory, timers: Timers, launcher=None):
        self.memory = memory
        self.timers = timers
        self.launcher = launcher     # tests swap this for a fake so nothing really opens
        self.pending = None          # follow-up question we asked, e.g. ("timer", None)

    # Returns a reply string if a skill handled it, otherwise None (-> ask the AI).
    def handle(self, text: str):
        t = normalize(text)
        if not t:
            return None

        # Follow-ups to questions we just asked
        if self.pending:
            kind, data = self.pending
            self.pending = None
            if kind == "timer":
                secs = parse_duration(t)
                if secs:
                    return self._set_timer(secs, "")
            elif kind == "search":
                if _YES_RE.match(t):
                    web_search(data, self.launcher)
                    return f"Searching the web for {data}."
                if _NO_RE.match(t):
                    return "Alright."

        if _TIME_RE.search(t):
            return f"It's {spoken_time()}."
        if _DATE_RE.search(t):
            return f"Today is {spoken_date()}."

        if _TIMER_CANCEL_RE.search(t):
            n = self.timers.cancel_all()
            return "Done, I've cancelled your timer." if n == 1 else (
                f"Done, I've cancelled all {n} timers." if n else "There aren't any timers running.")
        if _TIMER_STATUS_RE.search(t):
            return self.timers.status()
        if _TIMER_SET_RE.search(t):
            secs = parse_duration(t)
            label = ""
            m = re.search(r"\bremind me (?:in .+? )?to (.+?)(?: in \S+ \w+)?$", t)
            if m:
                label = m.group(1).strip()
            if not secs:
                self.pending = ("timer", None)
                return "Of course. For how long?"
            return self._set_timer(secs, label)

        if _RECALL_RE.search(t):
            if not self.memory.facts:
                return "I don't have anything saved about you yet. You can say, remember that, and tell me something."
            facts = [to_second_person(f["fact"]).rstrip(".") for f in self.memory.facts]
            return "Here's what I remember: " + "; ".join(facts) + "."
        if _FORGET_ALL_RE.search(t):
            self.memory.clear()
            return "Done. I've wiped everything I remembered about you."
        m = _FORGET_RE.match(t)
        if m:
            n = self.memory.forget(m.group(1))
            return "Done, I've forgotten that." if n else "I couldn't find anything like that in my memory."
        m = _REMEMBER_RE.match(t)
        if m and len(m.group(1)) > 3:
            fact = to_third_person(m.group(1))
            self.memory.add(fact)
            return "Got it. I'll remember that."

        m = _SEARCH_RE.match(t)
        if m:
            q = m.group(1).strip()
            web_search(q, self.launcher)
            return f"Here are the search results for {q}."

        m = _OPEN_RE.match(t)
        if m:
            target = m.group(1).strip()
            if re.fullmatch(r"(?:a |the )?(?:timer|conversation|over|again)\b.*", target):
                return None
            ok, name = open_target(target, self.launcher)
            if ok:
                return f"Opening {name}."
            self.pending = ("search", target)
            return f"I couldn't find {name} on this laptop. Would you like me to search the web for it?"
        return None

    def _set_timer(self, secs, label):
        self.timers.add(secs, label)
        if label:
            return f"Okay, I'll remind you to {label} in {describe_duration(secs)}."
        return f"Timer set for {describe_duration(secs)}."

    # Actions requested by the AI via hidden tags
    def run_action(self, tag: str, value: str, extra=None):
        if tag == "remember" and value:
            self.memory.add(value)
        elif tag == "open" and value:
            ok, name = open_target(value, self.launcher)
            if not ok:
                print(f"  (Couldn't find '{value}' to open.)")
        elif tag == "search" and value:
            web_search(value, self.launcher)
        elif tag == "timer":
            try:
                secs = int(float(extra)) if extra else parse_duration(value)
            except ValueError:
                secs = parse_duration(value)
            if secs > 0:
                self.timers.add(secs, value if extra else "")
