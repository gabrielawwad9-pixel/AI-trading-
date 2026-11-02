"""Tests recording, end-of-speech detection and interruption using a simulated sound card.

No real microphone/speaker is needed: a fake 'sounddevice' module plays scripted audio
into the mic and records what would have gone to the speakers.
"""

import sys
import threading
import time
import types
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SPEED = 8.0   # run the simulation 8x faster than real time


def loud(seconds, level=3000, rate=16000):
    rng = np.random.default_rng(0)
    return (rng.standard_normal(int(seconds * rate)) * level).astype(np.int16)


def quiet(seconds, rate=16000):
    return np.zeros(int(seconds * rate), dtype=np.int16)


def make_fake_sd(mic_clip):
    sd = types.ModuleType("sounddevice")

    class InputStream:
        def __init__(self, samplerate, channels, dtype, blocksize, device, callback):
            self.cb, self.block, self.rate = callback, blocksize, samplerate
            self.running = False

        def start(self):
            self.running = True

            def feed():
                clip = np.concatenate([mic_clip, quiet(30)])
                for i in range(0, len(clip) - self.block, self.block):
                    if not self.running:
                        return
                    self.cb(clip[i:i + self.block].reshape(-1, 1), self.block, None, None)
                    time.sleep(self.block / self.rate / SPEED)
            threading.Thread(target=feed, daemon=True).start()

        def stop(self):
            self.running = False

        def close(self):
            pass

    class OutputStream:
        written = []
        aborted = False

        def __init__(self, samplerate, channels, dtype, device=None):
            self.rate = samplerate
            self.latency = 0.01
            OutputStream.written = []
            OutputStream.aborted = False

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def write(self, data):
            OutputStream.written.append(len(data))
            time.sleep(len(data) / self.rate / SPEED)

        def abort(self):
            OutputStream.aborted = True

    sd.InputStream = InputStream
    sd.OutputStream = OutputStream
    sd.query_devices = lambda *a, **k: {"default_samplerate": 16000}
    return sd


class ToneVoice:
    sample_rate = 24000

    def synthesize(self, text):
        return (np.sin(np.arange(int(24000 * 0.5 * len(text.split()))) / 10) * 8000).astype(np.int16)


class TestAudioSimulation(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get("sounddevice")

    def tearDown(self):
        if self._saved is not None:
            sys.modules["sounddevice"] = self._saved
        else:
            sys.modules.pop("sounddevice", None)

    def _patch_time(self):
        """record_command / monitor use wall-clock time; scale it to the simulation speed."""
        import jarvis_core.audio as audio_mod
        import jarvis_core.tts as tts_mod
        real = time.time
        start = real()
        fake_time = types.SimpleNamespace(time=lambda: start + (real() - start) * SPEED, sleep=time.sleep)
        audio_mod.time = fake_time
        tts_mod.time = fake_time
        self.addCleanup(setattr, audio_mod, "time", time)
        self.addCleanup(setattr, tts_mod, "time", time)

    def test_record_command_endpointing(self):
        clip = np.concatenate([quiet(1.0), loud(1.5), quiet(3.0)])
        sys.modules["sounddevice"] = make_fake_sd(clip)
        self._patch_time()
        from jarvis_core.audio import Microphone, record_command
        mic = Microphone().start()
        audio = record_command(mic, silence_level=400, start_timeout=5, end_silence=0.9)
        mic.stop()
        self.assertIsNotNone(audio)
        secs = len(audio) / 16000
        self.assertTrue(1.5 <= secs <= 3.3, f"recorded {secs:.2f}s")

    def test_record_command_nobody_speaks(self):
        sys.modules["sounddevice"] = make_fake_sd(quiet(5))
        self._patch_time()
        from jarvis_core.audio import Microphone, record_command
        mic = Microphone().start()
        self.assertIsNone(record_command(mic, silence_level=400, start_timeout=1.5))
        mic.stop()

    def test_speech_plays_fully_without_interruption(self):
        fake = make_fake_sd(quiet(10))
        sys.modules["sounddevice"] = fake
        self._patch_time()
        from jarvis_core.audio import Microphone
        from jarvis_core.tts import InterruptMonitor, Speaker
        mic = Microphone().start()
        sp = Speaker(ToneVoice())
        mon = InterruptMonitor(mic, None, "voice", 2500)
        interrupted = sp.speak_stream(iter(["one two three four", "five six"]), mon)
        mic.stop()
        self.assertFalse(interrupted)
        self.assertFalse(fake.OutputStream.aborted)
        self.assertEqual(sum(fake.OutputStream.written), 24000 * 0.5 * 6)

    def test_talking_over_jarvis_interrupts(self):
        fake = make_fake_sd(np.concatenate([quiet(1.0), loud(3.0)]))
        sys.modules["sounddevice"] = fake
        self._patch_time()
        from jarvis_core.audio import Microphone
        from jarvis_core.tts import InterruptMonitor, Speaker
        mic = Microphone().start()
        sp = Speaker(ToneVoice())
        mon = InterruptMonitor(mic, None, "voice", 2500)
        interrupted = sp.speak_stream(iter(["word " * 20]), mon)   # 10 s of speech
        mic.stop()
        self.assertTrue(interrupted)
        self.assertEqual(mon.reason, "voice")
        self.assertTrue(fake.OutputStream.aborted)
        played = sum(fake.OutputStream.written) / 24000
        self.assertLess(played, 3.0, f"played {played:.1f}s before stopping")

    def test_echo_below_level_does_not_interrupt(self):
        fake = make_fake_sd(loud(10, level=1200))   # JARVIS's own voice leaking into the mic
        sys.modules["sounddevice"] = fake
        self._patch_time()
        from jarvis_core.audio import Microphone
        from jarvis_core.tts import InterruptMonitor, Speaker
        mic = Microphone().start()
        mon = InterruptMonitor(mic, None, "voice", 2500)
        self.assertFalse(Speaker(ToneVoice()).speak_stream(iter(["a b c d"]), mon))
        mic.stop()

    def test_tts_error_is_reported(self):
        sys.modules["sounddevice"] = make_fake_sd(quiet(2))

        class BrokenVoice(ToneVoice):
            def synthesize(self, text):
                raise ConnectionError("no internet")

        from jarvis_core.tts import Speaker
        with self.assertRaises(ConnectionError):
            Speaker(BrokenVoice()).speak("hello")

    def test_fallback_voice_with_different_rate(self):
        fake = make_fake_sd(quiet(2))
        sys.modules["sounddevice"] = fake

        class BrokenVoice(ToneVoice):
            def synthesize(self, text):
                raise ConnectionError("no internet")

        class Piperish(ToneVoice):
            sample_rate = 22050

            def synthesize(self, text):
                return np.zeros(22050, dtype=np.int16)   # 1 second

        from jarvis_core.tts import Speaker
        sp = Speaker(BrokenVoice(), fallback_voice_factory=lambda: Piperish())
        sp.speak("hello")
        self.assertAlmostEqual(sum(fake.OutputStream.written), 24000, delta=10)  # still 1 s at 24 kHz


if __name__ == "__main__":
    unittest.main()
