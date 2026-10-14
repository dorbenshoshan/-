"""מנוע הקריינות החינמי (TTS).

מנגנון ראשי: ``gTTS`` – ספריית Python חינמית לחלוטין, ללא מפתח API וללא תשלום.
מנגנון גיבוי אופליין: ``pyttsx3`` (מבוסס espeak) – משמש אם אין חיבור אינטרנט.

המנוע בודק תמיד שהקובץ נוצר באמת ושגודלו סביר, כדי לא לייצר "שקט" בשקט.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .errors import TTSSynthesisError

# מגבלת גוגל לבקשה אחת (בתווים). התסריטים שלנו עד 50 שניות – בהחלט בטווח.
MAX_TTS_CHARS = 5000
# מינימום בייטים שקובץ תקין צריך להגיע אליו (קבצים "ריקים" נזרקים)
MIN_AUDIO_BYTES = 1024

# ייבוא עצל של gTTS (כך שהמודול נטען גם בלי הספרייה)
try:  # pragma: no cover - תלוי בסביבה
    from gtts import gTTS as GTTSSynthesizer
except ImportError:  # pragma: no cover
    GTTSSynthesizer = None  # type: ignore[assignment]


@dataclass(frozen=True)
class SynthesisResult:
    """תוצאת הפקת הקריינות."""

    path: Path
    engine: str
    size_bytes: int


class TextToSpeechEngine:
    """מנהל את המרת טקסט לאודיו, עם גיבוי אוטומטי."""

    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self._settings = settings
        self._logger = logger

    # ------------------------------------------------------------------
    # API ציבורי
    # ------------------------------------------------------------------
    def synthesize(self, text: str, output_path: Path) -> SynthesisResult:
        """ממיר טקסט לקובץ שמע.

        מנסה תחילה gTTS; אם היא נכשלה (אין אינטרנט, חסימת רשת וכד') –
        עובר אוטומטית ל-pyttsx3 האופליין.

        Raises:
            TTSSynthesisError: אם שני המנגנונים נכשלו או שהטקסט אינו תקין.
        """
        clean_text = (text or "").strip()
        if not clean_text:
            raise TTSSynthesisError("אין טקסט להקרנה – התסריט ריק.")
        if len(clean_text) > MAX_TTS_CHARS:
            raise TTSSynthesisError(
                f"טקסט התסריט ארוך מדי ({len(clean_text)} תווים). "
                f"המקסימום לבקשה אחת הוא {MAX_TTS_CHARS}."
            )

        output_path = Path(output_path)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TTSSynthesisError(f"יצירת תיקיית האודיו נכשלה: {exc}") from exc

        try:
            return self._synthesize_with_gtts(clean_text, output_path)
        except TTSSynthesisError as exc:
            self._logger.warning(
                "gTTS נכשלה (%s). מנסה מנוע אופליין חלופי (pyttsx3)...", exc
            )

        return self._synthesize_with_pyttsx3(clean_text, output_path)

    # ------------------------------------------------------------------
    # מנגנון 1: gTTS (חינמי, דורש אינטרנט)
    # ------------------------------------------------------------------
    def _synthesize_with_gtts(self, text: str, output_path: Path) -> SynthesisResult:
        """הפקה באמצעות gTTS. זורק TTSSynthesisError בכל כשל."""
        if GTTSSynthesizer is None:
            raise TTSSynthesisError("gTTS לא מותקנת. התקן עם: pip install gTTS")

        lang = self._settings.tts_lang
        if not self._is_supported_lang(lang):
            raise TTSSynthesisError(
                f"שפת הקריינות '{lang}' אינה נתמכת ע\"י gTTS (עברית = 'iw')."
            )

        try:
            synthesizer = GTTSSynthesizer(text=text, lang=lang, slow=self._settings.tts_slow)
            synthesizer.save(str(output_path))
        except Exception as exc:  # noqa: BLE001 – gTTS עלולה לזרוק דברים רבים
            raise TTSSynthesisError(f"כשל ב-gTTS: {exc}") from exc

        self._verify_audio(output_path)
        self._logger.info(
            "אודיו הופק בהצלחה בעזרת gTTS (שפה=%s, איטי=%s): %s",
            lang, self._settings.tts_slow, output_path.name,
        )
        return SynthesisResult(
            path=output_path, engine="gTTS", size_bytes=output_path.stat().st_size
        )

    @staticmethod
    def _is_supported_lang(lang: str) -> bool:
        """בודק מול רשימת השפות הפנימית של gTTS (ללא קריאת רשת)."""
        try:
            from gtts.lang import tts_langs  # ייבוא מקומי – זול וללא רשת

            return lang in tts_langs()
        except Exception:  # noqa: BLE001 – אם הרשימה לא נגישה, נותנים לזה להיכשל מאוחר יותר
            return True

    # ------------------------------------------------------------------
    # מנגנון 2: pyttsx3 (אופליין, גיבוי)
    # ------------------------------------------------------------------
    def _synthesize_with_pyttsx3(self, text: str, output_path: Path) -> SynthesisResult:
        """הפקה אופליין עם pyttsx3. מגיע ל-WAV בלבד (מגבלת המנוע)."""
        try:
            import pyttsx3
        except ImportError as exc:
            raise TTSSynthesisError(
                "גם gTTS וגם pyttsx3 אינם זמינים. התקן את gTTS עם: pip install gTTS"
            ) from exc

        target_path = output_path
        if output_path.suffix.lower() != ".wav":
            target_path = output_path.with_suffix(".wav")
            self._logger.warning(
                "pyttsx3 שומר רק קבצי WAV – הקובץ יישמר כ-%s במקום %s.",
                target_path.name, output_path.name,
            )

        try:
            engine = pyttsx3.init()
            try:
                engine.setProperty("rate", 165)  # קצב דיבור נוח לעריכה
                engine.save_to_file(text, str(target_path))
                engine.runAndWait()
            finally:
                try:
                    engine.stop()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            raise TTSSynthesisError(
                f"כשל ב-pyttsx3 ({exc}). בדוק שהמנוע espeak מותקן במערכת."
            ) from exc

        self._verify_audio(target_path)
        self._logger.info("אודיו הופק בעזרת מנוע הגיבוי האופליין: %s", target_path.name)
        return SynthesisResult(
            path=target_path, engine="pyttsx3", size_bytes=target_path.stat().st_size
        )

    # ------------------------------------------------------------------
    # אימות
    # ------------------------------------------------------------------
    @staticmethod
    def _verify_audio(path: Path) -> None:
        """מוודא שהקובץ קיים ושגודלו מעל המינימום (לא "ריק")."""
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise TTSSynthesisError(f"קובץ האודיו '{path}' לא נוצר.") from exc
        if size < MIN_AUDIO_BYTES:
            raise TTSSynthesisError(
                f"קובץ האודיו '{path}' נוצר אבל נראה ריק ({size} בתים)."
            )
