"use strict";
/* Handwriting capture pad.
 * Records pointer strokes as (x, y, t, p) in canvas CSS-pixel coordinates.
 * While the pen is down the trace is gray; on pen-up it is redrawn black
 * (same behavior as the EC2014 capture system). A stroke that starts
 * outside the field is ignored; leaving the field cancels the stroke. */

const $ = (id) => document.getElementById(id);
const canvas = $("pad");
const ctx = canvas.getContext("2d");

let promptSets = {};
let currentSet = null;   // key into promptSets
let queue = [];          // remaining chars in current set
let queueTotal = 0;      // initial queue length (chars × repeat)
let currentChar = null;
let strokes = [];        // finished strokes: arrays of {x,y,t,p}
let live = null;         // stroke being drawn
let t0 = null;           // time origin (first pen-down of this sample)
let summary = {};        // char -> sample count for current writer

function cssSize() {
  const r = canvas.getBoundingClientRect();
  return { w: r.width, h: r.height };
}

function resizeCanvas() {
  const { w, h } = cssSize();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  redraw();
}

function drawGuide() {
  const { w, h } = cssSize();
  ctx.save();
  ctx.strokeStyle = "#ddd";
  ctx.setLineDash([6, 6]);
  ctx.beginPath();
  ctx.moveTo(w / 2, 0); ctx.lineTo(w / 2, h);
  ctx.moveTo(0, h / 2); ctx.lineTo(w, h / 2);
  ctx.stroke();
  ctx.restore();
}

function drawStroke(pts, color, width) {
  if (!pts.length) return;
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].x, pts[i].y);
  if (pts.length === 1) ctx.lineTo(pts[0].x + 0.1, pts[0].y);
  ctx.stroke();
}

function redraw() {
  const { w, h } = cssSize();
  ctx.clearRect(0, 0, w, h);
  drawGuide();
  for (const s of strokes) drawStroke(s, "#111", 3);
  if (live) drawStroke(live, "#999", 3);
  $("strokeInfo").textContent = `${strokes.length + (live ? 1 : 0)} 画目`;
}

function pointFromEvent(e) {
  const r = canvas.getBoundingClientRect();
  return {
    x: e.clientX - r.left,
    y: e.clientY - r.top,
    t: t0 === null ? 0 : performance.now() - t0,
    p: e.pressure || 0,
  };
}

function inField(pt) {
  const { w, h } = cssSize();
  return pt.x >= 0 && pt.y >= 0 && pt.x <= w && pt.y <= h;
}

canvas.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  if (t0 === null) t0 = performance.now();
  const pt = pointFromEvent(e);
  if (!inField(pt)) return;
  live = [pt];
  canvas.setPointerCapture(e.pointerId);
  redraw();
});

canvas.addEventListener("pointermove", (e) => {
  if (!live) return;
  e.preventDefault();
  const events = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
  for (const ev of events) {
    const pt = pointFromEvent(ev);
    if (!inField(pt)) { live = null; redraw(); setStatus("枠の外に出たため一画を取り消しました"); return; }
    live.push(pt);
  }
  redraw();
});

canvas.addEventListener("pointerup", (e) => {
  if (!live) return;
  e.preventDefault();
  strokes.push(live);
  live = null;
  redraw();
});

canvas.addEventListener("pointercancel", () => { live = null; redraw(); });

function setStatus(msg) { $("status").textContent = msg; }

function updatePromptView() {
  const set = promptSets[currentSet];
  const target = $("targetChar");
  target.textContent = currentChar ?? "✓";
  const isLatin = !!currentChar && /[A-Za-z0-9]/.test(currentChar);
  target.classList.toggle("latin", isLatin);
  target.classList.toggle("kso", !!currentChar && !isLatin);
  $("setDescription").textContent = set ? set.description : "";
  const done = queueTotal - queue.length - (currentChar ? 1 : 0);
  $("progress").textContent = set ? `${done} / ${queueTotal}` : "";
  const n = currentChar ? (summary[currentChar] || 0) : 0;
  $("sampleInfo").textContent = currentChar ? `この文字の保存済み: ${n} 回` : "このセットは完了です";
}

function nextChar() {
  strokes = []; live = null; t0 = null;
  currentChar = queue.length ? queue.shift() : null;
  redraw();
  updatePromptView();
}

async function loadSummary() {
  const writer = $("writer").value.trim();
  summary = {};
  if (!writer) return;
  try {
    const res = await fetch(`/api/writers/${encodeURIComponent(writer)}/summary`);
    if (res.ok) summary = (await res.json()).chars;
  } catch { /* offline is fine */ }
  updatePromptView();
}

function repeatSettings() {
  const n = Math.max(1, Math.min(10, Number($("repeat").value) || 1));
  return { n, order: $("repeatOrder").value };
}

function startSet(key) {
  currentSet = key;
  const chars = [...promptSets[key].chars];
  const { n, order } = repeatSettings();
  if (order === "consecutive") {
    queue = chars.flatMap((c) => Array(n).fill(c));   // ああ…いい…
  } else {
    queue = Array(n).fill(chars).flat();               // あい…ん あい…ん
  }
  queueTotal = queue.length;
  nextChar();
}

$("promptSet").addEventListener("change", (e) => startSet(e.target.value));
for (const id of ["repeat", "repeatOrder"]) {
  $(id).addEventListener("change", () => {
    localStorage.setItem("nhw-repeat", $("repeat").value);
    localStorage.setItem("nhw-order", $("repeatOrder").value);
    if (currentSet) { startSet(currentSet); setStatus("回数設定を変更したためセットを最初からやり直します"); }
  });
}

/* --- input pad size --- */
function setPadSize(px, keepStrokes = true) {
  px = Math.max(250, Math.min(850, px));
  const wrap = canvas.parentElement;
  const before = cssSize().w;
  wrap.style.width = `min(${px}px, 100%)`;
  document.querySelector("main").style.width = `min(${Math.max(560, px)}px, 100%)`;
  $("padSizeVal").textContent = `${px}px`;
  const after = canvas.getBoundingClientRect().width;
  if (keepStrokes && before > 0 && after > 0 && before !== after) {
    const r = after / before;                      // rescale in-progress strokes
    for (const s of strokes) for (const p of s) { p.x *= r; p.y *= r; }
    if (live) for (const p of live) { p.x *= r; p.y *= r; }
  }
  resizeCanvas();
}

$("padSize").addEventListener("input", () => {
  localStorage.setItem("nhw-padsize", $("padSize").value);
  setPadSize(Number($("padSize").value));
});
$("writer").addEventListener("change", () => {
  localStorage.setItem("nhw-writer", $("writer").value.trim());
  loadSummary();
});

$("undoStroke").addEventListener("click", () => { strokes.pop(); redraw(); });
$("clearAll").addEventListener("click", () => { strokes = []; live = null; t0 = null; redraw(); });
$("skip").addEventListener("click", () => { nextChar(); setStatus("スキップしました"); });

$("save").addEventListener("click", async () => {
  const writer = $("writer").value.trim();
  if (!writer) { setStatus("書き手IDを入力してください"); return; }
  if (!currentChar) { setStatus("お題がありません(セットを選び直してください)"); return; }
  if (!strokes.length) { setStatus("何も書かれていません"); return; }
  const { w, h } = cssSize();
  const body = {
    writer, char: currentChar,
    device: navigator.maxTouchPoints > 1 ? "touch-pen" : "mouse",
    canvas: [w, h],
    strokes,
  };
  try {
    const res = await fetch("/api/samples", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    const out = await res.json();
    summary[out.char] = out.count;
    setStatus(`「${out.char}」を保存しました(${out.count} 回目)`);
    nextChar();
  } catch (err) {
    setStatus(`保存に失敗: ${err.message}`);
  }
});

async function init() {
  const saved = localStorage.getItem("nhw-writer");
  if (saved) $("writer").value = saved;
  $("repeat").value = localStorage.getItem("nhw-repeat") || "1";
  $("repeatOrder").value = localStorage.getItem("nhw-order") || "loop";
  setPadSize(Number(localStorage.getItem("nhw-padsize")) || 560, false);
  $("padSize").value = String(Math.max(250, Math.min(850, Number(localStorage.getItem("nhw-padsize")) || 560)));
  const res = await fetch("/api/prompts");
  promptSets = await res.json();
  const sel = $("promptSet");
  for (const [key, v] of Object.entries(promptSets)) {
    const opt = document.createElement("option");
    opt.value = key; opt.textContent = v.label;
    sel.appendChild(opt);
  }
  window.addEventListener("resize", resizeCanvas);
  resizeCanvas();
  await loadSummary();
  startSet(Object.keys(promptSets)[0]);
}

init();
