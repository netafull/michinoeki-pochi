#!/usr/bin/env python3
"""道の駅ポチ: 都道府県ごとに、道の駅の基本情報（住所・駐車場・設備）を一次情報でまとめるサイト。

起動（ローカル）:
  .venv/bin/python app.py
  -> http://localhost:8080

守っている規約・方針（詳細は README.md）
- データは一次情報のみ（国土交通省の登録一覧・全国道の駅連絡会・各駅の公式サイト・自治体）。
  各駅に source_url（出典）と checked（確認日）を必須とし、ローダーが検証する。
- 確認できなかった項目は null のままにし、表示側では行・チップごと出さない（推測で埋めない）。
- 0件のジャンルはページ自体を作らない（リンクも出さない）。
- 公開は都道府県単位。データの prefectures.<slug>.published が true の県だけを表示する
  （データの精査が終わった県から順次公開する運用。未公開の県はページ自体を作らない）。
- EV充電の有無は、公式・自治体に加え、充電ネットワーク事業者の公表値や専門データベース
  （EVsmart、EV Smart Charge）の登録でも裏付け可とする。その場合は ev_source_url に確認元の
  URLを持ち、駅ページの出典ブロックに「EV充電の確認元」としてリンクを出す。
  ユーザー投稿型サイト（GoGoEV等）の登録だけを根拠にはしない。
"""
import datetime
import html
import json
import os
import re
import urllib.parse

from flask import Flask, Response, abort

# ---------- サイト名・基本設定 ----------
SITE_NAME = "道の駅ポチ"
TAGLINE = "道の駅の駐車場・設備を、まとめて探す"
DESCRIPTION = ("全国の道の駅について、住所・電話・営業時間・駐車場台数・EV充電や温泉などの設備を、"
               "各駅の公式サイトや道の駅連絡会などの一次情報で確認してまとめています。")
SITE_URL = os.environ.get("SITE_URL", "https://michinoeki.netaful.jp").rstrip("/")

# 共通ページテンプレート・文言を最後に変えた日（sitemap.xml の lastmod の下限）。テンプレートや文言を変えたら手で更新する
PAGES_UPDATED = "2026-11-16"

# フッターの関連サイト（ポチシリーズ。道の駅ポチ自身は載せない。名前・説明は他のポチの config.json と同じ）
SERIES_SITES = (
    ("電書ポチ", "Kindle本セール", "https://book.netaful.jp/"),
    ("家電ポチ", "ガジェット・家電セール", "https://kaden.netaful.jp/"),
    ("林檎ポチ", "Apple整備済製品", "https://apple.netaful.jp/"),
    ("漫画ポチ", "Webマンガ横断検索", "https://manga.netaful.jp/"),
    ("コンビニポチ", "コンビニ新商品アーカイブ", "https://conbini.netaful.jp/"),
    ("ファストフードポチ", "ファストフード限定メニュー", "https://fastfood.netaful.jp/"),
    ("カフェポチ", "カフェ季節限定メニュー", "https://cafe.netaful.jp/"),
    ("回転寿司ポチ", "回転寿司の期間限定ネタ", "https://sushi.netaful.jp/"),
    ("カップ麺ポチ", "カップ麺の新商品", "https://cupmen.netaful.jp/"),
    ("ホテルポチ", "空室ホテルを安い順に検索", "https://hotel.netaful.jp/"),
    ("温泉宿ポチ", "温泉地の空室を、すぐ探す", "https://onsen.netaful.jp/"),
    ("離島宿ポチ", "島の空室を、すぐ探す", "https://ritou.netaful.jp/"),
    ("新発売ポチ", "新商品を発売日でまとめて", "https://shinhatsubai.netaful.jp/"),
)

# トップの都道府県一覧の地方区分（各区分の中は北から南、JISの県コード順）。
# 未公開の県も含めてよい（表示は公開済みの県だけ）。新しい県はここへ足す。
PREFECTURE_REGIONS = (
    ("東北", ("aomori", "iwate", "miyagi", "akita", "yamagata", "fukushima")),
    ("関東", ("ibaraki", "tochigi", "gunma", "saitama", "chiba", "tokyo", "kanagawa")),
    ("甲信越", ("niigata", "yamanashi", "nagano")),
    ("北陸", ("toyama", "ishikawa", "fukui")),
    ("東海", ("gifu", "shizuoka", "aichi", "mie")),
    ("近畿", ("shiga",)),
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "michinoeki.json")

# 注意書き（日帰り温泉ポチと同じ文面。料金・営業時間は変わるため、公式確認を必ず促す）
CAUTION = ("料金・営業時間・休館日などは変更される場合があります。"
           "お出かけ前に、必ず各施設の公式ページで最新の情報をご確認ください。")

# ジャンル: slug -> (表示名, データのキー)。True の駅だけを並べる
GENRES = {
    "ev": ("EV充電あり", "ev"),
    "onsen": ("温泉・足湯あり", "onsen_ashiyu"),
    "dogrun": ("ドッグランあり", "dogrun"),
    "restaurant": ("レストランあり", "restaurant"),
    "shop": ("物産・直売所あり", "shop"),
}
# 設備チップの並び（ジャンルと同じ順）
FEATURE_KEYS = ("ev", "onsen_ashiyu", "dogrun", "restaurant", "shop")
FEATURE_LABELS = {"ev": "EV充電", "onsen_ashiyu": "温泉・足湯", "dogrun": "ドッグラン",
                  "restaurant": "レストラン", "shop": "物産・直売所"}

# ローダーが通すキー（これ以外は落とす）
KNOWN_KEYS = ("slug", "name", "address", "tel", "hours", "closed",
              "parking_normal", "parking_large",
              "ev", "onsen_ashiyu", "dogrun", "restaurant", "shop",
              "official_url", "source_url", "checked", "ev_source_url")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _is_url(v):
    return isinstance(v, str) and (v.startswith("https://") or v.startswith("http://"))


def _is_date(value):
    """YYYY-MM-DD の実在する日付か。"""
    try:
        return isinstance(value, str) and datetime.date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


class StationStore:
    """data/michinoeki.json を読み、駅単位で検証する。

    検証に落ちた駅は丸ごと（データ全体を）落とさず、その駅だけを除外して理由を標準出力に出す。
    必須: name / slug（一意・形式）/ source_url（URL）/ checked（実在する日付・未来日は不可）。
    任意項目は型が合わなければ None に落とす（駅自体は残す）。キーは既知のものだけ通す。
    """

    def __init__(self, path=DATA_PATH):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        self.updated = raw.get("updated")
        self.prefectures = {}   # slug -> {"name": str, "stations": [station, ...]}
        self._by_slug = {}      # station slug -> (pref slug, station)
        seen = set()
        for pref_slug, pref in (raw.get("prefectures") or {}).items():
            stations = []
            for item in pref.get("stations") or []:
                st, reason = self._validate(item, seen)
                if st is None:
                    print("[michinoeki] 駅を除外しました: %s (%s)" % (item.get("name") or item.get("slug") or "?", reason))
                    continue
                seen.add(st["slug"])
                stations.append(st)
                self._by_slug[st["slug"]] = (pref_slug, st)
            if stations:
                self.prefectures[pref_slug] = {"name": pref.get("name") or pref_slug, "stations": stations,
                                               "published": pref.get("published") is True}

    @staticmethod
    def _validate(item, seen):
        if not isinstance(item, dict):
            return None, "オブジェクトでない"
        st = {k: item.get(k) for k in KNOWN_KEYS}
        if not isinstance(st["name"], str) or not st["name"]:
            return None, "name がない"
        if not isinstance(st["slug"], str) or not SLUG_RE.match(st["slug"]):
            return None, "slug の形式が不正"
        if st["slug"] in seen:
            return None, "slug が重複"
        if not _is_url(st["source_url"]):
            return None, "source_url がない/URLでない"
        try:
            checked = datetime.date.fromisoformat(st["checked"])
        except (TypeError, ValueError):
            return None, "checked が実在する日付でない"
        if checked > datetime.date.today():
            return None, "checked が未来日"
        # 任意項目の型を整える（合わなければ None）
        for k in ("address", "tel", "hours", "closed"):
            if not isinstance(st[k], str) or not st[k]:
                st[k] = None
        for k in ("parking_normal", "parking_large"):
            if not isinstance(st[k], int) or isinstance(st[k], bool) or st[k] < 0:
                st[k] = None
        for k in FEATURE_KEYS:
            if not isinstance(st[k], bool):
                st[k] = None
        if not _is_url(st["official_url"]):
            st["official_url"] = None
        if not _is_url(st["ev_source_url"]):
            st["ev_source_url"] = None
        return st, None

    def all_stations(self):
        """(都道府県slug, 駅) の一覧（データの並び順）。公開・未公開を問わない全データ。"""
        out = []
        for pref_slug, pref in self.prefectures.items():
            for st in pref["stations"]:
                out.append((pref_slug, st))
        return out

    def public_prefectures(self):
        """公開中（published が true）の都道府県だけ。表示・書き出しはこちらを使う。"""
        return {slug: p for slug, p in self.prefectures.items() if p["published"]}

    def public_stations(self):
        """公開中の都道府県の駅だけ。"""
        out = []
        for pref_slug, pref in self.prefectures.items():
            if not pref["published"]:
                continue
            for st in pref["stations"]:
                out.append((pref_slug, st))
        return out

    def get(self, slug):
        return self._by_slug.get(slug)

    def genre_stations(self, genre_slug):
        key = GENRES[genre_slug][1]
        return [(p, s) for p, s in self.public_stations() if s[key] is True]

    def live_genres(self):
        """1駅以上あるジャンルだけ（0件のジャンルはページもリンクも作らない）。"""
        return {slug: g for slug, g in GENRES.items() if self.genre_stations(slug)}


STORE = StationStore()

app = Flask(__name__, static_folder="static", static_url_path="/static")

# ---------- テンプレート ----------
BASE_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-JLZ2CJH787"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-JLZ2CJH787');</script>
<title>{{PAGE_TITLE}}</title>
<meta name="description" content="{{DESCRIPTION}}">
<link rel="canonical" href="{{CANONICAL}}">
<link rel="icon" type="image/png" sizes="96x96" href="/static/assets/favicon.png">
<link rel="apple-touch-icon" href="/static/assets/apple-touch-icon.png">
<meta property="og:type" content="website">
<meta property="og:title" content="{{PAGE_TITLE}}">
<meta property="og:description" content="{{DESCRIPTION}}">
<meta property="og:url" content="{{CANONICAL}}">
<meta property="og:site_name" content="{{SITE_NAME}}">
<meta property="og:locale" content="ja_JP">
<meta property="og:image" content="{{OGP_IMAGE}}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="stylesheet" href="/static/style.css">
{{JSONLD}}</head>
<body>
<header class="site-header">
{{SITE_HEAD}}
<p class="tagline">{{TAGLINE}}</p>
</header>
<main>
{{CONTENT}}</main>
<footer class="site-footer">
<p>{{SITE_NAME}}は、道の駅の情報を各駅の公式サイトや道の駅連絡会などの一次情報で確認してまとめています。</p>
<p>当サイトは各道の駅・国土交通省・全国道の駅連絡会とは関係のない非公式サイトです。営業時間・駐車台数・設備は、各駅のページに書いた確認日の時点のものです。最新の情報は各駅の公式サイトでご確認ください。</p>
<p><a href="/">トップ</a> ｜ <a href="https://netaful.jp/policy.html">メディアポリシー</a></p>
{{SERIES_NAV}}</footer>
</body>
</html>
"""


def _series_nav():
    """フッターの関連サイト（チップ表示）。"""
    links = "\n".join('<a href="%s">%s<span class="lbl"> %s</span></a>'
                      % (html.escape(u, quote=True), html.escape(n), html.escape(d)) for n, d, u in SERIES_SITES)
    return '<nav class="sites"><span class="lbl">関連サイト</span>\n%s\n</nav>\n' % links


def _site_head(is_top):
    """ヘッダーのサイト名。h1 になるのはトップだけ（ほかのページはそのページの主題が h1）。"""
    name = ('<a href="/"><img src="/static/assets/logo.png" alt="" width="44" height="44">%s</a>'
            % html.escape(SITE_NAME))
    return '<h1 class="site-title">%s</h1>' % name if is_top else '<div class="site-title">%s</div>' % name


def _render(title, description, canonical, content, jsonld="", is_top=False):
    """{{NAME}} を1回の置換で差し替える。通常の値は html.escape、content/jsonld は組み立て済みHTML。"""
    vals = {"PAGE_TITLE": html.escape(title, quote=True), "DESCRIPTION": html.escape(description, quote=True),
            "CANONICAL": html.escape(canonical, quote=True), "SITE_NAME": html.escape(SITE_NAME),
            "TAGLINE": html.escape(TAGLINE), "CONTENT": content, "JSONLD": jsonld,
            "OGP_IMAGE": html.escape(SITE_URL + "/static/assets/ogp.jpg", quote=True), "SITE_HEAD": _site_head(is_top),
            "SERIES_NAV": _series_nav()}
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: vals.get(m.group(1), m.group(0)), BASE_TEMPLATE)


def _jsonld(obj):
    """<script type="application/ld+json"> の中身。"<" を逃がして </script> で閉じられないようにする。"""
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return '<script type="application/ld+json">%s</script>\n' % body


def _crumbs(*items):
    """パンくず（BreadcrumbList）の JSON-LD。items は (名前, 絶対URL) の並び。先頭にサイト名を足す。"""
    rows = [(SITE_NAME, SITE_URL + "/")] + list(items)
    return _jsonld({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": u} for i, (n, u) in enumerate(rows)]})


def _crumbs_nav(*items):
    """見えるパンくず。items は (名前, パス) の並び。末尾（現在のページ）はリンクにしない。"""
    e = html.escape
    rows = [(SITE_NAME, "/")] + list(items)
    parts = ['<a href="%s">%s</a>' % (e(u, True), e(n)) for n, u in rows[:-1]]
    parts.append('<span aria-current="page">%s</span>' % e(rows[-1][0]))
    return '<nav class="crumbs" aria-label="パンくずリスト">' + " &gt; ".join(parts) + "</nav>\n"


def _fmt_checked(checked):
    try:
        y, m, d = checked.split("-")
        return "%d年%d月%d日" % (int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return checked


def _chips(st):
    """設備チップ。True のものだけ出す（null/false は出さない）。"""
    items = "".join('<li class="ms-chip">%s</li>' % html.escape(FEATURE_LABELS[k])
                    for k in FEATURE_KEYS if st[k] is True)
    return '<ul class="ms-chips">%s</ul>' % items if items else ""


def _parking_html(st, big=False):
    """駐車場台数。カードではある項目だけ出す。駅ページ（big）では未確認の項目も
    小さめの文字で「未確認」と出す（数字と同じ書体だと同じ重さに見えるため）。"""
    parts = []
    if st["parking_normal"] is not None:
        parts.append('<span class="ms-parking-item"><span class="ms-parking-label">普通車</span>'
                     '<strong class="ms-parking-num">%d台</strong></span>' % st["parking_normal"])
    elif big:
        parts.append('<span class="ms-parking-item"><span class="ms-parking-label">普通車</span>'
                     '<span class="ms-parking-unknown">未確認</span></span>')
    if st["parking_large"] is not None:
        parts.append('<span class="ms-parking-item"><span class="ms-parking-label">大型車</span>'
                     '<strong class="ms-parking-num">%d台</strong></span>' % st["parking_large"])
    elif big:
        parts.append('<span class="ms-parking-item"><span class="ms-parking-label">大型車</span>'
                     '<span class="ms-parking-unknown">未確認</span></span>')
    if not parts:
        return ""
    return '<p class="ms-parking%s">%s</p>' % (" ms-parking--big" if big else "", "".join(parts))


def _station_card(pref_slug, st, show_pref=False):
    """駅カード。名前を大きく、駐車台数を目立たせ、設備チップと公式サイトボタンを付ける。
    True の設備キーは data-feats に空白区切りで持たせ、県ページのJSフィルタが使う。"""
    e = html.escape
    url = "/station/%s/" % st["slug"]
    feats = " ".join(k for k in FEATURE_KEYS if st[k] is True)
    out = '<li class="ms-card" data-feats="%s">' % feats
    out += '<div class="ms-card-head"><h3><a href="%s">%s</a></h3>' % (e(url, True), e(st["name"]))
    if show_pref:
        out += '<span class="ms-pref">%s</span>' % e(STORE.prefectures[pref_slug]["name"])
    out += "</div>"
    out += _parking_html(st)
    out += _chips(st)
    if st["address"]:
        out += ('<dl class="ms-facts-list"><div><dt>住所</dt><dd>%s</dd></div></dl>' % e(st["address"]))
    links = '<p class="ms-card-links"><a class="ms-detail" href="%s">駅の詳細</a>' % e(url, True)
    if st["official_url"]:
        links += ('<a class="ms-official" href="%s" target="_blank" rel="noopener">公式サイト</a>'
                  % e(st["official_url"], True))
    out += links + "</p>"
    return out + "</li>"


def _sources_block(st):
    """出典ブロック。一次情報で確認していることと確認日だけを細く残す（リンク列は並べない）。
    出典URLは1本だけ「出典」として出す。"""
    e = html.escape
    ev_note = ""
    ev_link = ""
    if st["ev"] is True and st["ev_source_url"]:
        ev_note = "EV充電については、確認元の情報でも確認しています。"
        ev_link = ('<p class="ms-source-link">EV充電の確認元: <a href="%s" target="_blank" rel="noopener">%s</a></p>'
                   % (e(st["ev_source_url"], True), e(st["ev_source_url"])))
    return ('<section class="ms-sources"><h2>出典について</h2>'
            '<p class="fact-checked">住所・営業時間などの情報は、各駅の公式サイトや全国道の駅連絡会などの'
            '一次情報で確認しています（%s確認）。%s</p>'
            '<p class="ms-source-link">出典: <a href="%s" target="_blank" rel="noopener">%s</a></p>%s</section>\n'
            % (e(_fmt_checked(st["checked"])), e(ev_note), e(st["source_url"], True), e(st["source_url"]), ev_link))


def _filter_bar(total):
    """県ページの設備フィルタバー。チェックした設備をすべて持つ駅だけをJSが表示する（AND条件）。
    JS無効時は絞り込みが働かず全カードが見えるのが既定。件数はサーバー側でも総数を出しておき、JSが更新する。"""
    e = html.escape
    boxes = "".join(
        '<label class="ms-filter-chip"><input type="checkbox" class="ms-filter-input" value="%s"> %s</label>'
        % (k, e(FEATURE_LABELS[k])) for k in FEATURE_KEYS)
    return ('<section class="ms-filter" aria-label="設備で絞り込む">'
            '<h2 class="ms-filter-title">設備で絞り込む</h2>'
            '<div class="ms-filter-checks">%s</div>'
            '<p class="ms-filter-status"><span class="ms-filter-count" aria-live="polite">%d駅が該当</span>'
            '<button type="button" class="ms-filter-reset">リセット</button></p>'
            '<p class="ms-filter-empty" hidden>条件に合う駅がありません。条件をゆるめてみてください。</p>'
            '</section>\n' % (boxes, total))


def _genre_links():
    """1駅以上あるジャンルへの導線（件数つき）。"""
    e = html.escape
    items = ""
    for slug, (label, _key) in GENRES.items():
        n = len(STORE.genre_stations(slug))
        if n == 0:
            continue
        items += '<li><a href="/genre/%s/">%s<small>%d駅</small></a></li>' % (slug, e(label), n)
    return '<ul class="ms-nav-chips">%s</ul>' % items if items else ""


# ---------- ページ ----------
@app.route("/")
def index():
    e = html.escape
    pubs = STORE.public_prefectures()
    total = sum(len(p["stations"]) for p in pubs.values())

    def pref_item(slug):
        p = pubs[slug]
        return ('<li><a href="/%s/">%s<small>%d駅</small></a></li>'
                % (slug, e(p["name"]), len(p["stations"])))

    ordered = []   # 表示順（地方区分の順）の県スラッグ
    groups = []    # (地方名, [県スラッグ])
    for region, slugs in PREFECTURE_REGIONS:
        members = [s for s in slugs if s in pubs]
        if members:
            groups.append((region, members))
            ordered.extend(members)
    leftovers = [s for s in pubs if s not in ordered]
    if leftovers:  # 区分表にない公開県は落とさず最後に並べる
        groups.append((None, leftovers))
        ordered.extend(leftovers)
    pref_groups = "".join(
        (('<h3 class="ms-region">%s</h3>' % e(region)) if region else "")
        + '<ul class="ms-nav-chips">%s</ul>' % "".join(pref_item(s) for s in members)
        for region, members in groups)
    if pubs:
        intro = ('ドライブの休憩に立ち寄る道の駅について、駐車場の台数やEV充電・温泉などの設備を'
                 'まとめました。現在は%sの%d駅を掲載しています。%s'
                 % (e("・".join(pubs[s]["name"] for s in ordered)), total, e(CAUTION)))
        sections = ('<section><h2>都道府県から探す</h2>%s</section>\n'
                    '<section><h2>設備から探す</h2>%s</section>\n' % (pref_groups, _genre_links()))
    else:
        intro = ('ドライブの休憩に立ち寄る道の駅について、駐車場の台数やEV充電・温泉などの設備を'
                 'まとめています。ただいま準備中です。')
        sections = ""
    content = (
        '<section class="hero">'
        '<p class="intro">%s</p></section>\n'
        '%s'
        % (intro, sections))
    return _render(SITE_NAME, DESCRIPTION, SITE_URL + "/", content, is_top=True)


@app.route("/<pref_slug>/")
def prefecture(pref_slug):
    pref = STORE.prefectures.get(pref_slug)
    if pref is None or not pref["published"]:
        abort(404)
    e = html.escape
    title = "%sの道の駅" % pref["name"]
    desc = "%sの道の駅%d駅の一覧です。駐車場台数・営業時間・EV充電や温泉などの設備を、公式の案内をもとにまとめました。" % (
        pref["name"], len(pref["stations"]))
    cards = "".join(_station_card(pref_slug, st) for st in pref["stations"])
    canonical = "%s/%s/" % (SITE_URL, pref_slug)
    content = ('<section class="hero"><h1>%s</h1>\n%s'
               '<p class="intro">%sにある道の駅%d駅の一覧です。%s</p></section>\n'
               % (e(title), _crumbs_nav((title, "/%s/" % pref_slug)), e(pref["name"]),
                  len(pref["stations"]), e(CAUTION)))
    content += _filter_bar(len(pref["stations"]))
    content += '<ul class="ms-cards">%s</ul>\n' % cards
    content += '<script src="/static/app.js" defer></script>\n'
    return _render("%s | %s" % (title, SITE_NAME), desc, canonical, content,
                   _crumbs((title, canonical)))


@app.route("/station/<slug>/")
def station(slug):
    found = STORE.get(slug)
    if found is None:
        abort(404)
    pref_slug, st = found
    if not STORE.prefectures[pref_slug]["published"]:
        abort(404)
    pref_name = STORE.prefectures[pref_slug]["name"]
    e = html.escape
    title = "道の駅 %s" % st["name"]
    desc = "%sの道の駅「%s」の基本情報です。住所・電話・営業時間・駐車場台数と、EV充電や温泉などの設備を公式の案内をもとにまとめました。" % (
        pref_name, st["name"])
    canonical = "%s/station/%s/" % (SITE_URL, slug)

    rows = ""
    if st["address"]:
        maps = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(st["address"])
        rows += ('<div><dt>住所</dt><dd><a href="%s" target="_blank" rel="noopener">📍 %s</a></dd></div>'
                 % (e(maps, True), e(st["address"])))
    if st["tel"]:
        rows += '<div><dt>電話</dt><dd><a href="tel:%s">📞 %s</a></dd></div>' % (e(st["tel"], True), e(st["tel"]))
    if st["hours"]:
        rows += '<div><dt>営業時間</dt><dd>%s</dd></div>' % e(st["hours"])
    else:
        rows += '<div><dt>営業時間</dt><dd class="ms-unknown">未確認</dd></div>'
    if st["closed"]:
        rows += '<div><dt>休館日</dt><dd>%s</dd></div>' % e(st["closed"])
    else:
        rows += '<div><dt>休館日</dt><dd class="ms-unknown">未確認</dd></div>' 

    content = ('<section class="hero"><h1>%s</h1>\n%s'
               '<p class="intro">%sの道の駅です。%s</p></section>\n'
               % (e(title), _crumbs_nav(("%sの道の駅" % pref_name, "/%s/" % pref_slug), (title, "/station/%s/" % slug)),
                  e(pref_name), e(CAUTION)))
    card = _parking_html(st, big=True) + _chips(st)
    if rows:
        card += '<dl class="ms-facts-list">%s</dl>' % rows
    card += '<p class="ms-chips-note">確認できた設備だけを表示しています。</p>'
    if st["official_url"]:
        card += ('<p class="ms-official-row"><a class="ms-official" href="%s" target="_blank" rel="noopener">公式サイト</a></p>'
                 % e(st["official_url"], True))
    if card:
        content += '<div class="ms-card ms-card--station">%s</div>\n' % card
    content += _sources_block(st)
    return _render("%s | %s" % (title, SITE_NAME), desc, canonical, content,
                   _crumbs(("%sの道の駅" % pref_name, "%s/%s/" % (SITE_URL, pref_slug)), (title, canonical)))


@app.route("/genre/<genre_slug>/")
def genre(genre_slug):
    if genre_slug not in GENRES:
        abort(404)
    stations = STORE.genre_stations(genre_slug)
    if not stations:
        abort(404)
    e = html.escape
    label = GENRES[genre_slug][0]
    title = "%sの道の駅" % label
    desc = "%s道の駅%d駅の一覧です。駐車場台数・営業時間などを、公式の案内をもとにまとめました。" % (label, len(stations))
    canonical = "%s/genre/%s/" % (SITE_URL, genre_slug)
    cards = "".join(_station_card(p, st, show_pref=True) for p, st in stations)
    content = ('<section class="hero"><h1>%s</h1>\n%s'
               '<p class="intro">%s道の駅は%d駅あります。%s</p></section>\n'
               '<ul class="ms-cards">%s</ul>\n'
               % (e(title), _crumbs_nav((title, "/genre/%s/" % genre_slug)), e(label),
                  len(stations), e(CAUTION), cards))
    return _render("%s | %s" % (title, SITE_NAME), desc, canonical, content,
                   _crumbs((title, canonical)))


@app.route("/sitemap.xml")
def sitemap():
    # lastmod: 共通テンプレートの更新日（PAGES_UPDATED）と、そのページに載る駅の確認日（checked）の新しいほう
    def newest(*dates):
        return max(d for d in dates if d)

    all_checked = [st["checked"] for _p, st in STORE.public_stations()]
    urls = [(SITE_URL + "/", newest(PAGES_UPDATED, STORE.updated if _is_date(STORE.updated) else None, *all_checked))]
    for pref_slug, pref in STORE.public_prefectures().items():
        urls.append(("%s/%s/" % (SITE_URL, pref_slug),
                     newest(PAGES_UPDATED, *(st["checked"] for st in pref["stations"]))))
    for _p, st in STORE.public_stations():
        urls.append(("%s/station/%s/" % (SITE_URL, st["slug"]), newest(PAGES_UPDATED, st["checked"])))
    for slug in STORE.live_genres():
        urls.append(("%s/genre/%s/" % (SITE_URL, slug),
                     newest(PAGES_UPDATED, *(st["checked"] for _p, st in STORE.genre_stations(slug)))))
    body = "".join("<url><loc>%s</loc><lastmod>%s</lastmod></url>" % (html.escape(u), m) for u, m in urls)
    return Response('<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>' % body,
                    mimetype="application/xml")


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nAllow: /\nSitemap: %s/sitemap.xml\n" % SITE_URL, mimetype="text/plain")


@app.errorhandler(404)
def not_found(_err):
    content = ('<section class="hero"><h1>ページが見つかりません</h1>'
               '<p class="intro">お探しのページは存在しないか、まだ掲載していない道の駅です。</p></section>\n')
    return _render("ページが見つかりません | %s" % SITE_NAME, DESCRIPTION, SITE_URL + "/", content), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8080")))
