"use strict";
/* Library view: overlay of raw samples (thin, colored) and the Fourier
 * average character (thick red), like Fig. 5 of the EC2014 paper. */

const $ = (id) => document.getElementById(id);
const canvas = $("view");
const ctx = canvas.getContext("2d");
const COLORS = ["#4a7", "#47a", "#a47", "#7a4", "#a74", "#77c"];
let currentChar = null;
let rewriteTarget = null;  // char the "rewrite" button opens; survives a reset

function setStatus(m) { $("status").textContent = m; }

function fitCanvas() {
  const r = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(r.width * dpr);
  canvas.height = Math.round(r.height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { w: r.width, h: r.height };
}

/* Map sample strokes from their capture field into the 0–1000 box, keeping
 * written size/position (same field-relative rule as the server), so small
 * kana and punctuation overlay correctly with the averaged result. */
function normalizeField(strokes, canvas) {
  const [cw, ch] = canvas && canvas.length === 2 ? canvas : [1000, 1000];
  const scale = 1000 / Math.max(cw, ch, 1e-9);
  const offX = (1000 - cw * scale) / 2;
  const offY = (1000 - ch * scale) / 2;
  return strokes.map(s => s.map(p => [p.x * scale + offX, p.y * scale + offY]));
}

function drawPolyline(pts, color, width, w, h) {
  const sx = w / 1100, sy = h / 1100, off = 50;
  ctx.strokeStyle = color; ctx.lineWidth = width;
  ctx.lineCap = "round"; ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.moveTo((pts[0][0] + off) * sx, (pts[0][1] + off) * sy);
  for (let i = 1; i < pts.length; i++)
    ctx.lineTo((pts[i][0] + off) * sx, (pts[i][1] + off) * sy);
  ctx.stroke();
}

async function showChar(writer, char) {
  currentChar = char;
  rewriteTarget = char;
  for (const b of document.querySelectorAll(".chargrid button"))
    b.classList.toggle("active", b.dataset.char === char);
  const { w, h } = fitCanvas();
  ctx.clearRect(0, 0, w, h);

  const raw = await (await fetch(`/api/writers/${encodeURIComponent(writer)}/chars/${encodeURIComponent(char)}`)).json();
  raw.samples.forEach((s, i) => {
    for (const pts of normalizeField(s.strokes, s.canvas))
      drawPolyline(pts, COLORS[i % COLORS.length], 1.2, w, h);
  });

  const res = await fetch(`/api/writers/${encodeURIComponent(writer)}/chars/${encodeURIComponent(char)}/beautify`);
  if (!res.ok) { setStatus(`平均文字の計算に失敗: ${await res.text()}`); return; }
  const avg = await res.json();
  for (const pts of avg.strokes) drawPolyline(pts, "#d22", 4, w, h);
  setStatus(`「${char}」 サンプル ${avg.usedSamples}/${avg.totalSamples} 使用 ` +
            `(${avg.strokeCount} 画, ${avg.mode === "average" ? "平均" : "単一サンプル平滑化"})`);
}

async function loadWriter(writer) {
  const grid = $("charGrid");
  grid.innerHTML = "";
  rewriteTarget = null;
  if (!writer) return;
  const sum = await (await fetch(`/api/writers/${encodeURIComponent(writer)}/summary`)).json();
  const chars = Object.keys(sum.chars).sort();
  for (const c of chars) {
    const b = document.createElement("button");
    b.dataset.char = c;
    b.innerHTML = `${c}<span class="cnt">×${sum.chars[c]}</span>`;
    b.addEventListener("click", () => showChar(writer, c));
    grid.appendChild(b);
  }
  if (chars.length) showChar(writer, chars[0]);
  else setStatus("この書き手のデータはまだありません");
}

async function resetChar() {
  const writer = $("writerSel").value;
  if (!writer || !currentChar) { setStatus("文字を選択してください"); return; }
  if (!confirm(`「${currentChar}」のサンプルをすべて削除します。よろしいですか?`)) return;
  const res = await fetch(
    `/api/writers/${encodeURIComponent(writer)}/chars/${encodeURIComponent(currentChar)}`,
    { method: "DELETE" });
  if (!res.ok) { setStatus(`削除に失敗: ${await res.text()}`); return; }
  const deleted = currentChar;
  currentChar = null;
  await loadWriter(writer);
  rewriteTarget = deleted;
  setStatus(`「${deleted}」を削除しました。「この文字だけ書き直す」で再入力できます`);
}

function rewriteChar() {
  const writer = $("writerSel").value;
  if (!rewriteTarget) { setStatus("文字を選択してください"); return; }
  location.href = `/?char=${encodeURIComponent(rewriteTarget)}` +
                  (writer ? `&writer=${encodeURIComponent(writer)}` : "");
}

async function init() {
  // Wait for stylesheets so the canvas has its laid-out size before drawing.
  if (document.readyState !== "complete")
    await new Promise((r) => window.addEventListener("load", r, { once: true }));
  window.addEventListener("resize", () => {
    const w = $("writerSel").value;
    if (w && currentChar) showChar(w, currentChar);
  });
  const writers = (await (await fetch("/api/writers")).json()).writers;
  const sel = $("writerSel");
  for (const wname of writers) {
    const opt = document.createElement("option");
    opt.value = wname; opt.textContent = wname;
    sel.appendChild(opt);
  }
  sel.addEventListener("change", () => loadWriter(sel.value));
  if (writers.length) loadWriter(writers[0]);
  else setStatus("データがありません。まず入力ページで文字を書いてください。");
}

$("resetChar").addEventListener("click", resetChar);
$("rewriteChar").addEventListener("click", rewriteChar);
init();
