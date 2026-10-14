"""בדיקות יחידה ל-Shorts Factory.

כל השירותים החיצוניים (Groq, gTTS, pyttsx3) מוחלפים ב-mock, ולכן הבדיקות
עובדות מהר, ללא מפתח API וללא חיבור אינטרנט.

הרצה:  python -m unittest discover -v -s tests
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from shorts_factory import cli as cli_module
from shorts_factory import groq_client as groq_client_module
from shorts_factory import tts_engine as tts_engine_module
from shorts_factory.cli import EXIT_AI, EXIT_OK, EXIT_TTS, ShortsFactory, main
from shorts_factory.config import Settings, load_settings
from shorts_factory.errors import (
    AIEngineError,
    AIResponseError,
    ConfigurationError,
    TTSSynthesisError,
)
from shorts_factory.groq_client import GroqTextEngine
from shorts_factory.schemas import (
    Idea,
    estimate_duration_seconds,
    extract_json_object,
    normalize_hashtags,
    normalize_tags,
    parse_content,
    parse_ideas,
    slugify,
)
from shorts_factory.storage import ProjectStorage
from shorts_factory.tts_engine import TextToSpeechEngine
from shorts_factory.ui import TerminalUI


# ---------------------------------------------------------------------------
# עזרים לטסטים
# ---------------------------------------------------------------------------
def make_settings(**overrides) -> Settings:
    """בונה Settings עם ערכים בטוחים לטסט (כולל תיקיית פלט זמנית)."""
    base = dict(
        groq_api_key="gsk_test_key_123",
        groq_model="llama-3.3-70b-versatile",
        output_dir=Path(tempfile.mkdtemp(prefix="shorts_test_")),
        tts_lang="iw",
        tts_slow=False,
        skip_audio=False,
        ideas_count=5,
        ideas_temperature=0.9,
        content_temperature=0.7,
        request_timeout=30.0,
        max_retries=3,
        retry_base_delay=0.0,
        script_max_seconds=50,
        scenes_min=3,
        scenes_max=4,
        tags_count=15,
        no_color=True,
        verbose=False,
    )
    base.update(overrides)
    return Settings(**base)


def make_logger():
    import logging

    logger = logging.getLogger("shorts_factory_test")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    return logger


IDEAS_JSON = json.dumps(
    {
        "ideas": [
            {
                "number": i,
                "title": f"רעיון מספר {i}",
                "hook": f"הוק מספר {i}",
                "summary": f"תקציר מספר {i}",
            }
            for i in range(1, 6)
        ]
    },
    ensure_ascii=False,
)

CONTENT_JSON = json.dumps(
    {
        "title": "5 טעויות שגורמות לכם להפסיד כסף",
        "description": "בסרטון הזה תגלו 5 טעויות נפודות. עשו לייק והישארו לעוד.",
        "hashtags": ["#כסף", "#חסכון", "#טיפים", "#שורטס"],
        "tags": [f"תגית{i}" for i in range(1, 16)] + ["תגית-מיותרת"],
        "script": {
            "full_text": "אם אתם חושבים שחסכון זה רק הפקדה בבנק, אפסתם לחלוטין. "
            "הנה חמש טעויות שעושות כמעט לכולנו, ואתם עדיין יכולים לתקן אותן עוד היום. "
            "שמרו את הסרטון, כי הטעות הרביעית תזעזע אתכם לגמרי.",
            "scenes": [
                {
                    "scene_number": i,
                    "time_range": f"{i * 10}-{i * 10 + 10}s",
                    "narration": f"חלק {i} מהתסריט.",
                    "visual_prompt": (
                        f"Cinematic shot {i}: a young person counting cash at home, "
                        "soft morning light, slow dolly zoom, vertical 9:16 composition."
                    ),
                }
                for i in range(1, 5)
            ],
        },
    },
    ensure_ascii=False,
)


# --- Groq מזויף ------------------------------------------------------------
class FakeGroqError(Exception):
    pass


class FakeRateLimitError(FakeGroqError):
    pass


class FakeAuthError(FakeGroqError):
    pass


class FakeConnError(FakeGroqError):
    pass


class FakeTimeoutError(FakeGroqError):
    pass


class FakeStatusError(FakeGroqError):
    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message)
        self.status_code = status_code


class FakeInternalError(FakeStatusError):
    def __init__(self, message: str = "server error"):
        super().__init__(message, status_code=500)


class FakeCompletions:
    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        action = self._script.pop(0)
        if isinstance(action, Exception):
            raise action
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=action))]
        )


def make_fake_groq(script):
    """מחזיר (מודול_מזויף, לקוח_מזויף) עם תסריט תשובות/חריגות."""
    completions = FakeCompletions(script)
    client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=completions),
        models=types.SimpleNamespace(
            list=lambda: types.SimpleNamespace(
                data=[types.SimpleNamespace(id="llama-3.3-70b-versatile")]
            )
        ),
    )

    def factory(**kwargs):
        client.kwargs = kwargs
        return client

    fake = types.SimpleNamespace(
        Groq=factory,
        GroqError=FakeGroqError,
        RateLimitError=FakeRateLimitError,
        AuthenticationError=FakeAuthError,
        APIConnectionError=FakeConnError,
        APITimeoutError=FakeTimeoutError,
        APIStatusError=FakeStatusError,
        InternalServerError=FakeInternalError,
    )
    return fake, client


# ---------------------------------------------------------------------------
# 1. בדיקות JSON / ולידציה
# ---------------------------------------------------------------------------
class ExtractJsonTests(unittest.TestCase):
    def test_plain_json(self):
        data = extract_json_object('{"a": 1}')
        self.assertEqual(data, {"a": 1})

    def test_markdown_fenced(self):
        data = extract_json_object('```json\n{"a": 1}\n```')
        self.assertEqual(data, {"a": 1})

    def test_prose_wrapped(self):
        data = extract_json_object('הנה התשובה:\n{"a": 1}\nתודה')
        self.assertEqual(data, {"a": 1})

    def test_invalid_raises(self):
        with self.assertRaises(AIResponseError):
            extract_json_object("זו לא JSON בכלל")

    def test_non_dict_raises(self):
        with self.assertRaises(AIResponseError):
            extract_json_object("[1, 2, 3]")

    def test_empty_raises(self):
        with self.assertRaises(AIResponseError):
            extract_json_object("   ")


class HelperTests(unittest.TestCase):
    def test_slugify_english(self):
        self.assertEqual(slugify("Top 5 Money Tips!!"), "top-5-money-tips")

    def test_slugify_hebrew_falls_back(self):
        # עברית נמחקת (בטיחות cross-platform) -> מחרוזת ריקה
        self.assertEqual(slugify("טיפים לחסוך כסף"), "")

    def test_slugify_max_length(self):
        slug = slugify("a" * 100, max_length=10)
        self.assertEqual(slug, "a" * 10)

    def test_estimate_duration(self):
        self.assertGreater(estimate_duration_seconds("מילה " * 130), 45)

    def test_normalize_tags_dedup_and_cap(self):
        tags = normalize_tags(["#כסף", "כסף", " חסכון ", "", "x" * 3], limit=3)
        self.assertEqual(tags, ["כסף", "חסכון", "x" * 3])

    def test_normalize_hashtags_adds_hash_and_removes_spaces(self):
        tags = normalize_hashtags(["שורטס", "#Shorts ", "שורטס"])
        self.assertEqual(tags, ["#שורטס", "#Shorts"])


class ParseIdeasTests(unittest.TestCase):
    def test_valid_five_ideas(self):
        ideas = parse_ideas(IDEAS_JSON, expected_count=5)
        self.assertEqual(len(ideas), 5)
        self.assertEqual(ideas[0].number, 1)
        self.assertEqual(ideas[4].title, "רעיון מספר 5")

    def test_too_few_ideas_raises(self):
        payload = json.dumps({"ideas": [{"title": "רק רעיון אחד"}]}, ensure_ascii=False)
        with self.assertRaises(AIResponseError):
            parse_ideas(payload, expected_count=5)

    def test_extra_ideas_are_sliced(self):
        payload = json.dumps(
            {"ideas": [{"title": f"רעיון {i}"} for i in range(8)]}, ensure_ascii=False
        )
        ideas = parse_ideas(payload, expected_count=5)
        self.assertEqual(len(ideas), 5)


class ParseContentTests(unittest.TestCase):
    def test_full_parse(self):
        content = parse_content(CONTENT_JSON, min_scenes=3, max_scenes=4, tags_count=15)
        self.assertEqual(len(content.scenes), 4)
        self.assertEqual(len(content.tags), 15)  # התגית המיותרת נחתכה
        self.assertEqual(content.hashtags, ("#כסף", "#חסכון", "#טיפים", "#שורטס"))
        self.assertTrue(content.script_text)
        self.assertGreater(content.duration_estimate_seconds, 0)
        self.assertEqual(content.scenes[0].visual_prompt.split()[0], "Cinematic")

    def test_too_many_scenes_truncated_with_warning(self):
        payload = json.loads(CONTENT_JSON)
        payload["script"]["scenes"].append(
            {"scene_number": 5, "narration": "עוד", "visual_prompt": "extra scene prompt"}
        )
        logger = make_logger()
        with self.assertLogs(logger, level="WARNING") as captured:
            content = parse_content(
                json.dumps(payload, ensure_ascii=False), max_scenes=4, logger=logger
            )
        self.assertEqual(len(content.scenes), 4)
        self.assertTrue(any("סצנות" in message for message in captured.output))

    def test_too_few_scenes_raises(self):
        payload = json.loads(CONTENT_JSON)
        payload["script"]["scenes"] = payload["script"]["scenes"][:2]
        with self.assertRaises(AIResponseError):
            parse_content(json.dumps(payload, ensure_ascii=False), min_scenes=3)

    def test_missing_title_raises(self):
        payload = json.loads(CONTENT_JSON)
        del payload["title"]
        with self.assertRaises(AIResponseError):
            parse_content(json.dumps(payload, ensure_ascii=False))

    def test_script_assembled_from_narrations(self):
        payload = json.loads(CONTENT_JSON)
        payload["script"]["full_text"] = ""
        content = parse_content(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(content.script_text, " ".join(s.narration for s in content.scenes))

    def test_to_dict_roundtrip(self):
        content = parse_content(CONTENT_JSON)
        data = content.to_dict()
        self.assertEqual(data["script"]["scenes"][0]["scene_number"], 1)
        self.assertEqual(len(data["tags"]), 15)


# ---------------------------------------------------------------------------
# 2. בדיקות מנוע Groq
# ---------------------------------------------------------------------------
class GroqEngineTests(unittest.TestCase):
    def test_retry_on_rate_limit_then_success(self):
        fake, client = make_fake_groq(
            [FakeRateLimitError("429"), FakeInternalError("500"), IDEAS_JSON]
        )
        settings = make_settings()
        with mock.patch.object(groq_client_module, "groq_sdk", fake), mock.patch.object(
            groq_client_module.time, "sleep"
        ), mock.patch.object(groq_client_module.random, "uniform", return_value=0.0):
            engine = GroqTextEngine(settings, make_logger())
            ideas = engine.generate_ideas("נושא לבדיקה")

        self.assertEqual(len(ideas), 5)
        self.assertEqual(len(client.chat.completions.calls), 3)
        # הבקשה נשלחה עם JSON mode וטיימאאוט
        kwargs = client.chat.completions.calls[-1]
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(kwargs["timeout"], settings.request_timeout)
        self.assertEqual(kwargs["messages"][0]["role"], "system")
        self.assertIn("JSON", kwargs["messages"][1]["content"])

    def test_auth_error_raises_configuration_error_without_retry(self):
        fake, client = make_fake_groq([FakeAuthError("401")])
        with mock.patch.object(groq_client_module, "groq_sdk", fake):
            engine = GroqTextEngine(make_settings(), make_logger())
            with self.assertRaises(ConfigurationError):
                engine.generate_ideas("נושא")
        self.assertEqual(len(client.chat.completions.calls), 1)

    def test_bad_request_not_retried(self):
        fake, client = make_fake_groq([FakeStatusError("bad model", 404)])
        with mock.patch.object(groq_client_module, "groq_sdk", fake):
            engine = GroqTextEngine(make_settings(), make_logger())
            with self.assertRaises(AIEngineError):
                engine.generate_ideas("נושא")
        self.assertEqual(len(client.chat.completions.calls), 1)

    def test_invalid_json_not_retried(self):
        fake, client = make_fake_groq(["לא JSON"])
        with mock.patch.object(groq_client_module, "groq_sdk", fake):
            engine = GroqTextEngine(make_settings(), make_logger())
            with self.assertRaises(AIResponseError):
                engine.generate_ideas("נושא")
        self.assertEqual(len(client.chat.completions.calls), 1)

    def test_all_retries_fail(self):
        fake, _client = make_fake_groq([FakeRateLimitError("429")] * 3)
        with mock.patch.object(groq_client_module, "groq_sdk", fake), mock.patch.object(
            groq_client_module.time, "sleep"
        ), mock.patch.object(groq_client_module.random, "uniform", return_value=0.0):
            engine = GroqTextEngine(make_settings(max_retries=2), make_logger())
            with self.assertRaises(AIEngineError):
                engine.generate_ideas("נושא")

    def test_missing_sdk_raises_configuration_error(self):
        with mock.patch.object(groq_client_module, "groq_sdk", None):
            engine = GroqTextEngine(make_settings(), make_logger())
            with self.assertRaises(ConfigurationError):
                engine.generate_ideas("נושא")

    def test_generate_content(self):
        fake, _client = make_fake_groq([CONTENT_JSON])
        with mock.patch.object(groq_client_module, "groq_sdk", fake):
            engine = GroqTextEngine(make_settings(), make_logger())
            content = engine.generate_content(
                Idea(number=1, title="רעיון", hook="הוק", summary="תקציר")
            )
        self.assertEqual(len(content.scenes), 4)
        self.assertEqual(len(content.tags), 15)

    def test_list_models(self):
        fake, _client = make_fake_groq([])
        with mock.patch.object(groq_client_module, "groq_sdk", fake):
            engine = GroqTextEngine(make_settings(), make_logger())
            models = engine.list_models()
        self.assertIn("llama-3.3-70b-versatile", models)


# ---------------------------------------------------------------------------
# 3. בדיקות מנוע TTS
# ---------------------------------------------------------------------------
class FakeGTTSType:
    """מדמה gTTS – כותב קובץ אמיתי כדי לבדוק את זרימת העבודה."""

    last_kwargs = None

    def __init__(self, **kwargs):
        FakeGTTSType.last_kwargs = kwargs

    def save(self, path):
        Path(path).write_bytes(b"ID3" + b"x" * 4096)


class FakeGTTSTypeFailing:
    def __init__(self, **kwargs):
        pass

    def save(self, path):
        raise ConnectionError("no internet")


class FakePyttsx3Engine:
    def __init__(self):
        self.props = {}

    def setProperty(self, name, value):
        self.props[name] = value

    def save_to_file(self, text, path):
        Path(path).write_bytes(b"RIFF" + b"y" * 4096)

    def runAndWait(self):
        pass

    def stop(self):
        pass


class TtsEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="shorts_tts_"))
        self.settings = make_settings(output_dir=self.tmp)

    def test_gtts_success(self):
        with mock.patch.object(tts_engine_module, "GTTSSynthesizer", FakeGTTSType):
            engine = TextToSpeechEngine(self.settings, make_logger())
            result = engine.synthesize("שלום עולם", self.tmp / "voiceover.mp3")
        self.assertEqual(result.engine, "gTTS")
        self.assertTrue(result.path.exists())
        self.assertGreater(result.size_bytes, 1024)
        self.assertEqual(FakeGTTSType.last_kwargs["lang"], "iw")

    def test_fallback_to_pyttsx3(self):
        fake_module = types.SimpleNamespace(init=lambda: FakePyttsx3Engine())
        with mock.patch.object(
            tts_engine_module, "GTTSSynthesizer", FakeGTTSTypeFailing
        ), mock.patch.dict(sys.modules, {"pyttsx3": fake_module}):
            engine = TextToSpeechEngine(self.settings, make_logger())
            result = engine.synthesize("שלום עולם", self.tmp / "voiceover.mp3")
        self.assertEqual(result.engine, "pyttsx3")
        # pyttsx3 שומר WAV בלבד
        self.assertEqual(result.path.suffix, ".wav")
        self.assertTrue(result.path.exists())

    def test_both_engines_fail(self):
        with mock.patch.object(
            tts_engine_module, "GTTSSynthesizer", FakeGTTSTypeFailing
        ), mock.patch.dict(sys.modules, {"pyttsx3": None}):
            engine = TextToSpeechEngine(self.settings, make_logger())
            with self.assertRaises(TTSSynthesisError):
                engine.synthesize("שלום", self.tmp / "voiceover.mp3")

    def test_empty_text_raises(self):
        engine = TextToSpeechEngine(self.settings, make_logger())
        with self.assertRaises(TTSSynthesisError):
            engine.synthesize("   ", self.tmp / "voiceover.mp3")

    def test_text_too_long_raises(self):
        engine = TextToSpeechEngine(self.settings, make_logger())
        with self.assertRaises(TTSSynthesisError):
            engine.synthesize("א" * 6000, self.tmp / "voiceover.mp3")

    def test_unsupported_language(self):
        with mock.patch.object(tts_engine_module, "GTTSSynthesizer", FakeGTTSType):
            engine = TextToSpeechEngine(
                make_settings(output_dir=self.tmp, tts_lang="xx"), make_logger()
            )
            with self.assertRaises(TTSSynthesisError):
                engine.synthesize("שלום", self.tmp / "voiceover.mp3")

    def test_empty_audio_file_rejected(self):
        class FakeTiny(FakeGTTSType):
            def save(self, path):
                Path(path).write_bytes(b"tiny")

        with mock.patch.object(tts_engine_module, "GTTSSynthesizer", FakeTiny):
            engine = TextToSpeechEngine(self.settings, make_logger())
            with self.assertRaises(TTSSynthesisError):
                engine.synthesize("שלום", self.tmp / "voiceover.mp3")


# ---------------------------------------------------------------------------
# 4. בדיקות אחסון
# ---------------------------------------------------------------------------
class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="shorts_store_"))
        self.settings = make_settings(output_dir=self.tmp)
        self.storage = ProjectStorage(self.settings, make_logger())
        self.idea = Idea(number=1, title="Top 5 Money Tips", hook="הוק", summary="תקציר")
        self.content = parse_content(CONTENT_JSON)

    def test_create_project_and_collision(self):
        paths1 = self.storage.create_project(self.idea)
        self.assertTrue(paths1.root.is_dir())
        self.assertEqual(paths1.root.name, "idea-01-top-5-money-tips")

        paths2 = self.storage.create_project(self.idea)
        self.assertEqual(paths2.root.name, "idea-01-top-5-money-tips-2")

    def test_write_content_json(self):
        paths = self.storage.create_project(self.idea)
        payload = {"idea": self.idea.to_dict()}
        out = self.storage.write_content_json(paths, payload)
        data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["idea"]["title"], "Top 5 Money Tips")

    def test_write_metadata_contains_all_sections(self):
        paths = self.storage.create_project(self.idea)
        from shorts_factory.tts_engine import SynthesisResult

        audio = SynthesisResult(path=paths.audio, engine="gTTS", size_bytes=12345)
        meta = self.storage.write_metadata(
            paths,
            idea=self.idea,
            content=self.content,
            topic="כסף וחסכון",
            model="llama-3.3-70b-versatile",
            audio=audio,
        )
        text = meta.read_text(encoding="utf-8")
        for expected in [
            "Top 5 Money Tips",
            "5 טעויות שגורמות לכם להפסיד כסף",
            "#שורטס",
            "תגית15",
            "Cinematic shot 1",
            "voiceover.mp3",
            "gTTS",
            "7) סצנות ויזואליות",
        ]:
            self.assertIn(expected, text)

    def test_metadata_without_audio(self):
        paths = self.storage.create_project(self.idea)
        meta = self.storage.write_metadata(
            paths,
            idea=self.idea,
            content=self.content,
            topic="כסף",
            model="llama-3.3-70b-versatile",
            audio=None,
        )
        self.assertIn("לא הופק קובץ שמע", meta.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 5. בדיקות קונפיגורציה
# ---------------------------------------------------------------------------
class ConfigTests(unittest.TestCase):
    def test_missing_key_raises(self):
        with self.assertRaises(ConfigurationError):
            load_settings(env={}, dotenv_path=Path("/tmp/definitely-not-here.env"))

    def test_defaults_from_env(self):
        settings = load_settings(env={"GROQ_API_KEY": "gsk_abc"}, dotenv_path=Path("no.env"))
        self.assertEqual(settings.groq_model, "llama-3.3-70b-versatile")
        self.assertEqual(settings.tts_lang, "iw")
        self.assertEqual(settings.ideas_count, 5)
        self.assertEqual(settings.warnings, [])

    def test_dotenv_file_loaded(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as fh:
            fh.write("# תגובה\nGROQ_API_KEY=gsk_from_dotenv\nSHORTS_IDEAS_COUNT=7\n")
            env_path = Path(fh.name)
        try:
            settings = load_settings(env={}, dotenv_path=env_path)
            self.assertEqual(settings.groq_api_key, "gsk_from_dotenv")
            self.assertEqual(settings.ideas_count, 7)
        finally:
            env_path.unlink(missing_ok=True)

    def test_env_not_overwritten_by_dotenv(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as fh:
            fh.write("GROQ_API_KEY=gsk_from_dotenv\n")
            env_path = Path(fh.name)
        try:
            settings = load_settings(
                env={"GROQ_API_KEY": "gsk_from_env"}, dotenv_path=env_path
            )
            self.assertEqual(settings.groq_api_key, "gsk_from_env")
        finally:
            env_path.unlink(missing_ok=True)

    def test_ideas_count_out_of_range(self):
        with self.assertRaises(ConfigurationError):
            load_settings(
                env={"GROQ_API_KEY": "gsk_abc", "SHORTS_IDEAS_COUNT": "99"},
                dotenv_path=Path("no.env"),
            )

    def test_unknown_model_warns(self):
        settings = load_settings(
            env={"GROQ_API_KEY": "gsk_abc", "GROQ_MODEL": "some-paid-model"},
            dotenv_path=Path("no.env"),
        )
        self.assertTrue(settings.warnings)

    def test_bad_tts_lang_raises(self):
        with self.assertRaises(ConfigurationError):
            load_settings(
                env={"GROQ_API_KEY": "gsk_abc", "SHORTS_TTS_LANG": "עברית!!!"},
                dotenv_path=Path("no.env"),
            )

    def test_bool_parsing(self):
        settings = load_settings(
            env={"GROQ_API_KEY": "gsk_abc", "SHORTS_TTS_SLOW": "true"},
            dotenv_path=Path("no.env"),
        )
        self.assertTrue(settings.tts_slow)

    def test_overrides_beat_env(self):
        settings = load_settings(
            env={"GROQ_API_KEY": "gsk_env", "SHORTS_IDEAS_COUNT": "3"},
            dotenv_path=Path("no.env"),
            overrides={"ideas": 6},
        )
        self.assertEqual(settings.ideas_count, 6)


# ---------------------------------------------------------------------------
# 6. בדיקות אינטגרציה (עם stub)
# ---------------------------------------------------------------------------
class StubEngine:
    """מדמה את מנוע Groq בלי רשת."""

    def __init__(self):
        self.ideas_calls = []
        self.content_calls = []

    def generate_ideas(self, topic):
        self.ideas_calls.append(topic)
        return [
            Idea(number=i, title=f"רעיון {i}", hook=f"הוק {i}", summary=f"תקציר {i}")
            for i in range(1, 6)
        ]

    def generate_content(self, idea):
        self.content_calls.append(idea)
        return parse_content(CONTENT_JSON)


class StubTts:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def synthesize(self, text, output_path):
        self.calls.append((text, output_path))
        if self.fail:
            raise TTSSynthesisError("אין אינטרנט")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ID3" + b"z" * 4096)
        from shorts_factory.tts_engine import SynthesisResult

        return SynthesisResult(path=output_path, engine="stub", size_bytes=4099)


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="shorts_e2e_"))
        self.settings = make_settings(output_dir=self.tmp)
        self.ui = TerminalUI(no_color=True)
        self.storage = ProjectStorage(self.settings, make_logger())

    def _build(self, tts_fail=False):
        return ShortsFactory(
            self.settings,
            make_logger(),
            self.ui,
            StubEngine(),
            StubTts(fail=tts_fail),
            self.storage,
        )

    def test_full_run_creates_all_files(self):
        app = self._build()
        with mock.patch("builtins.input", return_value="2"):
            exit_code = app.run(topic="כסף וחסכון")

        self.assertEqual(exit_code, EXIT_OK)
        project_dir = self.tmp / "idea-02-2"  # slug של "רעיון 2" -> "2"
        self.assertTrue((project_dir / "voiceover.mp3").is_file())
        self.assertTrue((project_dir / "Script_Metadata.txt").is_file())
        self.assertTrue((project_dir / "content.json").is_file())
        metadata = (project_dir / "Script_Metadata.txt").read_text(encoding="utf-8")
        self.assertIn("Cinematic shot 1", metadata)
        self.assertIn("רעיון 2", metadata)

    def test_run_with_tts_failure_still_writes_metadata(self):
        app = self._build(tts_fail=True)
        with mock.patch("builtins.input", return_value="1"):
            exit_code = app.run(topic="כסף")

        self.assertEqual(exit_code, EXIT_TTS)
        project_dir = self.tmp / "idea-01-1"
        self.assertFalse((project_dir / "voiceover.mp3").exists())
        self.assertTrue((project_dir / "Script_Metadata.txt").is_file())

    def test_skip_audio_mode(self):
        settings = make_settings(output_dir=self.tmp, skip_audio=True)
        app = ShortsFactory(
            settings,
            make_logger(),
            self.ui,
            StubEngine(),
            StubTts(),
            self.storage,
        )
        with mock.patch("builtins.input", return_value="3"):
            exit_code = app.run(topic="כסף")
        self.assertEqual(exit_code, EXIT_OK)
        self.assertFalse((self.tmp / "idea-03-3" / "voiceover.mp3").exists())

    def test_user_abort_on_quit(self):
        app = self._build()
        with mock.patch("builtins.input", return_value="q"):
            exit_code = app.run(topic="כסף")
        self.assertEqual(exit_code, cli_module.EXIT_USER_ABORT)


class CliMainTests(unittest.TestCase):
    def test_check_command(self):
        fake, _client = make_fake_groq([])
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(
                "os.environ", {"GROQ_API_KEY": "gsk_test_key_123"}, clear=False
            ), mock.patch.object(groq_client_module, "groq_sdk", fake), mock.patch(
                "shorts_factory.cli.GroqTextEngine.list_models",
                return_value=["llama-3.3-70b-versatile", "openai/gpt-oss-120b"],
            ):
                exit_code = main(["--check", "--output-dir", tmp])
        self.assertEqual(exit_code, EXIT_OK)

    def test_missing_key_returns_config_error(self):
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.dict(
            sys.modules, {}
        ):
            exit_code = main(["--check"])
        self.assertEqual(exit_code, cli_module.EXIT_CONFIG)

    def test_full_run_via_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub_engine = StubEngine()
            with mock.patch.dict("os.environ", {"GROQ_API_KEY": "gsk_test"}, clear=False), \
                 mock.patch("shorts_factory.cli.GroqTextEngine", return_value=stub_engine), \
                 mock.patch(
                     "shorts_factory.cli.TextToSpeechEngine",
                     return_value=StubTts(),
                 ), mock.patch("builtins.input", return_value="2"):
                exit_code = main(["--topic", "כסף", "--output-dir", tmp, "--no-color"])
        self.assertEqual(exit_code, EXIT_OK)
        self.assertEqual(len(stub_engine.ideas_calls), 1)

    def test_ai_error_returns_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict("os.environ", {"GROQ_API_KEY": "gsk_test"}, clear=False), \
                 mock.patch(
                     "shorts_factory.cli.GroqTextEngine.generate_ideas",
                     side_effect=AIEngineError("Groq לא מגיב"),
                 ):
                exit_code = main(["--topic", "כסף", "--output-dir", tmp])
        self.assertEqual(exit_code, EXIT_AI)


if __name__ == "__main__":
    unittest.main()
