"""מודלי הנתונים, פרסור תשובות ה-AI ונרמול נתונים.

המודול אינו יודע כלום על Groq – הוא רק מקבל מחרוזת (תשובת AI) ומחזיר
אובייקטים מובנים ומאומתים. זה הופך את הלוגיקה לנטולה תלויות וקלה לבדיקה.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .errors import AIResponseError

# ממוצע דיבור בעברית: ~2.5-2.7 מילים בשנייה (נשתמש ב-2.6 להערכת אורך)
HEBREW_WORDS_PER_SECOND = 2.6

MAX_HASHTAGS = 8


# ---------------------------------------------------------------------------
# מודלי נתונים
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Idea:
    """רעיון אחד ל-Short (שלב 1)."""

    number: int
    title: str
    hook: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "hook": self.hook,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class Scene:
    """סצנה ויזואלית אחת (שלב 2)."""

    scene_number: int
    time_range: str
    narration: str
    visual_prompt: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_number": self.scene_number,
            "time_range": self.time_range,
            "narration": self.narration,
            "visual_prompt": self.visual_prompt,
        }


@dataclass(frozen=True)
class ShortContent:
    """חבילת התוכן המלאה ל-Short (שלב 2)."""

    title: str
    description: str
    hashtags: tuple[str, ...]
    tags: tuple[str, ...]
    script_text: str
    scenes: tuple[Scene, ...]
    duration_estimate_seconds: float = 0.0
    word_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        # מחשבים אומדן משך הקריינות אם לא סופק
        if not self.duration_estimate_seconds and self.script_text:
            object.__setattr__(
                self, "duration_estimate_seconds", estimate_duration_seconds(self.script_text)
            )
        if not self.word_count and self.script_text:
            object.__setattr__(self, "word_count", len(self.script_text.split()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "hashtags": list(self.hashtags),
            "tags": list(self.tags),
            "script": {
                "full_text": self.script_text,
                "word_count": self.word_count,
                "duration_estimate_seconds": self.duration_estimate_seconds,
                "scenes": [scene.to_dict() for scene in self.scenes],
            },
        }


# ---------------------------------------------------------------------------
# עזרים כלליים
# ---------------------------------------------------------------------------
def estimate_duration_seconds(text: str) -> float:
    """מעריך את משך הקריינות בעברית (בשניות) לפי מספר המילים."""
    words = len(text.split())
    return round(words / HEBREW_WORDS_PER_SECOND, 1)


def slugify(text: str, max_length: int = 40) -> str:
    """הופך כותרת ל-"slug" ASCII בטוח לשימוש בשם תיקייה בכל מערכת הפעלה.

    עברית (וכל תו לא-ASCII) נמחקים – כך שהשמות עובדים גם ב-Windows.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    if len(ascii_text) > max_length:
        ascii_text = ascii_text[:max_length].rstrip("-")
    return ascii_text


def _safe_int(value: Any, default: int) -> int:
    """ממיר ערך למספר שלם בצורה בטוחה (מחזיר ברירת מחדל אם אי אפשר)."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _clean_str(value: Any) -> str:
    """מנקה מחרוזה: מסיר רווחים מיותרים ותווי בקרה."""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\u200b", "").replace("\ufeff", "")  # zero-width chars
    return text.strip()


def extract_json_object(raw_text: str) -> dict[str, Any]:
    """מחלץ אובייקט JSON מתשובת AI – גם אם היא עטופה ב-markdown או בטקסט.

    Raises:
        AIResponseError: אם לא הצלחנו למצוא אובייקט JSON תקין.
    """
    if not raw_text or not raw_text.strip():
        raise AIResponseError("התשובה שהתקבלה מה-AI ריקה.")

    text = raw_text.strip()

    # מסירים גדרות markdown אם המודל הוסיף (...```json ...```)
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    candidates = [text]
    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidates.append(text[first : last + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
        raise AIResponseError(
            "ה-JSON שהתקבל מה-AI אינו אובייקט (dict) – התקבל: %s" % type(data).__name__
        )

    raise AIResponseError(
        "לא הצלחתי לפרש JSON מתשובת ה-AI. התשובה (300 תווים ראשונים): %r" % raw_text[:300]
    )


# ---------------------------------------------------------------------------
# נרמול תגיות והאשטאגים
# ---------------------------------------------------------------------------
def normalize_tags(raw: Any, limit: int = 15) -> list[str]:
    """מנרמל רשימת תגיות: מסיר '#', רווחים וכפולות, חותך ל-``limit`` תגיות."""
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = _clean_str(item).lstrip("#").strip()
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
        if len(tags) >= limit:
            break
    return tags


def normalize_hashtags(raw: Any, limit: int = MAX_HASHTAGS) -> list[str]:
    """מנרמל האשטאגים: מוסיף '#', מסיר רווחים פנימיים, מסיר כפולות."""
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
        return []
    hashtags: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = _clean_str(item).replace(" ", "")
        if not tag or tag == "#":
            continue
        if not tag.startswith("#"):
            tag = "#" + tag
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        hashtags.append(tag)
        if len(hashtags) >= limit:
            break
    return hashtags


# ---------------------------------------------------------------------------
# פרסור שלב 1 – רעיונות
# ---------------------------------------------------------------------------
def parse_ideas(raw_text: str, expected_count: int = 5) -> list[Idea]:
    """מפרש את תשובת ה-AI לרשימת רעיונות.

    Raises:
        AIResponseError: אם אין מספיק רעיונות תקינים.
    """
    data = extract_json_object(raw_text)
    ideas_raw = data.get("ideas")
    if not isinstance(ideas_raw, list) or not ideas_raw:
        raise AIResponseError("תשובת ה-AI אינה מכילה רשימת 'ideas'.")

    ideas: list[Idea] = []
    for index, item in enumerate(ideas_raw, start=1):
        if not isinstance(item, dict):
            continue
        title = _clean_str(item.get("title"))
        if not title:
            continue
        ideas.append(
            Idea(
                number=_safe_int(item.get("number"), index) or index,
                title=title,
                hook=_clean_str(item.get("hook")),
                summary=_clean_str(item.get("summary")),
            )
        )
        if len(ideas) >= expected_count:
            break

    if len(ideas) < expected_count:
        raise AIResponseError(
            f"התקבלו רק {len(ideas)} רעיונות תקינים מתוך {expected_count} שביקשנו. "
            "נסה להריץ שוב או להחליף מודל."
        )
    return ideas


# ---------------------------------------------------------------------------
# פרסור שלב 2 – תסריט + פרומפטים + SEO
# ---------------------------------------------------------------------------
def parse_content(
    raw_text: str,
    *,
    min_scenes: int = 3,
    max_scenes: int = 4,
    tags_count: int = 15,
    logger: Optional[logging.Logger] = None,
) -> ShortContent:
    """מפרש את תשובת ה-AI לחבילת תוכן מלאה ומנורמלת.

    Raises:
        AIResponseError: אם חסרים שדות חובה או שיש פחות מדי סצנות.
    """
    data = extract_json_object(raw_text)

    title = _clean_str(data.get("title"))
    if not title:
        raise AIResponseError("חסרה כותרת SEO ('title') בתשובת ה-AI.")
    description = _clean_str(data.get("description"))

    script_obj = data.get("script")
    if not isinstance(script_obj, dict):
        raise AIResponseError("חסר אובייקט 'script' בתשובת ה-AI.")

    # --- סצנות ויזואליות ---
    scenes_raw = script_obj.get("scenes")
    scenes: list[Scene] = []
    if isinstance(scenes_raw, list):
        for index, item in enumerate(scenes_raw, start=1):
            if not isinstance(item, dict):
                continue
            visual_prompt = _clean_str(item.get("visual_prompt"))
            if not visual_prompt:
                continue
            scenes.append(
                Scene(
                    scene_number=_safe_int(item.get("scene_number"), index) or index,
                    time_range=_clean_str(item.get("time_range")),
                    narration=_clean_str(item.get("narration")),
                    visual_prompt=visual_prompt,
                )
            )

    if not scenes:
        raise AIResponseError("לא התקבלה אף סצנה ויזואלית עם 'visual_prompt'.")
    if len(scenes) < min_scenes:
        raise AIResponseError(
            f"התקבלו {len(scenes)} סצנות בלבד – מינימום נדרש: {min_scenes}. נסה שוב."
        )
    if len(scenes) > max_scenes:
        if logger:
            logger.warning(
                "התקבלו %d סצנות (מקסימום %d) – חותכים ל-%d הראשונות.",
                len(scenes), max_scenes, max_scenes,
            )
        scenes = scenes[:max_scenes]

    # --- טקסט התסריט ---
    script_text = _clean_str(script_obj.get("full_text"))
    if not script_text:
        # גיבוי: מרכיבים את התסריט מהקריינות של כל הסצנות
        script_text = " ".join(scene.narration for scene in scenes if scene.narration).strip()
    if not script_text:
        raise AIResponseError("טקסט התסריט ('full_text') ריק.")

    # --- SEO ---
    tags = normalize_tags(data.get("tags"), limit=tags_count)
    hashtags = normalize_hashtags(data.get("hashtags"))
    if logger and len(tags) < tags_count:
        logger.warning("התקבלו %d תגיות בלבד מתוך %d שביקשנו.", len(tags), tags_count)

    return ShortContent(
        title=title,
        description=description,
        hashtags=tuple(hashtags),
        tags=tuple(tags),
        script_text=script_text,
        scenes=tuple(scenes),
        raw=data,
    )
