"""Loads settings from the .env file (with sensible defaults for everything)."""

import os
from dataclasses import dataclass
from pathlib import Path

# The folder that contains jarvis.py, personality.txt, .env, etc.
ROOT = Path(__file__).resolve().parent.parent


def _load_env_file():
    env_path = ROOT / ".env"
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(env_path, override=False)
    # The trading bot's .env (one folder up) can hold the Robinhood login, so you only enter it once.
    parent_env = ROOT.parent / ".env"
    if parent_env.exists():
        load_dotenv(parent_env, override=False)


def _get(name, default=""):
    value = os.getenv(name)
    if value is None:
        return default
    # Allow inline comments like:  WAKE_THRESHOLD=0.5   # lower = more sensitive
    value = value.split(" #")[0].strip().strip('"').strip("'")
    return value if value != "" else default


def _get_float(name, default):
    try:
        return float(_get(name, default))
    except ValueError:
        return float(default)


def _get_int(name, default):
    try:
        return int(float(_get(name, default)))
    except ValueError:
        return int(default)


def _get_device(name):
    """Audio device: blank = system default, a number = device index, text = part of the name."""
    raw = _get(name, "")
    if raw == "":
        return None
    return int(raw) if raw.isdigit() else raw


@dataclass
class Config:
    # Brain
    llm_provider: str
    anthropic_api_key: str
    claude_model: str
    ollama_model: str
    ollama_url: str
    max_reply_tokens: int
    # Ears
    whisper_model: str
    whisper_device: str
    wake_word_model: str
    wake_threshold: float
    mic_device: object
    silence_level: float
    end_of_speech_seconds: float
    follow_up_seconds: float
    # Mouth
    tts_engine: str
    edge_voice: str
    edge_rate: str
    piper_voice: str
    speaker_device: object
    chime: bool
    # Interruptions
    interrupt_mode: str
    voice_interrupt_level: float
    # You
    user_name: str
    # Trading
    trading_enabled: bool
    trading_mode: str
    max_order_usd: float
    paper_starting_cash: float
    market_data: str
    alert_check_seconds: float
    robinhood_username: str
    robinhood_password: str
    robinhood_totp: str
    # Files
    personality_file: Path
    memory_file: Path


def load_config() -> Config:
    _load_env_file()
    piper_voice = _get("PIPER_VOICE", "voices/en_GB-alan-medium.onnx")
    if not Path(piper_voice).is_absolute():
        piper_voice = str(ROOT / piper_voice)
    return Config(
        llm_provider=_get("LLM_PROVIDER", "claude").lower(),
        anthropic_api_key=_get("ANTHROPIC_API_KEY", ""),
        claude_model=_get("CLAUDE_MODEL", "claude-sonnet-5-5"),
        ollama_model=_get("OLLAMA_MODEL", "llama3.2"),
        ollama_url=_get("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        max_reply_tokens=_get_int("MAX_REPLY_TOKENS", 400),
        whisper_model=_get("WHISPER_MODEL", "base.en"),
        whisper_device=_get("WHISPER_DEVICE", "cpu").lower(),
        wake_word_model=_get("WAKE_WORD_MODEL", "hey_jarvis"),
        wake_threshold=_get_float("WAKE_THRESHOLD", 0.5),
        mic_device=_get_device("MIC_DEVICE"),
        silence_level=_get_float("SILENCE_LEVEL", 400),
        end_of_speech_seconds=_get_float("END_OF_SPEECH_SECONDS", 0.9),
        follow_up_seconds=_get_float("FOLLOW_UP_SECONDS", 5),
        tts_engine=_get("TTS_ENGINE", "edge").lower(),
        edge_voice=_get("EDGE_VOICE", "en-GB-RyanNeural"),
        edge_rate=_get("EDGE_RATE", "-5%"),
        piper_voice=piper_voice,
        speaker_device=_get_device("SPEAKER_DEVICE"),
        chime=_get("CHIME", "on").lower() in ("on", "true", "yes", "1"),
        interrupt_mode=_get("INTERRUPT_MODE", "both").lower(),
        voice_interrupt_level=_get_float("VOICE_INTERRUPT_LEVEL", 2500),
        user_name=_get("USER_NAME", ""),
        trading_enabled=_get("TRADING", "on").lower() in ("on", "true", "yes", "1"),
        trading_mode="live" if _get("TRADING_MODE", "paper").lower() == "live" else "paper",
        max_order_usd=_get_float("MAX_ORDER_USD", 500),
        paper_starting_cash=_get_float("PAPER_STARTING_CASH", 10000),
        market_data=_get("MARKET_DATA", "auto").lower(),
        alert_check_seconds=max(15.0, _get_float("ALERT_CHECK_SECONDS", 60)),
        robinhood_username=_get("ROBINHOOD_USERNAME", ""),
        robinhood_password=os.getenv("ROBINHOOD_PASSWORD", "").strip(),
        robinhood_totp=_get("ROBINHOOD_TOTP_SECRET", ""),
        personality_file=ROOT / "personality.txt",
        memory_file=ROOT / _get("MEMORY_FILE", "memory.json"),
    )
