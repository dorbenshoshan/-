"""נתוני הדגמה + ייצור קובץ שמע הדגמה (ללא אינטרנט).

מצב הדגמה מאפשר לבדוק את **כל** זרימת העבודה באתר (רעיונות → תסריט → שמע → הורדות)
גם כשאין גישה ל-Groq או ל-Google TTS – למשל בסביבה WITHOUT אינטרנט או כדי שהמשתמש
יבין איך הממשק עובד לפני שמזין מפתח API אמיתי.

כל הנתונים כאן הם דוגמה בלבד ואין בהם קריאה ל-AI.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

# ---------------------------------------------------------------------------
# 5 רעיונות לדוגמה
# ---------------------------------------------------------------------------
DEMO_IDEAS = [
    {
        "number": 1,
        "title": "5 טעויות שגורמות לכם להפסיד כסף כל חודש",
        "hook": "אם אתם חושבים שחסכון זה רק להפקיד בבנק – אפסתם לגמרי.",
        "summary": "חמש טעויות יומיומיות שנעשות בלי לשים לב, וכל אחת מהן עולה לכם מאות שקלים בחודש.",
    },
    {
        "number": 2,
        "title": "למה העשירים לא קונים מכוניות חדשות",
        "hook": "המכונית החדשה שלכם מאבדת 30% מערכה ברגע שיוצאים מהסלון.",
        "summary": "ההסבר הפשוט למכונית משומשת, ותרגיל חשבון מהיר שמראה לכם בכמה באמת זה עולה.",
    },
    {
        "number": 3,
        "title": "3 דקות של בוקר שיחסכו לכם 500 ש״ח בחודש",
        "hook": "שלוש דקות בכל בוקר – ומאפיינים מאות שקלים לחיסון בכל חודש.",
        "summary": "שגרה בוקר קטנה: בדיקת סכומים, ביטול מנויים, והעברת עודפים – הכל מהנייד.",
    },
    {
        "number": 4,
        "title": "הטעות הכי יקרה שעושים בגיל 30",
        "hook": "זו הטעות שרוב האנשים עושים בלי להבין מה העלות שלה בעוד 20 שנה.",
        "summary": "על דחיית השקעה, ותרגיל פשוט שמראה את ההבדל בין להתחיל היום ובין בעוד 5 שנים.",
    },
    {
        "number": 5,
        "title": "איך לבנות קרן חירום בלי להיפגע באורח חיים",
        "hook": "אין צורך לוותר על קפה כדי לבנות קרן חירום – יש דרך חכמה יותר.",
        "summary": "שיטת 3 קופות פשוטה שמאפשרת לחסוך בלי להרגיש ויתור, עם דוגמה מספרית.",
    },
]

# ---------------------------------------------------------------------------
# תסריט + פרומפטים + SEO לדוגמה
# ---------------------------------------------------------------------------
DEMO_CONTENT = {
    "title": "5 טעויות שגורמות לכם להפסיד כסף כל חודש 💸",
    "description": "בסרטון הזה תגלו 5 טעויות נפוצות שעושות לכם להפסיד מאות שקלים כל חודש – "
    "ואיך לתקן כל אחת מהן בעשר דקות. עשו לייק והישארו לעוד טיפים על כסף.",
    "hashtags": ["#כסף", "#חסכון", "#טיפים_לחיסכון", "#פיננסים", "#שורטס", "#כלכלה"],
    "tags": [
        "טיפים לחיסכון",
        "ניהול כספים",
        "חסכון חודשי",
        "טעויות בכסף",
        "ייעוץ פיננסי",
        "תקציב אישי",
        "כסף חכם",
        "חיסכון לילדים",
        "פיננסים אישיים",
        "טיפים כספיים",
        "איך לחסוך",
        "מעקב הוצאות",
        "מנויים מיותרים",
        "רכישות אימפולסיביות",
        "money tips",
    ],
    "script": {
        "full_text": "אם אתם חושבים שחסכון זה רק להפקיד בבנק, אפסתם לחלוטין. הנה חמש טעויות "
        "שעושים כמעט כולנו, ואתם עדיין יכולים לתקן אותן עוד היום. הראשונה: מנויים שאתם "
        "לא משתמשים בהם – בממוצע הם עולים בין 150 ל-400 שקלים בחודש. השנייה: "
        "קניות אימפולסיביות – חכו 48 שעות לפני כל קנייה מעל מאה שקל. השלישית: אין תקציב "
        "כתוב – בלי לעקוב, הכסף פשוט נעלם. הרביעית: לא חוצים על המחיר מול הספק – שינו חבילה פעם בשנה. "
        "והחמישית: אין קרן חירום – התחילו מ-500 שקל ותגדילו. שמרו את הסרטון, והתחילו מהטעות "
        "הראשונה עוד הערב.",
        "word_count": 128,
        "duration_estimate_seconds": 49.2,
        "scenes": [
            {
                "scene_number": 1,
                "time_range": "0-11s",
                "narration": "אם אתם חושבים שחסכון זה רק להפקיד בבנק, אפסתם לחלוטין. הנה חמש טעויות שעושים כמעט כולנו.",
                "visual_prompt": "Cinematic close-up of a young person looking shocked at a banking app on their phone, "
                "warm apartment lighting, slow dolly in, shallow depth of field, vertical 9:16 composition, no text on screen.",
            },
            {
                "scene_number": 2,
                "time_range": "11-24s",
                "narration": "הראשונה: מנויים שאתם לא משתמשים בהם – בממוצע הם עולים בין 150 ל-400 שקלים בחודש.",
                "visual_prompt": "Overhead shot of subscription icons floating above a kitchen table, soft morning light, "
                "gentle camera drift, minimal modern interior, vertical 9:16 composition, no text on screen.",
            },
            {
                "scene_number": 3,
                "time_range": "24-37s",
                "narration": "השנייה: קניות אימפולסיביות – חכו 48 שעות לפני כל קנייה מעל מאה שקל. השלישית: אין תקציב כתוב.",
                "visual_prompt": "Split scene of a hand hesitating over a credit card at a store checkout, shallow depth of field, "
                "cool retail lighting, subtle slow motion, vertical 9:16 composition, no text on screen.",
            },
            {
                "scene_number": 4,
                "time_range": "37-50s",
                "narration": "והחמישית: אין קרן חירום – התחילו מ-500 שקל ותגדילו. שמרו את הסרטון והתחילו עוד הערב.",
                "visual_prompt": "A smiling person placing coins into a glass savings jar on a sunny windowsill, golden hour light, "
                "slow tilt up, cozy hopeful mood, vertical 9:16 composition, no text on screen.",
            },
        ],
    },
}


# ---------------------------------------------------------------------------
# ייצור קובץ שמע הדגמה (WAV אמיתי, ללא אינטרנט)
# ---------------------------------------------------------------------------
def write_demo_wav(path: Path, seconds: float = 6.0, sample_rate: int = 22050) -> Path:
    """מייצר קובץ WAV תקין וסמוך לגל חמים – כדי שהנגן בדפדפן וההורדות יעבדו.

    Args:
        path: נתיב ה-WAV ליצירה.
        seconds: משך הקובץ בשניות.
        sample_rate: קצב הדגימה.

    Returns:
        הנתיב לקובץ שנוצר.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    total_frames = int(seconds * sample_rate)
    frames = bytearray()
    for i in range(total_frames):
        t = i / sample_rate
        # שני גלי סינוס + דעיכה עדינה – נשמע כמו "צליל הדגמה" נעים
        value = 0.30 * math.sin(2 * math.pi * 220 * t)
        value += 0.15 * math.sin(2 * math.pi * 330 * t)
        value *= 0.55 + 0.45 * math.sin(2 * math.pi * 0.25 * t)
        frames.extend(struct.pack("<h", int(max(-1.0, min(1.0, value)) * 32767)))

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)          # מונו
        wav_file.setsampwidth(2)          # 16-ביט
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(bytes(frames))

    return path


if __name__ == "__main__":
    out = write_demo_wav(Path("/tmp/demo_voice.wav"))
    print(f"נוצר קובץ הדגמה: {out} ({out.stat().st_size:,} בתים)")
