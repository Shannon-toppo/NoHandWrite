"use strict";
/* Typesetting tool: lay out text in the writer's handwriting on a mm page,
 * preview it, and export pen-plotter G-code (or SVG). */

const $ = (id) => document.getElementById(id);

function setStatus(m) { $("status").textContent = m; }

const JITTER_IDS = { hiragana: "jHiragana", katakana: "jKatakana", kanji: "jKanji",
                     alnum: "jAlnum", other: "jOther" };

function jitterParams() {
  const j = {};
  for (const [key, id] of Object.entries(JITTER_IDS)) j[key] = Number($(id).value);
  return j;
}

function params() {
  return {
    writer: $("writerSel").value,
    text: $("text").value.replace(/\s+$/, ""),
    smooth: $("smoothChk").checked,
    jitter: jitterParams(),
    char_size_mm: Number($("charSize").value) || 15,
    char_gap_mm: Number($("charGap").value) || 0,
    line_gap_mm: Number($("lineGap").value) || 0,
    max_width_mm: Number($("maxWidth").value) || 180,
    margin_mm: Number($("margin").value) || 0,
    proportional: $("propChk").checked,
    vertical: $("vertChk").checked,
  };
}

function num(id, fallback) {
  const v = Number($(id).value);
  return Number.isFinite(v) ? v : fallback;
}

function gcodeParams() {
  return {
    feed_draw: Number($("feedDraw").value) || 1500,
    feed_travel: Number($("feedTravel").value) || 3000,
    pen_up_cmd: $("penUp").value.trim() || "G0 Z5.0",
    pen_down_cmd: $("penDown").value.trim() || "G1 Z0.0 F300",
    flip_y: $("flipY").checked,
    pressure_width: $("pressWidthChk").checked,
    pressure_z: $("pressZChk").checked,
    z_light: num("zLight", 0),
    z_heavy: num("zHeavy", -0.4),
  };
}

let lastPreview = null;                       // redraw on checkbox toggle

function drawPreview(data) {
  lastPreview = data;
  const [pw, ph] = data.page;                 // mm
  const canvas = $("page");
  const container = canvas.parentElement.getBoundingClientRect();
  const scale = Math.min((container.width - 32) / pw, 3.5); // px per mm
  const dpr = window.devicePixelRatio || 1;
  canvas.style.width = `${pw * scale}px`;
  canvas.style.height = `${ph * scale}px`;
  canvas.width = Math.round(pw * scale * dpr);
  canvas.height = Math.round(ph * scale * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr * scale, 0, 0, dpr * scale, 0, 0);   // draw in mm units
  ctx.clearRect(0, 0, pw, ph);
  if ($("ruleChk").checked && data.guides) {
    ctx.strokeStyle = "#9db4d0";
    ctx.lineWidth = 0.2;
    for (const [a, b] of data.guides) {
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(b[0], b[1]);
      ctx.stroke();
    }
  }
  ctx.strokeStyle = "#111";
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  const pressOn = $("pressWidthChk").checked;
  for (const s of data.strokes) {
    const pts = s.points;
    // points are [x, y] or [x, y, pressure]; with pressure data and the
    // toggle on, draw per-segment widths matching the SVG export (0.2–1.0mm)
    if (pressOn && pts[0].length > 2 && pts.some((q) => q[2] > 0)) {
      for (let i = 1; i < pts.length; i++) {
        const p = Math.min(Math.max((pts[i - 1][2] + pts[i][2]) / 2, 0), 1);
        ctx.lineWidth = 0.2 + 0.8 * p;
        ctx.beginPath();
        ctx.moveTo(pts[i - 1][0], pts[i - 1][1]);
        ctx.lineTo(pts[i][0], pts[i][1]);
        ctx.stroke();
      }
      continue;
    }
    ctx.lineWidth = 0.4;
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.stroke();
  }
  const nGen = Object.values(data.modes).filter((m) => m === "generated").length;
  const nAvg = Object.values(data.modes).filter((m) => m !== "generated").length;
  $("pageinfo").textContent =
    `ページ: ${pw} × ${ph} mm / ストローク数: ${data.strokes.length} / ` +
    `自分の筆跡 ${nAvg} 字種・AI生成 ${nGen} 字種`;
}

async function preview() {
  const p = params();
  if (!p.writer || !p.text) { setStatus("書き手と文章を指定してください"); return; }
  setStatus("レイアウト中…(未入力文字があると初回はモデル読み込みで数十秒かかります)");
  $("preview").disabled = true;
  try {
    const res = await fetch("/api/typeset", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    });
    if (!res.ok) throw new Error(await res.text());
    drawPreview(await res.json());
    setStatus("プレビュー更新");
  } catch (err) {
    setStatus(`失敗: ${err.message}`);
  } finally {
    $("preview").disabled = false;
  }
}

async function download(format) {
  const p = params();
  if (!p.writer || !p.text) { setStatus("書き手と文章を指定してください"); return; }
  setStatus(`${format} を作成中…`);
  try {
    const res = await fetch("/api/export", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...p, ...gcodeParams(), format }),
    });
    if (!res.ok) throw new Error(await res.text());
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = format === "svg" ? "nohandwrite.svg" : "nohandwrite.gcode";
    a.click();
    URL.revokeObjectURL(a.href);
    setStatus("ダウンロードしました");
  } catch (err) {
    setStatus(`失敗: ${err.message}`);
  }
}

/* Paper presets: the select holds "WxH" in mm; the writable line length is
 * the paper dimension along the writing direction (width horizontally,
 * height vertically) minus both margins. The cross direction is not
 * constrained (the page grows with the text). */
function applyPaper() {
  const v = $("paperSel").value;
  if (!v) return;
  const [w, h] = v.split("x").map(Number);
  const margin = Number($("margin").value) || 0;
  $("maxWidth").value = ($("vertChk").checked ? h : w) - 2 * margin;
}
$("paperSel").addEventListener("change", applyPaper);
$("margin").addEventListener("input", applyPaper);
$("vertChk").addEventListener("change", applyPaper);
$("maxWidth").addEventListener("input", () => { $("paperSel").value = ""; });

for (const id of Object.values(JITTER_IDS)) {
  $(id).addEventListener("input", (e) => {
    e.target.nextElementSibling.textContent = Number(e.target.value).toFixed(1);
  });
}

$("ruleChk").addEventListener("change", () => { if (lastPreview) drawPreview(lastPreview); });
$("pressWidthChk").addEventListener("change", () => { if (lastPreview) drawPreview(lastPreview); });

$("preview").addEventListener("click", preview);
$("dlGcode").addEventListener("click", () => download("gcode"));
$("dlSvg").addEventListener("click", () => download("svg"));

async function init() {
  const writers = (await (await fetch("/api/writers")).json()).writers;
  const sel = $("writerSel");
  for (const w of writers) {
    const opt = document.createElement("option");
    opt.value = w; opt.textContent = w;
    sel.appendChild(opt);
  }
  if (!writers.length) setStatus("データがありません。まず入力ページで文字を書いてください。");
}

init();
