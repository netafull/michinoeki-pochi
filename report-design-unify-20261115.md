# 見た目をポチシリーズ共通デザインにそろえた（2026-11-15）

ブランチ: `claude/design-unify`（ローカルコミットのみ。push・docs/ の再生成はしていない）

## 何を変えたか
- `static/style.css` を全面書き換え。色変数を `--bg --card --text --muted --accent --line` の形にし、`prefers-color-scheme: dark` で差し替え。緑 `#2e7d32` を基本、ダークは `#81c784`。ボタンの白文字は、ライトで白 on `#2e7d32`（約5.1:1）、ダークで濃緑文字 on `#81c784`（約9:1）。
- `app.py`
  - ヘッダー: ロゴ画像（44px・alt空）＋サイト名＋説明文。h1 になるのはトップだけ。ほかのページはサイト名を `div.site-title` にした。
  - トップは hero 内の h1 を外し、ヘッダーの h1（サイト名）に一本化。
  - `<head>` に favicon・apple-touch-icon・og:image（絶対URL `SITE_URL/static/assets/ogp.jpg`）ほかOGPを追加。
  - 駅カード: 名前 → 駐車台数（最大の数字）→ 設備チップ → 住所（ラベル付き dl）→ 駅の詳細／公式サイトのボタン。
  - 駅ページ: 表（table）をやめ、同じ階層のカード（駐車台数 大 → チップ → dl の事実 → 公式サイトボタン）に変更。値が null の項目は従来どおり出さない。
  - 節の見出し h2 は左に4pxの縦バー（アクセント色）。パンくずは h1 直下のまま（確認済み）。BreadcrumbList JSON-LD は変更なし。
- `static/assets/` の4アイコンをコミットに含めた。
- `test_app.py`: 駅ページが表から dl になったため、休館日が null のときの否定アサーションを `<th>休館日</th>` から `<dt>休館日</dt>` に変更（意図は同じ）。

## 変えていないもの
ルーティング・URL・canonical、フィルタJS（`app.js`）とそのクラス名・data属性、データとローダー、`build_static.py`、docs/。

## お手本との違い・迷った点
- アイコンのパスは `/static/assets/...`（Flaskの静的配信と書き出しの仕組みを変えないため。カフェポチは `/assets/`）。
- CSSは外部ファイルのまま（カフェポチはインライン）。
- 住所はカード内の dl に移した（旧: 補足文）。カード一覧では電話・営業時間は出していない（元からないため増やさなかった）。
- 日帰り温泉の無料バッジ・カテゴリ色のような分類は道の駅に対応物がないため入れていない。

## 検証
- `python -m unittest`: 18件すべて OK（変更前も18件OK）。
- フィルタ（ヘッドレスChrome＋注入スクリプト）: 初期21 → EV 7 → EV+温泉 1 → 4つ選択 0（空状態の表示は同スクリプトでは `hidden=false` を確認）→ リセット21。EV+物産で7駅表示のスクリーンショットも撮影。
- 静的書き出しは `--out` でリポジトリ外に出力: 30ページ、`static/assets/` の4ファイルを含む。ローカルで配信して4アイコンとCSSが200、トップのh1がサイト名・県/駅ページのh1が主題であることを確認。
- `git status`: docs/ に差分なし。

## 未確認
- 実機（スマホ）での見え方。モバイルは390px幅のiframeで撮影。
- コントラスト比は計算値（測定ツールは未使用）。
- 本番反映後のOGP表示（X・LINE等）。

## スクリーンショット
`/private/tmp/claude-501/-Users-kogure-Desktop-Claude/2d580877-6e8d-4739-af12-43403d591b31/scratchpad/michinoeki-shots/` の `before/` と `after/`
（top・pref・station の mobile / pc、pref と station の mobile-dark。after のみ pref-mobile-filtered.png、static-top-pc.png）
