"""Test each part of JARVIS one at a time, with plain-English results.

    check.bat mic         1. Is the microphone working?
    check.bat voice       2. Can JARVIS speak?        (add --download-piper for the offline voice)
    check.bat wake        3. Does it hear "Jarvis"?
    check.bat stt         4. Does it understand what you say?
    check.bat brain       5. Can it think (Claude or Ollama)?
    check.bat interrupt   6. Can you interrupt it while it talks?
    check.bat all         Run 1-6 in order, stopping at the first problem.
    check.bat download    Download the wake-word + speech models (setup does this for you).
"""

import argparse
import sys
import time

from jarvis_core.config import ROOT, load_config
from jarvis_core.errors import report

PASS = "[OK]"
FAIL = "[X]"
WARN = "[!]"


def header(n, title, what):
    print("\n" + "=" * 60)
    print(f" STEP {n}: {title}")
    print("=" * 60)
    print(what + "\n")


def bar(level, scale=4000, width=40):
    filled = int(min(1.0, level / scale) * width)
    return "#" * filled + "." * (width - filled)


def wait_enter(prompt="Press Enter when you're ready..."):
    try:
        input(prompt)
    except EOFError:
        pass


# ---------------------------------------------------------------------------
def check_mic(cfg, args):
    header(1, "MICROPHONE", "Checking JARVIS can hear you. You'll speak for 5 seconds.")
    import numpy as np
    import sounddevice as sd
    from jarvis_core.audio import Microphone, rms

    print("Audio devices on this laptop:")
    devices = sd.query_devices()
    default_in, default_out = sd.default.device
    for i, d in enumerate(devices):
        kinds = []
        if d["max_input_channels"] > 0:
            kinds.append("MIC" + (" (default)" if i == default_in else ""))
        if d["max_output_channels"] > 0:
            kinds.append("SPEAKER" + (" (default)" if i == default_out else ""))
        if kinds:
            print(f"   [{i:2d}] {d['name'][:45]:45s}  {', '.join(kinds)}")
    print(f"\nUsing mic: {cfg.mic_device if cfg.mic_device is not None else 'Windows default'}"
          "   (change with MIC_DEVICE in .env)\n")

    mic = Microphone(cfg.mic_device).start()
    print("Stay quiet for 2 seconds (measuring background noise)...")
    quiet = []
    t0 = time.time()
    while time.time() - t0 < 2:
        f = mic.read(1)
        if f is not None:
            quiet.append(rms(f))
    print("Now talk normally for 5 seconds - count to ten, read something aloud...\n")
    levels, frames = [], []
    t0 = time.time()
    while time.time() - t0 < 5:
        f = mic.read(1)
        if f is None:
            continue
        lv = rms(f)
        levels.append(lv)
        frames.append(f)
        sys.stdout.write(f"\r   volume |{bar(lv)}| {int(lv):5d}")
        sys.stdout.flush()
    mic.stop()
    print("\n")

    if not levels:
        print(f"{FAIL} No audio arrived at all from the microphone.")
        print("   - Windows Settings > Privacy & security > Microphone: turn on access for desktop apps.")
        print("   - Pick a different MIC_DEVICE number from the list above.")
        return False
    noise = float(np.median(quiet)) if quiet else 0
    speech = float(np.percentile(levels, 90))
    print(f"   Background noise level: {noise:.0f}")
    print(f"   Your speaking level:    {speech:.0f}")
    good = True
    if speech < 50:
        print(f"{FAIL} The mic is recording silence. It may be muted or the wrong device.")
        print("   - Check the mute key on your keyboard (Dell: F4 or the mic key), and the volume in")
        print("     Windows Settings > System > Sound > Input. Or pick another MIC_DEVICE.")
        return False
    if speech < 300:
        print(f"{WARN} You're quite quiet. Turn up the mic in Windows Settings > System > Sound > Input,")
        print("   or move closer. JARVIS may struggle to hear you.")
        good = True
    if speech < noise * 2.5:
        print(f"{WARN} Your voice is barely louder than the background noise. Try a quieter room or")
        print("   a headset.")
    suggested = max(200, int(noise * 3), int(min(speech * 0.25, 800)))
    print(f"\n   Suggested SILENCE_LEVEL for your .env: {suggested}  (current: {cfg.silence_level:.0f})")

    if not args.no_playback:
        print("\nPlaying your recording back so you can hear how it sounds...")
        try:
            audio = np.concatenate(frames)
            sd.play(audio, 16000, device=cfg.speaker_device)
            sd.wait()
        except Exception as e:
            report(e, "playing the recording")
    print(f"\n{PASS} Microphone works!" if good else "")
    return good


# ---------------------------------------------------------------------------
def check_voice(cfg, args):
    header(2, "VOICE", "JARVIS will say a test sentence through your speakers.")
    from jarvis_core.tts import PiperVoice, Speaker, download_piper_voice, make_voice

    if args.download_piper:
        try:
            import piper  # noqa: F401
        except ImportError:
            print(f"{FAIL} Piper isn't installed. Run:  .venv\\Scripts\\pip install piper-tts")
            return False
        path = download_piper_voice(ROOT / "voices")
        print(f"{PASS} Piper voice downloaded to {path}")
        print("   To use it, set TTS_ENGINE=piper in .env (it's also used automatically if the")
        print("   online voice fails).")
        voice = PiperVoice(path)
    else:
        print(f"Engine: {cfg.tts_engine}   Voice: "
              f"{cfg.edge_voice if cfg.tts_engine == 'edge' else cfg.piper_voice}")
        voice = make_voice(cfg)
    speaker = Speaker(voice, cfg.speaker_device)
    text = "Good day. All systems are online, and I'm ready when you are."
    t0 = time.time()
    audio = speaker._synth(text)
    print(f"   Voice generated in {time.time() - t0:.1f}s. Playing now...")
    speaker.play_audio(audio)
    try:
        ans = input("\nDid you hear JARVIS speak? (y/n): ").strip().lower()
    except EOFError:
        ans = "y"
    if ans.startswith("n"):
        print(f"{FAIL} The voice was generated but you didn't hear it. Check:")
        print("   - Laptop volume isn't muted (and headphones aren't plugged in somewhere else).")
        print("   - Set SPEAKER_DEVICE in .env to the right number from  check.bat mic")
        return False
    print(f"{PASS} Voice works!")
    print("   Want a different voice? Set EDGE_VOICE in .env, e.g. en-GB-ThomasNeural, en-US-GuyNeural,")
    print("   en-US-AndrewNeural, en-GB-SoniaNeural (female). Make it slower/faster with EDGE_RATE.")
    return True


# ---------------------------------------------------------------------------
def check_wake(cfg, args):
    header(3, "WAKE WORD", "For the next 30 seconds, say \"Jarvis\" (or \"Hey Jarvis\") a few times,\n"
           "pausing a couple of seconds between each. Watch the score bar jump.")
    from jarvis_core.audio import Microphone
    from jarvis_core.wakeword import WakeWordDetector

    wake = WakeWordDetector(cfg.wake_word_model, cfg.wake_threshold)
    mic = Microphone(cfg.mic_device).start()
    wait_enter()
    mic.clear()
    hits, peak = 0, 0.0
    peaks = []
    current_peak = 0.0
    t0 = time.time()
    while time.time() - t0 < 30:
        f = mic.read(1)
        if f is None:
            continue
        triggered = wake.detect(f)
        s = wake.last_score
        peak = max(peak, s)
        current_peak = max(current_peak, s)
        if s < 0.05 and current_peak > 0.1:
            peaks.append(current_peak)
            current_peak = 0.0
        left = 30 - int(time.time() - t0)
        sys.stdout.write(f"\r   score |{bar(s, 1.0)}| {s:.2f}   detections: {hits}   ({left:2d}s left) ")
        sys.stdout.flush()
        if triggered:
            hits += 1
            sys.stdout.write("  <-- JARVIS heard you!\n")
    mic.stop()
    print("\n")
    print(f"   Detections: {hits}    Highest score: {peak:.2f}    Threshold: {cfg.wake_threshold}")
    if hits == 0:
        if peak >= 0.15:
            suggestion = max(0.1, round(peak * 0.7, 2))
            print(f"{FAIL} It almost heard you (best score {peak:.2f}) but didn't reach the threshold.")
            print(f"   Fix: set WAKE_THRESHOLD={suggestion} in .env and run this test again.")
            print("   Tip: the built-in model is trained on \"Hey Jarvis\" - saying that is more reliable.")
        else:
            print(f"{FAIL} It never heard the wake word. Check step 1 (mic) passes, speak a bit louder,")
            print("   and try saying \"Hey Jarvis\" clearly.")
        return False
    print(f"{PASS} Wake word works!")
    print("   If it triggers on its own later (TV, music), raise WAKE_THRESHOLD (e.g. 0.6-0.7).")
    return True


# ---------------------------------------------------------------------------
def check_stt(cfg, args):
    header(4, "SPEECH RECOGNITION", "After you press Enter, say a sentence, like:\n"
           "   \"What's the weather usually like in London in spring?\"\n"
           "JARVIS stops recording when you pause.")
    from jarvis_core.audio import Microphone, record_command
    from jarvis_core.stt import SpeechToText

    print(f"Loading speech model '{cfg.whisper_model}' (first time downloads it - can take a minute)...")
    t0 = time.time()
    stt = SpeechToText(cfg.whisper_model, cfg.whisper_device)
    print(f"   loaded in {time.time() - t0:.1f}s")
    mic = Microphone(cfg.mic_device).start()
    # learn the room's noise level first
    t0 = time.time()
    while time.time() - t0 < 1.0:
        f = mic.read(1)
        if f is not None:
            mic.track_noise(f)
    wait_enter()
    mic.clear()
    print("   Speak now...")
    audio = record_command(mic, cfg.silence_level, start_timeout=8,
                           end_silence=cfg.end_of_speech_seconds, preroll_frames=3)
    mic.stop()
    if audio is None:
        print(f"{FAIL} I didn't hear any speech. Re-run step 1 and check SILENCE_LEVEL in .env -")
        print("   if it's higher than your speaking level, lower it.")
        return False
    print(f"   Recorded {len(audio) / 16000:.1f}s of speech. Transcribing...")
    t0 = time.time()
    text = stt.transcribe(audio)
    took = time.time() - t0
    print(f"\n   JARVIS heard: \"{text}\"   ({took:.1f}s)\n")
    if not text:
        print(f"{FAIL} Nothing understandable came through. Speak clearly and a bit closer to the mic.")
        return False
    if took > 4:
        print(f"{WARN} That was slow. For quicker replies set WHISPER_MODEL=tiny.en in .env.")
    print(f"{PASS} Speech recognition works! (If it's often wrong, try WHISPER_MODEL=small.en - more")
    print("   accurate but slower.)")
    return True


# ---------------------------------------------------------------------------
def check_brain(cfg, args):
    header(5, "BRAIN", f"Asking {cfg.llm_provider} a quick question.")
    from jarvis_core.brain import make_brain

    brain = make_brain(cfg)
    personality = cfg.personality_file.read_text(encoding="utf-8")
    t0 = time.time()
    first = None
    out = []
    print("   JARVIS: ", end="", flush=True)
    for delta in brain.stream(personality + "\nReply in one short sentence.",
                              [{"role": "user", "content": "Introduce yourself in one sentence."}]):
        if first is None:
            first = time.time() - t0
        out.append(delta)
        print(delta, end="", flush=True)
    print("\n")
    if not "".join(out).strip():
        print(f"{FAIL} The brain replied with nothing. Try again, or try a different model.")
        return False
    print(f"   First words after {first:.1f}s, full reply in {time.time() - t0:.1f}s.")
    print(f"{PASS} Brain works! (model: {brain.model})")
    return True


# ---------------------------------------------------------------------------
def check_interrupt(cfg, args):
    header(6, "INTERRUPTING", "JARVIS will talk for a while. Part 1: stay QUIET for the first few\n"
           "seconds so it can measure how loud its own voice is in the mic. Part 2: when\n"
           "you see 'TALK NOW', interrupt it - say \"Jarvis, stop\" or just start talking.")
    from jarvis_core.audio import Microphone, rms
    from jarvis_core.tts import InterruptMonitor, Speaker, make_voice
    from jarvis_core.wakeword import WakeWordDetector

    speaker = Speaker(make_voice(cfg), cfg.speaker_device)
    wake = WakeWordDetector(cfg.wake_word_model, cfg.wake_threshold)
    mic = Microphone(cfg.mic_device).start()
    long_text = ("This is a test of the interruption system. I am going to keep talking for quite a "
                 "while, so that you have plenty of time to cut me off. The quick brown fox jumps over "
                 "the lazy dog. Meanwhile, I am measuring how loud my own voice sounds in your "
                 "microphone, so that I don't accidentally interrupt myself. Go ahead and interrupt me "
                 "whenever you are ready. I will just keep going until you do, or until I run out of "
                 "things to say, which may take a little while longer still.")
    audio = speaker._synth(long_text)
    wait_enter()

    class Measuring(InterruptMonitor):
        echo = []
        started = time.time()
        announced = False

        def check(self):
            elapsed = time.time() - self.started
            if elapsed < 4:
                while True:
                    f = self.mic.read(timeout=0)
                    if f is None:
                        return False
                    self.echo.append(rms(f))
            if not self.announced:
                self.announced = True
                print("\n   >>> TALK NOW - interrupt me! <<<\n")
            return super().check()

    mon = Measuring(mic, wake, "both", cfg.voice_interrupt_level)
    mon.started = time.time()
    t0 = time.time()
    interrupted = speaker.play_audio(audio, mon)
    mic.stop()
    import numpy as np
    echo_peak = float(np.percentile(mon.echo, 95)) if mon.echo else 0.0
    print(f"   JARVIS's own voice in the mic: about {echo_peak:.0f}")
    suggested = int(max(1500, echo_peak * 1.6))
    if interrupted:
        how = "the wake word" if mon.reason == "wake" else "your voice"
        print(f"{PASS} You interrupted it after {time.time() - t0:.1f}s (detected by {how}).")
    else:
        print(f"{WARN} It wasn't interrupted.")
        print("   - Saying \"Jarvis\" clearly should always work (INTERRUPT_MODE=both or wakeword).")
    print(f"\n   Suggested VOICE_INTERRUPT_LEVEL for .env: {suggested}  (current: {cfg.voice_interrupt_level:.0f})")
    if echo_peak > 3000:
        print(f"{WARN} Your speakers are loud in the mic, so JARVIS may interrupt itself. Options:")
        print("   - Use headphones (best), lower the volume, or set INTERRUPT_MODE=wakeword so only")
        print("     saying \"Jarvis\" interrupts it.")
    return True


# ---------------------------------------------------------------------------
def download(cfg, args):
    print("Downloading models (one time only, ~160 MB total)...")
    from jarvis_core.wakeword import download_wake_models
    print(" - wake word model")
    download_wake_models(cfg.wake_word_model)
    print(f" - speech recognition model ({cfg.whisper_model})")
    from faster_whisper import WhisperModel
    WhisperModel(cfg.whisper_model, device="cpu", compute_type="int8")
    print(f"{PASS} Models downloaded.")
    return True


STEPS = {
    "mic": check_mic, "voice": check_voice, "wake": check_wake, "stt": check_stt,
    "brain": check_brain, "interrupt": check_interrupt, "download": download,
}


def main():
    p = argparse.ArgumentParser(description="Test JARVIS step by step.")
    p.add_argument("step", nargs="?", default="all", choices=list(STEPS) + ["all"])
    p.add_argument("--download-piper", action="store_true", help="download the offline Piper voice")
    p.add_argument("--no-playback", action="store_true", help="don't play the mic recording back")
    p.add_argument("--debug", action="store_true", help="show technical error details")
    args = p.parse_args()
    cfg = load_config()

    order = ["mic", "voice", "wake", "stt", "brain", "interrupt"] if args.step == "all" else [args.step]
    for name in order:
        try:
            passed = STEPS[name](cfg, args)
        except KeyboardInterrupt:
            print("\nStopped.")
            return 1
        except Exception as e:
            report(e, f"step '{name}'", show_trace=args.debug)
            passed = False
        if not passed:
            print(f"\nFix the problem above, then run:  check.bat {name}")
            return 1
    if args.step == "all":
        print("\nAll checks passed! Start JARVIS with:  start_jarvis.bat")
    return 0


if __name__ == "__main__":
    sys.exit(main())
