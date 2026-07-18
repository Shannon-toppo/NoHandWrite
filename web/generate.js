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

const MODE_LABEL = { average: "平均文字", smooth: "平滑化", generated: "AI生成", unavailable: "不可" };
const MODE_COLOR = { average: "#111", smooth: "#111", generated: "#111", unavailable: "#c92525" };

$("run").addEventListener("click", async () => {
  const writer = $("writerSel").value;
  const text = $("text").value.trim();
  if (!writer || !text) { setStatus("書き手とテキストを指定してください"); return; }
  setStatus("生成中…(初回はモデル読み込みに数十秒かかることがあります)");
  $("run").disabled = true;
  try {
    const res = await fetch("/api/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ writer, text, smooth: $("smoothChk").checked,
                             jitter: jitterParams() }),
    });
    if (!res.ok) throw new Error((await res.text()));
    const data = await res.json();
    const out = $("out");
    out.innerHTML = "";
    for (const e of data.chars) {
      const cell = document.createElement("div");
      cell.className = `cell ${e.mode}`;
      const cv = document.createElement("canvas");
      cell.appendChild(cv);
      const label = document.createElement("span");
      label.textContent = `${e.char} · ${MODE_LABEL[e.mode] ?? e.mode}`;
      cell.appendChild(label);
      out.appendChild(cell);
      if (e.strokes) drawChar(cv, e.strokes, MODE_COLOR[e.mode]);
      else cell.title = e.reason || "";
    }
    setStatus("完了");
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
