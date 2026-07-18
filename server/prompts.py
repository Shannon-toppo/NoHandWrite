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

# Optional extra style sets (do them in order 2 → 5 after the basic set).
# Each adds 25 kanji chosen to expose structures the earlier sets lack.
# 2: enclosures (国円), radicals-as-crowns (花草空字学竹), しんにょう (道),
#    stand-alone components (糸貝目耳石白玉王立音年) and curve/sweep-heavy
#    forms (気風虫犬見).
STYLE_REFERENCE_2 = "国道花空草竹糸貝見目耳石白玉王立音字学円年気風虫犬"
# 3: sweeps and hooks — left/right払い (入八天太友今分), はね (也丸飛戸),
#    curve rhythm in few strokes (九千万久), box-less enclosures (区医),
#    dense multi-part forms (民衣長鳥角魚食光).
STYLE_REFERENCE_3 = "入八九千万久丸也民衣長鳥飛区医角魚食今分光戸友天太"
# 4: high stroke-count composites — density balance and how the writer
#    compresses crowded elements (門構え, 雨冠, offset radicals).
STYLE_REFERENCE_4 = "間朝夜書春夏秋冬晴雪電雲遠園数楽新聞暗温館駅橋曜週"
# 5: remaining distinctive radical shapes — そり・戈 (成我代式),
#    おおざと/こざと (都部陽院), りっとう (前別), 走・建 and しんにょう
#    variants (起走建近返送), 弓 (強弱), layered forms (表里重室屋助動).
STYLE_REFERENCE_5 = "成我代式都部陽院前別助動室屋起走建近返送強弱表里重"

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
    "style2": {
        "label": "スタイル学習2(漢字25字)",
        "chars": STYLE_REFERENCE_2,
        "description": "精度を上げたい人向けの追加セット(2→5の順に)。囲い・かんむり・しんにょうなど基本セットにない構造を補う。",
    },
    "style3": {
        "label": "スタイル学習3(漢字25字)",
        "chars": STYLE_REFERENCE_3,
        "description": "追加セットその2。左右の払い・はね・少画数の字で、線のリズムと勢いを学習させる。",
    },
    "style4": {
        "label": "スタイル学習4(漢字25字)",
        "chars": STYLE_REFERENCE_4,
        "description": "追加セットその3。画数の多い複合字で、密な字のバランスの取り方を学習させる。",
    },
    "style5": {
        "label": "スタイル学習5(漢字25字)",
        "chars": STYLE_REFERENCE_5,
        "description": "追加セットその4。そり・おおざと・りっとうなど残りの特徴的な部首形をカバーする。",
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
