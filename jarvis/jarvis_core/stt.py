"""Speech-to-text with faster-whisper (runs locally on your laptop)."""

import re

# Phrases Whisper sometimes "hears" in background noise. Ignore them if they're all we got.
_HALLUCINATIONS = {
    "", "you", "thank you", "thanks", "thank you very much", "thanks for watching",
    "thank you for watching", "bye", "okay", "uh", "um", "hmm", "so",
}


class SpeechToText:
    def __init__(self, model_size="base.en", device="cpu"):
        from faster_whisper import WhisperModel

        compute_type = "float16" if device == "cuda" else "int8"
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self.language = "en" if model_size.endswith(".en") else None

    def transcribe(self, audio) -> str:
        """audio: float32 numpy array at 16 kHz. Returns the text (may be empty)."""
        segments, _info = self.model.transcribe(
            audio,
            language=self.language or "en",
            beam_size=1,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text.strip() for seg in segments if seg.no_speech_prob < 0.8).strip()
        bare = re.sub(r"[^a-z ]", "", text.lower()).strip()
        if bare in _HALLUCINATIONS and len(audio) < 16000 * 2.5:
            return ""
        return text
