"""JARVIS - your personal voice assistant.

Start it with:   start_jarvis.bat        (or:  python jarvis.py)
Options:
    --text     type instead of talking (no microphone needed)
    --quiet    don't speak out loud, just print replies (use with --text)
    --debug    show full technical error details
"""

import argparse
import sys

from jarvis_core.config import load_config
from jarvis_core.errors import report


def step(label):
    print(f"  - {label}...", end=" ", flush=True)


def ok(extra=""):
    print("OK" + (f" ({extra})" if extra else ""))


def main():
    parser = argparse.ArgumentParser(description="JARVIS voice assistant")
    parser.add_argument("--text", action="store_true", help="type instead of talking")
    parser.add_argument("--quiet", action="store_true", help="don't speak replies out loud")
    parser.add_argument("--debug", action="store_true", help="show technical error details")
    args = parser.parse_args()

    print("=" * 56)
    print("  J.A.R.V.I.S.  starting up")
    print("=" * 56)
    cfg = load_config()

    current = "loading settings"
    try:
        current = "personality.txt"
        step("Loading personality")
        personality = cfg.personality_file.read_text(encoding="utf-8")
        ok()

        current = "memory"
        from jarvis_core.memory import ConversationHistory, LongTermMemory
        from jarvis_core.skills import Skills, Timers
        step("Loading memory")
        memory = LongTermMemory(cfg.memory_file)
        ok(f"{len(memory.facts)} facts about you")

        current = "the AI brain"
        from jarvis_core.brain import make_brain
        step(f"Connecting brain ({cfg.llm_provider})")
        brain = make_brain(cfg)
        ok(getattr(brain, "model", ""))

        current = "the voice"
        from jarvis_core.tts import PiperVoice, Speaker, make_voice
        step(f"Preparing voice ({cfg.tts_engine})")
        speaker = None
        if not (args.text and args.quiet):
            voice = make_voice(cfg)

            def fallback():
                if cfg.tts_engine != "edge":
                    return None
                try:
                    return PiperVoice(cfg.piper_voice)
                except Exception:
                    return None

            speaker = Speaker(voice, cfg.speaker_device, fallback_voice_factory=fallback)
        else:
            speaker = _SilentSpeaker()
        if args.quiet and speaker is not None:
            speaker.muted = True
        ok()

        mic = wake = stt = None
        if not args.text:
            current = "the microphone"
            from jarvis_core.audio import Microphone
            step("Opening microphone")
            mic = Microphone(cfg.mic_device).start()
            ok()

            current = "the wake word"
            from jarvis_core.wakeword import WakeWordDetector
            step("Loading wake word")
            wake = WakeWordDetector(cfg.wake_word_model, cfg.wake_threshold)
            ok(f"threshold {cfg.wake_threshold}")

            current = "speech recognition"
            from jarvis_core.stt import SpeechToText
            step(f"Loading speech recognition ({cfg.whisper_model})")
            stt = SpeechToText(cfg.whisper_model, cfg.whisper_device)
            ok()

        from jarvis_core.assistant import Assistant
        timers = Timers()
        assistant = Assistant(
            cfg, speaker, brain, memory, ConversationHistory(), Skills(memory, timers), timers,
            mic=mic, wake=wake, stt=stt, personality=personality,
        )
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 1
    except Exception as e:
        print("FAILED")
        report(e, current, show_trace=args.debug)
        _pause_hint()
        return 1

    try:
        if args.text:
            assistant.run_text()
        else:
            assistant.run_voice()
    except KeyboardInterrupt:
        print("\nShutting down. Goodbye!")
    except SystemExit:
        pass
    except Exception as e:
        report(e, "while running", show_trace=args.debug)
        _pause_hint()
        return 1
    finally:
        if mic is not None:
            mic.stop()
    return 0


class _SilentSpeaker:
    """Used for --text --quiet: prints replies, never touches the speakers."""
    sample_rate = 24000
    muted = True

    def speak_stream(self, sentences, monitor=None, prelude=(), rate=None):
        for _ in sentences:
            pass
        return False

    def speak(self, text, monitor=None):
        return False

    def play_audio(self, audio, monitor=None, rate=None):
        return False


def _pause_hint():
    print("Tip: run  check.bat  to test each part (mic, wake word, voice...) one at a time.")


if __name__ == "__main__":
    sys.exit(main())
