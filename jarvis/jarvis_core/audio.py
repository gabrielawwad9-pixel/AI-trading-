"""Microphone input, volume measurement, recording a spoken command, and simple sounds."""

import collections
import math
import queue
import time

import numpy as np

SAMPLE_RATE = 16000      # what openWakeWord and Whisper expect
FRAME_SAMPLES = 1280     # 80 ms of audio per frame (what openWakeWord wants)
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE


def rms(frame: np.ndarray) -> float:
    """Loudness of an int16 audio frame (0 = silence, ~1000-6000 = normal speech near a laptop mic)."""
    if frame is None or len(frame) == 0:
        return 0.0
    f = frame.astype(np.float32)
    return float(np.sqrt(np.mean(f * f)))


def _import_sounddevice():
    import sounddevice as sd  # imported lazily so the error message can be friendly
    return sd


class Microphone:
    """Continuously captures 16 kHz mono audio in 80 ms frames on a background thread."""

    def __init__(self, device=None):
        self.sd = _import_sounddevice()
        self.device = device
        self.q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=1000)
        self.recent = collections.deque(maxlen=12)        # ~1 s of most recent audio (pre-roll)
        self._noise = collections.deque(maxlen=60)        # loudness history while idle
        self.native_rate = SAMPLE_RATE
        self._resample = None
        self.stream = None

    # -- stream management -------------------------------------------------
    def start(self):
        try:
            self._open(SAMPLE_RATE)
        except Exception as e:  # some mics refuse 16 kHz -> record at their native rate and convert
            if "sample rate" not in str(e).lower():
                raise
            info = self.sd.query_devices(self.device, "input")
            self._open(int(info["default_samplerate"]))
        return self

    def _open(self, rate):
        self.native_rate = rate
        block = FRAME_SAMPLES
        if rate != SAMPLE_RATE:
            from math import gcd
            from scipy.signal import resample_poly
            g = gcd(rate, SAMPLE_RATE)
            up, down = SAMPLE_RATE // g, rate // g
            block = FRAME_SAMPLES * down // up
            self._resample = lambda x: resample_poly(x.astype(np.float32), up, down).astype(np.int16)
        self.stream = self.sd.InputStream(
            samplerate=rate, channels=1, dtype="int16", blocksize=block,
            device=self.device, callback=self._callback,
        )
        self.stream.start()

    def _callback(self, indata, frames, time_info, status):
        data = indata[:, 0].copy()
        if self._resample is not None:
            data = self._resample(data)[:FRAME_SAMPLES]
        try:
            self.q.put_nowait(data)
        except queue.Full:
            pass

    def stop(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    # -- reading -------------------------------------------------------------
    def read(self, timeout=0.5):
        """Next 80 ms frame (int16 numpy array) or None if nothing arrived in time."""
        try:
            frame = self.q.get(timeout=timeout)
        except queue.Empty:
            return None
        self.recent.append(frame)
        return frame

    def clear(self):
        """Throw away audio that queued up (e.g. while JARVIS was busy)."""
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                break
        self.recent.clear()

    # -- background-noise tracking ---------------------------------------------
    def track_noise(self, frame):
        self._noise.append(rms(frame))

    @property
    def noise_floor(self) -> float:
        if len(self._noise) < 10:
            return 150.0
        return float(np.percentile(self._noise, 30))


def speech_threshold(mic: Microphone, silence_level: float) -> float:
    """Loudness above which we treat audio as 'someone is speaking'."""
    return max(silence_level, mic.noise_floor * 3.0)


def record_command(mic: Microphone, silence_level: float, start_timeout: float = 6.0,
                   end_silence: float = 0.9, max_seconds: float = 15.0,
                   preroll_frames: int = 4, on_level=None):
    """Record one spoken command.

    Waits up to `start_timeout` seconds for speech to begin, then stops after
    `end_silence` seconds of quiet. Returns float32 audio for Whisper, or None
    if nobody spoke.
    """
    threshold = speech_threshold(mic, silence_level)
    frames = list(mic.recent)[-preroll_frames:] if preroll_frames else []
    started = False
    loud_run = 0
    quiet_run = 0
    t0 = time.time()
    speech_frames = 0

    while True:
        frame = mic.read(timeout=0.5)
        now = time.time()
        if frame is None:
            if not started and now - t0 > start_timeout:
                return None
            continue
        level = rms(frame)
        if on_level:
            on_level(level, threshold)
        frames.append(frame)
        loud = level > threshold

        if not started:
            loud_run = loud_run + 1 if loud else 0
            if loud_run >= 2:                       # 160 ms of sound = speech has started
                started = True
                speech_frames = loud_run
            else:
                if now - t0 > start_timeout:
                    return None
                frames = frames[-(preroll_frames + 3):]  # keep only a short lead-in
            continue

        if loud:
            quiet_run = 0
            speech_frames += 1
        else:
            quiet_run += 1
        if quiet_run * FRAME_SECONDS >= end_silence:
            break
        if len(frames) * FRAME_SECONDS >= max_seconds:
            break

    if speech_frames < 3:      # just a cough / click
        return None
    audio = np.concatenate(frames).astype(np.float32) / 32768.0
    return audio


# ---------------------------------------------------------------------------
# Sounds
# ---------------------------------------------------------------------------
def tone(freqs, seconds, rate, volume=0.25):
    """A soft sine-wave tone (or a sequence of tones) as int16 audio."""
    parts = []
    for f in freqs:
        t = np.arange(int(rate * seconds)) / rate
        wave = np.sin(2 * math.pi * f * t)
        fade = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.02)  # 20 ms fade in/out, no clicks
        parts.append((wave * fade * volume * 32767).astype(np.int16))
    return np.concatenate(parts)


def wake_chime(rate=24000):
    return tone([660, 880], 0.09, rate, volume=0.18)


def alarm_chime(rate=24000):
    beep = tone([880], 0.18, rate, volume=0.3)
    gap = np.zeros(int(rate * 0.12), dtype=np.int16)
    return np.concatenate([beep, gap, beep, gap, beep])
