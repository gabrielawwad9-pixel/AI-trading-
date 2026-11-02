"""The 'brain': sends the conversation to Claude (online) or Ollama (local) and streams the reply."""

import json

from .errors import FriendlyError


class ClaudeBrain:
    name = "Claude"

    def __init__(self, api_key: str, model: str, max_tokens: int = 400):
        if not api_key or not api_key.startswith("sk-"):
            raise FriendlyError(
                "No Claude API key found.\n"
                "  Fix: open the .env file in Notepad and paste your key after ANTHROPIC_API_KEY=\n"
                "  (get one at https://console.anthropic.com/settings/keys - it starts with sk-ant-).\n"
                "  Or set LLM_PROVIDER=ollama to use a free local model instead."
            )
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=60)
        self.model = model
        self.max_tokens = max_tokens

    def stream(self, system: str, messages: list):
        """Yield the reply a few words at a time."""
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text


class OllamaBrain:
    name = "Ollama"

    def __init__(self, url: str, model: str, max_tokens: int = 400):
        import requests
        self.requests = requests
        self.url = url
        self.model = model
        self.max_tokens = max_tokens

    def check(self):
        """Make sure Ollama is running and the model is downloaded."""
        try:
            r = self.requests.get(f"{self.url}/api/tags", timeout=5)
        except self.requests.exceptions.RequestException as e:
            raise ConnectionError(f"Could not reach Ollama at {self.url} (port 11434): {e}") from None
        names = [m.get("name", "") for m in r.json().get("models", [])]
        wanted = self.model if ":" in self.model else self.model + ":latest"
        if self.model not in names and wanted not in names:
            raise LookupError(
                f"Ollama model '{self.model}' not found (404) - run:  ollama pull {self.model}"
            )

    def stream(self, system: str, messages: list):
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "stream": True,
            "options": {"num_predict": self.max_tokens},
        }
        try:
            r = self.requests.post(f"{self.url}/api/chat", json=payload, stream=True, timeout=120)
        except self.requests.exceptions.RequestException as e:
            raise ConnectionError(f"Could not reach Ollama at {self.url} (port 11434): {e}") from None
        if r.status_code == 404:
            raise LookupError(f"Ollama model '{self.model}' not found (404) - run:  ollama pull {self.model}")
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            if "error" in chunk:
                raise RuntimeError(f"Ollama error: {chunk['error']}")
            text = chunk.get("message", {}).get("content", "")
            if text:
                yield text
            if chunk.get("done"):
                break


def make_brain(cfg):
    if cfg.llm_provider == "ollama":
        brain = OllamaBrain(cfg.ollama_url, cfg.ollama_model, cfg.max_reply_tokens)
        brain.check()
        return brain
    if cfg.llm_provider != "claude":
        raise FriendlyError(f"LLM_PROVIDER in .env must be 'claude' or 'ollama' (it's currently '{cfg.llm_provider}').")
    return ClaudeBrain(cfg.anthropic_api_key, cfg.claude_model, cfg.max_reply_tokens)
