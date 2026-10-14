"""הגדרת הלוגר המרכזי של המערכת (פלט לקונסולה + אופציונלית לקובץ)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

LOGGER_NAME = "shorts_factory"
CONSOLE_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"
FILE_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%H:%M:%S"


def setup_logger(
    name: str = LOGGER_NAME,
    *,
    log_file: Optional[Path] = None,
    verbose: bool = False,
) -> logging.Logger:
    """יוצר (או מאפס) לוגר עם פורמט עברי-ידידותי.

    Args:
        name: שם הלוגר.
        log_file: נתיב קובץ לוג (אופציונלי). אם אי אפשר לפתוח – ממשיכים בלי.
        verbose: אם ``True`` – רמת הדירוג היא DEBUG.

    Returns:
        מופע ``logging.Logger`` מוכן לשימוש.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    # מונע כפילות של handlers אם הפונקציה נקראת מספר פעמים
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001 – סגירת handler לא אמורה להפיל את התוכנית
            pass

    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt=DATE_FORMAT))
    logger.addHandler(console_handler)

    if log_file is not None:
        try:
            log_file = Path(log_file)
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
            logger.addHandler(file_handler)
        except OSError as exc:
            logger.warning("לא ניתן לפתוח קובץ לוג '%s': %s", log_file, exc)

    return logger
