"use strict";
/* Remembered UI state, so moving between pages does not throw away what you
 * typed — including the round trip through 「✏️ 自分で書く」 and back.
 *
 * The capture page has kept the writer id under "nhw-writer" since the
 * beginning; the generate and typeset pages read and write that same key, so
 * the whole app agrees on who you are writing as. The two texts are kept
 * apart: the typeset page usually holds a whole document, and going to the
 * generate page to check one character must not overwrite it.
 *
 * localStorage throws in Safari's private mode instead of returning null, so
 * every access is guarded — losing the memory is not worth losing the page.
 */

const REMEMBER_WRITER = "nhw-writer";

function remembered(key, fallback = "") {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}

function remember(key, value) {
  try { localStorage.setItem(key, value); } catch { /* private mode: skip */ }
}

/** Keep a textarea's content across navigation and reloads. */
function rememberTextarea(el, key) {
  const saved = remembered(key);
  if (saved && !el.value) el.value = saved;
  let timer = null;
  el.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => remember(key, el.value), 300);
  });
  // leaving the page inside that window would otherwise lose the last words
  addEventListener("pagehide", () => remember(key, el.value));
}

/** Restore the writer picked on another page, and remember changes here.
 *  Call once the <select> has been filled — a remembered writer whose data
 *  has since been deleted is ignored. */
function rememberWriter(sel) {
  const saved = remembered(REMEMBER_WRITER);
  if (saved && [...sel.options].some((o) => o.value === saved)) sel.value = saved;
  sel.addEventListener("change", () => remember(REMEMBER_WRITER, sel.value));
}
