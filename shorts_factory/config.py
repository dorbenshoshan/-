"""מרכז הקונפיגורציה של Shorts Factory.

הקובץ אחיד לשלושה תפקידים:

1. הגדרת שמות משתני הסביבה (Environment Variables) שהמשתמש צריך להגדיר.
2. טעינת קובץ ``.env`` אופציונלי (ללא תלות בספריית ``python-dotenv``).
3. ולידציית ההגדרות עם הודעות שגיאה ברורות בעברית.

דוגמת שימוש::

    from shorts_factory.config import load_settings
    settings = load_settings()
    print(settings.groq_model)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, MutableMapping, Optional

from .errors import ConfigurationError

# ---------------------------------------------------------------------------
# שמות משתני הסביבה (Environment Variables)
# ---------------------------------------------------------------------------
GROQ_API_KEY_ENV = "GROQ_API_KEY"
GROQ_MODEL_ENV = "GROQ_MODEL"
OUTPUT_DIR_ENV = "SHORTS_OUTPUT_DIR"
TTS_LANG_ENV = "SHORTS_TTS_LANG"
TTS_SLOW_ENV = "SHORTS_TTS_SLOW"
SKIP_AUDIO_ENV = "SHORTS_SKIP_AUDIO"
IDEAS_COUNT_ENV = "SHORTS_IDEAS_COUNT"
REQUEST_TIMEOUT_ENV = "SHORTS_REQUEST_TIMEOUT"
MAX_RETRIES_ENV = "SHORTS_MAX_RETRIES"

# ---------------------------------------------------------------------------
# ברירות מחדל
# ---------------------------------------------------------------------------
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_TTS_LANG = "iw"  # קוד השפה "iw" = עברית במנגנון של gTTS
DEFAULT_IDEAS_COUNT = 5
DEFAULT_SCRIPT_MAX_SECONDS = 50
DEFAULT_SCENES_MIN = 3
DEFAULT_SCENES_MAX = 4
DEFAULT_TAGS_COUNT = 15
DEFAULT_REQUEST_TIMEOUT = 60.0  # שניות
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY = 2.0  # שניות (צומח מעריכית בניסיונות הבאים)
DEFAULT_IDEAS_TEMPERATURE = 0.9
DEFAULT_CONTENT_TEMPERATURE = 0.7

# מודלים חינמיים באמת ב-Groq (נבדק מול המסמכים הציבוריים של Groq, אוקטובר 2026).
# הרשימה נועדה לאזהרה בלבד – Groq מוסיף מודלים מעת לעת, ולכן אין חובה להשתמש בה.
FREE_GROQ_MODELS: tuple[str, ...] = (
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "moonshotai/kimi-k2-instruct",
    "qwen/qwen3-32b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
)

MIN_IDEAS = 3
MAX_IDEAS = 8

_TRUE_VALUES = {"1", "true", "yes", "y", "on", "כן"}
_FALSE_VALUES = {"0", "false", "no", "n", "off", "לא"}


@dataclass
class Settings:
    """הגדרות המפעל של המערכת (מומלץ לבנות דרך :func:`load_settings`)."""

    groq_api_key: str = ""
    groq_model: str = DEFAULT_GROQ_MODEL
    output_dir: Path = DEFAULT_OUTPUT_DIR
    tts_lang: str = DEFAULT_TTS_LANG
    tts_slow: bool = False
    skip_audio: bool = False
    ideas_count: int = DEFAULT_IDEAS_COUNT
    ideas_temperature: float = DEFAULT_IDEAS_TEMPERATURE
    content_temperature: float = DEFAULT_CONTENT_TEMPERATURE
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_base_delay: float = DEFAULT_RETRY_BASE_DELAY
    script_max_seconds: int = DEFAULT_SCRIPT_MAX_SECONDS
    scenes_min: int = DEFAULT_SCENES_MIN
    scenes_max: int = DEFAULT_SCENES_MAX
    tags_count: int = DEFAULT_TAGS_COUNT
    no_color: bool = False
    verbose: bool = False
    # אזהרות שנאספו במהלך הטעינה (מדווחות למשתמש אחר כך, לא מפילות את התוכנית)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # תמיכה בהעברת מחרוזת במקום Path
        self.output_dir = Path(self.output_dir).expanduser()


# ---------------------------------------------------------------------------
# טעינת קובץ .env (יישום מינימלי ללא תלות חיצונית)
# ---------------------------------------------------------------------------
def _load_dotenv(path: Path, env: MutableMapping[str, str]) -> None:
    """טוען משתנים מקובץ ``.env`` פשוט, מבלי לדרוס ערכים שקיימים כבר בסביבה."""
    if not path.is_file():
        return
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        return

    for line in raw_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'").strip()
        if key and key not in env:
            env[key] = value


def _parse_bool(value: Any, default: bool = False) -> bool:
    """ממיר ערך (מחרוזת/בוליאני) לבוליאני, עם תמיכה בעברית."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    return default


def _parse_int(value: Any, name: str, default: Optional[int] = None) -> Optional[int]:
    """ממיר ערך למספר שלם, עם שגיאה ברורה בעברית אם הערך אינו תקין."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"הערך '{value}' עבור '{name}' אינו מספר תקין."
        ) from exc


def _parse_float(value: Any, name: str, default: float) -> float:
    """ממיר ערך למספר עשרוני. מחזיר את ברירת המחדל אם הערך חסר/ריק."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    try:
        return float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(
            f"הערך '{value}' עבור '{name}' אינו מספר עשרוני תקין."
        ) from exc


# ---------------------------------------------------------------------------
# הפונקציה הראשית
# ---------------------------------------------------------------------------
def load_settings(
    overrides: Optional[dict[str, Any]] = None,
    env: Optional[MutableMapping[str, str]] = None,
    dotenv_path: Optional[Path] = None,
) -> Settings:
    """בונה אובייקט :class:`Settings` ממשתני סביבה + ערכי CLI.

    Args:
        overrides: ערכים מהטרמינל (argparse) – גובר על משתני הסביבה.
        env: מיפוי משתנים (ברירת מחדל: ``os.environ``).
        dotenv_path: נתיב קובץ ``.env`` (ברירת מחדל: ``.env`` בתיקייה הנוכחית).

    Raises:
        ConfigurationError: אם מפתח ה-API חסר או שאחד הערכים אינו תקין.
    """
    env = os.environ if env is None else env
    dotenv = Path(dotenv_path) if dotenv_path else Path(".env")
    _load_dotenv(dotenv, env)

    overrides = dict(overrides or {})
    warnings: list[str] = []

    # --- מפתח ה-API (חובה) ---------------------------------------------------
    api_key = str(overrides.get("api_key") or env.get(GROQ_API_KEY_ENV) or "").strip()
    if not api_key:
        raise ConfigurationError(
            "מפתח ה-API של Groq לא נמצא.\n"
            "יש להגדיר את משתנה הסביבה GROQ_API_KEY לפני ההפעלה.\n"
            "הוראות מפורטות מופיעות להלן ובקובץ README.md."
        )
    if not api_key.startswith("gsk_"):
        warnings.append(
            f"מפתח ה-API לא מתחיל ב-'gsk_' – ייתכן שהעתקת אותו לא נכון (התקבל: {api_key[:6]}...)."
        )

    # --- מודל ----------------------------------------------------------------
    model = str(overrides.get("model") or env.get(GROQ_MODEL_ENV) or DEFAULT_GROQ_MODEL).strip()
    if not model:
        model = DEFAULT_GROQ_MODEL
    if model not in FREE_GROQ_MODELS:
        warnings.append(
            f"המודל '{model}' אינו ברשימת המודלים החינמיים המאומתים "
            f"({', '.join(FREE_GROQ_MODELS)}). אם הוא דורש תשלום – תחויב."
        )

    # --- תיקיית פלט ----------------------------------------------------------
    output_raw = overrides.get("output_dir") or env.get(OUTPUT_DIR_ENV) or str(DEFAULT_OUTPUT_DIR)
    output_dir = Path(str(output_raw)).expanduser()

    # --- קריינות -------------------------------------------------------------
    tts_lang = str(overrides.get("tts_lang") or env.get(TTS_LANG_ENV) or DEFAULT_TTS_LANG).strip()
    if not tts_lang or len(tts_lang) > 6 or not tts_lang.replace("-", "").isalpha():
        raise ConfigurationError(
            f"קוד שפת הקריינות '{tts_lang}' אינו תקין (עברית = 'iw', אנגלית = 'en')."
        )
    tts_slow = _parse_bool(overrides.get("slow_tts") or env.get(TTS_SLOW_ENV), False)
    skip_audio = _parse_bool(overrides.get("skip_audio") or env.get(SKIP_AUDIO_ENV), False)

    # --- מספר רעיונות --------------------------------------------------------
    ideas_count = _parse_int(
        overrides.get("ideas") or env.get(IDEAS_COUNT_ENV), "SHORTS_IDEAS_COUNT", DEFAULT_IDEAS_COUNT
    )
    if ideas_count is None:  # safety
        ideas_count = DEFAULT_IDEAS_COUNT
    if not (MIN_IDEAS <= ideas_count <= MAX_IDEAS):
        raise ConfigurationError(
            f"מספר הרעיונות חייב להיות בין {MIN_IDEAS} ל-{MAX_IDEAS} (התקבל: {ideas_count})."
        )

    # --- רשת/retries ----------------------------------------------------------
    request_timeout = _parse_float(
        env.get(REQUEST_TIMEOUT_ENV), REQUEST_TIMEOUT_ENV, DEFAULT_REQUEST_TIMEOUT
    )
    if request_timeout <= 0:
        raise ConfigurationError(f"{REQUEST_TIMEOUT_ENV} חייב להיות גדול מ-0.")
    max_retries = _parse_int(env.get(MAX_RETRIES_ENV), MAX_RETRIES_ENV, DEFAULT_MAX_RETRIES)
    if max_retries is None or max_retries < 1:
        raise ConfigurationError(f"{MAX_RETRIES_ENV} חייב להיות לפחות 1.")

    no_color = _parse_bool(overrides.get("no_color") or env.get("NO_COLOR"), False)
    verbose = bool(overrides.get("verbose"))

    return Settings(
        groq_api_key=api_key,
        groq_model=model,
        output_dir=output_dir,
        tts_lang=tts_lang,
        tts_slow=tts_slow,
        skip_audio=skip_audio,
        ideas_count=ideas_count,
        request_timeout=request_timeout,
        max_retries=max_retries,
        no_color=no_color,
        verbose=verbose,
        warnings=warnings,
    )
