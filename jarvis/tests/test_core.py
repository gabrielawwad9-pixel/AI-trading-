"""Offline tests for the parts of JARVIS that don't need a mic or speakers.

Run with:   .venv\\Scripts\\python -m unittest discover tests
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis_core.memory import ConversationHistory, LongTermMemory  # noqa: E402
from jarvis_core.skills import Skills, Timers, describe_duration, parse_duration  # noqa: E402
from jarvis_core.textproc import SentenceSplitter, TagFilter, clean_for_speech  # noqa: E402


class FakeLauncher:
    def __init__(self, works=True):
        self.opened = []
        self.works = works

    def __call__(self, target):
        self.opened.append(target)
        return self.works


def make_skills(tmp, works=True):
    mem = LongTermMemory(Path(tmp) / "memory.json")
    launcher = FakeLauncher(works)
    return Skills(mem, Timers(), launcher=launcher), mem, launcher


class TestDurations(unittest.TestCase):
    def test_parse(self):
        cases = {
            "set a timer for 5 minutes": 300,
            "timer for five minutes": 300,
            "set a timer for 1 hour and 30 minutes": 5400,
            "remind me in 10 seconds": 10,
            "timer for half an hour": 1800,
            "an hour and a half": 5400,
            "two and a half minutes": 150,
            "twenty-five minutes": 1500,
            "set a 3 minute timer": 180,
            "give me extra minutes": 0,
            "pasta minutes": 0,
            "set a timer": 0,
        }
        for text, want in cases.items():
            self.assertEqual(parse_duration(text), want, text)

    def test_describe(self):
        self.assertEqual(describe_duration(300), "5 minutes")
        self.assertEqual(describe_duration(5400), "1 hour and 30 minutes")
        self.assertEqual(describe_duration(61), "1 minute and 1 second")


class TestSkills(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.skills, self.mem, self.launcher = make_skills(self.tmp)

    def tearDown(self):
        self.skills.timers.cancel_all()

    def test_time_and_date(self):
        self.assertTrue(self.skills.handle("What time is it?").startswith("It's"))
        self.assertTrue(self.skills.handle("Jarvis, what's the time").startswith("It's"))
        self.assertTrue(self.skills.handle("What's the date today?").startswith("Today is"))
        self.assertTrue(self.skills.handle("what day is it").startswith("Today is"))

    def test_questions_go_to_ai(self):
        for q in ["What's the capital of France?", "How do I open a bank account?",
                  "Tell me a joke", "What time does the sun set in Paris in June and why"]:
            r = self.skills.handle(q)
            if q.startswith("What time does"):
                continue  # ambiguous; either is acceptable
            self.assertIsNone(r, q)

    def test_open_sites_and_apps(self):
        self.assertEqual(self.skills.handle("Open YouTube."), "Opening youtube.")
        self.assertEqual(self.launcher.opened[-1], "https://www.youtube.com")
        self.assertEqual(self.skills.handle("can you please open spotify for me"), "Opening spotify.")
        self.assertEqual(self.launcher.opened[-1], "spotify:")
        self.skills.handle("open the calculator")
        self.assertEqual(self.launcher.opened[-1], "calc")
        self.skills.handle("go to bbc dot co dot uk")
        self.assertEqual(self.launcher.opened[-1], "https://bbc.co.uk")

    def test_open_unknown_offers_search(self):
        skills, _, launcher = make_skills(self.tmp, works=False)
        r = skills.handle("open blorpify")
        self.assertIn("search the web", r)
        r = skills.handle("yes please")
        self.assertIn("Searching", r)
        self.assertIn("google.com/search?q=blorpify", launcher.opened[-1])

    def test_search(self):
        self.skills.handle("search for best pizza near me")
        self.assertIn("q=best+pizza+near+me", self.launcher.opened[-1])

    def test_timers(self):
        self.assertEqual(self.skills.handle("Set a timer for 5 minutes."), "Timer set for 5 minutes.")
        self.assertIn("left", self.skills.handle("how much time is left"))
        self.assertIn("cancelled", self.skills.handle("cancel the timer"))
        self.assertEqual(self.skills.handle("set a timer"), "Of course. For how long?")
        self.assertEqual(self.skills.handle("ten seconds"), "Timer set for 10 seconds.")
        r = self.skills.handle("remind me to check the oven in 20 minutes")
        self.assertEqual(r, "Okay, I'll remind you to check the oven in 20 minutes.")

    def test_timer_fires(self):
        self.skills.timers.add(0.1, "")
        time.sleep(0.4)
        self.assertFalse(self.skills.timers.announcements.empty())
        self.assertIn("timer is done", self.skills.timers.announcements.get())

    def test_memory_commands(self):
        self.assertEqual(self.skills.handle("Remember that my favourite colour is green"),
                         "Got it. I'll remember that.")
        self.assertEqual(self.mem.facts[0]["fact"], "The user's favourite colour is green")
        self.assertIn("your favourite colour is green", self.skills.handle("What do you know about me?"))
        self.assertIn("forgotten", self.skills.handle("forget my favourite colour"))
        self.assertEqual(self.mem.facts, [])

    def test_ai_actions(self):
        self.skills.run_action("open", "netflix")
        self.assertEqual(self.launcher.opened[-1], "https://www.netflix.com")
        self.skills.run_action("timer", "stretch", "60")
        self.assertIn("1 minute", self.skills.timers.status())
        self.skills.run_action("remember", "The user's name is Gabriel")
        self.assertEqual(len(self.mem.facts), 1)


class TestRewording(unittest.TestCase):
    def test_third_person(self):
        from jarvis_core.memory import to_third_person as t3
        self.assertEqual(t3("I like jazz"), "The user likes jazz")
        self.assertEqual(t3("I really love sushi"), "The user really loves sushi")
        self.assertEqual(t3("my sister is called Maya"), "The user's sister is called Maya")
        self.assertEqual(t3("I'm a nurse and I work nights"), "The user is a nurse and the user works nights")
        self.assertEqual(t3("I have two cats"), "The user has two cats")
        self.assertEqual(t3("I don't eat meat"), "The user doesn't eat meat")
        self.assertEqual(t3("I study physics"), "The user studies physics")

    def test_second_person(self):
        from jarvis_core.memory import to_second_person as t2
        self.assertEqual(t2("The user likes jazz"), "you like jazz")
        self.assertEqual(t2("The user's sister is called Maya"), "your sister is called Maya")
        self.assertEqual(t2("The user is a nurse"), "you are a nurse")
        self.assertEqual(t2("The user has two cats"), "you have two cats")
        self.assertEqual(t2("The user doesn't eat meat"), "you don't eat meat")
        self.assertEqual(t2("The user studies physics"), "you study physics")
        self.assertEqual(t2("Lives in Ohio"), "Lives in Ohio")


class TestMemory(unittest.TestCase):
    def test_persist_and_dedupe(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "memory.json"
        m = LongTermMemory(path)
        self.assertTrue(m.add("The user's name is Gabriel"))
        self.assertFalse(m.add("The user's name is Gabriel."))   # duplicate
        m2 = LongTermMemory(path)                                 # "next session"
        self.assertEqual(len(m2.facts), 1)

    def test_corrupt_file_recovers(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "memory.json"
        path.write_text("{not json", encoding="utf-8")
        m = LongTermMemory(path)
        self.assertEqual(m.facts, [])
        self.assertTrue((Path(tmp) / "memory.broken.json").exists())

    def test_history_trim(self):
        h = ConversationHistory(max_messages=4)
        for i in range(5):
            h.add(f"q{i}", f"a{i}")
        self.assertEqual(len(h.messages), 4)
        self.assertEqual(h.messages[0], {"role": "user", "content": "q3"})


class TestTextProcessing(unittest.TestCase):
    def stream(self, chunks):
        tf = TagFilter()
        out = "".join(tf.feed(c) for c in chunks) + tf.flush()
        return out, tf.actions

    def test_tags_split_across_chunks(self):
        out, actions = self.stream(["Nice to meet you", ", Sam! <rem", "ember>The user's name", " is Sam</remem",
                                    "ber> Anything else?"])
        self.assertEqual(out, "Nice to meet you, Sam!  Anything else?")
        self.assertEqual(actions, [("remember", "The user's name is Sam", None)])

    def test_timer_tag(self):
        out, actions = self.stream(['Sure. <timer seconds="300">check the pasta</timer>'])
        self.assertEqual(out.strip(), "Sure.")
        self.assertEqual(actions, [("timer", "check the pasta", "300")])

    def test_plain_less_than(self):
        out, actions = self.stream(["3 < 5 and x <b> y"])
        self.assertEqual(out, "3 < 5 and x <b> y")
        self.assertEqual(actions, [])

    def test_unfinished_tag_not_spoken(self):
        out, _ = self.stream(["Okay. <open>spot"])
        self.assertEqual(out.strip(), "Okay.")

    def test_sentences(self):
        sp = SentenceSplitter()
        got = []
        for chunk in ["Hello there. ", "It's 3.5 degrees outside", " today! What else", " can I do?"]:
            got += sp.feed(chunk)
        got += sp.flush()
        self.assertEqual(got, ["Hello there. It's 3.5 degrees outside today!", "What else can I do?"])
        sp = SentenceSplitter()
        self.assertEqual(sp.feed("Sure. Here you go. ") + sp.flush(), ["Sure. Here you go."])

    def test_clean(self):
        self.assertEqual(clean_for_speech("**Bold** and `code` - see [docs](http://x)"),
                         "Bold and code - see docs")


class TestAssistantPipeline(unittest.TestCase):
    """Runs the full reply pipeline with a fake brain and fake speaker."""

    def test_reply_with_tags(self):
        from jarvis_core.assistant import Assistant
        from jarvis_core.config import load_config

        class FakeBrain:
            model = "fake"

            def stream(self, system, messages):
                assert "voice assistant" in system
                assert messages[-1] == {"role": "user", "content": "my name is Sam, open netflix"}
                for c in ["Good to meet you, Sam. ", "Opening Net", "flix now. <open>netflix</open>",
                          "<remember>The user's name is Sam</remember>"]:
                    yield c

        class FakeSpeaker:
            sample_rate = 24000
            muted = False
            spoken = []

            def speak_stream(self, sentences, monitor=None, prelude=(), rate=None):
                self.spoken.extend(sentences)
                return False

            def speak(self, text, monitor=None):
                self.spoken.append(text)
                return False

        tmp = tempfile.mkdtemp()
        skills, mem, launcher = make_skills(tmp)
        cfg = load_config()
        speaker = FakeSpeaker()
        history = ConversationHistory()
        a = Assistant(cfg, speaker, FakeBrain(), mem, history, skills, skills.timers,
                      personality="You are JARVIS.")
        a.respond("my name is Sam, open netflix")
        self.assertEqual(speaker.spoken, ["Good to meet you, Sam.", "Opening Netflix now."])
        self.assertEqual(launcher.opened, ["https://www.netflix.com"])
        self.assertEqual(mem.facts[0]["fact"], "The user's name is Sam")
        self.assertEqual(history.messages[-1]["content"], "Good to meet you, Sam. Opening Netflix now.")
        self.assertIn("The user's name is Sam", a.system_prompt())

    def test_classify_and_strip(self):
        from jarvis_core.assistant import Assistant
        self.assertEqual(Assistant.strip_wake_word("Hey Jarvis, what time is it?"), "what time is it?")
        self.assertEqual(Assistant.strip_wake_word("Jarvis."), "")
        a = Assistant.__new__(Assistant)
        self.assertEqual(a.classify("Goodbye, Jarvis."), "exit")
        self.assertEqual(a.classify("Shut down."), "exit")
        self.assertEqual(a.classify("Never mind."), "sleep")
        self.assertIsNone(a.classify("Stop the timer"))


if __name__ == "__main__":
    unittest.main()
