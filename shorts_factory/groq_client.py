"""מנוע הטקסט החכם – עטיפה מעל Groq API (מודל Llama חינמי).

תכונות עיקריות:
* טעינה עצלה (lazy) של ספריית ``groq`` – כך שאפשר להריץ ``--help`` גם בלי להתקין.
* retries חכמים עם backoff מעריכי על 429/5xx/שגיאות רשת.
* מיפוי שגיאות Groq לחריגות פנימיות עם הודעות בעברית.
* JSON mode (:func:`_chat`) + ולידציה של התשובה ב-:mod:`shorts_factory.schemas`.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

from .config import Settings
from .errors import AIEngineError, AIResponseError, ConfigurationError
from .prompts import build_content_messages, build_ideas_messages
from .schemas import Idea, ShortContent, parse_content, parse_ideas

# הספרייה מיובאת בכוונה ברמת המודל כדי שניתן להחליף אותה בטסטים
try:  # pragma: no cover - תלוי בסביבה
    import groq as groq_sdk
except ImportError:  # pragma: no cover
    groq_sdk = None  # type: ignore[assignment]


class GroqTextEngine:
    """מנהל את כל התקשורת עם מודל ה-AI של Groq."""

    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self._settings = settings
        self._logger = logger
        self._client: Any = None

    @property
    def model(self) -> str:
        """שם המודל שנמצא בשימוש (להצגה/דיבוג)."""
        return self._settings.groq_model

    # ------------------------------------------------------------------
    # ניהול הלקוח
    # ------------------------------------------------------------------
    def _get_client(self) -> Any:
        """יוצר את לקוח Groq בפעם הראשונה ומשתמש בו מכאן ואילך."""
        if self._client is not None:
            return self._client

        if groq_sdk is None:
            raise ConfigurationError(
                "חבילת 'groq' לא מותקנת. התקן אותה עם: pip install groq"
            )
        try:
            # max_retries=0: אנחנו מנהלים retries בעצמנו (ראו _chat)
            self._client = groq_sdk.Groq(
                api_key=self._settings.groq_api_key,
                timeout=self._settings.request_timeout,
                max_retries=0,
            )
        except Exception as exc:  # noqa: BLE001 – כל כשל ביצירת הלקוח רלוונטי
            raise AIEngineError(f"יצירת לקוח Groq נכשלה: {exc}") from exc
        self._logger.debug("לקוח Groq נוצר (מודל: %s).", self._settings.groq_model)
        return self._client

    # ------------------------------------------------------------------
    # API ציבורי
    # ------------------------------------------------------------------
    def generate_ideas(self, topic: str) -> list[Idea]:
        """שלב 1: מייצר רשימת רעיונות לנושא נתון."""
        messages = build_ideas_messages(topic, self._settings.ideas_count)
        raw_response = self._chat(
            messages,
            temperature=self._settings.ideas_temperature,
            max_tokens=1500,
        )
        ideas = parse_ideas(raw_response, self._settings.ideas_count)
        self._logger.info("התקבלו %d רעיונים מה-AI לנושא '%s'.", len(ideas), topic)
        return ideas

    def generate_content(self, idea: Idea) -> ShortContent:
        """שלב 2: מייצר תסריט, פרומפטים ויזואליים וחבילת SEO לרעיון שנבחר."""
        messages = build_content_messages(
            idea,
            scenes=self._settings.scenes_min,
            tags=self._settings.tags_count,
            max_seconds=self._settings.script_max_seconds,
        )
        raw_response = self._chat(
            messages,
            temperature=self._settings.content_temperature,
            max_tokens=3000,
        )
        content = parse_content(
            raw_response,
            min_scenes=self._settings.scenes_min,
            max_scenes=self._settings.scenes_max,
            tags_count=self._settings.tags_count,
            logger=self._logger,
        )
        self._logger.info(
            "חבילת התוכן נוצרה: %d סצנות, %d תגיות, אורך משוער %.1f שניות.",
            len(content.scenes),
            len(content.tags),
            content.duration_estimate_seconds,
        )
        if content.duration_estimate_seconds > self._settings.script_max_seconds:
            self._logger.warning(
                "אורך התסריט המשוער (%.1f ש') חורג מהמגבלה (%d ש') – שקול לקצר.",
                content.duration_estimate_seconds,
                self._settings.script_max_seconds,
            )
        return content

    def list_models(self) -> list[str]:
        """מחזיר את רשימת המודלים הזמינים בחשבון (משמש ל-``--check``)."""
        client = self._get_client()
        try:
            page = client.models.list()
            return sorted(model.id for model in page.data)
        except Exception as exc:  # noqa: BLE001
            mapped, _retryable = self._map_exception(exc)
            raise mapped from exc

    # ------------------------------------------------------------------
    # ליבת התקשורת (עם retries)
    # ------------------------------------------------------------------
    def _chat(
        self, messages: list[dict[str, str]], *, temperature: float, max_tokens: int
    ) -> str:
        """שולח בקשה ל-Groq ומחזיר את תוכן התשובה (מחרוזת)."""
        client = self._get_client()
        max_retries = self._settings.max_retries

        for attempt in range(1, max_retries + 1):
            try:
                self._logger.debug(
                    "Groq: שולח בקשה (ניסיון %d/%d, מודל=%s)...",
                    attempt, max_retries, self._settings.groq_model,
                )
                response = client.chat.completions.create(
                    model=self._settings.groq_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                    timeout=self._settings.request_timeout,
                )
                content = self._extract_message_content(response)
                if not content or not content.strip():
                    raise AIResponseError("המודל החזיר תשובה ריקה.")
                return content

            except Exception as exc:  # noqa: BLE001 – כל שגיאה עובלת מיפוי
                mapped, retryable = self._map_exception(exc)
                if not retryable or attempt >= max_retries:
                    if mapped is exc:
                        raise
                    raise mapped from exc

                delay = self._settings.retry_base_delay * (2 ** (attempt - 1)) + random.uniform(
                    0.0, 1.0
                )
                self._logger.warning(
                    "%s (ניסיון %d/%d) – מנסה שוב בעוד %.1f שניות.",
                    mapped, attempt, max_retries, delay,
                )
                time.sleep(delay)

        # לא אמור להגיע לכאן לוגית, אבל נשאירים כיסוי בטוח
        raise AIEngineError("כל ניסיונות הקריאה ל-Groq נכשלו.")

    @staticmethod
    def _extract_message_content(response: Any) -> Optional[str]:
        """מחלץ את הטקסט מתשובת ה-API בבטחה (לא מניח המבנה)."""
        try:
            choices = getattr(response, "choices", None) or []
            if not choices:
                return None
            message = getattr(choices[0], "message", None)
            return getattr(message, "content", None)
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------
    # מיפוי שגיאות
    # ------------------------------------------------------------------
    def _map_exception(self, exc: Exception) -> tuple[Exception, bool]:
        """ממפה חריגה מ-Groq לחריגה פנימית + האם כדאי לנסות שוב.

        Returns:
            זוג (חריגה_פנימית, האם_לנסות_שוב)
        """
        # שגיאות שכבר בסכמת שלנו – לא נוגעים בהן
        if isinstance(exc, (AIResponseError, ConfigurationError)):
            return exc, False

        if groq_sdk is None:
            return AIEngineError(f"שגיאה לא צפויה בקריאה ל-Groq: {exc}"), False

        if isinstance(exc, groq_sdk.AuthenticationError):
            return (
                ConfigurationError(
                    "מפתח ה-API של Groq נדחה (401). ודא שהמפתח ב-GROQ_API_KEY תקין "
                    "ופעיל ב-https://console.groq.com/keys"
                ),
                False,
            )
        if isinstance(exc, groq_sdk.RateLimitError):
            return (
                AIEngineError(
                    "חריגה ממגבלת הבקשות החינמית של Groq (429). "
                    "המתן מעט או החלף מודל (ראה GROQ_MODEL)."
                ),
                True,
            )
        if isinstance(exc, (groq_sdk.APIConnectionError, groq_sdk.APITimeoutError)):
            return (
                AIEngineError(f"בעיה בתקשורת עם שרתי Groq: {exc}"),
                True,
            )
        if isinstance(exc, groq_sdk.InternalServerError):
            return (
                AIEngineError(f"שגיאה פנימית בשרתי Groq (5xx): {exc}"),
                True,
            )
        if isinstance(exc, groq_sdk.APIStatusError):
            status_code = getattr(exc, "status_code", 0) or 0
            if status_code >= 500:
                return AIEngineError(f"שגיאת שרת מ-Groq ({status_code}): {exc}"), True
            return (
                AIEngineError(
                    f"Groq דחה את הבקשה ({status_code}). ייתכן שהמודל '{self._settings.groq_model}' "
                    f"לא קיים או לא זמין בחשבון החינמי. נסה מודל אחר בעזרת GROQ_MODEL. ({exc})"
                ),
                False,
            )
        if isinstance(exc, groq_sdk.GroqError):
            return AIEngineError(f"שגיאה כללית מ-Groq: {exc}"), False

        return AIEngineError(f"שגיאה לא צפויה בקריאה ל-Groq: {exc}"), False
