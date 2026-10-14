"""ניהול תיקיות הפרויקט, שמות הקבצים וכתיבת קובץ המטאדאטה.

כל רעיון שנבחר מקבל תיקייה משלו תחת תיקיית הפלט, כדי ששתי הרצות לא ידרסו
זו את זו, והכל יהיה מאורגן וניתן להעברה לכלי עריכה (CapCut, Premiere וכו').
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .config import Settings
from .errors import StorageError
from .schemas import Idea, ShortContent, estimate_duration_seconds, slugify
from .tts_engine import SynthesisResult

METADATA_FILENAME = "Script_Metadata.txt"
AUDIO_FILENAME = "voiceover.mp3"
CONTENT_JSON_FILENAME = "content.json"

SEP = "=" * 78
SUB = "-" * 78


@dataclass(frozen=True)
class ProjectPaths:
    """הנתיבים הרלוונטיים בתוך תיקיית הפרויקט של הרעיון."""

    root: Path
    audio: Path
    metadata: Path
    content_json: Path


class ProjectStorage:
    """יוצר ומנהל את תיקיות הפלט של המערכת."""

    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self._settings = settings
        self._logger = logger

    # ------------------------------------------------------------------
    # יצירת פרויקט
    # ------------------------------------------------------------------
    def create_project(self, idea: Idea) -> ProjectPaths:
        """יוצר תיקייה חדשה עבור הרעיון (לא דורס תיקיות קיימות)."""
        slug = slugify(idea.title) or "short"
        folder_name = f"idea-{idea.number:02d}-{slug}"

        try:
            self._settings.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError(
                f"יצירת תיקיית הפלט '{self._settings.output_dir}' נכשלה: {exc}"
            ) from exc

        root = self._settings.output_dir / folder_name
        attempt = 2
        while root.exists():
            root = self._settings.output_dir / f"{folder_name}-{attempt}"
            attempt += 1

        try:
            root.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            raise StorageError(f"יצירת תיקיית הפרויקט '{root}' נכשלה: {exc}") from exc

        self._logger.info("תיקיית הפרויקט נוצרה: %s", root)
        return ProjectPaths(
            root=root,
            audio=root / AUDIO_FILENAME,
            metadata=root / METADATA_FILENAME,
            content_json=root / CONTENT_JSON_FILENAME,
        )

    # ------------------------------------------------------------------
    # כתיבת קבצים
    # ------------------------------------------------------------------
    def write_content_json(self, paths: ProjectPaths, payload: dict[str, Any]) -> Path:
        """שומר את הנתונים הגולמיים מה-AI כ-JSON (לשימוש חוזר/דיבוג)."""
        try:
            paths.content_json.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            raise StorageError(f"כתיבת '{paths.content_json}' נכשלה: {exc}") from exc
        self._logger.debug("נשמר JSON גולמי: %s", paths.content_json.name)
        return paths.content_json

    def write_metadata(
        self,
        paths: ProjectPaths,
        *,
        idea: Idea,
        content: ShortContent,
        topic: str,
        model: str,
        audio: Optional[SynthesisResult] = None,
        generated_at: Optional[datetime] = None,
    ) -> Path:
        """יוצר את קובץ ``Script_Metadata.txt`` המסודר עם כל חומרי הגלם."""
        text = self._build_metadata_text(
            idea=idea,
            content=content,
            topic=topic,
            model=model,
            audio=audio,
            generated_at=generated_at or datetime.now(),
        )
        try:
            paths.metadata.write_text(text, encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"כתיבת '{paths.metadata}' נכשלה: {exc}") from exc
        self._logger.info("קובץ המטאדאטה נשמר: %s", paths.metadata)
        return paths.metadata

    # ------------------------------------------------------------------
    # בניית תוכן הקובץ
    # ------------------------------------------------------------------
    @staticmethod
    def _build_metadata_text(
        *,
        idea: Idea,
        content: ShortContent,
        topic: str,
        model: str,
        audio: Optional[SynthesisResult],
        generated_at: datetime,
    ) -> str:
        """בונה את התוכן המלא של Script_Metadata.txt."""
        lines: list[str] = []
        lines.append(SEP)
        lines.append("  🎬 Shorts Factory – חומרי גלם מוכנים להפקת YouTube Short")
        lines.append(SEP)
        lines.append(f"תאריך יצירה  : {generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"נושא כללי    : {topic}")
        lines.append(f"מודל AI      : {model}")
        lines.append(f"רעיון נבחר   : #{idea.number}")
        lines.append("")

        # 1. הרעיון
        lines.append(SUB)
        lines.append("1) הרעיון שנבחר")
        lines.append(SUB)
        lines.append(f"כותרת : {idea.title}")
        lines.append(f"הוק   : {idea.hook}")
        lines.append(f"תקציר : {idea.summary}")
        lines.append("")

        # 2. כותרת SEO
        lines.append(SUB)
        lines.append("2) כותרת ל-SEO (מקסימום הקלקות)")
        lines.append(SUB)
        lines.append(content.title)
        lines.append("")

        # 3. תיאור
        lines.append(SUB)
        lines.append("3) תיאור ל-YouTube")
        lines.append(SUB)
        lines.append(content.description)
        lines.append("")

        # 4. תגיות
        lines.append(SUB)
        lines.append(f"4) תגיות ({len(content.tags)})")
        lines.append(SUB)
        lines.append(", ".join(content.tags))
        lines.append("")

        # 5. האשטאגים
        lines.append(SUB)
        lines.append("5) האשטאגים")
        lines.append(SUB)
        lines.append(" ".join(content.hashtags))
        lines.append("")

        # 6. תסריט
        lines.append(SUB)
        lines.append("6) תסריט הקריינות המלא")
        lines.append(SUB)
        lines.append(content.script_text)
        lines.append("")
        duration = content.duration_estimate_seconds or estimate_duration_seconds(
            content.script_text
        )
        word_count = content.word_count or len(content.script_text.split())
        lines.append(
            f"(מספר מילים: {word_count} | משך משוער: ~{duration:.0f} שניות)"
        )
        lines.append("")

        # 7. סצנות ויזואליות
        lines.append(SUB)
        lines.append(f"7) סצנות ויזואליות + פרומפטים באנגלית ({len(content.scenes)} סצנות)")
        lines.append(SUB)
        for scene in content.scenes:
            lines.append(f"סצנה {scene.scene_number} ({scene.time_range})")
            lines.append(f"  קריינות     : {scene.narration}")
            lines.append(f"  פרומפט וידאו: {scene.visual_prompt}")
            lines.append("")

        # 8. אודיו
        lines.append(SUB)
        lines.append("8) קובץ השמע (קריינות)")
        lines.append(SUB)
        if audio is not None:
            lines.append(f"קובץ        : {audio.path.name}")
            lines.append(f"מנגנון TTS  : {audio.engine} (חינמי)")
            lines.append(f"גודל        : {audio.size_bytes:,} בתים")
        else:
            lines.append("לא הופק קובץ שמע (ההפקה דולגה או נכשלה).")
        lines.append("")

        # 9. הנחיות סיום
        lines.append(SUB)
        lines.append("9) המשך עבודה מומלץ (כל הכלים חינמיים)")
        lines.append(SUB)
        lines.append("1. צרו את קטעי הווידאו לפי הפרומפטים בסעיף 7 בכלי חינמי כגון")
        lines.append("   Kling, Hailuo, PixVerse או Canva (מסלול חינמי).")
        lines.append("2. הרכיבו את הקטעים + קובץ הקריינות ב-CapCut (חינם) בפרופורט 9:16.")
        lines.append("3. הוסיפו כתוביות אוטומטיות, מוזיקת רקע ועיצוב.")
        lines.append("4. העלו ל-YouTube Shorts עם הכותרת/התיאור/התגיות מסעיפים 2-5.")
        lines.append("")
        lines.append(SEP)
        lines.append("  נוצר אוטומטית על ידי Shorts Factory – 100% חינם, ללא כרטיס אשראי")
        lines.append(SEP)

        return "\n".join(lines) + "\n"
