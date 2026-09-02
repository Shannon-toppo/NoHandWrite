"use strict";
/* Progress line for the long requests (typeset / generate / export).
 *
 * Those POSTs block for as long as SDT needs — tens of seconds for the first
 * one, which loads the checkpoint — and a status line that says nothing for
 * that long reads as a hang. Each request carries a job id, the server
 * records what it is doing under it, and this polls that while the request
 * is in flight.
 *
 * Loaded before the page scripts, so everything here is prefixed to stay out
 * of their way (classic scripts share one global scope). */

const RENDER_STAGE_LABEL = {
  starting: "準備中",
  samples: "手書きサンプルを読み込み中",
  style: "スタイル参照を準備中",
  model: "SDTモデルを読み込み中(初回のみ・数十秒かかります)",
  generate: "未入力の文字をAI生成中",
  retry: "生成をやり直し中(うまくいかなかった字)",
  layout: "組版中",
  export: "出力データを作成中",
  done: "仕上げ中",
};

/** crypto.randomUUID is only available over https/localhost, and this app is
 *  usually opened from an iPad over plain http on the LAN. */
function newJobId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function renderProgressText(p) {
  const label = RENDER_STAGE_LABEL[p.stage] ?? p.stage;
  const count = p.total ? ` ${Math.min(p.done, p.total)}/${p.total} 字` : "";
  return `${label}${count}… ${Math.round(p.elapsed_s)}秒`;
}

/** Poll `job` and hand each update to `show`. Returns the function that
 *  stops it — call that when the request it belongs to settles. */
function watchRenderProgress(job, show, intervalMs = 400) {
  let stopped = false;
  (async () => {
    while (!stopped) {
      await new Promise((r) => setTimeout(r, intervalMs));
      if (stopped) return;
      try {
        const p = await (await fetch(`/api/render/progress/${job}`)).json();
        // an unknown job means the POST has not reached the server yet
        if (!stopped && p.stage) show(renderProgressText(p));
      } catch { /* a dropped poll is not worth reporting */ }
    }
  })();
  return () => { stopped = true; };
}
