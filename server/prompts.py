"""Prompt character sets shown in the capture UI."""

HIRAGANA_46 = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"
HIRAGANA_DAKUTEN = "がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ"
KATAKANA_46 = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン"
KATAKANA_DAKUTEN = "ガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポ"

# Style-reference set for SDT: 25 kanji chosen to expose writing style —
# 永 covers the "eight principles"; 水火木金土日月 are frequent components;
# 山川口田 give folds/enclosures; 人心手女力 give hooks and sweeps;
# 乙之 are curve-heavy; 雨車馬 are dense; 東語海 add left–right composites
# with common radicals (言, 氵).
STYLE_REFERENCE = "永水火木金土日月山川口田人心手女力乙之雨車馬東語海"

SYMBOLS = "、。,.「」『』()!?・ー〜…"

ALPHANUMERIC = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "abcdefghijklmnopqrstuvwxyz"
                "0123456789")

PROMPT_SETS: dict[str, dict] = {
    "style_alnum": {
        "label": "スタイル学習+英数字(87字)",
        "chars": STYLE_REFERENCE + ALPHANUMERIC,
        "description": "推奨の基本セット。漢字25字(字体学習・AI生成用)+英数字62字を通しで入力する。",
    },
    "style": {
        "label": "スタイル学習用(漢字25字)",
        "chars": STYLE_REFERENCE,
        "description": "字体学習(生成)に使う推奨セット。まずはこれを1回ずつ。",
    },
    "hiragana": {
        "label": "ひらがな(71字)",
        "chars": HIRAGANA_46 + HIRAGANA_DAKUTEN,
        "description": "論文と同じひらがな71字。平均文字(補正)に使うには同じ文字を複数回書く。",
    },
    "katakana": {
        "label": "カタカナ(71字)",
        "chars": KATAKANA_46 + KATAKANA_DAKUTEN,
        "description": "カタカナ71字。",
    },
    "alnum": {
        "label": "英数字(62字)",
        "chars": ALPHANUMERIC,
        "description": "アルファベットと数字。AI生成は日本語のみ対応のため、英数字は書いた文字の補正(平均文字)で使う。",
    },
    "symbols": {
        "label": "記号(16字)",
        "chars": SYMBOLS,
        "description": "句読点・括弧など日常的な記号。枠の中で実際の大きさ・位置のとおりに書く(例: 。は左下に小さく)。AI生成対象外のため書いた記号がそのまま使われる。",
    },
}
