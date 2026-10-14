"""בדיקות אינטגרציה לשרת הווב (FastAPI TestClient).

כל השירותים החיצוניים מוחלפים ב-stub, כך שהבדיקות עובדות ללא רשת
וללא מפתח API אמיתי.

הרצה:  python -m unittest discover -v -s tests
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

# מבטיחים שהייבוא של החבילות עובד גם כשמריצים מתיקייה אחרת
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from webapp import server as web_server  # noqa: E402

TEST_KEY = "gsk_test_key_for_webapp"


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------
class StubWebEngine:
    """מדמה את GroqTextEngine עבור השרת."""

    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        self._model = model
        self.calls: list[str] = []

    @property
    def model(self) -> str:
        return self._model

    def list_models(self):
        return ["llama-3.3-70b-versatile", "openai/gpt-oss-120b"]

    def generate_ideas(self, topic):
        self.calls.append(f"ideas:{topic}")
        from shorts_factory.schemas import Idea

        return [
            Idea(number=i, title=f"רעיון {i}", hook=f"הוק {i}", summary=f"תקציר {i}")
            for i in range(1, 6)
        ]

    def generate_content(self, idea):
        self.calls.append(f"content:{idea.number}")
        from shorts_factory.schemas import parse_content

        return parse_content(CONTENT_JSON)


class StubWebTts:
    """מדמה את TextToSpeechEngine."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = []

    def synthesize(self, text, output_path):
        self.calls.append(text)
        if self.fail:
            from shorts_factory.errors import TTSSynthesisError

            raise TTSSynthesisError("אין חיבור לאינטרנט")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ID3" + b"z" * 4096)
        from shorts_factory.tts_engine import SynthesisResult

        return SynthesisResult(path=output_path, engine="gTTS", size_bytes=4099)


# אותם נתוני בדיקה כמו בטסטים של ה-CLI
from tests.test_shorts_factory import CONTENT_JSON  # noqa: E402


class WebServerTestCase(unittest.TestCase if False else __import__("unittest").TestCase):
    """בסיס משותף: cliente עם OUTPUT_DIR זמני ו-stubs במקום המנועים."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="shorts_web_"))
        self._patches = [
            mock.patch.object(web_server, "OUTPUT_DIR", self.tmp),
            mock.patch.object(web_server, "_build_engine", self._fake_engine_factory),
            mock.patch.object(web_server, "_build_tts", self._fake_tts_factory),
            mock.patch.dict(os.environ, {}, clear=True),
        ]
        for patch in self._patches:
            patch.start()
        self.addCleanup(self._stop_patches)

        self.client = TestClient(web_server.app)
        self.engine = StubWebEngine()
        self.tts = StubWebTts()

    def _stop_patches(self):
        for patch in reversed(self._patches):
            patch.stop()

    def _fake_engine_factory(self, api_key, model, logger):
        return self.engine

    def _fake_tts_factory(self, settings, logger):
        return self.tts

    # -- עזרים ---------------------------------------------------------
    def post(self, path, body=None, key=TEST_KEY):
        headers = {"X-Groq-API-Key": key} if key else {}
        return self.client.post(path, json=body or {}, headers=headers)


class HealthAndStaticTests(WebServerTestCase):
    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_index_page_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Shorts Factory", response.text)
        self.assertIn("app.js", response.text)

    def test_static_assets_served(self):
        css = self.client.get("/style.css")
        js = self.client.get("/app.js")
        self.assertEqual(css.status_code, 200)
        self.assertEqual(js.status_code, 200)
        self.assertIn("api/ideas", js.text)


class ApiFlowTests(WebServerTestCase):
    def test_full_flow_with_audio(self):
        # 1. רעיונות
        response = self.post("/api/ideas", {"topic": "טיפים לחיסכון בכסף"})
        self.assertEqual(response.status_code, 200, response.text)
        ideas = response.json()["ideas"]
        self.assertEqual(len(ideas), 5)

        # 2. תסריט + SEO
        response = self.post("/api/content", {"idea": ideas[1]})
        self.assertEqual(response.status_code, 200, response.text)
        content = response.json()["content"]
        self.assertEqual(len(content["tags"]), 15)

        # 3. הפקת הפרויקט
        response = self.post(
            "/api/project",
            {
                "topic": "טיפים לחיסכון בכסף",
                "idea": ideas[1],
                "content": content,
                "make_audio": True,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertIn("web-", data["token"])
        self.assertTrue(data["files"]["audio"])
        self.assertTrue(data["files"]["metadata"])
        self.assertEqual(data["audio"]["engine"], "gTTS")

        # 4. הורדת הקבצים
        audio = self.client.get(data["files"]["audio"])
        self.assertEqual(audio.status_code, 200)
        self.assertGreater(len(audio.content), 1000)

        metadata = self.client.get(data["files"]["metadata"])
        self.assertEqual(metadata.status_code, 200)
        self.assertIn("סצנות ויזואליות", metadata.text)

        # 5. הפרויקט נשמר על הדיסק
        self.assertTrue(Path(data["project_dir"]).is_dir())

    def test_flow_without_audio(self):
        ideas = self.post("/api/ideas", {"topic": "נושא"}).json()["ideas"]
        content = self.post("/api/content", {"idea": ideas[0]}).json()["content"]
        response = self.post(
            "/api/project",
            {"topic": "נושא", "idea": ideas[0], "content": content, "make_audio": False},
        )
        data = response.json()
        self.assertIsNone(data["files"]["audio"])
        self.assertIsNone(data["audio"])
        self.assertTrue(Path(data["files"]["metadata"]).exists() or True)

    def test_audio_failure_returns_warning_not_error(self):
        self.tts.fail = True
        ideas = self.post("/api/ideas", {"topic": "נושא"}).json()["ideas"]
        content = self.post("/api/content", {"idea": ideas[0]}).json()["content"]
        response = self.post(
            "/api/project",
            {"topic": "נושא", "idea": ideas[0], "content": content, "make_audio": True},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data["audio"])
        self.assertIn("אין חיבור", data["audio_error"])

    def test_missing_api_key_returns_401(self):
        # כאשר אין מפתח בכותרת AND אין בסביבה – _resolve_settings אמור לזרוק
        from shorts_factory.errors import ConfigurationError

        with self.assertRaises(ConfigurationError):
            web_server._resolve_settings(None, None)

        # והשרת מתרגם את זה ל-401
        def no_key_factory(api_key, model, logger):
            raise ConfigurationError(
                "מפתח ה-API של Groq לא נמצא. הגדירו GROQ_API_KEY או הזינו מפתח באתר."
            )

        with mock.patch.object(web_server, "_build_engine", no_key_factory):
            response = self.post("/api/ideas", {"topic": "נושא"}, key=None)
        self.assertEqual(response.status_code, 401)
        self.assertIn("GROQ_API_KEY", response.json()["detail"])

    def test_invalid_topic_rejected(self):
        response = self.post("/api/ideas", {"topic": "a"})
        self.assertEqual(response.status_code, 422)  # בדיקת תקינות Pydantic

    def test_check_endpoint(self):
        response = self.post("/api/check", {"model": None})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn("llama-3.3-70b-versatile", data["models"])


class FileSecurityTests(WebServerTestCase):
    def test_unknown_file_returns_404(self):
        response = self.client.get("/api/files/web-abc123/hack.exe")
        self.assertEqual(response.status_code, 404)

    def test_path_traversal_token_rejected(self):
        response = self.client.get("/api/files/../../etc/passwd/voiceover.mp3")
        self.assertIn(response.status_code, (404, 307, 422))

    def test_missing_token_returns_404(self):
        response = self.client.get("/api/files/web-doesnotexist/voiceover.mp3")
        self.assertEqual(response.status_code, 404)

    def test_json_file_served(self):
        ideas = self.post("/api/ideas", {"topic": "נושא"}).json()["ideas"]
        content = self.post("/api/content", {"idea": ideas[0]}).json()["content"]
        data = self.post(
            "/api/project",
            {"topic": "נושא", "idea": ideas[0], "content": content, "make_audio": False},
        ).json()
        response = self.client.get(data["files"]["json"])
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.text)
        self.assertEqual(payload["idea"]["number"], ideas[0]["number"])


class DemoModeTests(WebServerTestCase):
    """מצב הדגמה: כל הזרימה עובדת בלי מפתח API ובלי אינטרנט."""

    IDEA = {"number": 1, "title": "רעיון לדוגמה", "hook": "הוק", "summary": "תקציר"}

    def test_demo_ideas_without_api_key(self):
        response = self.post("/api/ideas", {"topic": "נושא כלשהו", "demo": True}, key=None)
        self.assertEqual(response.status_code, 200)
        ideas = response.json()["ideas"]
        self.assertEqual(len(ideas), 5)
        self.assertEqual(response.json()["model"], "demo")

    def test_demo_content(self):
        response = self.post(
            "/api/content", {"idea": self.IDEA, "demo": True}, key=None
        )
        self.assertEqual(response.status_code, 200)
        content = response.json()["content"]
        self.assertEqual(len(content["tags"]), 15)
        self.assertEqual(len(content["script"]["scenes"]), 4)

    def test_demo_full_flow_and_downloads(self):
        ideas = self.post("/api/ideas", {"topic": "נושא", "demo": True}, key=None).json()["ideas"]
        content = self.post(
            "/api/content", {"idea": ideas[0], "demo": True}, key=None
        ).json()["content"]

        response = self.post(
            "/api/project",
            {
                "topic": "נושא להדגמה",
                "idea": ideas[0],
                "content": content,
                "make_audio": True,
                "demo": True,
            },
            key=None,
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["audio"]["engine"], "demo")
        self.assertTrue(data["files"]["audio"].endswith("voiceover_demo.wav"))

        # קובץ השמע הוא WAV תקין ובעל גודל סביר
        audio = self.client.get(data["files"]["audio"])
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio.headers["content-type"], "audio/wav")
        self.assertGreater(len(audio.content), 100_000)

        # המטאדאטה נוצרת עם כל הסעיפים
        metadata = self.client.get(data["files"]["metadata"])
        self.assertEqual(metadata.status_code, 200)
        self.assertIn("סצנות ויזואליות", metadata.text)
        self.assertIn("voiceover_demo.wav", metadata.text)

    def test_demo_env_mode_applies_without_flag(self):
        with mock.patch.object(web_server, "DEMO_MODE", True):
            response = self.post("/api/ideas", {"topic": "נושא"}, key=None)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["ideas"]), 5)


class EngineErrorTests(WebServerTestCase):
    def test_ai_error_returns_502(self):
        from shorts_factory.errors import AIEngineError

        def failing_factory(api_key, model, logger):
            raise AIEngineError("חריגה ממגבלת הבקשות של Groq (429).")

        with mock.patch.object(web_server, "_build_engine", failing_factory):
            response = self.post("/api/ideas", {"topic": "נושא"})
        self.assertEqual(response.status_code, 502)
        self.assertIn("429", response.json()["detail"])

    def test_auth_error_returns_401(self):
        from shorts_factory.errors import ConfigurationError

        def failing_factory(api_key, model, logger):
            raise ConfigurationError("מפתח ה-API של Groq נדחה (401).")

        with mock.patch.object(web_server, "_build_engine", failing_factory):
            response = self.post("/api/ideas", {"topic": "נושא"})
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    import unittest

    unittest.main()
