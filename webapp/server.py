"""שרת הווב של Shorts Factory (FastAPI + Uvicorn).

================================================================================
 מה השרת הזה עושה
================================================================================
הוא "גשר" בין הדפדפן לשירותים החינמיים:

  דפדפן  ──POST /api/ideas (עם המפתח בכותרת X-Groq-API-Key)──▶  שרת  ──▶  Groq API
         ◀────────── 5 רעיונות ────────────────────────────        (מודל Llama חינמי)

  דפדפן  ──POST /api/content ──▶  שרת  ──▶  Groq  (תסריט + פרומפטים + SEO)
  דפדפן  ──POST /api/project ──▶  שרת  ──▶  gTTS  (קריינות MP3) + כתיבת הקבצים
  דפדפן  ──GET  /api/files/... ──▶  שרת  ──▶  הורדת voiceover.mp3 / Script_Metadata.txt

למה בכלל צריך שרת (ולא לקרוא ל-Groq ישירות מהדפדפן)?
  1. Groq לא תומך ב-CORS – קריאה ישירה מהדפדפן תיחסם על ידי הדפדפן.
  2. המפתח נשלח רק לשרת *המקומי שלך* (localhost), לא לאף צד שלישי.
  3. gTTS ויצירת הקבצים דורשות גישה למערכת הקבצים – שקיימת רק בצד השרת.

אבטחה:
  • המפתח מתקבל בכותרת HTTP ומשמש רק לזמן הבקשה – אינו נשמר לדיסק ואינו נכתב ללוגים.
  • שמות הקבצים להורדה עוברים רשימה לבנה + בדיקת מניעת Path Traversal.
  • אם תפרסו את השרת לציבור – הוסיפו אימות משתמשים (מחוץ להיקף המדריך הזה).

הרצה:
  python webapp/server.py                 # או:
  uvicorn webapp.server:app --reload      # לפיתוח
"""

from __future__ import annotations

import logging
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# מבטיח שהייבוא של shorts_factory עובד גם כשמריצים מ-webapp/ (python webapp/server.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from shorts_factory.config import Settings, load_settings
from shorts_factory.errors import (
    AIEngineError,
    AIResponseError,
    ConfigurationError,
    ShortsFactoryError,
    StorageError,
    TTSSynthesisError,
)
from shorts_factory.groq_client import GroqTextEngine
from shorts_factory.logger import setup_logger
from shorts_factory.schemas import Idea, ShortContent
from shorts_factory.storage import ProjectStorage
from shorts_factory.tts_engine import SynthesisResult, TextToSpeechEngine
from webapp.demo_data import DEMO_CONTENT, DEMO_IDEAS, write_demo_wav

# ---------------------------------------------------------------------------
# קבועים
# ---------------------------------------------------------------------------
API_KEY_HEADER = "X-Groq-API-Key"
TOKEN_PREFIX = "web-"
TOKEN_PATTERN = re.compile(r"^web-[a-zA-Z0-9]{6,32}$")
ALLOWED_FILENAMES = {
    "voiceover.mp3",
    "voiceover.wav",
    "voiceover_demo.wav",
    "Script_Metadata.txt",
    "content.json",
}
MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
}

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
OUTPUT_DIR = Path(os.environ.get("SHORTS_OUTPUT_DIR", "output")).expanduser().resolve()

# מצב הדגמה: מאפשר לבדוק את כל זרימת האתר גם בלי גישה ל-Groq/gTTS.
# מופעל ע"י משתנה הסביבה SHORTS_DEMO_MODE=1 או ע"י סימון התיבה באתר.
DEMO_MODE = os.environ.get("SHORTS_DEMO_MODE", "").strip().lower() in {"1", "true", "yes", "on"}

logger = setup_logger(log_file=None)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """הכנות בעליית השרת: יצירת תיקיית הפלט."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Shorts Factory Web עלה על רגליים | תיקיית פלט: %s", OUTPUT_DIR)
    yield
    logger.info("Shorts Factory Web כובה.")

# ---------------------------------------------------------------------------
# מודלי בקשה/תגובה
# ---------------------------------------------------------------------------
class TopicRequest(BaseModel):
    """בקשה לייצור רעיונות."""

    topic: str = Field(..., min_length=2, max_length=300)
    model: Optional[str] = None
    demo: bool = False


class IdeaPayload(BaseModel):
    """רעיון שנשלח מהדפדפן בחזרה."""

    number: int = 1
    title: str = Field(..., min_length=1)
    hook: str = ""
    summary: str = ""


class ContentRequest(BaseModel):
    """בקשה לייצור תסריט/פרומפטים/SEO."""

    idea: IdeaPayload
    model: Optional[str] = None
    demo: bool = False


class ProjectRequest(BaseModel):
    """בקשה להפקת הפרויקט המלא (אודיו + קבצים)."""

    topic: str = Field(..., min_length=2, max_length=300)
    idea: IdeaPayload
    content: dict[str, Any]
    make_audio: bool = True
    model: Optional[str] = None
    demo: bool = False


class CheckRequest(BaseModel):
    """בדיקת תקינות המפתח."""

    model: Optional[str] = None


# ---------------------------------------------------------------------------
# אפליקציה
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Shorts Factory Web",
    description="מערכת אוטומציה חינמית ליצירת חומרי גלם ל-YouTube Shorts",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# פונקציות עזר (ניתנות להחלפה בטסטים)
# ---------------------------------------------------------------------------
def _resolve_settings(
    api_key: Optional[str], model: Optional[str], *, subdir: Optional[str] = None
) -> Settings:
    """בונה Settings לבקשה הנוכחית.

    סדר העדיפויות: מפתח מהכותרת ← משתנה הסביבה GROQ_API_KEY.
    אם לא סופק מפתח כלל – נזרקת ConfigurationError (מתורגמת ל-401).
    """
    output_dir = OUTPUT_DIR / subdir if subdir else OUTPUT_DIR
    return load_settings(
        overrides={"api_key": api_key, "model": model, "output_dir": output_dir, "no_color": True},
        dotenv_path=BASE_DIR.parent / ".env",
    )


def _build_engine(api_key: Optional[str], model: Optional[str], log: logging.Logger) -> GroqTextEngine:
    """יוצר מנוע Groq עבור בקשה (מחליף לטסטים)."""
    settings = _resolve_settings(api_key, model)
    return GroqTextEngine(settings, log)


def _build_tts(settings: Settings, log: logging.Logger) -> TextToSpeechEngine:
    """יוצר מנוע TTS עבור בקשה (מחליף לטסטים)."""
    return TextToSpeechEngine(settings, log)


def _http_error(exc: Exception) -> HTTPException:
    """מתרגם חריגה פנימית לתשובת HTTP עם הודעה בעברית."""
    if isinstance(exc, ConfigurationError):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, (AIResponseError,)):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, (AIEngineError, TTSSynthesisError, StorageError, ShortsFactoryError)):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail=f"שגיאה לא צפויה בשרת: {exc}")


def _idea_from_payload(payload: IdeaPayload) -> Idea:
    return Idea(
        number=payload.number,
        title=payload.title,
        hook=payload.hook,
        summary=payload.summary,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/health")
def api_health() -> dict[str, Any]:
    """בדיקת תקינות + האם לשרת יש מפתח מובנה בסביבה."""
    return {
        "status": "ok",
        "app": "Shorts Factory Web",
        "server_has_env_key": bool(os.environ.get("GROQ_API_KEY", "").strip()),
        "demo_mode": DEMO_MODE,
    }


@app.post("/api/check")
def api_check(payload: CheckRequest, x_groq_api_key: Optional[str] = Header(default=None)) -> dict[str, Any]:
    """בודק את המפתח מול Groq ומחזיר את המודלים הזמינים בחשבון."""
    try:
        engine = _build_engine(x_groq_api_key, payload.model, logger)
        models = engine.list_models()
    except Exception as exc:  # noqa: BLE001 – ממופים מיד להמשך
        raise _http_error(exc) from exc
    return {"ok": True, "model": engine.model, "models": models}


@app.post("/api/ideas")
def api_ideas(
    payload: TopicRequest, x_groq_api_key: Optional[str] = Header(default=None)
) -> dict[str, Any]:
    """שלב 1: מייצר 5 רעיונות לנושא שהמשתמש הזין."""
    try:
        if payload.demo or DEMO_MODE:
            logger.info("מצב הדגמה: מחזיר 5 רעיונות לדוגמה (בלי קריאה ל-Groq).")
            return {"topic": payload.topic, "model": "demo", "ideas": DEMO_IDEAS}
        engine = _build_engine(x_groq_api_key, payload.model, logger)
        ideas = engine.generate_ideas(payload.topic)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return {
        "topic": payload.topic,
        "model": engine.model,
        "ideas": [idea.to_dict() for idea in ideas],
    }


@app.post("/api/content")
def api_content(
    payload: ContentRequest, x_groq_api_key: Optional[str] = Header(default=None)
) -> dict[str, Any]:
    """שלב 2: מייצר תסריט, פרומפטים ויזואליים וחבילת SEO לרעיון שנבחר."""
    try:
        if payload.demo or DEMO_MODE:
            logger.info("מצב הדגמה: מחזיר תסריט + פרומפטים + SEO לדוגמה (בלי קריאה ל-Groq).")
            return {"content": DEMO_CONTENT}
        engine = _build_engine(x_groq_api_key, payload.model, logger)
        content = engine.generate_content(_idea_from_payload(payload.idea))
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return {"content": content.to_dict()}


@app.post("/api/project")
def api_project(
    payload: ProjectRequest, x_groq_api_key: Optional[str] = Header(default=None)
) -> dict[str, Any]:
    """שלבים 3+4: מפיק את קובץ הקריינות ואת כל קבצי הפרויקט, ומחזיר קישורים להורדה."""
    token = TOKEN_PREFIX + uuid.uuid4().hex[:12]
    audio_result: Optional[SynthesisResult] = None
    audio_error: Optional[str] = None

    try:
        demo = payload.demo or DEMO_MODE
        if demo:
            # במצב הדגמה אין צורך במפתח API – בונים Settings ישירות
            settings = Settings(
                groq_api_key="demo",
                groq_model="demo",
                output_dir=OUTPUT_DIR / token,
                no_color=True,
            )
        else:
            settings = _resolve_settings(x_groq_api_key, payload.model, subdir=token)
        content = ShortContent.from_dict(payload.content)
        idea = _idea_from_payload(payload.idea)

        storage = ProjectStorage(settings, logger)
        paths = storage.create_project(idea)
        storage.write_content_json(
            paths,
            {
                "topic": payload.topic,
                "idea": idea.to_dict(),
                "content": content.to_dict(),
                "model": "demo" if demo else settings.groq_model,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            },
        )

        if demo:
            # מקריאים קובץ WAV אמיתי (6 שניות) שנוצר מקומית – כדי שהנגן
            # וההורדות באתר יעבדו במלואם גם בלי gTTS
            if payload.make_audio:
                demo_audio_path = paths.root / "voiceover_demo.wav"
                write_demo_wav(demo_audio_path)
                audio_result = SynthesisResult(
                    path=demo_audio_path, engine="demo", size_bytes=demo_audio_path.stat().st_size
                )
                logger.info("מצב הדגמה: נוצר קובץ שמע לדוגמה (%d בתים).", audio_result.size_bytes)
        elif payload.make_audio:
            try:
                tts = _build_tts(settings, logger)
                audio_result = tts.synthesize(content.script_text, paths.audio)
            except TTSSynthesisError as exc:
                # כישלון האודיו לא מפיל את כל הבקשה – מחזירים אזהרה
                audio_error = str(exc)
                logger.warning("הפקת האודיו נכשלה: %s", exc)

        metadata_path = storage.write_metadata(
            paths,
            idea=idea,
            content=content,
            topic=payload.topic,
            model="demo" if demo else settings.groq_model,
            audio=audio_result,
        )

        files: dict[str, Optional[str]] = {
            "metadata": f"/api/files/{token}/{metadata_path.name}",
            "json": f"/api/files/{token}/{paths.content_json.name}",
            "audio": (
                f"/api/files/{token}/{audio_result.path.name}" if audio_result else None
            ),
        }
        return {
            "token": token,
            "project_dir": str(paths.root),
            "files": files,
            "audio": (
                {
                    "engine": audio_result.engine,
                    "size_bytes": audio_result.size_bytes,
                    "filename": audio_result.path.name,
                }
                if audio_result
                else None
            ),
            "audio_error": audio_error,
        }

    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc


@app.get("/api/files/{token}/{filename}")
def api_file(token: str, filename: str) -> FileResponse:
    """מגיש קבצי פרויקט להורדה (voiceover / Script_Metadata.txt / content.json)."""
    if not TOKEN_PATTERN.match(token) or filename not in ALLOWED_FILENAMES:
        raise HTTPException(status_code=404, detail="הקובץ המבוקש לא נמצא.")

    project_root = (OUTPUT_DIR / token).resolve()
    if not project_root.is_dir():
        raise HTTPException(status_code=404, detail="הפרויקט המבוקש לא נמצא.")

    matches = sorted(project_root.rglob(filename))
    if not matches:
        raise HTTPException(status_code=404, detail="הקובץ המבוקש לא נמצא.")

    file_path = matches[0].resolve()
    # הגנה כפולה מפני Path Traversal: הקובץ חייב להיות בתוך תיקיית הפלט
    if OUTPUT_DIR not in file_path.parents:
        raise HTTPException(status_code=404, detail="הקובץ המבוקש לא נמצא.")

    media_type = MEDIA_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
    return FileResponse(path=file_path, filename=filename, media_type=media_type)


# ---------------------------------------------------------------------------
# קבצים סטטיים (מתמוצעים בסוף – אחרי כל ה-API)
# ---------------------------------------------------------------------------
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


# ---------------------------------------------------------------------------
# הרצה ישירה: python webapp/server.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "webapp.server:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )
