/* ==========================================================================
   Shorts Factory – לוגיקת הדפדפן
   הלוגיקה מתבססת על 4 שלבים שנשלחים לשרת המקומי (FastAPI):
     1. /api/check    – בדיקת המפתח
     2. /api/ideas    – 5 רעיונות לנושא
     3. /api/content  – תסריט + פרומפטים + SEO
     4. /api/project  – הפקת שמע + קבצים
   המפתח נשלח בכל בקשה בכותרת X-Groq-API-Key (ונשמר רק ב-sessionStorage).
   ========================================================================== */

"use strict";

// ---------------------------------------------------------------------------
// מצב הגלובלי של האפליקציה
// ---------------------------------------------------------------------------
const state = {
  apiKey: sessionStorage.getItem("sf_api_key") || "",
  model: "",
  demo: false,
  topic: "",
  ideas: [],
  selectedIdea: null,
  content: null,
  project: null,
};

// ---------------------------------------------------------------------------
// עזרי DOM
// ---------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);

function showStep(step) {
  document.querySelectorAll(".card").forEach((card) => card.classList.remove("active"));
  const card = $(`step-${step}`);
  if (card) card.classList.add("active");

  document.querySelectorAll(".step-dot").forEach((dot) => {
    const dotStep = Number(dot.dataset.step);
    dot.classList.toggle("active", dotStep === step);
    dot.classList.toggle("done", dotStep < step);
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

let toastTimer = null;
function toast(message, type = "info", duration = 5000) {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), duration);
}

function setBusy(button, busy, busyText = "מעבד...") {
  if (!button) return;
  if (busy) {
    button.dataset.originalText = button.innerHTML;
    button.innerHTML = `<span class="spinner"></span>${busyText}`;
    button.disabled = true;
  } else {
    button.innerHTML = button.dataset.originalText || button.innerHTML;
    button.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// שכבת התקשורת עם השרת
// ---------------------------------------------------------------------------
async function api(path, body = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.apiKey) headers["X-Groq-API-Key"] = state.apiKey;

  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
  } catch (networkError) {
    throw new Error("לא הצלחתי להתחבר לשרת. ודאו שהשרת רץ (python webapp/server.py).");
  }

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    if (response.status === 401) {
      // בעיה במפתח – חוזרים לשלב 0
      showStep(0);
      throw new Error(data.detail || "מפתח ה-API אינו תקין או חסר.");
    }
    throw new Error(data.detail || `השרת החזיר שגיאה (${response.status}).`);
  }
  return data;
}

// ---------------------------------------------------------------------------
// שלב 0: מפתח API
// ---------------------------------------------------------------------------
function initStep0() {
  if (state.apiKey) $("apiKey").value = state.apiKey;

  $("checkKeyBtn").addEventListener("click", async () => {
    state.apiKey = $("apiKey").value.trim();
    state.model = $("modelSelect").value;
    if (!state.apiKey) {
      toast("נא להזין מפתח API תחילה.", "error");
      return;
    }
    const result = $("checkResult");
    result.textContent = "בודק...";
    result.className = "check-result";
    setBusy($("checkKeyBtn"), true, "בודק...");
    try {
      const data = await api("/api/check", { model: state.model || null });
      result.textContent = `✅ המפתח תקין! ${data.models.length} מודלים זמינים.`;
      result.className = "check-result ok";
      toast("החיבור ל-Groq הצליח!", "success");
    } catch (error) {
      result.textContent = `❌ ${error.message}`;
      result.className = "check-result err";
      toast(error.message, "error", 7000);
    } finally {
      setBusy($("checkKeyBtn"), false);
    }
  });

  $("toStep1Btn").addEventListener("click", () => {
    state.apiKey = $("apiKey").value.trim();
    state.model = $("modelSelect").value;
    if (!state.apiKey) {
      toast("נא להזין מפתח API כדי להמשיך.", "error");
      return;
    }
    if ($("rememberKey").checked) {
      sessionStorage.setItem("sf_api_key", state.apiKey);
    }
    showStep(1);
  });
}

// ---------------------------------------------------------------------------
// שלב 1: נושא + רעיונות
// ---------------------------------------------------------------------------
function initStep1() {
  $("genIdeasBtn").addEventListener("click", async () => {
    const topic = $("topicInput").value.trim();
    if (topic.length < 2) {
      toast("נא להזין נושא (לפחות 2 תווים).", "error");
      return;
    }
    state.topic = topic;
    setBusy($("genIdeasBtn"), true, "מייצר רעיונות...");
    try {
      const data = await api("/api/ideas", { topic, model: state.model || null, demo: state.demo });
      state.ideas = data.ideas;
      renderIdeas(data.ideas);
      $("ideasBox").classList.remove("hidden");
      toast(`התקבלו ${data.ideas.length} רעיונות!`, "success");
    } catch (error) {
      toast(error.message, "error", 7000);
    } finally {
      setBusy($("genIdeasBtn"), false);
    }
  });

  $("genContentBtn").addEventListener("click", async () => {
    if (!state.selectedIdea) {
      toast("נא לבחור רעיון מהרשימה.", "error");
      return;
    }
    setBusy($("genContentBtn"), true, "כותב תסריט...");
    try {
      const data = await api("/api/content", {
        idea: state.selectedIdea,
        model: state.model || null,
        demo: state.demo,
      });
      state.content = data.content;
      renderContent(data.content);
      showStep(2);
    } catch (error) {
      toast(error.message, "error", 7000);
    } finally {
      setBusy($("genContentBtn"), false);
    }
  });
}

function renderIdeas(ideas) {
  const box = $("ideasList");
  box.innerHTML = "";
  ideas.forEach((idea, index) => {
    const card = document.createElement("div");
    card.className = "idea-card";
    card.innerHTML = `
      <div class="idea-title"><span class="idea-num">#${idea.number}</span>${escapeHtml(idea.title)}</div>
      <div class="idea-hook">🎣 ${escapeHtml(idea.hook || "")}</div>
      <div class="idea-summary">${escapeHtml(idea.summary || "")}</div>
    `;
    card.addEventListener("click", () => {
      box.querySelectorAll(".idea-card").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      state.selectedIdea = idea;
    });
    box.appendChild(card);
    if (index === 0) card.click(); // בחירת הרעיון הראשון כברירת מחדל
  });
}

// ---------------------------------------------------------------------------
// שלב 2: הצגת התסריט וה-SEO
// ---------------------------------------------------------------------------
function renderContent(content) {
  const box = $("contentBox");
  const script = content.script || {};
  const scenes = script.scenes || [];

  const scenesHtml = scenes
    .map(
      (scene) => `
      <div class="scene">
        <div class="scene-head">
          <strong>סצנה ${scene.scene_number}</strong>
          <span class="time">${escapeHtml(scene.time_range || "")}</span>
        </div>
        <div class="narration">🗣️ ${escapeHtml(scene.narration || "")}</div>
        <div class="prompt" id="prompt-${scene.scene_number}">${escapeHtml(scene.visual_prompt || "")}</div>
        <button class="secondary small copy-btn" data-target="prompt-${scene.scene_number}">📋 העתק פרומפט</button>
      </div>`
    )
    .join("");

  box.innerHTML = `
    <h3>🏆 כותרת ל-SEO</h3>
    <div class="seo-title-box" id="seoTitle">${escapeHtml(content.title || "")}</div>
    <button class="secondary small copy-btn" data-target="seoTitle">📋 העתק כותרת</button>

    <h3>📝 תיאור ל-YouTube</h3>
    <div class="script-box" id="seoDesc">${escapeHtml(content.description || "")}</div>
    <button class="secondary small copy-btn" data-target="seoDesc">📋 העתק תיאור</button>

    <h3>🎙️ תסריט הקריינות (${script.word_count || 0} מילים, ~${Math.round(
      script.duration_estimate_seconds || 0
    )} שניות)</h3>
    <div class="script-box" id="scriptText">${escapeHtml(script.full_text || "")}</div>
    <button class="secondary small copy-btn" data-target="scriptText">📋 העתק תסריט</button>

    <h3>🎨 סצנות ויזואליות + פרומפטים לאנגלית (${scenes.length})</h3>
    ${scenesHtml}

    <h3>🏷️ תגיות (${(content.tags || []).length})</h3>
    <div class="chips">${(content.tags || []).map((tag) => `<span class="chip">${escapeHtml(tag)}</span>`).join("")}</div>

    <h3>#️⃣ האשטאגים</h3>
    <div class="chips">${(content.hashtags || [])
      .map((tag) => `<span class="chip hash">${escapeHtml(tag)}</span>`)
      .join("")}</div>
  `;

  // כפתורי העתקה
  box.querySelectorAll(".copy-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const text = $(btn.dataset.target).textContent;
      try {
        await navigator.clipboard.writeText(text);
        btn.textContent = "✅ הועתק!";
      } catch {
        btn.textContent = "❌ לא הצלחתי להעתיק";
      }
      setTimeout(() => (btn.textContent = "📋 העתק"), 1500);
    });
  });
}

// ---------------------------------------------------------------------------
// שלב 3+4: הפקת הפרויקט
// ---------------------------------------------------------------------------
function initStep3() {
  $("genProjectBtn").addEventListener("click", async () => {
    setBusy($("genProjectBtn"), true, "מייצר שמע...");
    try {
      const data = await api("/api/project", {
        topic: state.topic,
        idea: state.selectedIdea,
        content: state.content,
        make_audio: $("makeAudioChk").checked,
        model: state.model || null,
        demo: state.demo,
      });
      state.project = data;
      renderProject(data);
      showStep(3);
      toast("כל חומרי הגלם מוכנים!", "success");
    } catch (error) {
      toast(error.message, "error", 7000);
    } finally {
      setBusy($("genProjectBtn"), false);
    }
  });

  $("restartBtn").addEventListener("click", () => {
    state.ideas = [];
    state.selectedIdea = null;
    state.content = null;
    state.project = null;
    $("topicInput").value = "";
    $("ideasBox").classList.add("hidden");
    $("contentBox").innerHTML = "";
    $("filesBox").innerHTML = "";
    $("audioBox").classList.add("hidden");
    $("audioErrorBox").classList.add("hidden");
    showStep(1);
  });
}

function renderProject(project) {
  $("projectDirHint").textContent = `נשמר בשרת תחת: ${project.project_dir}`;

  // נגן האודיו
  if (project.files.audio) {
    $("audioPlayer").src = project.files.audio;
    $("audioBox").classList.remove("hidden");
  } else {
    $("audioBox").classList.add("hidden");
  }

  // הודעת שגיאה על האודיו (אם היתה)
  if (project.audio_error) {
    $("audioErrorBox").textContent = `⚠️ הפקת השמע נכשלה: ${project.audio_error}\n(קבצי הטקסט נוצרו כרגיל.)`;
    $("audioErrorBox").classList.remove("hidden");
  } else {
    $("audioErrorBox").classList.add("hidden");
  }

  // קישורי הורדה
  const files = [
    { url: project.files.metadata, name: "Script_Metadata.txt", desc: "תסריט + פרומפטים + SEO" },
    { url: project.files.audio, name: project.audio ? project.audio.filename : null, desc: "קריינות בעברית" },
    { url: project.files.json, name: "content.json", desc: "נתונים גולמיים מה-AI" },
  ].filter((file) => file.url);

  $("filesBox").innerHTML = files
    .map(
      (file) => `
      <a class="file-link" href="${file.url}" download>
        <span class="fname">📄 ${escapeHtml(file.name)}</span>
        <span class="fdesc">${escapeHtml(file.desc)} ⬇️</span>
      </a>`
    )
    .join("");
}

// ---------------------------------------------------------------------------
// עזרים
// ---------------------------------------------------------------------------
function escapeHtml(text) {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ---------------------------------------------------------------------------
// אתחול
// ---------------------------------------------------------------------------
async function initDemoMode() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    state.demo = Boolean(data.demo_mode);
  } catch {
    state.demo = false;
  }
  $("demoModeChk").checked = state.demo;
  $("demoModeChk").addEventListener("change", (event) => {
    state.demo = event.target.checked;
    $("demoBadge").classList.toggle("hidden", !state.demo);
  });
  $("demoBadge").classList.toggle("hidden", !state.demo);
}

document.addEventListener("DOMContentLoaded", () => {
  initStep0();
  initStep1();
  initStep3();
  initDemoMode();
  showStep(0);
});
