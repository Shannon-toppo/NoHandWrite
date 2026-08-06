"use strict";
/* Generate page: type text, render it in the writer's handwriting style. */

const $ = (id) => document.getElementById(id);

function drawChar(canvas, strokes, color) {
  const dpr = window.devicePixelRatio || 1;
  const px = 110;
  canvas.width = px * dpr; canvas.height = px * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, px, px);
  const s = px / 1100, off = 50;
  ctx.strokeStyle = color; ctx.lineWidth = 3;
  ctx.lineCap = "round"; ctx.lineJoin = "round";
  for (const stroke of strokes) {
    ctx.beginPath();
    ctx.moveTo((stroke[0][0] + off) * s, (stroke[0][1] + off) * s);
    for (let i = 1; i < stroke.length; i++)
      ctx.lineTo((stroke[i][0] + off) * s, (stroke[i][1] + off) * s);
    ctx.stroke();
  }
}

function setStatus(m) { $("status").textContent = m; }

const JITTER_IDS = { hiragana: "jHiragana", katakana: "jKatakana", kanji: "jKanji",
                     alnum: "jAlnum", other: "jOther" };

function jitterParams() {
  const j = {};
  for (const [key, id] of Object.entries(JITTER_IDS)) j[key] = Number($(id).value);
  return j;
}

for (const id of Object.values(JITTER_IDS)) {
  $(id).addEventListener("input", (e) => {
    e.target.nextElementSibling.textContent = Number(e.target.value).toFixed(1);
  });
}

const MODE_LABEL = { average: "平均文字", smooth: "平滑化", generated: "AI生成",
                     generated_weak: "AI生成 ⚠", unavailable: "不可" };
const MODE_COLOR = { average: "#111", smooth: "#111", generated: "#111",
                     generated_weak: "#111", unavailable: "#c92525" };

/** Characters the writer never wrote: SDT produced them (or failed to), so
 *  offer a way out — sample again, or go and write the character by hand. */
const NEEDS_ESCAPE = new Set(["generated", "generated_weak", "unavailable"]);
/** Reasons no amount of resampling can fix — only "write it yourself" helps. */
const HOPELESS = new Set(["unsupported", "model_missing"]);

function qualityTitle(e) {
  const q = e.quality;
  const parts = [];
  if (e.reason) parts.push(e.reason);
  if (q) {
    parts.push(`一致度 ${q.score}`);
    parts.push(`ストローク ${q.n_strokes}${q.expected_strokes ? ` / 目安 ${q.expected_strokes}` : ""}`);
    if (!q.completed) parts.push("終端フラグなし(打ち切り)");
  }
  return parts.join(" · ");
}

/** One result tile. `regen` re-requests just this character. */
function makeCell(e, regen) {
  const cell = document.createElement("div");
  cell.className = `cell ${e.mode}`;
  const cv = document.createElement("canvas");
  cell.appendChild(cv);
  const label = document.createElement("span");
  label.textContent = `${e.char} · ${MODE_LABEL[e.mode] ?? e.mode}`;
  cell.appendChild(label);
  if (e.strokes) drawChar(cv, e.strokes, MODE_COLOR[e.mode]);
  cell.title = qualityTitle(e);
  if (e.reason) {
    const warn = document.createElement("span");
    warn.className = "warn";
    warn.textContent = e.reason;
    cell.appendChild(warn);
  }
  if (NEEDS_ESCAPE.has(e.mode)) {
    const actions = document.createElement("span");
    actions.className = "actions";
    if (!HOPELESS.has(e.reason_code)) {
      const again = document.createElement("button");
      again.textContent = "↻ 再生成";
      again.addEventListener("click", () => regen(e.char, cell, again));
      actions.appendChild(again);
    }
    const write = document.createElement("a");
    write.textContent = "✏️ 自分で書く";
    write.href = `/?char=${encodeURIComponent(e.char)}&writer=${encodeURIComponent($("writerSel").value)}`;
    actions.appendChild(write);
    cell.appendChild(actions);
  }
  return cell;
}

async function requestChars(text) {
  const res = await fetch("/api/generate", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ writer: $("writerSel").value, text,
                           smooth: $("smoothChk").checked, jitter: jitterParams() }),
  });
  if (!res.ok) throw new Error(await res.text());
  return (await res.json()).chars;
}

async function regenerate(char, cell, button) {
  button.disabled = true;
  setStatus(`「${char}」を再生成中…`);
  try {
    const [e] = await requestChars(char);
    cell.replaceWith(makeCell(e, regenerate));
    setStatus(`「${char}」を再生成しました`);
  } catch (err) {
    button.disabled = false;
    setStatus(`再生成に失敗: ${err.message}`);
  }
}

$("run").addEventListener("click", async () => {
  const writer = $("writerSel").value;
  const text = $("text").value.trim();
  if (!writer || !text) { setStatus("書き手とテキストを指定してください"); return; }
  setStatus("生成中…(初回はモデル読み込みに数十秒かかることがあります)");
  $("run").disabled = true;
  try {
    const chars = await requestChars(text);
    const out = $("out");
    out.innerHTML = "";
    for (const e of chars) out.appendChild(makeCell(e, regenerate));
    const weak = chars.filter((e) => e.mode !== "generated" && e.reason);
    setStatus(weak.length
      ? `完了(要確認 ${weak.length} 字: ${weak.map((e) => e.char).join("")})`
      : "完了");
  } catch (err) {
    setStatus(`失敗: ${err.message}`);
  } finally {
    $("run").disabled = false;
  }
});

async function download(format) {
  const writer = $("writerSel").value;
  const text = $("text").value.trim();
  if (!writer || !text) { setStatus("書き手とテキストを指定してください"); return; }
  setStatus(`${format} を作成中…`);
  const res = await fetch("/api/export", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ writer, text, smooth: $("smoothChk").checked,
                           jitter: jitterParams(),
                           format, char_size_mm: Number($("sizeMm").value) || 15 }),
  });
  if (!res.ok) { setStatus(`失敗: ${await res.text()}`); return; }
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = format === "svg" ? "nohandwrite.svg" : "nohandwrite.gcode";
  a.click();
  URL.revokeObjectURL(a.href);
  setStatus("ダウンロードしました");
}

$("dlSvg").addEventListener("click", () => download("svg"));
$("dlGcode").addEventListener("click", () => download("gcode"));

async function init() {
  const writers = (await (await fetch("/api/writers")).json()).writers;
  const sel = $("writerSel");
  for (const w of writers) {
    const opt = document.createElement("option");
    opt.value = w; opt.textContent = w;
    sel.appendChild(opt);
  }
  const st = await (await fetch("/api/generate/status")).json();
  if (!st.available)
    setStatus("注意: SDTモデル/データが見つからないため、未入力文字のAI生成は使えません。");
}

init();
