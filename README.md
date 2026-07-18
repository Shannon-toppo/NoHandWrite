# NoHandWrite

少量の手書き入力からその人の字体を学習し、

1. **補正** — 書いた文字を字体を保ったまま綺麗にする(中村ら「[平均文字は美しい](https://dl.nkmr-lab.org/papers/196/paper.pdf)」EC2014 のフーリエ級数平均を実装)
2. **生成** — 書いていない文字をその字体で生成する([SDT](https://github.com/dailenson/SDT), CVPR 2023 の日本語学習済みモデルを利用)
3. **出力** — ペンプロッター用の単線SVG / G-code を書き出す

全パイプラインがストローク(筆順付き点列)ベースで、Windows / Mac 両対応(ブラウザUI)。

## セットアップ

必要なもの: [uv](https://docs.astral.sh/uv/), Python 3.11+

```sh
uv sync
```

### SDT(未入力文字のAI生成)を使う場合

`third_party/SDT` に学習済みモデルとデータ辞書が必要です(なくても補正・入力は動作します):

- 学習済みモデル → `third_party/SDT/model_zoo/saved_weights/Japanese/checkpoint-iter147999.pth`
- 日本語データセット(のうち `Japanese_content.pkl` などの辞書) → `third_party/SDT/data/TUATHANDS_JAPANESE/`

入手先は [SDTのREADME](https://github.com/dailenson/SDT#-pre-trained-model)(Google Drive)。データセットはTUAT HANDSに由来する研究用データです。**研究・個人利用の範囲で使用してください。**

## 起動

```sh
uv run uvicorn server.main:app --host 0.0.0.0 --port 8765
```

ブラウザで http://localhost:8765 を開く。

- **✏️ 入力** — お題文字を手書きで入力(推奨: 「スタイル学習+英数字(87字)」)。「回数」で同じ文字を複数回書いて平均文字の精度を上げられる(順序は「セット全体をN周(推奨)」か「連続N回」)。「入力枠」スライダーで書く領域の大きさを変更可能
- **📚 ライブラリ** — 書いた文字の重ね描きと平均文字(赤太線)を確認
- **🖋 生成** — テキストを入力すると、書いた文字は平均文字、未入力文字はAI生成で描画。SVG / G-code をダウンロード
- **🖨 組版** — 文章をmm指定(文字サイズ・文字間・行間・行幅・余白)でページにレイアウトし、プレビューを確認してペンプロッター用G-code(送り速度・ペン上下コマンド・Y軸反転も指定可)/ SVG を出力

### iPad + Apple Pencil で入力する

同じWi-Fi上のiPadのSafariから `http://<Macのローカル(LAN)IP>:8765` を開くだけです(サーバは `--host 0.0.0.0` で起動)。Apple Pencilの筆圧も記録されます。MacのIPは システム設定 → Wi-Fi で確認できます。

## データ

`data/<書き手ID>/uXXXX.json` に1文字1ファイルで保存(座標・時刻・筆圧、複数回分)。git管理外です。

## テスト

```sh
uv run pytest
```

## 構成

```
core/nohandwrite/   ロジック本体(strokes / fourier / beautify / generate / export / store)
server/             FastAPI(保存・補正・生成・エクスポートAPI + 静的配信)
web/                ブラウザUI(入力・ライブラリ・生成)
third_party/SDT/    SDT本体(vendored, MIT)— gmm.py にデバイス非依存化の小パッチ
scripts/            検証・デモ用スクリプト(M0スパイク、デモデータ投入)
```

## G-code について

デフォルトはZ軸でペン上下(GRBL系)。サーボ式は `core/nohandwrite/export/gcode.py` の
`GCodeOptions(pen_up_cmd="M3 S40", pen_down_cmd="M3 S90")` のように変更してください。
出力はmm単位・絶対座標、ストロークはRDPで簡略化済み(許容誤差0.05mm)。
