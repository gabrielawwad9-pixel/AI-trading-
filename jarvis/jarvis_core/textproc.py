"""Text helpers: splitting a streamed reply into sentences, and pulling out action tags.

The LLM can include hidden tags in its reply, e.g.
    "Sure, opening it now. <open>spotify</open>"
    "Nice to meet you, Sam! <remember>The user's name is Sam</remember>"
TagFilter removes them from what gets spoken and reports them as actions.
"""

import re

KNOWN_TAGS = ("remember", "open", "timer", "search")
_TAG_RE = re.compile(
    r"<(remember|open|search)>(.*?)</\1>|<timer(?:\s+seconds\s*=\s*[\"']?(\d+(?:\.\d+)?)[\"']?)?\s*>(.*?)</timer>",
    re.DOTALL | re.IGNORECASE,
)


class TagFilter:
    """Streaming filter. feed() returns speakable text; actions are appended to self.actions."""

    def __init__(self):
        self.buf = ""
        self.actions = []   # list of (tag, value, extra)

    def feed(self, text: str) -> str:
        self.buf += text
        out = []
        while True:
            i = self.buf.find("<")
            if i == -1:
                out.append(self.buf)
                self.buf = ""
                break
            out.append(self.buf[:i])
            self.buf = self.buf[i:]
            m = _TAG_RE.match(self.buf)
            if m:
                if m.group(1):
                    self.actions.append((m.group(1).lower(), m.group(2).strip(), None))
                else:
                    self.actions.append(("timer", (m.group(4) or "").strip(), m.group(3)))
                self.buf = self.buf[m.end():]
                continue
            if self._could_be_tag(self.buf):
                break       # wait for more text
            out.append("<")  # just a normal "<" character
            self.buf = self.buf[1:]
        return "".join(out)

    @staticmethod
    def _could_be_tag(s: str) -> bool:
        head = s[1:].lower()
        for tag in KNOWN_TAGS:
            if len(head) < len(tag):
                if tag.startswith(head):
                    return True          # e.g. "<rem" - might become "<remember>"
            elif head.startswith(tag) and (len(head) == len(tag) or head[len(tag)] in "> "):
                # full tag name seen: still incomplete until the closing tag arrives
                return f"</{tag}>" not in head and len(s) < 600
        return False

    def flush(self) -> str:
        rest = self.buf
        self.buf = ""
        if self._could_be_tag(rest):
            return ""   # an unfinished tag - don't read it aloud
        return rest


_SENTENCE_END = re.compile(r"(?<=[.!?;:])[\"')\]]*\s+|\n+")


class SentenceSplitter:
    """Collects streamed text and hands back whole sentences, so speech can start early."""

    def __init__(self, min_chars=15):
        self.buf = ""
        self.min_chars = min_chars

    def feed(self, text: str):
        self.buf += text
        sentences = []
        while True:
            m = None
            for cand in _SENTENCE_END.finditer(self.buf):
                if cand.end() >= self.min_chars:
                    m = cand
                    break
            if not m:
                break
            piece = self.buf[: m.end()].strip()
            self.buf = self.buf[m.end():]
            if piece:
                sentences.append(piece)
        return sentences

    def flush(self):
        piece = self.buf.strip()
        self.buf = ""
        return [piece] if piece else []


def clean_for_speech(text: str) -> str:
    """Remove markdown and symbols that sound silly when read aloud."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)      # [label](url) -> label
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
