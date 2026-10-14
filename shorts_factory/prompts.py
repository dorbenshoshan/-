"""תבניות הפרומפטים שנשלחים למודל ה-AI של Groq.

כל הפרומפטים נבנים כך שהמודל **יחזיר אך ורק אובייקט JSON תקין** (Groq תומכת
ב-JSON mode), ושכל הטקסטים שמופנים למשתמש – בעברית שוטפת, בעוד הפרומפטים
לוידאו נכתבים באנגלית (כי כך עובדים כלי הווידאו החינמיים).
"""

from __future__ import annotations

from typing import Any

from .schemas import Idea

# ---------------------------------------------------------------------------
# שלב 1 – יצירת רעיונות
# ---------------------------------------------------------------------------
IDEAS_SYSTEM_PROMPT = """You are a world-class YouTube Shorts strategist who has grown
multiple channels to millions of views. You know exactly what makes people stop scrolling.

STRICT OUTPUT RULES:
- You ALWAYS answer with ONE single valid JSON object and NOTHING else.
- No markdown, no code fences, no explanations, no text before or after the JSON.
- All user-facing strings inside the JSON (title, hook, summary) MUST be written in
  fluent, natural, SPOKEN Hebrew - the kind of Hebrew a creator says out loud on camera.
- Never write user-facing text in English."""

IDEAS_JSON_SCHEMA = """{
  "ideas": [
    {
      "number": 1,
      "title": "כותרת קליטה בעברית (עד 60 תווים)",
      "hook": "משפט הפתיחה הנאמר בסרטון (עד 2 שניות)",
      "summary": "תקציר של 1-2 משפטים על הערך של הסרטון"
    }
  ]
}"""

IDEAS_USER_TEMPLATE = """Create exactly {count} viral YouTube Shorts ideas for the general
topic: "{topic}".

Requirements for EVERY idea:
- "title": a punchy, curiosity-driven Hebrew title (max 60 characters). No clickbait lies.
- "hook": the very first sentence spoken in the video (Hebrew) - it must stop the scroll
  in under 2 seconds (question, bold claim, or surprising fact).
- "summary": 1-2 short Hebrew sentences describing the concrete value/angle of the short.
- Cover DIFFERENT emotional angles across the ideas: curiosity, FOMO, quick win,
  contrarian opinion, mini-story, mistake-to-avoid.
- Every idea must be filmable as a vertical short of up to 50 seconds.

Return ONLY this JSON schema (no markdown):
{schema}"""


def build_ideas_messages(topic: str, count: int) -> list[dict[str, Any]]:
    """בונה את רשימת ההודעות (system + user) לייצור הרעיונות."""
    user_prompt = IDEAS_USER_TEMPLATE.format(
        topic=topic.strip(), count=count, schema=IDEAS_JSON_SCHEMA
    )
    return [
        {"role": "system", "content": IDEAS_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


# ---------------------------------------------------------------------------
# שלב 2 – תסריט, פרומפטים ויזואליים ו-SEO
# ---------------------------------------------------------------------------
CONTENT_SYSTEM_PROMPT = """You are an expert short-form video scriptwriter, a prompt
engineer for AI video generators, and a YouTube SEO specialist.

STRICT OUTPUT RULES:
- You ALWAYS answer with ONE single valid JSON object and NOTHING else.
- No markdown, no code fences, no explanations.
- Narration, SEO title and description MUST be fluent, natural, SPOKEN Hebrew.
- Every "visual_prompt" MUST be written in English (it is fed to AI video tools).
- Respect all numeric limits exactly (scene count, tag count, script length)."""

CONTENT_JSON_SCHEMA = """{
  "title": "כותרת SEO בעברית עם פוטנציאל הקלקה מקסימלי (עד 70 תווים)",
  "description": "תיאור קצר ל-YouTube בעברית (2-3 משפטים) עם קריאה לפעולה",
  "hashtags": ["#האשטאג1", "#האשטאג2"],
  "tags": ["תגית1", "תגית2"],
  "script": {
    "full_text": "טקסט הקריינות המלא בעברית (עד 50 שניות)",
    "scenes": [
      {
        "scene_number": 1,
        "time_range": "0-12s",
        "narration": "החלק מהתסריט שנאמר בסצנה",
        "visual_prompt": "Detailed English prompt for an AI video generator"
      }
    ]
  }
}"""

CONTENT_USER_TEMPLATE = """Write the complete production package for this YouTube Short idea:

Idea number: {number}
Title: {title}
Hook: {hook}
Summary: {summary}

Requirements:
1. "script.full_text": the complete voice-over narration in Hebrew. It must be readable
   in AT MOST {max_seconds} seconds (about 110-130 Hebrew words). Punchy, spoken language,
   no stage directions, no emojis, no English.
2. "script.scenes": exactly {scenes} visual scenes that cover the whole script.
   For each scene provide:
   - "scene_number": integer, starting from 1
   - "time_range": e.g. "0-12s"
   - "narration": the Hebrew narration spoken during that scene (a slice of full_text)
   - "visual_prompt": a DETAILED English prompt for a free AI video generator
     (Runway, Pika, Kling, Haiper, Luma...). Include: subject, action, camera movement,
     lighting, mood, and "vertical 9:16 composition". Max 60 words. NO on-screen text.
3. "title": an SEO title in Hebrew, max 70 characters, engineered for maximum
   click-through rate (numbers, power words, curiosity gap).
4. "description": a short YouTube description in Hebrew (2-3 sentences) ending with a
   call to action (like / subscribe / comment).
5. "tags": EXACTLY {tags} YouTube search tags in Hebrew (Hebrew/English mix is OK where
   natural). No "#" prefix, no duplicates.
6. "hashtags": between 5 and 8 strong hashtags, each starting with "#".

Return ONLY this JSON schema (no markdown):
{schema}"""


def build_content_messages(
    idea: Idea,
    *,
    scenes: int = 3,
    tags: int = 15,
    max_seconds: int = 50,
) -> list[dict[str, Any]]:
    """בונה את רשימת ההודעות (system + user) לייצור התסריט/פרומפטים/SEO."""
    user_prompt = CONTENT_USER_TEMPLATE.format(
        number=idea.number,
        title=idea.title,
        hook=idea.hook,
        summary=idea.summary,
        scenes=scenes,
        tags=tags,
        max_seconds=max_seconds,
        schema=CONTENT_JSON_SCHEMA,
    )
    return [
        {"role": "system", "content": CONTENT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
