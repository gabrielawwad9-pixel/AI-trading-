"""Memory: short-term conversation history + long-term facts saved to memory.json."""

import datetime as dt
import difflib
import json
import os
import re
from pathlib import Path


class LongTermMemory:
    """Facts about you, kept in a small JSON file so JARVIS remembers you next time."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.facts = []          # list of {"fact": str, "saved": "YYYY-MM-DD"}
        self.load()

    def load(self):
        if not self.path.exists():
            self.facts = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.facts = [f for f in data.get("facts", []) if isinstance(f, dict) and f.get("fact")]
        except (json.JSONDecodeError, OSError, AttributeError):
            backup = self.path.with_suffix(".broken.json")
            try:
                self.path.replace(backup)
                print(f"  (memory.json was damaged - saved a copy as {backup.name} and started fresh.)")
            except OSError:
                pass
            self.facts = []

    def save(self):
        data = {"facts": self.facts}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)   # write-then-rename so a crash can't corrupt the file

    def add(self, fact: str) -> bool:
        fact = fact.strip().rstrip(".").strip()
        if len(fact) < 3:
            return False
        low = fact.lower()
        for existing in self.facts:
            if difflib.SequenceMatcher(None, existing["fact"].lower(), low).ratio() > 0.85:
                existing["fact"] = fact          # update wording, don't duplicate
                existing["saved"] = dt.date.today().isoformat()
                self.save()
                return False
        self.facts.append({"fact": fact, "saved": dt.date.today().isoformat()})
        self.save()
        return True

    def forget(self, query: str) -> int:
        """Remove facts that share the important words of `query`. Returns how many were removed."""
        words = {w for w in re.findall(r"[a-z0-9']+", query.lower()) if len(w) > 2} - _STOP
        if not words:
            return 0
        keep = []
        removed = 0
        for f in self.facts:
            fw = set(re.findall(r"[a-z0-9']+", f["fact"].lower()))
            if len(words & fw) >= max(1, (len(words) + 1) // 2):
                removed += 1
            else:
                keep.append(f)
        if removed:
            self.facts = keep
            self.save()
        return removed

    def clear(self):
        self.facts = []
        self.save()

    def as_text(self) -> str:
        return "\n".join(f"- {f['fact']}" for f in self.facts)


_STOP = {"the", "that", "and", "about", "you", "your", "my", "i'm", "was", "are", "for", "with", "have", "this"}


class ConversationHistory:
    """What's been said in this session (sent to the LLM so it can follow the conversation)."""

    def __init__(self, max_messages=24):
        self.messages = []
        self.max_messages = max_messages

    def add(self, user_text: str, assistant_text: str):
        self.messages.append({"role": "user", "content": user_text})
        self.messages.append({"role": "assistant", "content": assistant_text or "(no reply)"})
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]
        while self.messages and self.messages[0]["role"] != "user":
            self.messages.pop(0)

    def with_new(self, user_text: str):
        return self.messages + [{"role": "user", "content": user_text}]

    def clear(self):
        self.messages = []


# ---------------------------------------------------------------------------
# Rewording facts:  "I like jazz" <-> "The user likes jazz" <-> "you like jazz"
# ---------------------------------------------------------------------------
_ADVERB = r"(?:(really|also|usually|always|never|just|still|often|sometimes|absolutely|totally|mostly|actually)\s+)?"
_NOT_VERBS = {"could", "should", "might", "must", "did", "had", "used", "may", "shall", "need", "ought"}


def _third_person_verb(v: str) -> str:
    if v in _NOT_VERBS:
        return v
    if v == "have":
        return "has"
    if v == "do":
        return "does"
    if v == "go":
        return "goes"
    if re.search(r"(s|sh|ch|x|z|o)$", v):
        return v + "es"
    if re.search(r"[^aeiou]y$", v):
        return v[:-1] + "ies"
    return v + "s"


def _base_verb(v: str) -> str:
    irregular = {"has": "have", "does": "do", "goes": "go", "is": "are", "was": "were"}
    if v in irregular:
        return irregular[v]
    if v.endswith("ies") and len(v) > 4:
        return v[:-3] + "y"
    if re.search(r"(sses|shes|ches|xes|zes|oes)$", v):
        return v[:-2]
    if v.endswith("s") and not v.endswith("ss"):
        return v[:-1]
    return v


def to_third_person(text: str) -> str:
    """'I really like jazz and my dog is Rex' -> 'The user really likes jazz and the user's dog is Rex'."""
    t = text.strip()
    fixed = [
        (r"\bi am\b|\bi'm\b", "the user is"), (r"\bi was\b", "the user was"),
        (r"\bi've\b", "the user has"), (r"\bi don't\b", "the user doesn't"),
        (r"\bi do not\b", "the user does not"), (r"\bi can't\b", "the user can't"),
        (r"\bi'll\b|\bi will\b", "the user will"), (r"\bi'd\b|\bi would\b", "the user would"),
        (r"\bi can\b", "the user can"), (r"\bmyself\b", "themselves"),
        (r"\bmy\b", "the user's"), (r"\bmine\b", "the user's"), (r"\bme\b", "the user"),
    ]
    for pat, rep in fixed:
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    t = re.sub(r"\bi\s+" + _ADVERB + r"([a-z]+)\b",
               lambda m: "the user " + (m.group(1) + " " if m.group(1) else "") + _third_person_verb(m.group(2).lower()),
               t, flags=re.IGNORECASE)
    t = re.sub(r"\bi\b", "the user", t, flags=re.IGNORECASE)
    return t[0].upper() + t[1:] if t else t


def to_second_person(fact: str) -> str:
    """'The user likes jazz' -> 'you like jazz' (for reading memories back out loud)."""
    t = fact.strip()
    t = re.sub(r"\b(?:the user|user)'s\b", "your", t, flags=re.IGNORECASE)
    t = re.sub(r"\b(?:the user|user)\s+" + _ADVERB + r"([a-z']+)\b",
               lambda m: "you " + (m.group(1) + " " if m.group(1) else "") + _base_verb(m.group(2).lower()),
               t, flags=re.IGNORECASE)
    t = re.sub(r"\byou doesn't\b", "you don't", t)
    t = re.sub(r"\b(?:the user|user)\b", "you", t, flags=re.IGNORECASE)
    t = re.sub(r"\bthemselves\b", "yourself", t)
    return t
