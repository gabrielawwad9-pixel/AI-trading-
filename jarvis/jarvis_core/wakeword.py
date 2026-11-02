"""Wake-word detection with openWakeWord (runs fully offline)."""

import numpy as np


def download_wake_models(model_name="hey_jarvis"):
    """Download the wake-word model files (only needed once, ~5 MB)."""
    from openwakeword.utils import download_models
    download_models(model_names=[model_name])


class WakeWordDetector:
    """Feed it 80 ms frames; it tells you when it hears "Jarvis".

    openWakeWord's ready-made model is trained on "Hey Jarvis", but it usually
    fires on a clear "Jarvis" too. If it misses you, lower WAKE_THRESHOLD
    (e.g. 0.3); if it triggers by itself, raise it (e.g. 0.7).
    """

    def __init__(self, model_name="hey_jarvis", threshold=0.5):
        from openwakeword.model import Model

        self.threshold = threshold
        self.last_score = 0.0
        self._cooldown = 0
        model_ref = model_name
        try:
            self.model = Model(wakeword_models=[model_ref], inference_framework="onnx")
        except Exception as e:
            # First run: model files aren't downloaded yet -> fetch and retry once.
            if model_name.endswith((".onnx", ".tflite")):
                raise
            print("  Downloading wake-word model (one time only)...")
            download_wake_models(model_name)
            try:
                self.model = Model(wakeword_models=[model_ref], inference_framework="onnx")
            except Exception:
                raise e

    def score(self, frame: np.ndarray) -> float:
        scores = self.model.predict(frame)
        self.last_score = max(scores.values()) if scores else 0.0
        return self.last_score

    def detect(self, frame: np.ndarray) -> bool:
        s = self.score(frame)
        if self._cooldown > 0:
            self._cooldown -= 1
            return False
        if s >= self.threshold:
            self.reset()
            self._cooldown = 12  # ignore ~1 s afterwards so one "Jarvis" = one trigger
            return True
        return False

    def reset(self):
        self.model.reset()
