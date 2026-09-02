"""Full-width ⇄ half-width character pairs.

Japanese text mixes the two widths freely — （） and ()、；： and ;: are the
same punctuation written in a different box — but a handwriting sample set
(and SDT's content dictionary) usually covers only one of each pair. This
module gives the counterpart of a character so callers can fall back to the
form they actually have, and `both_widths` so tables of punctuation
(kinsoku sets, vertical glyph forms) cover both without listing each twice.

Covered: the ASCII ↔ FULLWIDTH FORMS block (U+0021–007E ↔ U+FF01–FF5E) and
the halfwidth CJK punctuation that has no fullwidth counterpart there
(｡｢｣､･ｰ). Kana and letters with diacritics are deliberately out of scope —
a halfwidth ｶﾞ is two codepoints, not one.
"""
from __future__ import annotations

from typing import Iterable

#: half-width -> full-width, for the printable ASCII range
_ASCII_TO_FULL = {chr(o): chr(o - 0x21 + 0xFF01) for o in range(0x21, 0x7F)}

#: half-width CJK punctuation -> its ordinary (full-width) form
_HALF_CJK_TO_FULL = {
    "｡": "。", "｢": "「", "｣": "」", "､": "、", "･": "・", "ｰ": "ー",
}

_PAIRS: dict[str, str] = {}
for _a, _b in {**_ASCII_TO_FULL, **_HALF_CJK_TO_FULL}.items():
    _PAIRS[_a] = _b
    _PAIRS[_b] = _a
del _a, _b


def width_variant(char: str) -> str | None:
    """The other-width form of `char`, or None if it has no counterpart.

    >>> width_variant("(") == "（" and width_variant("；") == ";"
    True
    """
    return _PAIRS.get(char)


def both_widths(chars: Iterable[str]) -> set[str]:
    """`chars` plus every counterpart form, as a set."""
    out = set(chars)
    out.update(v for c in out.copy() if (v := width_variant(c)))
    return out
