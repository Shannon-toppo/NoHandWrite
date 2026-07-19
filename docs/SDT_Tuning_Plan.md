# SDT ファインチューニング計画(M5)

自分の手書きデータで SDT の日本語学習済みモデルを追加学習し、スタイル参照15枚では拾いきれない癖(字形の崩し方、ハネ・トメ、画のつなぎ)を生成に反映する。学習は NVIDIA 機(Windows 11 / Ryzen 7 7800X3D / RAM 32GB / RTX 4070 Ti 12GB)で行い、推論は今までどおり Mac (MPS) のアプリで使う。

## 前提と現有資産

- `third_party/SDT` に学習コード一式と学習済み `checkpoint-iter147999.pth`、TUAT HANDS 日本語データセット(train 3.1GB + train_style_samples 3.2GB + test 計約8GB)が揃っている。`train.py --pretrained_model <ckpt>` で任意のチェックポイントから学習再開できるので、学習スクリプト自体の改造はほぼ不要
- SDT の学習データ形式(`data_loader/loader.py` で確認):
  - **LMDB**(train/): エントリは `{tag_char, coordinates, fname}`。coordinates は絶対座標 (N, 5) の (x, y, s1, s2, s3)。ローダー側で正規化と相対座標化をする
  - **style_samples**(書き手ごとの pkl): `[{img: 64×64 uint8, label: cp932 hex}, ...]`
  - `writer_dict.pkl`(fname → writer_id)、`character_dict.pkl`(文字列。`.find(char)` でID化)
  - 150点を超える文字は学習から除外される(`max_len=150`)
- ハード的な見立て: モデルは Transformer 2+2層と小さく、64×64 画像 × batch 64 なら VRAM は数GBで 12GB に余裕。LMDB はメモリマップ読みなので RAM 32GB も問題ない。8コアの 7800X3D は DataLoader worker 4〜8 で足りる

## 手順

### M5.1 Windows 環境構築(半日)

1. リポジトリを clone、`uv sync`(アプリ側)+ SDT 用に PyTorch CUDA 版(cu121 以降)、`lmdb`、`opencv-python`、`pillow`、`pyyaml`、`fastdtw` を入れる。`environment.yml` は古いので参考程度
2. 動作確認: 既存チェックポイントで `user_generate.py` か本アプリの生成APIを CUDA で動かし、Mac と同じ出力が出ることを見る(`models/gmm.py` のデバイス非依存パッチは CUDA でもそのまま動く)
3. つまずいたら DataLoader の `NUM_THREADS` を 0 にして切り分ける(Windows の multiprocessing 起因の失敗が定番)。素の Windows でダメなら WSL2 + Ubuntu に切り替える

### M5.2 データ変換器(1日)

`scripts/m5_export_sdt_dataset.py` を書く。`data/<writer>/uXXXX.json` → SDT 形式:

- 各サンプルを (x, y, s1, s2, s3) 列に変換して LMDB に追記。点数が 150 を超える文字は RDP か等弧長リサンプリングで間引く(でないと学習から落ちる)
- スタイル画像は `sdt_adapter.render_style_image` を流用して 64×64 で書き手 pkl に書き出す。ラベルは cp932 hex 形式に合わせる
- `writer_dict` に自分の writer を新 ID で追記
- `character_dict` / `Japanese_content.pkl` に無い文字は今回は捨てる(辞書追加は content 画像の整備も要るので M5 の範囲外)
- 検証: 変換した LMDB を SDT の `ScriptDataset` でそのまま読み、崩れていないか数件を目視

### M5.3 学習(半日〜、試行錯誤込みで数日)

- `configs/Japanese_TUATHANDS_finetune.yml` を作る: `BASE_LR 1e-5〜2e-5`(元は 2e-4)、`MAX_ITER 5000〜20000`、`WARMUP_ITERS 500`、`SNAPSHOT_ITERS 1000`
- **データは TUAT train + 自分のデータの混合**にする。自分のデータだけで回すと、書き手対比の NCE 損失が成立しない(書き手が1人)うえ、破滅的忘却で他の字が崩れる。自分のサンプルを複製して全体の 5〜10% になる程度から始める
- `python train.py --cfg configs/Japanese_TUATHANDS_finetune.yml --pretrained_model model_zoo/saved_weights/Japanese/checkpoint-iter147999.pth`
- 見積り: batch 64 × 10,000 iter なら 4070 Ti で1〜2時間の桁。1000 iter ごとの snapshot を全部残し、後から一番良い点を選ぶ

### M5.4 評価(1日)

- 入力済み文字の2割を hold-out し、その文字を生成 → 実際の筆跡とのDTW距離を before/after で比較
- 未入力文字の目視グリッド(既存チェックポイントとの並置画像)を評価スクリプトで吐く。崩れやすい画数の多い字と小書き仮名を必ず入れる
- 過学習の兆候(hold-out の距離悪化、他の書体らしさへの引っ張られ)が出たら、より早い snapshot か混合比を下げてやり直す

### M5.5 アプリ統合(半日)

- 採用チェックポイントを Mac に持ち帰り、まず `SDTGenerator(ckpt=...)` の差し替えで動作確認(MPS で推論できることは確認済み)
- その後 `data/<writer>/sdt.pth` があればそれを優先ロードする仕組みを入れ、書き手ごとにチューニング済みモデルを持てるようにする

## リスクと対策

- **忘却・過学習** — 混合学習+snapshot 総当たり比較で対処。ダメなら学習率をさらに下げるか、コンテンツエンコーダを freeze する
- **字典外の文字** — 今回は学習対象外。生成できない文字は従来どおり手書きで埋める運用
- **Windows 固有の失敗** — LMDB のパス・worker 数・cp932 まわり。切り分け手順は M5.1 に記載、最終手段は WSL2
- **ライセンス** — TUAT HANDS 由来データでの学習なので、成果物のモデルも研究・個人利用のみ。この方針はプロジェクト全体の前提と同じ

## Mac ↔ Windows の運用

コードは git(このリポジトリ)、`data/<writer>/` と `third_party/SDT/data` は LAN で転送(どちらも git 管理外)。チェックポイントは 200MB 程度なので AirDrop や LAN コピーで十分。学習の試行ログは `third_party/SDT/OUTPUT_DIR`(config で指定)に残る。
