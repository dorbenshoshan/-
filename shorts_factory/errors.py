"""שגיאות מותאמות אישית של מערכת Shorts Factory.

כל חריגה במערכת יורשת מ-:class:`ShortsFactoryError`, כך שאפשר לתפוס את כל
השגיאות הצפויות של המערכת במקום אחד (``except ShortsFactoryError``).
"""

from __future__ import annotations


class ShortsFactoryError(Exception):
    """בסיס לכל השגיאות של המערכת."""


class ConfigurationError(ShortsFactoryError):
    """שגיאת קונפיגורציה – למשל מפתח API חסר, לא תקין או ערך הפנימי שגוי."""


class AIEngineError(ShortsFactoryError):
    """שגיאה בתקשורת או בעיבוד בצד מנוע ה-AI (Groq).

    כולל: בעיות רשת, חריגה ממגבלת בקשות (rate limit) ושגיאות שרת 5xx.
    """


class AIResponseError(ShortsFactoryError):
    """התשובה שהתקבלה מה-AI אינה עומדת בסכימה הצפויה (JSON פגום, שדות חסרים)."""


class TTSSynthesisError(ShortsFactoryError):
    """כשל בהפקת קובץ הקריינות (האודיו)."""


class StorageError(ShortsFactoryError):
    """כשל ביצירה או בכתיבה של קבצים ותיקיות בפרויקט."""


class UserAbortError(ShortsFactoryError):
    """המשתמש ביטל את הפעולה (למעט Ctrl+C שמטופל בנפרד)."""
