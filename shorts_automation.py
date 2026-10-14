#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
מערכת אוטומציה ליצירת חומרי גלם לסרטוני YouTube Shorts.

מה הסקריפט עושה (לפי השלבים):
  1. מקבל נושא מהמשתמש, מבקש מ-Groq (Llama) 5 רעיונות לכותרות, ומציג אותם.
     המשתמש בוחר מספר 1-5.
  2. עבור הרעיון שנבחר מבקש מ-Groq: תסריט (עד ~50 שניות), 3-4 סצנות עם פרומפטים
     באנגלית לכלי וידאו, וניתוח SEO (כותרת, תיאור, 15 תגיות/האשטאגים).
  3. ממיר את התסריט ל-MP3 בעזרת gTTS (חינמי, ללא מפתח).
  4. שומר בתיקיית פרויקט ייעודית: את קובץ ה-MP3 ואת Script_Metadata.txt.

-----------------------------------------------------------------------
התקנה (Python 3.9+):
    pip install groq gtts

שימו לב: gTTS שולח את הטקסט לשירות התרגום של Google ולכן דורש חיבור לאינטרנט.
(pyttsx3 עובד אופליין, אבל קולות העברית תלויים במערכת ההפעלה ולכן לא נכלל כברירת מחדל.)

הגדרת מפתח Groq (חינמי - מפתח נוצר ב-https://console.groq.com/keys ללא כרטיס אשראי):
    Linux / macOS:
        export GROQ_API_KEY="gsk_..."
    Windows (PowerShell):
        $env:GROQ_API_KEY="gsk_..."
    Windows (cmd):
        set GROQ_API_KEY=gsk_...
אם המשתנה לא מוגדר, הסקריפט יבקש את המפתח בטרמינל (ההקלדה לא תוצג על המסך).

משתני סביבה אופציונליים:
    GROQ_MODEL     מודל Groq (ברירת מחדל: llama-3.3-70b-versatile)
    CONTENT_LANG   שפת התסריט (ברירת מחדל: he - עברית). לדוגמה: en
    OUTPUT_DIR     תיקיית הפלט (ברירת מחדל: ./shorts_projects)
    MAX_SCRIPT_WORDS  מקסימום מילים בתסריט (ברירת מחדל: 115 ≈ 50 שניות דיבור)

הרצה:
    python shorts_automation.py
-----------------------------------------------------------------------
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# ייבוא ספריות חיצוניות עם הודעת שגיאה ברורה אם לא מותקנות
# ---------------------------------------------------------------------------
try:
    from groq import Groq
    import groq as groq_module
except ImportError:  # pragma: no cover
    print("שגיאה: ספריית groq לא מותקנת. הריצו: pip install groq", file=sys.stderr)
    sys.exit(1)

try:
    from gtts import gTTS
    from gtts.lang import tts_langs
    from gtts.tts import gTTSError
except ImportError:  # pragma: no cover
    print("שגיאה: ספריית gtts לא מותקנת. הריצו: pip install gtts", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# הגדרות כלליות
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_OUTPUT_DIR = "shorts_projects"
DEFAULT_CONTENT_LANG = "he"
DEFAULT_MAX_SCRIPT_WORDS = 115  # כ-130 מילים לדקה * 50 שניות ≈ 108; מרווח קטן
IDEAS_COUNT = 5
SCENES_MIN, SCENES_MAX = 3, 4
TAGS_COUNT = 15
MAX_API_RETRIES = 3          # כמות ניסיונות חוזרים לכל קריאה ל-Groq
RETRY_BASE_DELAY = 2.0       # שניות; מוכפל בכל ניסיון (backoff)
API_TIMEOUT_SECONDS = 60.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("shorts_automation")


# ---------------------------------------------------------------------------
# מחלקות שגיאה מותאמות
# ---------------------------------------------------------------------------
class AutomationError(Exception):
    """שגיאה כללית של המערכת."""


class AIResponseError(AutomationError):
    """המודל החזיר תשובה שאינה תקינה (JSON שגוי או שדות חסרים)."""


class TTSError(AutomationError):
    """שגיאה בהפקת קובץ השמע."""


# ---------------------------------------------------------------------------
# מבני נתונים
# ---------------------------------------------------------------------------
@dataclass
class Idea:
    """רעיון לסרטון שנוצר בשלב 1."""
    number: int
    title: str
    summary: str


@dataclass
class Scene:
    """סצנה ויזואלית בשלב 2."""
    number: int
    duration_seconds: int
    description_he: str
    prompt_en: str


@dataclass
class ShortPlan:
    """כל חומר הגלם לסרטון שנוצר בשלב 2."""
    script: str
    scenes: List[Scene]
    seo_title: str
    seo_description: str
    tags: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# פונקציות עזר
# ---------------------------------------------------------------------------
def sanitize_filename(name: str, max_length: int = 80) -> str:
    """
    ממיר טקסט לשם תיקייה/קובץ חוקי בכל מערכת הפעלה.
    מסיר תווים אסורים (<>:"/\\|?*), תווי בקרה, נקודות/רווחים בסוף, ומקצר את האורך.
    """
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(". ")
    cleaned = cleaned[:max_length].rstrip(". ")
    return cleaned or "project"


def make_unique_dir(base: Path) -> Path:
    """מחזיר נתיב תיקייה שלא קיים (מוסיף סיומת מספרית במקרה של התנגשות)."""
    candidate = base
    counter = 2
    while candidate.exists():
        candidate = base.parent / f"{base.name}_{counter}"
        counter += 1
    return candidate


def count_words(text: str) -> int:
    """סופר מילים בטקסט (הפרדה לפי רווחים)."""
    return len(text.split())


def extract_json(raw: str) -> Dict[str, Any]:
    """
    מנסה לחלץ אובייקט JSON מתשובת המודל.
    מטפל גם במקרה שהמודל עטף את ה-JSON בבלוק ```json ... ```.
    """
    if not raw or not raw.strip():
        raise AIResponseError("התשובה מהמודל ריקה.")

    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # ניסיון אחרון: לקחת את החלק בין הסוגריים המסולסלים הראשונים והאחרונים
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise AIResponseError("לא נמצא JSON תקין בתשובת המודל.")
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise AIResponseError(f"פענוח ה-JSON נכשל: {exc}") from exc

    if not isinstance(data, dict):
        raise AIResponseError("התשובה חייבת להיות אובייקט JSON.")
    return data


# ---------------------------------------------------------------------------
# שכבת תקשורת עם Groq
# ---------------------------------------------------------------------------
class GroqClient:
    """עטיפה ל-Groq API עם ניסיונות חוזרים (retry) וטיפול בשגיאות."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        try:
            self._client = Groq(api_key=api_key, timeout=API_TIMEOUT_SECONDS)
        except Exception as exc:
            raise AutomationError(f"לא ניתן לאתחל את לקוח Groq: {exc}") from exc

    def ask_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.8) -> Dict[str, Any]:
        """
        שולח בקשה למודל ומחזיר dict שנוצר מ-JSON.
        מנסה שוב במקרה של Rate Limit, בעיות רשת או שגיאות שרת (5xx).
        """
        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_API_RETRIES + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content or ""
                return extract_json(content)

            except AIResponseError as exc:
                # תשובה לא תקינה - ננסה שוב, המודל לפעמים מחזיר טקסט במקום JSON
                last_error = exc
                logger.warning("תשובה לא תקינה מהמודל (ניסיון %d/%d): %s", attempt, MAX_API_RETRIES, exc)

            except groq_module.RateLimitError as exc:
                last_error = exc
                logger.warning("הגעתם למגבלת קצב של Groq (ניסיון %d/%d). ממתין...", attempt, MAX_API_RETRIES)

            except groq_module.APIConnectionError as exc:
                last_error = exc
                logger.warning("בעיית תקשורת עם Groq (ניסיון %d/%d): %s", attempt, MAX_API_RETRIES, exc)

            except groq_module.APIStatusError as exc:
                # 4xx (חוץ מ-429) הם שגיאות שאין טעם לנסות שוב
                last_error = exc
                status = getattr(exc, "status_code", None)
                if status is not None and status < 500 and status != 429:
                    raise AutomationError(
                        f"Groq החזיר שגיאה {status}: {exc}. "
                        "בדקו את מפתח ה-API ואת שם המודל (GROQ_MODEL)."
                    ) from exc
                logger.warning("שגיאת שרת מ-Groq (ניסיון %d/%d): %s", attempt, MAX_API_RETRIES, exc)

            except groq_module.APIError as exc:
                raise AutomationError(f"שגיאת Groq: {exc}") from exc

            except Exception as exc:  # הגנה אחרונה - שגיאה לא צפויה
                raise AutomationError(f"שגיאה לא צפויה בתקשורת עם Groq: {exc}") from exc

            if attempt < MAX_API_RETRIES:
                time.sleep(RETRY_BASE_DELAY * (2 ** (attempt - 1)))

        raise AutomationError(f"הבקשה ל-Groq נכשלה אחרי {MAX_API_RETRIES} ניסיונות: {last_error}")


# ---------------------------------------------------------------------------
# שלב 1 - יצירת רעיונות
# ---------------------------------------------------------------------------
IDEAS_SYSTEM_PROMPT = """You are an expert YouTube Shorts strategist.
Always respond ONLY with a valid JSON object, no extra text."""


def build_ideas_user_prompt(topic: str) -> str:
    """בונה את פרומפט הרעיונות (שלב 1)."""
    return f"""Topic from the user: "{topic}"

Create exactly {IDEAS_COUNT} viral, catchy YouTube Shorts video ideas about this topic.
Each idea needs a short, clickable title (max 70 characters) and a one-sentence summary.
Write titles and summaries in Hebrew.

Return JSON in exactly this format:
{{
  "ideas": [
    {{"title": "כותרת 1", "summary": "תקציר במשפט אחד"}},
    ... (exactly {IDEAS_COUNT} items)
  ]
}}"""


def parse_ideas(data: Dict[str, Any]) -> List[Idea]:
    """בודק ומחזיר את רשימת הרעיונות מהתשובה."""
    raw_ideas = data.get("ideas")
    if not isinstance(raw_ideas, list):
        raise AIResponseError("שדה 'ideas' חסר או אינו רשימה.")

    ideas: List[Idea] = []
    for item in raw_ideas:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        summary = str(item.get("summary", "")).strip()
        if title:
            ideas.append(Idea(number=len(ideas) + 1, title=title, summary=summary))
        if len(ideas) == IDEAS_COUNT:
            break

    if len(ideas) < IDEAS_COUNT:
        raise AIResponseError(f"התקבלו {len(ideas)} רעיונות בלבד, נדרשים {IDEAS_COUNT}.")
    return ideas


def generate_ideas(client: GroqClient, topic: str) -> List[Idea]:
    """שלב 1: מחזיר 5 רעיונות לסרטונים."""
    logger.info("מבקש מ-Groq 5 רעיונות לנושא: %s", topic)
    data = client.ask_json(IDEAS_SYSTEM_PROMPT, build_ideas_user_prompt(topic), temperature=0.9)
    return parse_ideas(data)


def show_ideas(ideas: List[Idea]) -> None:
    """מציג את הרעיונות בטרמינל."""
    print("\n" + "=" * 60)
    print("הרעיונות שנוצרו:")
    print("=" * 60)
    for idea in ideas:
        print(f"\n{idea.number}. {idea.title}")
        if idea.summary:
            print(f"   {idea.summary}")
    print("\n" + "=" * 60)


def ask_idea_choice(ideas: List[Idea]) -> Optional[Idea]:
    """
    מבקש מהמשתמש לבחור מספר 1-5.
    מחזיר None אם המשתמש הקליד 'q' ליציאה.
    """
    while True:
        choice = input(f"בחרו רעיון (1-{len(ideas)}), או 'q' ליציאה: ").strip().lower()
        if choice == "q":
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(ideas):
            return ideas[int(choice) - 1]
        print(f"קלט לא תקין. יש להזין מספר בין 1 ל-{len(ideas)}.")


# ---------------------------------------------------------------------------
# שלב 2 - תסריט, פרומפטים לוויזואל ו-SEO
# ---------------------------------------------------------------------------
PLAN_SYSTEM_PROMPT = """You are an elite YouTube Shorts scriptwriter, visual director and SEO analyst.
Always respond ONLY with a valid JSON object, no extra text."""


def build_plan_user_prompt(idea: Idea, script_lang_name: str, max_words: int) -> str:
    """בונה את פרומפט התסריט, הסצנות וה-SEO (שלב 2)."""
    return f"""Selected video idea:
Title: {idea.title}
Summary: {idea.summary}

Produce a complete production package for this YouTube Short.

(a) SCRIPT: a short, fast-paced voiceover script in {script_lang_name}.
    - It must be readable in at most 50 seconds (maximum {max_words} words).
    - Start with a strong hook in the first sentence. No stage directions, only spoken words.

(b) SCENES: split the video into {SCENES_MIN} to {SCENES_MAX} visual scenes.
    - "description_he": short description of the scene in Hebrew (for the creator).
    - "prompt_en": a detailed English prompt for a free AI video tool
      (for example: subject, setting, camera angle, lighting, style, "vertical 9:16", "no text, no watermark").
    - "duration_seconds": integer, the total of all scenes must be about 50 seconds or less.

(c) SEO:
    - "seo_title": a clickable title, max 70 characters, in {script_lang_name}.
    - "seo_description": a short description of 2-3 sentences, in {script_lang_name}.
    - "tags": EXACTLY {TAGS_COUNT} strong tags/hashtags in {script_lang_name}, without the '#' sign.

Return JSON in exactly this format:
{{
  "script": "...",
  "scenes": [
    {{"scene_number": 1, "duration_seconds": 12, "description_he": "...", "prompt_en": "..."}}
  ],
  "seo": {{
    "seo_title": "...",
    "seo_description": "...",
    "tags": ["tag1", "tag2"]
  }}
}}"""


def parse_plan(data: Dict[str, Any], max_words: int) -> ShortPlan:
    """בודק את תשובת המודל לשלב 2 ומחזיר ShortPlan תקין."""
    script = str(data.get("script", "")).strip()
    if not script:
        raise AIResponseError("שדה 'script' חסר או ריק.")
    if count_words(script) > max_words * 1.2:
        # לא זורקים את התשובה בגלל חריגה קלה, רק מתריעים
        logger.warning("התסריט ארוך מהמומלץ (%d מילים). ייתכן שהקריינות תעלה על 50 שניות.",
                       count_words(script))

    raw_scenes = data.get("scenes")
    if not isinstance(raw_scenes, list):
        raise AIResponseError("שדה 'scenes' חסר או אינו רשימה.")

    scenes: List[Scene] = []
    for item in raw_scenes:
        if not isinstance(item, dict):
            continue
        prompt_en = str(item.get("prompt_en", "")).strip()
        if not prompt_en:
            continue
        try:
            duration = int(item.get("duration_seconds", 0))
        except (TypeError, ValueError):
            duration = 0
        scenes.append(Scene(
            number=len(scenes) + 1,
            duration_seconds=max(duration, 0),
            description_he=str(item.get("description_he", "")).strip(),
            prompt_en=prompt_en,
        ))
    if not (SCENES_MIN <= len(scenes) <= SCENES_MAX):
        raise AIResponseError(f"התקבלו {len(scenes)} סצנות, נדרשות {SCENES_MIN}-{SCENES_MAX}.")

    seo = data.get("seo")
    if not isinstance(seo, dict):
        raise AIResponseError("שדה 'seo' חסר או אינו אובייקט.")
    seo_title = str(seo.get("seo_title", "")).strip()
    seo_description = str(seo.get("seo_description", "")).strip()
    if not seo_title:
        raise AIResponseError("שדה 'seo_title' חסר.")

    raw_tags = seo.get("tags", [])
    if not isinstance(raw_tags, list):
        raise AIResponseError("שדה 'tags' חייב להיות רשימה.")
    tags: List[str] = []
    for tag in raw_tags:
        clean = str(tag).strip().lstrip("#").strip()
        if clean and clean.lower() not in {t.lower() for t in tags}:
            tags.append(clean)
    if len(tags) < TAGS_COUNT:
        raise AIResponseError(f"התקבלו {len(tags)} תגיות, נדרשות {TAGS_COUNT}.")
    tags = tags[:TAGS_COUNT]

    return ShortPlan(
        script=script,
        scenes=scenes,
        seo_title=seo_title,
        seo_description=seo_description,
        tags=tags,
    )


def generate_plan(client: GroqClient, idea: Idea, script_lang_name: str, max_words: int) -> ShortPlan:
    """שלב 2: מחזיר תסריט, סצנות ו-SEO לרעיון שנבחר."""
    logger.info("מייצר תסריט, סצנות ו-SEO לרעיון: %s", idea.title)
    data = client.ask_json(
        PLAN_SYSTEM_PROMPT,
        build_plan_user_prompt(idea, script_lang_name, max_words),
        temperature=0.7,
    )
    return parse_plan(data, max_words)


# ---------------------------------------------------------------------------
# שלב 3 - הפקת קובץ שמע (gTTS)
# ---------------------------------------------------------------------------
def resolve_tts_language(lang: str) -> str:
    """
    ממיר קוד שפה לקוד ש-gTTS מכיר.
    gTTS משתמש בקוד 'iw' לעברית (לא 'he'), לכן ממפים אוטומטית.
    """
    normalized = lang.strip().lower()
    aliases = {"he": "iw", "he-il": "iw", "iw-il": "iw"}
    normalized = aliases.get(normalized, normalized)
    try:
        supported = tts_langs()
    except Exception:
        # אם אין גישה לרשימה, נחזיר את הקוד כפי שהוא
        return normalized
    if normalized not in supported:
        raise TTSError(f"gTTS אינו תומך בשפה '{lang}'. שפות נתמכות: {', '.join(sorted(supported))}")
    return normalized


def generate_audio(script: str, output_file: Path, lang: str) -> Path:
    """שלב 3: ממיר את התסריט ל-MP3 ושומר בנתיב שניתן."""
    tts_lang = resolve_tts_language(lang)
    logger.info("ממיר את התסריט לקול (שפה: %s)...", tts_lang)
    try:
        tts = gTTS(text=script, lang=tts_lang, slow=False)
        tts.save(str(output_file))
    except gTTSError as exc:
        raise TTSError(f"gTTS נכשל (בדקו חיבור לאינטרנט): {exc}") from exc
    except OSError as exc:
        raise TTSError(f"שמירת קובץ השמע נכשלה: {exc}") from exc
    except Exception as exc:
        raise TTSError(f"שגיאה לא צפויה בהפקת הקול: {exc}") from exc

    if not output_file.exists() or output_file.stat().st_size == 0:
        raise TTSError("קובץ השמע נוצר ריק או לא נוצר.")
    return output_file


# ---------------------------------------------------------------------------
# שלב 4 - שמירת הנתונים
# ---------------------------------------------------------------------------
def build_metadata_text(idea: Idea, plan: ShortPlan, audio_name: str) -> str:
    """בונה את תוכן הקובץ Script_Metadata.txt."""
    lines: List[str] = []
    sep = "=" * 70
    lines.append(sep)
    lines.append("Script_Metadata - חומרי גלם לסרטון Shorts")
    lines.append(f"נוצר בתאריך: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(sep)
    lines.append("")
    lines.append("[רעיון שנבחר]")
    lines.append(f"כותרת: {idea.title}")
    lines.append(f"תקציר: {idea.summary}")
    lines.append("")
    lines.append(f"[קובץ שמע] {audio_name}")
    lines.append("")
    lines.append("[תסריט מלא]")
    lines.append(f"(מספר מילים: {count_words(plan.script)})")
    lines.append(plan.script)
    lines.append("")
    lines.append("[סצנות ויזואליות - פרומפטים לכלי וידאו חינמיים]")
    for scene in plan.scenes:
        lines.append("")
        lines.append(f"--- סצנה {scene.number} (כ-{scene.duration_seconds} שניות) ---")
        if scene.description_he:
            lines.append(f"תיאור: {scene.description_he}")
        lines.append(f"Prompt (English): {scene.prompt_en}")
    lines.append("")
    lines.append("[SEO]")
    lines.append(f"כותרת ל-YouTube: {plan.seo_title}")
    lines.append("")
    lines.append("תיאור:")
    lines.append(plan.seo_description)
    lines.append("")
    lines.append(f"תגיות ({len(plan.tags)}):")
    lines.append(", ".join(plan.tags))
    lines.append("")
    lines.append("האשטאגים:")
    lines.append(" ".join(f"#{t.replace(' ', '')}" for t in plan.tags))
    lines.append("")
    return "\n".join(lines)


def save_metadata(project_dir: Path, idea: Idea, plan: ShortPlan, audio_name: str) -> Path:
    """שומר את Script_Metadata.txt בקידוד UTF-8 עם BOM (כדי ש-Notepad יציג עברית נכון)."""
    target = project_dir / "Script_Metadata.txt"
    try:
        target.write_text(build_metadata_text(idea, plan, audio_name), encoding="utf-8-sig")
    except OSError as exc:
        raise AutomationError(f"שמירת Script_Metadata.txt נכשלה: {exc}") from exc
    return target


# ---------------------------------------------------------------------------
# קלט מהמשתמש
# ---------------------------------------------------------------------------
def get_api_key() -> str:
    """קורא את מפתח Groq ממשתנה סביבה; אם חסר - מבקש בטרמינל בהקלדה מוסתרת."""
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        return key
    logger.info("המשתנה GROQ_API_KEY לא מוגדר. ניתן להגדיר אותו או להזין כאן (לא יוצג על המסך).")
    try:
        key = getpass.getpass("הזינו את מפתח Groq API: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise AutomationError("לא הוזן מפתח API.")
    if not key:
        raise AutomationError("מפתח Groq API ריק.")
    return key


def get_topic() -> str:
    """מבקש נושא כללי מהמשתמש עד שמתקבל קלט לא ריק."""
    while True:
        topic = input("הזינו נושא כללי לסרטונים: ").strip()
        if topic:
            return topic
        print("הנושא לא יכול להיות ריק.")


# ---------------------------------------------------------------------------
# זרימה ראשית
# ---------------------------------------------------------------------------
def run() -> int:
    """מריץ את כל השלבים. מחזיר קוד יציאה (0 = הצלחה)."""
    api_key = get_api_key()
    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    content_lang = os.environ.get("CONTENT_LANG", DEFAULT_CONTENT_LANG).strip() or DEFAULT_CONTENT_LANG
    output_root = Path(os.environ.get("OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    try:
        max_words = int(os.environ.get("MAX_SCRIPT_WORDS", DEFAULT_MAX_SCRIPT_WORDS))
    except ValueError:
        max_words = DEFAULT_MAX_SCRIPT_WORDS

    script_lang_name = "Hebrew" if resolve_tts_language(content_lang) == "iw" else content_lang
    client = GroqClient(api_key=api_key, model=model)

    # --- שלב 1 ---
    topic = get_topic()
    ideas = generate_ideas(client, topic)
    show_ideas(ideas)
    chosen = ask_idea_choice(ideas)
    if chosen is None:
        print("יצאתם מהתוכנית.")
        return 0
    logger.info("נבחר רעיון %d: %s", chosen.number, chosen.title)

    # --- שלב 2 ---
    plan = generate_plan(client, chosen, script_lang_name, max_words)

    # --- תיקיית פרויקט ---
    project_dir = make_unique_dir(output_root / sanitize_filename(chosen.title))
    try:
        project_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise AutomationError(f"לא ניתן ליצור את תיקיית הפרויקט {project_dir}: {exc}") from exc
    logger.info("תיקיית הפרויקט: %s", project_dir.resolve())

    # --- שלב 3 ---
    audio_path = project_dir / "voiceover.mp3"
    try:
        generate_audio(plan.script, audio_path, content_lang)
        audio_name = audio_path.name
    except TTSError as exc:
        # כשל בקול לא עוצר את שאר הפלט - מסמנים זאת בקובץ
        logger.error("הפקת השמע נכשלה: %s", exc)
        audio_name = "לא נוצר (שגיאה בהפקת הקול)"

    # --- שלב 4 ---
    metadata_path = save_metadata(project_dir, chosen, plan, audio_name)
    print("\nהסתיים בהצלחה!")
    print(f"  תסריט + SEO : {metadata_path.resolve()}")
    if audio_name.endswith(".mp3"):
        print(f"  קול (MP3)   : {audio_path.resolve()}")
    return 0


def main() -> int:
    """נקודת כניסה עם טיפול בשגיאות ויציאה נקייה."""
    try:
        return run()
    except KeyboardInterrupt:
        print("\nהתוכנית הופסקה על ידי המשתמש.")
        return 130
    except AutomationError as exc:
        logger.error("שגיאה: %s", exc)
        return 1
    except Exception as exc:  # הגנה אחרונה
        logger.exception("שגיאה לא צפויה: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
