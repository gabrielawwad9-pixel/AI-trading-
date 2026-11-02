"""Turns scary Python errors into plain-English explanations with a suggested fix."""

import traceback


class FriendlyError(Exception):
    """An error whose message is already written in plain English - shown as-is."""


def explain(exc: BaseException) -> str:
    """Return a friendly, beginner-readable explanation of an exception."""
    if isinstance(exc, FriendlyError):
        return str(exc)
    name = type(exc).__name__
    module = type(exc).__module__ or ""
    msg = str(exc)
    low = msg.lower()

    # --- Missing packages / broken installs -------------------------------
    if isinstance(exc, ModuleNotFoundError):
        pkg = getattr(exc, "name", None) or msg
        return (
            f"A required Python package is missing ({pkg}).\n"
            "  Fix: double-click setup.bat again (or run:  .venv\\Scripts\\pip install -r requirements.txt).\n"
            "  If you started JARVIS with plain 'python jarvis.py', use start_jarvis.bat instead so it uses\n"
            "  JARVIS's own Python environment."
        )
    if isinstance(exc, ImportError) and "dll" in low:
        return (
            "Windows couldn't load a system file (DLL) that the speech engines need.\n"
            "  Fix: install the 'Microsoft Visual C++ Redistributable (x64)' from\n"
            "  https://aka.ms/vs/17/release/vc_redist.x64.exe , restart your laptop, then try again."
        )

    # --- Microphone / speakers ---------------------------------------------
    if name == "PortAudioError" or "portaudio" in low:
        if "invalid sample rate" in low:
            return (
                "Your microphone or speaker refused the audio format JARVIS asked for.\n"
                "  Fix: try a different device by setting MIC_DEVICE / SPEAKER_DEVICE in .env\n"
                "  (run  check.bat mic  to see the list of devices and their numbers)."
            )
        if "invalid device" in low or "device unavailable" in low or "no default" in low:
            return (
                "JARVIS couldn't find the microphone or speaker it was told to use.\n"
                "  Fix: make sure a mic is plugged in / enabled, then run  check.bat mic  to list devices.\n"
                "  If MIC_DEVICE or SPEAKER_DEVICE is set in .env, check the number/name is right, or leave\n"
                "  it blank to use the Windows default."
            )
        return (
            "There was a problem talking to your microphone or speakers.\n"
            "  Things to check:\n"
            "   1. Windows Settings > Privacy & security > Microphone: turn ON 'Microphone access' AND\n"
            "      'Let desktop apps access your microphone'.\n"
            "   2. Close other apps that might be hogging the mic (Zoom, Teams, Discord, OBS).\n"
            "   3. Run  check.bat mic  to see which devices JARVIS can find.\n"
            f"  (Technical detail: {msg})"
        )

    # --- Claude API ------------------------------------------------------------
    if module.startswith("anthropic"):
        if name == "AuthenticationError":
            return (
                "Claude rejected your API key.\n"
                "  Fix: open the .env file and check ANTHROPIC_API_KEY. It should start with 'sk-ant-' and have\n"
                "  no spaces or quotes. You can create a new key at https://console.anthropic.com/settings/keys"
            )
        if name == "PermissionDeniedError":
            return "Your Claude API key doesn't have permission for this model. Try a different CLAUDE_MODEL in .env."
        if name == "NotFoundError":
            return (
                "Claude doesn't recognise the model name in your .env file.\n"
                "  Fix: set CLAUDE_MODEL=claude-sonnet-5-5 (or claude-haiku-5-5 for faster/cheaper replies)."
            )
        if name == "RateLimitError":
            return "You're sending requests to Claude too quickly. Wait a minute and try again."
        if name == "BadRequestError" and "credit" in low:
            return (
                "Your Anthropic account is out of credit.\n"
                "  Fix: add credit at https://console.anthropic.com/settings/billing , or switch to a free local\n"
                "  model by setting LLM_PROVIDER=ollama in .env (see the setup guide)."
            )
        if name in ("APIConnectionError", "APITimeoutError"):
            return (
                "JARVIS couldn't reach Claude over the internet.\n"
                "  Fix: check your Wi-Fi. If you're offline, set LLM_PROVIDER=ollama in .env to use a local model."
            )
        if name in ("InternalServerError", "OverloadedError") or "overloaded" in low:
            return "Claude's servers are busy right now. Wait a few seconds and ask again."

    # --- Ollama / general networking ---------------------------------------------
    if "11434" in msg or "ollama" in low:
        if "not found" in low or "404" in low:
            return (
                "Ollama is running, but the model in your .env isn't downloaded yet.\n"
                "  Fix: open a terminal and run:  ollama pull llama3.2   (or whatever OLLAMA_MODEL is set to)."
            )
        return (
            "JARVIS couldn't connect to Ollama (the local AI model program).\n"
            "  Fix: install it from https://ollama.com , open the Ollama app (it sits in the system tray),\n"
            "  and make sure you've run  ollama pull llama3.2  once."
        )
    if name in ("ClientConnectorError", "WSServerHandshakeError", "ClientConnectorDNSError") or (
        "speech.platform.bing.com" in low
    ):
        return (
            "The online voice (edge-tts) couldn't connect. It needs internet.\n"
            "  Fix: check your Wi-Fi, or switch to the offline Piper voice: run  check.bat voice --download-piper\n"
            "  then set TTS_ENGINE=piper in .env."
        )
    if "huggingface" in low or "hf_hub" in low or "localentrynotfound" in name.lower():
        return (
            "JARVIS couldn't download a model file it needs (the speech-recognition model, ~150 MB,\n"
            "  or the offline Piper voice). This only has to happen once.\n"
            "  Fix: check your internet connection, then run  check.bat download  again.\n"
            "  On a work/school network, a firewall may block huggingface.co - try a home network."
        )
    if module.startswith(("requests", "urllib3", "aiohttp")) or name in (
            "ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout", "NameResolutionError"):
        return f"A network request failed - check your internet connection. (Detail: {msg[:200]})"

    # --- Files ---------------------------------------------------------------------
    if isinstance(exc, FileNotFoundError):
        return (
            f"A file JARVIS needs is missing: {getattr(exc, 'filename', None) or msg}\n"
            "  Fix: make sure you're running JARVIS from its own folder (use start_jarvis.bat) and that you\n"
            "  haven't renamed or deleted it. For the Piper voice, run  check.bat voice --download-piper"
        )
    if isinstance(exc, PermissionError):
        return (
            f"Windows blocked JARVIS from reading or writing a file: {msg}\n"
            "  Fix: move the JARVIS folder somewhere you own (e.g. Documents), and make sure memory.json\n"
            "  isn't open in another program."
        )
    if isinstance(exc, MemoryError) or "out of memory" in low:
        return (
            "Your laptop ran out of memory.\n"
            "  Fix: close some apps, or use a smaller speech model: set WHISPER_MODEL=tiny.en in .env."
        )

    # --- Speech recognition ----------------------------------------------------------
    if "cuda" in low or "cublas" in low or "cudnn" in low:
        return (
            "JARVIS tried to use an NVIDIA graphics card for speech recognition and it didn't work.\n"
            "  Fix: set WHISPER_DEVICE=cpu in .env (this works on every laptop)."
        )

    # --- Fallback ------------------------------------------------------------------------
    return (
        f"Something unexpected went wrong ({name}): {msg}\n"
        "  If this keeps happening, copy the technical details below and ask for help."
    )


def report(exc: BaseException, what: str = "", show_trace: bool = False) -> None:
    """Print a friendly explanation (and optionally the technical traceback)."""
    header = f"[X] Problem{(' with ' + what) if what else ''}:"
    print("\n" + header)
    print("  " + explain(exc))
    if show_trace:
        print("\n  --- technical details ---")
        print("  " + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).replace("\n", "\n  "))
    print()
