"""Text-to-speech (edge-tts online voice or Piper offline voice) and interruptible playback."""

import asyncio
import queue
import threading
import time
from pathlib import Path

import numpy as np

from .audio import FRAME_SECONDS, rms

PIPER_VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/medium/"
PIPER_VOICE_FILE = "en_GB-alan-medium.onnx"


# ---------------------------------------------------------------------------
# Voice engines: each turns text into (int16 numpy audio, sample_rate)
# ---------------------------------------------------------------------------
class EdgeVoice:
    """Microsoft's natural online voices (free, needs internet). Default: calm British 'Ryan'."""

    sample_rate = 24000

    def __init__(self, voice="en-GB-RyanNeural", rate="-5%"):
        import edge_tts  # noqa: F401  (fail early if missing)
        import miniaudio  # noqa: F401
        self.voice = voice
        self.rate = rate

    def synthesize(self, text: str) -> np.ndarray:
        import edge_tts
        import miniaudio

        async def _get_mp3():
            data = bytearray()
            comm = edge_tts.Communicate(text, self.voice, rate=self.rate)
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    data.extend(chunk["data"])
            return bytes(data)

        mp3 = asyncio.run(_get_mp3())
        if not mp3:
            return np.zeros(0, dtype=np.int16)
        decoded = miniaudio.decode(
            mp3, output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1, sample_rate=self.sample_rate,
        )
        return np.frombuffer(decoded.samples, dtype=np.int16).copy()


class PiperVoice:
    """Fully offline neural voice. Needs `pip install piper-tts` and a voice file."""

    def __init__(self, model_path):
        if not Path(model_path).exists():
            raise FileNotFoundError(model_path)
        from piper import PiperVoice as _Piper
        self.voice = _Piper.load(str(model_path))
        self.sample_rate = self.voice.config.sample_rate

    def synthesize(self, text: str) -> np.ndarray:
        if hasattr(self.voice, "synthesize_stream_raw"):         # piper-tts 1.2.x
            raw = b"".join(self.voice.synthesize_stream_raw(text))
        else:                                                   # piper-tts 1.3+
            raw = b"".join(chunk.audio_int16_bytes for chunk in self.voice.synthesize(text))
        return np.frombuffer(raw, dtype=np.int16).copy()


def download_piper_voice(dest_dir: Path):
    import requests
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in (PIPER_VOICE_FILE, PIPER_VOICE_FILE + ".json"):
        target = dest_dir / name
        if target.exists():
            continue
        print(f"  Downloading {name} ...")
        r = requests.get(PIPER_VOICE_URL + name + "?download=true", timeout=60, stream=True)
        r.raise_for_status()
        tmp = target.with_suffix(target.suffix + ".part")
        with open(tmp, "wb") as f:
            for block in r.iter_content(1 << 16):
                f.write(block)
        tmp.replace(target)
    return dest_dir / PIPER_VOICE_FILE


def make_voice(cfg):
    """Create the configured voice, falling back to the other engine if possible."""
    if cfg.tts_engine == "piper":
        return PiperVoice(cfg.piper_voice)
    return EdgeVoice(cfg.edge_voice, cfg.edge_rate)


# ---------------------------------------------------------------------------
# Interruption detection while JARVIS is talking
# ---------------------------------------------------------------------------
class InterruptMonitor:
    """Watches the mic during playback. Interrupt by saying "Jarvis" or (optionally) just talking."""

    def __init__(self, mic, wake, mode="both", voice_level=2500):
        self.mic = mic
        self.wake = wake
        self.mode = mode if mic is not None else "off"
        self.voice_level = voice_level
        self.loud_run = 0
        self.t0 = time.time()
        self.peak_echo = 0.0
        self.reason = None          # "wake" or "voice" once interrupted
        if self.mic is not None:
            self.mic.clear()
        if self.wake is not None:
            self.wake.reset()

    def check(self) -> bool:
        if self.mode == "off":
            return False
        while True:
            frame = self.mic.read(timeout=0)
            if frame is None:
                return False
            if self.mode in ("wakeword", "both") and self.wake is not None:
                if self.wake.detect(frame):
                    self.reason = "wake"
                    return True
            if self.mode in ("voice", "both"):
                level = rms(frame)
                self.peak_echo = max(self.peak_echo, level)
                if time.time() - self.t0 < 0.4:   # ignore the first moment of playback
                    continue
                self.loud_run = self.loud_run + 1 if level > self.voice_level else 0
                if self.loud_run * FRAME_SECONDS >= 0.4:  # ~0.4 s of you talking over it
                    self.reason = "voice"
                    return True


# ---------------------------------------------------------------------------
# Speaker: plays a stream of sentences, synthesizing the next while the current one plays
# ---------------------------------------------------------------------------
_DONE = object()


class Speaker:
    def __init__(self, voice, device=None, fallback_voice_factory=None):
        import sounddevice as sd
        self.sd = sd
        self.voice = voice
        self.device = device
        self.fallback_voice_factory = fallback_voice_factory
        self.muted = False
        self.sample_rate = voice.sample_rate   # playback rate stays fixed even if the voice changes

    def _synth(self, text):
        audio = self._synth_raw(text)
        if self.voice.sample_rate != self.sample_rate:
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(self.voice.sample_rate, self.sample_rate)
            audio = resample_poly(audio.astype(np.float32), self.sample_rate // g,
                                  self.voice.sample_rate // g).clip(-32768, 32767).astype(np.int16)
        return audio

    def _synth_raw(self, text):
        try:
            return self.voice.synthesize(text)
        except Exception:
            if self.fallback_voice_factory is None:
                raise
            fallback = self.fallback_voice_factory()
            if fallback is None:
                raise
            print("  (Online voice failed - switching to the offline Piper voice.)")
            self.voice = fallback
            self.fallback_voice_factory = None
            return self.voice.synthesize(text)

    def play_audio(self, audio: np.ndarray, monitor: InterruptMonitor = None, rate=None) -> bool:
        """Play int16 audio. Returns True if interrupted."""
        return self.speak_stream(iter(()), monitor, prelude=[audio], rate=rate)

    def speak(self, text: str, monitor: InterruptMonitor = None) -> bool:
        return self.speak_stream(iter([text]), monitor)

    def speak_stream(self, sentences, monitor: InterruptMonitor = None, prelude=(), rate=None) -> bool:
        """Speak sentences from an iterator (which may still be streaming from the LLM).

        Returns True if the user interrupted.
        """
        if self.muted:
            for s in sentences:
                pass
            return False

        audio_q: "queue.Queue" = queue.Queue(maxsize=4)
        stop = threading.Event()

        def producer():
            try:
                for sentence in sentences:
                    if stop.is_set():
                        break
                    if not sentence.strip():
                        continue
                    audio = self._synth(sentence)
                    while not stop.is_set():
                        try:
                            audio_q.put(audio, timeout=0.1)
                            break
                        except queue.Full:
                            continue
            except Exception as e:  # pass errors to the playing thread
                audio_q.put(e)
            finally:
                audio_q.put(_DONE)

        worker = threading.Thread(target=producer, daemon=True)
        for a in prelude:
            audio_q.put(a)
        worker.start()

        rate = rate or self.sample_rate
        block = int(rate * 0.05)
        interrupted = False
        error = None
        with self.sd.OutputStream(samplerate=rate, channels=1, dtype="int16", device=self.device) as out:
            while True:
                try:
                    item = audio_q.get(timeout=0.1)
                except queue.Empty:
                    if monitor and monitor.check():
                        interrupted = True
                        break
                    continue
                if item is _DONE:
                    break
                if isinstance(item, Exception):
                    error = item
                    break
                for i in range(0, len(item), block):
                    if monitor and monitor.check():
                        interrupted = True
                        break
                    out.write(item[i:i + block])
                if interrupted:
                    break
            if interrupted:
                out.abort()
            else:
                # let the last bit of audio finish, still listening for interruptions
                end = time.time() + out.latency + 0.1
                while time.time() < end:
                    if monitor and monitor.check():
                        interrupted = True
                        out.abort()
                        break
                    time.sleep(0.02)
        stop.set()
        if error is not None:
            raise error
        return interrupted
