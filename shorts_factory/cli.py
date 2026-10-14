"""תזמורת התהליך + נקודת הכניסה הראשית (CLI).

הקובץ מחבר בין כל המודולים להרצה אחת מסודרת:

1. טעינת הגדרות ממשתני הסביבה (+ ``.env`` אופציונלי).
2. שלב 1: ייצור 5 רעיונות ב-Groq ובחירת הרעיון המנצח.
3. שלב 2: ייצור תסריט (עד 50 שניות), פרומפטים ויזואליים באנגלית וחבילת SEO.
4. שלב 3: הפקת קריינות ל-MP3 עם gTTS (חינם).
5. שלב 4: כתיבת ``Script_Metadata.txt`` + ``content.json`` בתיקיית הרעיון.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import __version__
from .config import (
    DEFAULT_GROQ_MODEL,
    DEFAULT_IDEAS_COUNT,
    FREE_GROQ_MODELS,
    MAX_IDEAS,
    MIN_IDEAS,
    Settings,
    load_settings,
)
from .errors import (
    AIEngineError,
    AIResponseError,
    ConfigurationError,
    ShortsFactoryError,
    StorageError,
    TTSSynthesisError,
    UserAbortError,
)
from .groq_client import GroqTextEngine
from .logger import setup_logger
from .storage import ProjectStorage
from .tts_engine import SynthesisResult, TextToSpeechEngine
from .ui import TerminalUI

APP_NAME = "Shorts Factory"

# ---------------------------------------------------------------------------
# קודי יציאה (קונבנציה סטנדרטית)
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_AI = 2
EXIT_TTS = 3
EXIT_STORAGE = 4
EXIT_USER_ABORT = 130
EXIT_UNEXPECTED = 5

# המפתחות מ-argparse שגוברים על משתני הסביבה
OVERRIDE_KEYS = (
    "topic",
    "ideas",
    "model",
    "output_dir",
    "tts_lang",
    "slow_tts",
    "skip_audio",
    "no_color",
    "verbose",
)

EXAMPLES = """
דוגמאות להרצה:
  python main.py                                  # מצב אינטראקטיבי מלא
  python main.py -t "טיפים לחיסכון בכסף"           # עם נושא מראש
  python main.py -t "כושר ביתי" -n 5 -o ./my_shorts
  python main.py --skip-audio -t "בישול מהיר"      # בלי להפיק אודיו
  python main.py --check                           # בדיקת מפתח API ומודלים
  GROQ_MODEL=openai/gpt-oss-120b python main.py    # בחירת מודל חינמי אחר
"""


# ---------------------------------------------------------------------------
# תזמורת התהליך
# ---------------------------------------------------------------------------
class ShortsFactory:
    """מריץ את 4 השלבים של המערכת לפי הסדר."""

    def __init__(
        self,
        settings: Settings,
        logger: logging.Logger,
        ui: TerminalUI,
        engine: GroqTextEngine,
        tts: TextToSpeechEngine,
        storage: ProjectStorage,
    ) -> None:
        self._settings = settings
        self._logger = logger
        self._ui = ui
        self._engine = engine
        self._tts = tts
        self._storage = storage

    def run(self, topic: Optional[str] = None) -> int:
        """מפעיל את כל התהליך. מחזיר קוד יציאה (0 = הצלחה)."""
        ui = self._ui
        try:
            if topic is None:
                topic = ui.prompt_topic()

            # --- שלב 1: רעיונות ---
            ui.step(1, "יצירת רעיונות וכותרות קליטות")
            self._logger.info("מייצר %d רעיונות לנושא: %s", self._settings.ideas_count, topic)
            ideas = self._engine.generate_ideas(topic)
            ui.show_ideas(ideas)
            choice = ui.prompt_choice(len(ideas))
            idea = ideas[choice - 1]
            ui.success(f"נבחר הרעיון #{choice}: {idea.title}")

            # --- שלב 2: תסריט + פרומפטים + SEO ---
            ui.step(2, "יצירת תסריט, פרומפטים לווידאו ו-SEO")
            content = self._engine.generate_content(idea)
            ui.show_content_preview(content)

            # --- הכנה לאחסון ---
            paths = self._storage.create_project(idea)
            payload: dict[str, Any] = {
                "topic": topic,
                "idea": idea.to_dict(),
                "content": content.to_dict(),
                "model": self._settings.groq_model,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
            }
            self._storage.write_content_json(paths, payload)

            # --- שלב 3: אודיו ---
            ui.step(3, "הפקת קריינות (MP3)")
            audio_result: Optional[SynthesisResult] = None
            tts_failed = False
            if self._settings.skip_audio:
                ui.warn("דילוג על הפקת האודיו (הדגל --skip-audio הוגדר).")
            else:
                try:
                    audio_result = self._tts.synthesize(content.script_text, paths.audio)
                    ui.success(
                        f"קובץ השמע נשמר: {audio_result.path} (מנגנון: {audio_result.engine})"
                    )
                except TTSSynthesisError as exc:
                    tts_failed = True
                    self._logger.error("הפקת האודיו נכשלה: %s", exc)
                    ui.error(f"הפקת האודיו נכשלה: {exc}")

            # --- שלב 4: מטאדאטה ---
            ui.step(4, "שמירת מטאדאטה וארגון הקבצים")
            metadata_path = self._storage.write_metadata(
                paths,
                idea=idea,
                content=content,
                topic=topic,
                model=self._settings.groq_model,
                audio=audio_result,
            )
            ui.print_final_summary(
                paths=paths,
                content=content,
                audio=audio_result,
                metadata_path=metadata_path,
            )

            if tts_failed:
                return EXIT_TTS
            return EXIT_OK

        except UserAbortError as exc:
            ui.warn(f"התהליך בוטל: {exc}")
            return EXIT_USER_ABORT
        except (AIEngineError, AIResponseError) as exc:
            ui.error(f"שגיאה במנוע ה-AI: {exc}")
            return EXIT_AI
        except StorageError as exc:
            ui.error(f"שגיאת אחסון: {exc}")
            return EXIT_STORAGE
        except ShortsFactoryError as exc:  # גיבוי כללי לחריגות הצפויות
            ui.error(f"שגיאה במערכת: {exc}")
            return EXIT_UNEXPECTED


# ---------------------------------------------------------------------------
# בדיקת חיבור
# ---------------------------------------------------------------------------
def _run_check(settings: Settings, logger: logging.Logger, ui: TerminalUI) -> int:
    """בודק את מפתח ה-API ומדפיס את המודלים הזמינים בחשבון."""
    ui.info("בודק חיבור ל-Groq...")
    engine = GroqTextEngine(settings, logger)
    try:
        models = engine.list_models()
    except ConfigurationError as exc:
        ui.error(str(exc))
        ui.print_key_setup_help()
        return EXIT_CONFIG
    except ShortsFactoryError as exc:
        ui.error(str(exc))
        return EXIT_AI

    ui.success(f"החיבור ל-Groq הצליח! זוהו {len(models)} מודלים בחשבון:")
    for model_id in models:
        marker = "  ✅ חינמי" if model_id in FREE_GROQ_MODELS else ""
        print(f"    • {model_id}{marker}")
    ui.info(f"המודל הנבחר להרצה: {settings.groq_model}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    """בונה את מנתח הארגומנטים של שורת הפקודה."""
    parser = argparse.ArgumentParser(
        prog="shorts-factory",
        description=(
            "מערכת אוטומציה חינמית (100% ללא תשלום) ליצירת חומרי גלם ל-YouTube Shorts: "
            "רעיונות, תסריט, פרומפטים לווידאו, SEO וקריינות MP3."
        ),
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--topic",
        "-t",
        default=None,
        metavar="נושא",
        help="נושא כללי ל-Shorts (אם לא יסופק – המסך ישאל אותו)",
    )
    parser.add_argument(
        "--ideas",
        "-n",
        type=int,
        default=None,
        metavar="N",
        help=f"מספר הרעיונות לייצור (ברירת מחדל: {DEFAULT_IDEAS_COUNT}, טווח {MIN_IDEAS}-{MAX_IDEAS})",
    )
    parser.add_argument(
        "--model",
        "-m",
        default=None,
        metavar="MODEL",
        help=f"מודל Groq להרצה (ברירת מחדל: {DEFAULT_GROQ_MODEL})",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=None,
        metavar="PATH",
        help="תיקיית הפלט הבסיסית (ברירת מחדל: output/)",
    )
    parser.add_argument(
        "--tts-lang",
        default=None,
        metavar="LANG",
        help="קוד שפת הקריינות (ברירת מחדל: iw = עברית; en = אנגלית)",
    )
    parser.add_argument(
        "--slow-tts",
        action="store_true",
        help="הקרנה איטית יותר של הקריינות",
    )
    parser.add_argument(
        "--skip-audio",
        action="store_true",
        help="דילוג על הפקת קובץ השמע (MP3)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="בדיקת מפתח ה-API ורשימת המודלים, ואז יציאה",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="השבתת צבעים בפלט",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="לוג מפורט (DEBUG)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    """נקודת הכניסה הראשית. מחזירה קוד יציאה לתהליך."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # ממשק בסיסי לתצוגת שגיאות אפילו לפני שההגדרות נטענו
    ui = TerminalUI(no_color=bool(getattr(args, "no_color", False)))
    ui.banner()

    # --- טעינת הגדרות ---
    try:
        settings = load_settings(
            overrides={key: getattr(args, key, None) for key in OVERRIDE_KEYS}
        )
    except ConfigurationError as exc:
        ui.error(str(exc))
        ui.print_key_setup_help()
        return EXIT_CONFIG

    # לוגר: קונסולה + קובץ factory.log בתיקיית הפלט
    logger = setup_logger(
        verbose=settings.verbose,
        log_file=Path(settings.output_dir) / "factory.log",
    )
    for warning in settings.warnings:
        logger.warning(warning)
    logger.info(
        "%s v%s | מודל=%s | פלט=%s | קריינות=%s",
        APP_NAME, __version__, settings.groq_model, settings.output_dir, settings.tts_lang,
    )

    # --- מצב בדיקה ---
    if args.check:
        return _run_check(settings, logger, ui)

    # --- הרצה מלאה ---
    try:
        engine = GroqTextEngine(settings, logger)
        tts = TextToSpeechEngine(settings, logger)
        storage = ProjectStorage(settings, logger)
        app = ShortsFactory(settings, logger, ui, engine, tts, storage)
        return app.run(topic=args.topic)

    except ConfigurationError as exc:
        ui.error(str(exc))
        ui.print_key_setup_help()
        return EXIT_CONFIG
    except KeyboardInterrupt:
        ui.warn("בוטל על ידי המשתמש (Ctrl+C).")
        return EXIT_USER_ABORT
    except ShortsFactoryError as exc:
        logger.exception("שגיאה לא מטופלת במערכת: %s", exc)
        ui.error(f"שגיאה במערכת: {exc}")
        return EXIT_UNEXPECTED
    except Exception as exc:  # noqa: BLE001 – רשת האחרונה של הטיפול בשגיאות
        logger.exception("שגיאה לא צפויה: %s", exc)
        ui.error(f"שגיאה לא צפויה: {exc}")
        return EXIT_UNEXPECTED
