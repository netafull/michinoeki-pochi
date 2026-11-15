# 道の駅ポチ

全国の道の駅について、住所・電話・営業時間・駐車場台数・EV充電や温泉などの設備を、一次情報で確認してまとめるサイト（ローカル試作）。

## 構成

- `app.py` — Flaskアプリ本体。ページは `/`（トップ）、`/<都道府県slug>/`（県ページ）、`/station/<slug>/`（駅ページ）、`/genre/<slug>/`（ジャンルページ）、`/sitemap.xml`、`/robots.txt`。
- `data/michinoeki.json` — 駅データ。`{"updated": ..., "prefectures": {"<都道府県slug>": {"name": ..., "stations": [...]}}}` の形で都道府県ごとに束ねる。表示とは分離して持つ。
- `static/style.css` — 緑系アクセント（温泉宿ポチと区別）。カードは「名前を大きく、数字（駐車台数）を目立たせる」階層。
- `test_app.py` — unittest（ローダーの検証・各ページのレンダリング・404）。

## 起動とテスト

```
.venv/bin/python app.py        # http://localhost:8080
.venv/bin/python -m unittest   # テスト
```

Flask はプロジェクト内の `.venv` に入っている（システムの Python には入れない）。

## データの決まり

- **一次情報のみ**：国土交通省の道の駅登録一覧、全国道の駅連絡会、各駅の公式サイト、自治体の情報だけを使う。既存のまとめサイトの文章・データのコピペはしない。
- **出典と確認日が必須**：各駅に `source_url`（出典URL）と `checked`（確認日）を付け、ローダーが検証する（URL形式・実在する日付・未来日でないこと）。検証に落ちた駅はデータ全体を落とさず、その駅だけを除外して理由を標準出力に出す。
- **未確認は null**：確認できなかった項目は推測で埋めず null にする。表示側は null の項目を行・チップごと出さない。
- **0件のジャンルは作らない**：該当駅が1駅もないジャンルはページ自体を作らず、リンクも出さない。
- 座標は持たない。国土数値情報の道の駅データは非商用ライセンスのため使わない（将来必要なら住所からのジオコーディングで作る）。

各駅のキー：`slug`（ローマ字・一意）、`name`、`address`、`tel`、`hours`、`closed`、`parking_normal`（普通車台数）、`parking_large`（大型車台数）、`ev`、`onsen_ashiyu`、`dogrun`、`restaurant`、`shop`（各 true/false/null）、`official_url`、`source_url`、`checked`。

## 現在の掲載

- 埼玉県：21駅（2026-11-15に一次情報で収集・検証済み）

## 今後の展開

- 都道府県単位でデータを追加していく（`data/michinoeki.json` の `prefectures` に足すだけで県ページが増える）。
- ジャンルは ev（EV充電あり）、onsen（温泉・足湯あり）、dogrun（ドッグランあり）、restaurant（レストランあり）、shop（物産・直売所あり）。
- 本番化のときにやること：リポジトリのGitHub化、ドメイン（michinoeki.netaful.jp 想定）の用意、Cloud Run へのデプロイ、帯（divider）画像の作成。
