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

/** Characters the export came out missing, as named by the response header
 *  (percent-encoded there because header values are latin-1). */
function missingChars(res) {
  return decodeURIComponent(res.headers.get("X-Missing-Chars") || "");
}

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
  if (e.substitute) {
    const sub = document.createElement("span");
    sub.className = "sub";
    sub.textContent = `${e.char} → ${e.substitute} で代用`;
    cell.appendChild(sub);
  }
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

/* `refresh` skips the server-side cache: SDT resamples its style references
 * every time, so it really is a fresh attempt at the character.
 * The job id is what the progress poll below follows. */
async function requestChars(text, refresh = false) {
  const job = newJobId();
  const stop = watchRenderProgress(job, setStatus);
  try {
    const res = await fetch("/api/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ writer: $("writerSel").value, text,
                             smooth: $("smoothChk").checked, jitter: jitterParams(),
                             width_fallback: $("widthChk").checked, refresh, job }),
    });
    if (!res.ok) throw new Error(await res.text());
    return await res.json();
  } finally {
    stop();
  }
}

async function regenerate(char, cell, button) {
  button.disabled = true;
  setStatus(`「${char}」を再生成中…`);
  try {
    const [e] = (await requestChars(char, true)).chars;
    cell.replaceWith(makeCell(e, regenerate));
    setStatus(`「${char}」を再生成しました`);
  } catch (err) {
    button.disabled = false;
    setStatus(`再生成に失敗: ${err.message}`);
  }
}

/** Banner above the tiles: which characters did not come out, and why.
 *  The tiles say the same per character, but a long text scrolls them out
 *  of sight — this is what stops a silent gap reaching the paper. */
function showIssues(chars) {
  const box = $("issues");
  const failed = chars.filter((e) => e.mode === "unavailable");
  const weak = chars.filter((e) => e.mode === "generated_weak");
  const subs = chars.filter((e) => e.substitute);
  if (!failed.length && !weak.length && !subs.length) { box.hidden = true; return; }
  box.replaceChildren();
  if (failed.length) {
    const why = [...new Set(failed.map((e) => e.reason))].join(" / ");
    box.append(chars_(failed), `は生成できませんでした(空白のまま出力されます)。${why}`,
               document.createElement("br"));
  }
  if (weak.length)
    box.append(chars_(weak), "は生成できましたが要確認です"
               + "(打ち切り・画数不足・一致度が低いなど)。橙枠の字を確認してください。",
               document.createElement("br"));
  if (subs.length)
    box.append(`全角/半角を代用: `
               + subs.map((e) => `${e.char}→${e.substitute}`).join("、"));
  box.hidden = false;
}

/** The characters of `entries`, emphasized. */
function chars_(entries) {
  const b = document.createElement("b");
  b.textContent = entries.map((e) => e.char).join("");
  return b;
}

async function run(refresh) {
  const writer = $("writerSel").value;
  const text = $("text").value.trim();
  if (!writer || !text) { setStatus("書き手とテキストを指定してください"); return; }
  setStatus("生成中…");
  $("run").disabled = $("rerun").disabled = true;
  try {
    const { chars, cache } = await requestChars(text, refresh);
    const out = $("out");
    out.innerHTML = "";
    for (const e of chars) out.appendChild(makeCell(e, regenerate));
    showIssues(chars);
    const bad = chars.filter((e) => e.reason);
    setStatus((bad.length
      ? `完了(要確認 ${bad.length} 字: ${bad.map((e) => e.char).join("")})`
      : "完了")
      + ` — ${cache.miss} 字種を新規描画、${cache.hit} 字種はキャッシュ`);
  } catch (err) {
    setStatus(`失敗: ${err.message}`);
  } finally {
    $("run").disabled = $("rerun").disabled = false;
  }
}

$("run").addEventListener("click", () => run(false));
$("rerun").addEventListener("click", () => run(true));

async function download(format) {
  const writer = $("writerSel").value;
  const text = $("text").value.trim();
  if (!writer || !text) { setStatus("書き手とテキストを指定してください"); return; }
  setStatus(`${format} を作成中…`);
  const job = newJobId();
  const stop = watchRenderProgress(job, setStatus);
  let res;
  try {
    res = await fetch("/api/export", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ writer, text, smooth: $("smoothChk").checked,
                             jitter: jitterParams(),
                             width_fallback: $("widthChk").checked, job,
                             format, char_size_mm: Number($("sizeMm").value) || 15 }),
    });
  } finally {
    stop();
  }
  if (!res.ok) { setStatus(`失敗: ${await res.text()}`); return; }
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
}

$("dlSvg").addEventListener("click", () => download("svg"));
$("dlGcode").addEventListener("click", () => download("gcode"));

rememberTextarea($("text"), "nhw-text-generate");

async function init() {
  const writers = (await (await fetch("/api/writers")).json()).writers;
  const sel = $("writerSel");
  for (const w of writers) {
    const opt = document.createElement("option");
    opt.value = w; opt.textContent = w;
    sel.appendChild(opt);
  }
  rememberWriter(sel);
  const st = await (await fetch("/api/generate/status")).json();
  if (!st.available)
    setStatus("注意: SDTモデル/データが見つからないため、未入力文字のAI生成は使えません。");
}

init();
