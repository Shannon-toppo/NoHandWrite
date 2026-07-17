"""Prompt character sets shown in the capture UI."""

HIRAGANA_46 = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"
HIRAGANA_DAKUTEN = "がぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ"
KATAKANA_46 = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン"
KATAKANA_DAKUTEN = "ガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポ"

# Style-reference set for SDT: 25 kanji chosen for stroke variety (永 covers the
# "eight principles"; the rest span radicals, curves, and stroke counts).
STYLE_REFERENCE = "永東京木林山川日月火水金土人心手口田力糸雨車食馬鳥"

ALPHANUMERIC = ("ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "abcdefghijklmnopqrstuvwxyz"
                "0123456789")

PROMPT_SETS: dict[str, dict] = {
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
}
