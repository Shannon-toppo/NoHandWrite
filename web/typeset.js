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
    width_fallback: $("widthChk").checked,
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

/* Paper size, sent only when we want the machine origin pinned to the
 * sheet's bottom-left corner instead of the text block's. */
function paperSize() {
  const v = $("paperSel").value;
  if (!v || !$("anchorPaper").checked) return {};
  const [w, h] = v.split("x").map(Number);
  return { paper_w_mm: w, paper_h_mm: h };
}

function gcodeParams() {
  return {
    feed_draw: num("feedDraw", 750),
    feed_travel: num("feedTravel", 3000),
    pen_up_cmd: $("penUp").value.trim() || "M3 S40",
    pen_down_cmd: $("penDown").value.trim() || "M3 S90",
    dwell_s: num("dwell", 0.25),
    flip_y: $("flipY").checked,
    pressure_width: $("pressWidthChk").checked,
    pressure_z: $("pressZChk").checked,
    z_light: num("zLight", 0),
    z_heavy: num("zHeavy", -0.4),
    ...paperSize(),
  };
}

/* Pen lift hardware. A servo needs a dwell after each command (it is still
 * travelling when the next move starts) and has no Z axis to modulate. */
const PEN_PRESETS = {
  servo: { up: "M3 S40", down: "M3 S90", dwell: 0.25,
           hint: "サーボ式: S値は機械に合わせて調整してください。GRBL 1.1 は $32=0(レーザーモードOFF)に。0.9 系に $32 はなく、M3 S… を効かせるには VARIABLE_SPINDLE 入りのファームが要ります。筆圧のZ変調は使えません。" },
  z: { up: "G0 Z5.0", down: "G1 Z0.0 F300", dwell: 0,
       hint: "Z軸式: ペン上げの高さと紙面のZ=0を機械に合わせてください。" },
};

function applyPenMode() {
  const mode = $("penMode").value;
  const preset = PEN_PRESETS[mode];
  $("penUp").value = preset.up;
  $("penDown").value = preset.down;
  $("dwell").value = preset.dwell;
  $("penHint").textContent = preset.hint;
  const servo = mode === "servo";
  if (servo) $("pressZChk").checked = false;
  for (const id of ["pressZChk", "zLight", "zHeavy"]) $(id).disabled = servo;
}

async function errText(res) {
  const body = await res.text();
  try { return JSON.parse(body).detail ?? body; } catch { return body; }
}

/** Characters the export came out missing, as named by the response header
 *  (percent-encoded there because header values are latin-1). */
function missingChars(res) {
  return decodeURIComponent(res.headers.get("X-Missing-Chars") || "");
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
  const modes = Object.values(data.modes);
  const count = (p) => modes.filter(p).length;
  const nGen = count((m) => m.startsWith("generated"));
  const nWeak = count((m) => m === "generated_weak");
  const nBad = count((m) => m === "unavailable");
  $("pageinfo").textContent =
    `ページ: ${pw} × ${ph} mm / ストローク数: ${data.strokes.length} / ` +
    `自分の筆跡 ${modes.length - nGen - nBad} 字種・AI生成 ${nGen} 字種` +
    (nWeak ? `(うち要確認 ${nWeak} 字種 — 生成ページで確認してください)` : "") +
    (nBad ? `・書けない字 ${nBad} 字種` : "") +
    (data.cache ? ` / 新規描画 ${data.cache.miss} 字種・キャッシュ ${data.cache.hit} 字種` : "");
  showIssues(data);
}

/** Banner above the preview: which characters will come out blank, which
 *  were generated badly, and which were swapped for their other width.
 *  A missing character is otherwise invisible — the page just has a gap. */
function showIssues(data) {
  const box = $("issues");
  const issues = data.issues || [];
  const failed = issues.filter((e) => e.mode === "unavailable");
  const weak = issues.filter((e) => e.mode === "generated_weak");
  const subs = data.substitutions || [];
  if (!failed.length && !weak.length && !subs.length) { box.hidden = true; return; }
  box.replaceChildren();
  if (failed.length) {
    const why = [...new Set(failed.map((e) => e.reason))].join(" / ");
    box.append(bold(failed.map((e) => e.char).join("")),
               `は書けないので空白になります。${why}`, br(), link());
  }
  if (weak.length)
    box.append(bold(weak.map((e) => e.char).join("")),
               "は生成できましたが要確認です(打ち切り・画数不足など)。", br());
  if (subs.length)
    box.append("全角/半角を代用: "
               + subs.map((e) => `${e.char}→${e.substitute}`).join("、"));
  box.hidden = false;
}

function bold(text) {
  const b = document.createElement("b");
  b.textContent = text;
  return b;
}

function br() { return document.createElement("br"); }

/** Where to go and fix it: the generate page shows each character on its own,
 *  with a 再生成 button and a link to write it by hand. */
function link() {
  const a = document.createElement("a");
  a.href = "/generate.html";
  a.textContent = "→ 生成ページで確認・再生成する";
  return a;
}

/* `refresh` ignores the server-side render cache and draws every character
 * again; without it only the characters that changed are re-rendered. */
async function preview(refresh = false) {
  const p = params();
  if (!p.writer || !p.text) { setStatus("書き手と文章を指定してください"); return; }
  setStatus("レイアウト中…");
  $("preview").disabled = $("rebuild").disabled = true;
  const job = newJobId();
  const stop = watchRenderProgress(job, setStatus);
  try {
    const res = await fetch("/api/typeset", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...p, refresh, job }),
    });
    if (!res.ok) throw new Error(await errText(res));
    const data = await res.json();
    stop();
    drawPreview(data);
    setStatus(data.missing.length
      ? `プレビュー更新 — 書けない文字: ${data.missing.join("")}`
      : "プレビュー更新");
  } catch (err) {
    setStatus(`失敗: ${err.message}`);
  } finally {
    stop();
    $("preview").disabled = $("rebuild").disabled = false;
  }
}

async function download(format) {
  const p = params();
  if (!p.writer || !p.text) { setStatus("書き手と文章を指定してください"); return; }
  setStatus(`${format} を作成中…`);
  const job = newJobId();
  const stop = watchRenderProgress(job, setStatus);
  try {
    const res = await fetch("/api/export", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...p, ...gcodeParams(), format, job }),
    });
    if (!res.ok) throw new Error(await errText(res));
    stop();
    const missing = missingChars(res);
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = format === "svg" ? "nohandwrite.svg" : "nohandwrite.gcode";
    a.click();
    URL.revokeObjectURL(a.href);
    setStatus(missing
      ? `ダウンロードしました — ただし ${missing} は書けないので空白になっています`
      : "ダウンロードしました");
  } catch (err) {
    setStatus(`失敗: ${err.message}`);
  } finally {
    stop();
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

$("penMode").addEventListener("change", applyPenMode);

$("preview").addEventListener("click", () => preview(false));
$("rebuild").addEventListener("click", () => preview(true));
$("dlGcode").addEventListener("click", () => download("gcode"));
$("dlSvg").addEventListener("click", () => download("svg"));

/* --- experimental: drive the plotter over USB ------------------------ */

let pollTimer = null;

async function refreshPorts() {
  const sel = $("portSel");
  const keep = sel.value;
  sel.replaceChildren();
  try {
    const { ports } = await (await fetch("/api/plot/ports")).json();
    if (!ports.length) {
      sel.appendChild(new Option("(見つかりません)", ""));
      return;
    }
    for (const p of ports) {
      sel.appendChild(new Option(`${p.device} — ${p.description}`, p.device));
    }
    if (keep) sel.value = keep;
  } catch {
    sel.appendChild(new Option("(取得に失敗しました)", ""));
  }
}

const PLOT_LABEL = { idle: "待機中", running: "描画中", done: "完了",
                     stopped: "停止", error: "エラー" };

function showPlot(s) {
  const pct = s.total ? Math.round((100 * s.sent) / s.total) : 0;
  const progress = s.total ? ` ${s.sent}/${s.total} 行 (${pct}%) ${s.elapsed_s}秒` : "";
  const pos = s.start_report ? ` / 開始時の機械位置 ${s.start_report}` : "";
  $("plotStatus").textContent =
    `${PLOT_LABEL[s.state] ?? s.state}${progress} ${s.message}${pos}`.trim();
  const running = s.state === "running";
  $("plotSend").disabled = running;
  $("plotStop").disabled = !running;
  return running;
}

async function pollPlot() {
  clearTimeout(pollTimer);
  try {
    const s = await (await fetch("/api/plot/status")).json();
    if (showPlot(s)) pollTimer = setTimeout(pollPlot, 700);
  } catch {
    pollTimer = setTimeout(pollPlot, 1500);
  }
}

async function plotSend() {
  const p = params();
  const port = $("portSel").value;
  if (!p.writer || !p.text) { setStatus("書き手と文章を指定してください"); return; }
  if (!port) { setStatus("送信先のポートを選んでください"); return; }
  if (!confirm(`${port} に送信してプロッターを動かします。\n`
               + "ペンが原点(紙の左下)にあり、周囲に障害物がないか確認してください。")) return;
  $("plotSend").disabled = true;
  $("plotStatus").textContent = "接続しています…";
  const job = newJobId();
  const stop = watchRenderProgress(job, (m) => { $("plotStatus").textContent = m; });
  try {
    const res = await fetch("/api/plot", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...p, ...gcodeParams(), port, job,
                             baud: num("baud", 115200),
                             unlock: $("unlockChk").checked,
                             set_origin: $("originChk").checked,
                             travel_x_mm: num("travelX", 0),
                             travel_y_mm: num("travelY", 0) }),
    });
    if (!res.ok) throw new Error(await errText(res));
    stop();
    const started = await res.json();
    showPlot(started);
    if (started.missing?.length)
      setStatus(`送信しました — ${started.missing.join("")} は書けないので空白になります`);
    pollPlot();
  } catch (err) {
    $("plotSend").disabled = false;
    $("plotStatus").textContent = `失敗: ${err.message}`;
  } finally {
    stop();
  }
}

async function plotStop() {
  $("plotStop").disabled = true;
  $("plotStatus").textContent = "停止しています…";
  try {
    const res = await fetch("/api/plot/stop", { method: "POST" });
    showPlot(await res.json());
  } catch (err) {
    $("plotStatus").textContent = `停止に失敗しました: ${err.message}`;
  }
}

rememberTextarea($("text"), "nhw-text-typeset");

$("portRefresh").addEventListener("click", refreshPorts);
$("plotSend").addEventListener("click", plotSend);
$("plotStop").addEventListener("click", plotStop);

async function init() {
  applyPenMode();
  const writers = (await (await fetch("/api/writers")).json()).writers;
  const sel = $("writerSel");
  for (const w of writers) {
    const opt = document.createElement("option");
    opt.value = w; opt.textContent = w;
    sel.appendChild(opt);
  }
  rememberWriter(sel);
  if (!writers.length) setStatus("データがありません。まず入力ページで文字を書いてください。");
  await refreshPorts();
  pollPlot();                     // reflect a job already running on the server
}

init();
