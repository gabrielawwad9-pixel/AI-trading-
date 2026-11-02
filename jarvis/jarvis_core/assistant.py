"""The main JARVIS loop: wait for the wake word -> listen -> think -> speak (interruptibly)."""

import datetime as dt
import re
import sys
import time

from . import audio as audio_mod
from .errors import explain
from .textproc import SentenceSplitter, TagFilter, clean_for_speech
from .tts import InterruptMonitor

_EXIT_RE = re.compile(r"^(?:jarvis\s+)?(?:goodbye|good bye|bye bye|shut down|shutdown|power down|power off|"
                      r"turn off|exit|quit)(?:\s+jarvis)?(?:\s+now)?$")
_SLEEP_RE = re.compile(r"^(?:go to sleep|sleep|that's all|that is all|that'll be all|that will be all|never mind|"
                       r"nevermind|stop|cancel|nothing|be quiet|shush|quiet|thanks that's all|"
                       r"thank you that's all|no thanks|no thank you|that's it)$")

_VOICE_RULES = """
## How you're being used right now
- You are a voice assistant. Everything you write is spoken aloud by a text-to-speech voice.
- Keep replies short: usually one to three sentences. Only go longer if the user asks for detail.
- Never use markdown, bullet points, headings, emoji, tables, or code blocks. Write numbers and
  symbols the way they should be said (e.g. "about 20 degrees", not "~20°").
- Speech recognition can mishear words. If a request seems garbled, make your best guess or ask briefly.
- You can't browse the internet. If asked about live information (news, weather, prices, scores),
  say you can't check that live and offer to open a web search instead.
- It is currently {now}. The user is on a Windows laptop.

## Hidden action tags
You can trigger actions by adding these tags to your reply. They are removed before speaking,
so also say something natural (e.g. "Opening Spotify now.").
- <remember>fact</remember> : when the user shares a lasting personal fact or preference worth
  keeping between sessions (their name, job, family, likes/dislikes, goals, routines). Write it in
  the third person, e.g. <remember>The user's sister is called Maya</remember>. Don't save trivia,
  one-off requests, or facts already listed below.
- <open>app name or website</open> : open an app or website on the laptop.
- <timer seconds="300">optional reminder text</timer> : set a countdown timer.
- <search>query</search> : open a Google search in the browser.
Only use action tags when the user actually wants that action.
"""


class Assistant:
    def __init__(self, cfg, speaker, brain, memory, history, skills, timers,
                 mic=None, wake=None, stt=None, personality=""):
        self.cfg = cfg
        self.mic = mic
        self.wake = wake
        self.stt = stt
        self.speaker = speaker
        self.brain = brain
        self.memory = memory
        self.history = history
        self.skills = skills
        self.timers = timers
        self.personality = personality.strip()
        self._last_interrupt_by_voice = False

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------
    def system_prompt(self) -> str:
        now = dt.datetime.now()
        parts = [self.personality or "You are JARVIS, a helpful voice assistant."]
        parts.append(_VOICE_RULES.format(now=now.strftime("%A %d %B %Y, %I:%M %p")))
        if self.cfg.user_name:
            parts.append(f"The user's name is {self.cfg.user_name}.")
        facts = self.memory.as_text()
        parts.append("## Things you remember about the user\n" + (facts or "(nothing yet)"))
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Speaking
    # ------------------------------------------------------------------
    def _monitor(self, mode=None):
        if self.mic is None:
            return None
        return InterruptMonitor(self.mic, self.wake, mode or self.cfg.interrupt_mode,
                                self.cfg.voice_interrupt_level)

    def say(self, text: str, interruptible=True) -> bool:
        print(f"JARVIS: {text}")
        try:
            monitor = self._monitor() if interruptible else None
            interrupted = self.speaker.speak(clean_for_speech(text), monitor)
            self._after_speaking(interrupted, monitor)
            return interrupted
        except Exception as e:
            print("  [!] Couldn't speak that out loud:\n  " + explain(e))
            return False

    def _after_speaking(self, interrupted, monitor):
        if self.mic is None:
            return
        if interrupted:
            print("  (interrupted)")
            # if they interrupted by talking, their words started a moment ago - keep that audio
            self._last_interrupt_by_voice = bool(monitor and monitor.reason == "voice")
        else:
            self.mic.clear()     # throw away JARVIS's own voice picked up by the mic
            self._last_interrupt_by_voice = False

    def _reply_sentences(self, user_text, spoken):
        """Stream the AI's reply as clean sentences, running any action tags as they appear."""
        tags = TagFilter()
        splitter = SentenceSplitter()
        done_actions = 0
        first = True

        def emit(sentences):
            nonlocal first
            for s in sentences:
                s = clean_for_speech(s)
                if not s:
                    continue
                spoken.append(s)
                print(("JARVIS: " if first else "        ") + s, flush=True)
                first = False
                yield s

        for delta in self.brain.stream(self.system_prompt(), self.history.with_new(user_text)):
            clean = tags.feed(delta)
            while done_actions < len(tags.actions):
                self.skills.run_action(*tags.actions[done_actions])
                done_actions += 1
            yield from emit(splitter.feed(clean))
        yield from emit(splitter.feed(tags.flush()) + splitter.flush())
        while done_actions < len(tags.actions):
            self.skills.run_action(*tags.actions[done_actions])
            done_actions += 1
        if not spoken:
            # The model only returned action tags (or nothing) - say something anyway.
            acts = [a[0] for a in tags.actions]
            msg = "Done." if acts else "Sorry, I don't have an answer for that."
            yield from emit([msg])

    # ------------------------------------------------------------------
    # Handling one thing the user said
    # ------------------------------------------------------------------
    def respond(self, text: str) -> bool:
        """Answer the user. Returns True if they interrupted the answer."""
        try:
            reply = self.skills.handle(text)
        except Exception as e:
            reply = "Sorry, that didn't work."
            print("  [!] " + explain(e))
        if reply:
            interrupted = self.say(reply)
            self.history.add(text, reply)
            return interrupted

        spoken = []
        monitor = self._monitor()
        t0 = time.time()
        try:
            interrupted = self.speaker.speak_stream(self._reply_sentences(text, spoken), monitor)
            self._after_speaking(interrupted, monitor)
        except Exception as e:
            print("\n[X] " + explain(e) + "\n")
            if self.mic is not None:
                self.mic.clear()
            if not spoken:
                self.say("Sorry, I ran into a problem. The details are on the screen.", interruptible=False)
            return False
        if not spoken:
            print(f"  (no reply after {time.time() - t0:.1f}s)")
        record = " ".join(spoken)
        if interrupted:
            record += " [the user interrupted me here]"
        self.history.add(text, record)
        return interrupted

    @staticmethod
    def strip_wake_word(text: str) -> str:
        return re.sub(r"^\W*(?:(?:hey|ok|okay|yo)\s+)?jarvis\b\W*", "", text.strip(), flags=re.IGNORECASE)

    def classify(self, text: str):
        """'exit', 'sleep', or None for a normal request."""
        t = re.sub(r"[.!?,]", "", text.lower()).strip()
        if _EXIT_RE.match(t):
            return "exit"
        if _SLEEP_RE.match(t):
            return "sleep"
        return None

    # ------------------------------------------------------------------
    # Voice mode
    # ------------------------------------------------------------------
    def greet(self):
        hour = dt.datetime.now().hour
        part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        name = f", {self.cfg.user_name}" if self.cfg.user_name else ""
        self.say(f"Good {part}{name}. JARVIS is online.", interruptible=False)

    def announce_timers(self):
        while not self.timers.announcements.empty():
            msg = self.timers.announcements.get()
            try:
                self.speaker.play_audio(audio_mod.alarm_chime(self.speaker.sample_rate))
            except Exception:
                pass
            self.say(msg)

    def wait_for_wake(self):
        self.mic.clear()
        self.wake.reset()
        print("\n[Waiting for 'Jarvis'...]  (Ctrl+C to quit)")
        while True:
            if not self.timers.announcements.empty():
                self.announce_timers()
                self.mic.clear()
                self.wake.reset()
            frame = self.mic.read(timeout=0.3)
            if frame is None:
                continue
            self.mic.track_noise(frame)
            if self.wake.detect(frame):
                return

    def listen(self, start_timeout, preroll):
        sys.stdout.write("  Listening... ")
        sys.stdout.flush()
        audio = audio_mod.record_command(
            self.mic, self.cfg.silence_level, start_timeout=start_timeout,
            end_silence=self.cfg.end_of_speech_seconds, preroll_frames=preroll,
        )
        if audio is None:
            print("(nothing heard)")
            return None
        print("transcribing...", end=" ", flush=True)
        t0 = time.time()
        text = self.stt.transcribe(audio)
        print(f"({time.time() - t0:.1f}s)")
        return text

    def conversation(self):
        """One back-and-forth session after the wake word, including follow-ups."""
        start_timeout, preroll = 6.0, 2
        misses = 0
        while True:
            text = self.listen(start_timeout, preroll)
            if text is None:
                return
            text = self.strip_wake_word(text)
            if not text:
                misses += 1
                if misses > 1:
                    return
                self.say("Sorry, I didn't catch that.")
                start_timeout, preroll = 6.0, 0
                continue
            misses = 0
            print(f"You: {text}")
            kind = self.classify(text)
            if kind == "exit":
                self.say("Goodbye. Shutting down.", interruptible=False)
                raise SystemExit(0)
            if kind == "sleep":
                self.say("Of course.", interruptible=False)
                return
            interrupted = self.respond(text)
            if interrupted:
                start_timeout = 6.0
                preroll = 10 if self._last_interrupt_by_voice else 2
                continue
            if self.cfg.follow_up_seconds <= 0:
                return
            if not self.timers.announcements.empty():
                self.announce_timers()
            start_timeout, preroll = self.cfg.follow_up_seconds, 0

    def run_voice(self):
        self.greet()
        while True:
            self.wait_for_wake()
            print("  Wake word heard!")
            if self.cfg.chime:
                try:
                    self.speaker.play_audio(audio_mod.wake_chime(self.speaker.sample_rate))
                except Exception:
                    pass
            self.conversation()

    # ------------------------------------------------------------------
    # Text mode (type instead of talking - handy for testing)
    # ------------------------------------------------------------------
    def run_text(self):
        print("\nText mode: type a message and press Enter. Type 'exit' to quit.\n")
        while True:
            self.announce_timers()
            try:
                text = input("You: ").strip()
            except EOFError:
                return
            if not text:
                continue
            kind = self.classify(self.strip_wake_word(text))
            if kind == "exit":
                self.say("Goodbye.", interruptible=False)
                return
            if kind == "sleep":
                continue
            self.respond(self.strip_wake_word(text))
