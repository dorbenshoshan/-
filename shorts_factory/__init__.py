"""Shorts Factory – מערכת אוטומציה חינמית ליצירת חומרי גלם ל-YouTube Shorts.

החבילה מחולקת למודולים ממוקדים:

=============  ==================================================================
מודול          תפקיד
=============  ==================================================================
``config``     טעינת הגדרות ממשתני סביבה + קובץ ``.env`` + ולידציה
``errors``     חריגות מותאמות אישית של המערכת
``logger``     הגדרת לוגר (קונסולה + קובץ)
``prompts``    תבניות הפרומפטים ל-Groq
``schemas``    מודלי נתונים (רעיון/סצנה/תוכן), פרסור JSON ונרמול
``groq_client`` מנוע הטקסט החכם (Groq / Llama) עם retries חכמים
``tts_engine`` מנוע הקריינות החינמי (gTTS, עם fallback אופליין ל-pyttsx3)
``storage``    ניהול תיקיות פרויקט, שמות קבצים וכתיבת מטאדאטה
``ui``         ממשק טרמינל צבעוני (קלט/פלט אינטראקטיבי)
``cli``        תזמורת התהליך + נקודת הכניסה הראשית
=============  ==================================================================
"""

from .errors import (
    AIEngineError,
    AIResponseError,
    ConfigurationError,
    ShortsFactoryError,
    StorageError,
    TTSSynthesisError,
    UserAbortError,
)

__version__ = "1.0.0"

__all__ = [
    "AIEngineError",
    "AIResponseError",
    "ConfigurationError",
    "ShortsFactoryError",
    "StorageError",
    "TTSSynthesisError",
    "UserAbortError",
    "__version__",
]
