"""ממשק הטרמינל האינטראקטיבי (קלט/פלט) של המערכת.

המודול אחראי לכל התצוגה והקלט מהמשתמש: כותרת, שלבים, הצגת רעיונות,
בחירת רעיון, ותצוגת סיכום. הוא אינו מכיל לוגיקה עסקית.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from .errors import UserAbortError
from .schemas import Idea, ShortContent
from .tts_engine import SynthesisResult

MAX_TOPIC_LENGTH = 300


class _Palette:
    """קודי צבע ANSI (משמשים רק כשהפלט הוא טרמינל)."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"


class TerminalUI:
    """מנהל את כל האינטראקציה עם המשתמש דרך הטרמינל."""

    def __init__(self, *, no_color: bool = False, stream=None) -> None:
        self._stream = stream if stream is not None else sys.stdout
        env_no_color = bool(os.environ.get("NO_COLOR"))
        self._color_enabled = not (no_color or env_no_color) and self._supports_color(self._stream)

    # ------------------------------------------------------------------
    # עזרי צבע
    # ------------------------------------------------------------------
    @staticmethod
    def _supports_color(stream) -> bool:
        try:
            return bool(stream.isatty())
        except Exception:  # noqa: BLE001 – streams לא סטנדרטיים
            return False

    def _paint(self, text: str, color: str) -> str:
        if not self._color_enabled:
            return text
        return f"{color}{text}{_Palette.RESET}"

    # ------------------------------------------------------------------
    # פלט
    # ------------------------------------------------------------------
    def banner(self) -> None:
        line = "=" * 78
        print(self._paint(line, _Palette.BLUE))
        print(
            self._paint(
                "  🎬 Shorts Factory – מערכת אוטומציה חינמית לחומרי גלם של YouTube Shorts",
                _Palette.BOLD,
            )
        )
        print(self._paint(line, _Palette.BLUE))

    def step(self, number: int, title: str) -> None:
        print()
        print(self._paint(f"▶ שלב {number}/4 – {title}", _Palette.CYAN + _Palette.BOLD))

    def info(self, message: str) -> None:
        print(self._paint(f"ℹ️  {message}", _Palette.BLUE))

    def success(self, message: str) -> None:
        print(self._paint(f"✅ {message}", _Palette.GREEN))

    def warn(self, message: str) -> None:
        print(self._paint(f"⚠️  {message}", _Palette.YELLOW))

    def error(self, message: str) -> None:
        print(self._paint(f"❌ {message}", _Palette.RED), file=sys.stderr)

    # ------------------------------------------------------------------
    # קלט
    # ------------------------------------------------------------------
    def prompt_topic(self) -> str:
        """שואל את המשתמש על נושא כללי (חוזר על עצמו עד שמתקבל קלט תקין)."""
        while True:
            try:
                raw = input(
                    self._paint("\n🎯 הזן נושא כללי ל-Shorts (לדוגמה: טיפים לחיסכון בכסף): ", _Palette.CYAN)
                )
            except EOFError as exc:
                raise UserAbortError("לא התקבל קלט מהמשתמש (EOF).") from exc
            except KeyboardInterrupt as exc:
                raise UserAbortError("הוקלד Ctrl+C.") from exc

            topic = raw.strip()
            if not topic:
                self.warn("הנושא ריק – נסה שוב.")
                continue
            if len(topic) > MAX_TOPIC_LENGTH:
                self.warn(f"הנושא ארוך מדי ({len(topic)} תווים) – קיצרו ל-{MAX_TOPIC_LENGTH}.")
                continue
            return topic

    def prompt_choice(self, count: int) -> int:
        """מבקש מהמשתמש לבחור רעיון לפי מספר (1..count)."""
        while True:
            try:
                raw = input(
                    self._paint(f"\n👉 בחר את הרעיון המנצח (1-{count}, או 'q' ליציאה): ", _Palette.CYAN)
                )
            except EOFError as exc:
                raise UserAbortError("לא התקבל קלט מהמשתמש (EOF).") from exc
            except KeyboardInterrupt as exc:
                raise UserAbortError("הוקלד Ctrl+C.") from exc

            choice = raw.strip()
            if choice.lower() in {"q", "quit", "exit", "יציאה"}:
                raise UserAbortError("המשתמש בחר לצאת.")
            try:
                number = int(choice)
            except ValueError:
                self.warn("אנא הזן מספר תקין.")
                continue
            if 1 <= number <= count:
                return number
            self.warn(f"הבחירה חייבת להיות בין 1 ל-{count}.")

    # ------------------------------------------------------------------
    # תצוגות
    # ------------------------------------------------------------------
    def show_ideas(self, ideas: Sequence[Idea]) -> None:
        """מציג את רשימת הרעיונות שהתקבלו מה-AI."""
        print(self._paint(f"\n💡 {len(ideas)} רעיונות ל-Shorts שה-CAI יצר:", _Palette.MAGENTA + _Palette.BOLD))
        for idea in ideas:
            print()
            print(self._paint(f"  [{idea.number}] {idea.title}", _Palette.BOLD))
            if idea.hook:
                print(f"      הוק  : {idea.hook}")
            if idea.summary:
                print(f"      תקציר: {idea.summary}")

    def show_content_preview(self, content: ShortContent) -> None:
        """מציג תצוגה מקדימה של התוכן שנוצר (תסריט + פרומפטים + SEO)."""
        print()
        print(self._paint("📄 התוכן נוצר:", _Palette.GREEN + _Palette.BOLD))
        print(f"  כותרת SEO  : {content.title}")
        print(f"  תיאור      : {content.description}")
        print(f"  תגיות      : {len(content.tags)} | האשטאגים: {len(content.hashtags)}")
        print(f"  סצנות      : {len(content.scenes)}")
        print(
            f"  משך משוער  : ~{content.duration_estimate_seconds:.0f} שניות "
            f"({content.word_count} מילים)"
        )
        preview = content.script_text[:180]
        suffix = "..." if len(content.script_text) > 180 else ""
        print(f"  תסריט      : {preview}{suffix}")

    def print_final_summary(
        self,
        *,
        paths,
        content: ShortContent,
        audio: Optional[SynthesisResult],
        metadata_path: Path,
    ) -> None:
        """מציג סיכום סופי עם נתיבי הקבצים שנוצרו."""
        print()
        print(self._paint("=" * 78, _Palette.GREEN))
        print(self._paint("🎉 הסתיים! כל חומרי הגלם נשמרו:", _Palette.GREEN + _Palette.BOLD))
        print(f"  📁 תיקייה          : {paths.root}")
        print(f"  🎙️ קובץ קריינות     : {paths.audio.name if audio else 'לא הופק'}")
        print(f"  📄 מטאדאטה + SEO   : {metadata_path.name}")
        print(f"  🧾 JSON גולמי      : {paths.content_json.name}")
        print()
        print(self._paint("=" * 78, _Palette.GREEN))
        print("המשך עבודה: צרו את הווידאו לפי הפרומפטים האנגליים ב-Script_Metadata.txt,")
        print("הרכיבו עם הקריינות ב-CapCut (חינם) והעלו ל-YouTube Shorts.")

    # ------------------------------------------------------------------
    # עזרי הדרכה
    # ------------------------------------------------------------------
    def print_key_setup_help(self) -> None:
        """מדפיס הוראות מפורטות להגדרת מפתח ה-API של Groq."""
        print()
        print(self._paint("🔑 כיצד מגדירים את מפתח ה-API של Groq (חינם לחלוטין):", _Palette.BOLD))
        print("  1. היכנסו ל-https://console.groq.com/keys (הרשמה חינמית, ללא כרטיס אשראי).")
        print("  2. צרו מפתח חדש והעתיקו אותו (מתחיל ב- gsk_...).")
        print("  3. הגדירו אותו באחת מהדרכים הבאות:")
        print("     • לינוקס/macOS (לסשן הנוכחי):")
        print('         export GROQ_API_KEY="gsk_..."')
        print("     • לינוקס/macOS (קבוע):")
        print('         echo \'export GROQ_API_KEY="gsk_..."\' >> ~/.bashrc && source ~/.bashrc')
        print("     • Windows (CMD):")
        print("         set GROQ_API_KEY=gsk_...")
        print("     • Windows (PowerShell):")
        print('         $env:GROQ_API_KEY="gsk_..."')
        print("     • קובץ .env בשורש הפרויקט (ראו .env.example) – נטען אוטומטית.")
        print()
