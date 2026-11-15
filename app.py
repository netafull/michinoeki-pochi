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
TAGLINE = "道の駅の駐車場・設備を、公式情報でまとめて探す"
DESCRIPTION = ("全国の道の駅について、住所・電話・営業時間・駐車場台数・EV充電や温泉などの設備を、"
               "各駅の公式サイトや道の駅連絡会などの一次情報で確認してまとめています。")
SITE_URL = os.environ.get("SITE_URL", "https://michinoeki.netaful.jp").rstrip("/")

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
              "official_url", "source_url", "checked")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _is_url(v):
    return isinstance(v, str) and (v.startswith("https://") or v.startswith("http://"))


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
                self.prefectures[pref_slug] = {"name": pref.get("name") or pref_slug, "stations": stations}

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
        return st, None

    def all_stations(self):
        """(都道府県slug, 駅) の一覧（データの並び順）。"""
        out = []
        for pref_slug, pref in self.prefectures.items():
            for st in pref["stations"]:
                out.append((pref_slug, st))
        return out

    def get(self, slug):
        return self._by_slug.get(slug)

    def genre_stations(self, genre_slug):
        key = GENRES[genre_slug][1]
        return [(p, s) for p, s in self.all_stations() if s[key] is True]

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
<title>{{PAGE_TITLE}}</title>
<meta name="description" content="{{DESCRIPTION}}">
<link rel="canonical" href="{{CANONICAL}}">
<link rel="stylesheet" href="/static/style.css">
{{JSONLD}}</head>
<body>
<header class="site-header"><a class="brand" href="/">{{SITE_NAME}}</a><span class="tagline">{{TAGLINE}}</span></header>
<main>
{{CONTENT}}</main>
<footer class="site-footer">
<p>{{SITE_NAME}}は、道の駅の情報を各駅の公式サイトや道の駅連絡会などの一次情報で確認してまとめています。</p>
<p><a href="/">トップ</a></p>
</footer>
</body>
</html>
"""


def _render(title, description, canonical, content, jsonld=""):
    """{{NAME}} を1回の置換で差し替える。通常の値は html.escape、content/jsonld は組み立て済みHTML。"""
    vals = {"PAGE_TITLE": html.escape(title, quote=True), "DESCRIPTION": html.escape(description, quote=True),
            "CANONICAL": html.escape(canonical, quote=True), "SITE_NAME": html.escape(SITE_NAME),
            "TAGLINE": html.escape(TAGLINE), "CONTENT": content, "JSONLD": jsonld}
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
    """駐車場台数。ある項目だけ出す。"""
    parts = []
    if st["parking_normal"] is not None:
        parts.append('<span class="ms-parking-item"><span class="ms-parking-label">普通車</span>'
                     '<strong class="ms-parking-num">%d台</strong></span>' % st["parking_normal"])
    if st["parking_large"] is not None:
        parts.append('<span class="ms-parking-item"><span class="ms-parking-label">大型車</span>'
                     '<strong class="ms-parking-num">%d台</strong></span>' % st["parking_large"])
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
    if st["address"]:
        out += '<p class="ms-address">%s</p>' % e(st["address"])
    out += _parking_html(st)
    out += _chips(st)
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
    return ('<section class="ms-sources"><h2>出典について</h2>'
            '<p class="fact-checked">住所・営業時間などの情報は、各駅の公式サイトや全国道の駅連絡会などの'
            '一次情報で確認しています（%s確認）。%s</p>'
            '<p class="ms-source-link">出典: <a href="%s" target="_blank" rel="noopener">%s</a></p></section>\n'
            % (e(_fmt_checked(st["checked"])), e(CAUTION), e(st["source_url"], True), e(st["source_url"])))


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
    total = len(STORE.all_stations())
    pref_items = "".join(
        '<li><a href="/%s/">%s<small>%d駅</small></a></li>' % (slug, e(p["name"]), len(p["stations"]))
        for slug, p in STORE.prefectures.items())
    content = (
        '<section class="hero"><h1>%s</h1>'
        '<p class="intro">ドライブの休憩に立ち寄る道の駅について、駐車場の台数やEV充電・温泉などの設備を、'
        '公式の案内をもとにまとめました。現在は%sの%d駅を掲載しています。%s</p></section>\n'
        '<section><h2>都道府県から探す</h2><ul class="ms-nav-chips">%s</ul></section>\n'
        '<section><h2>設備から探す</h2>%s</section>\n'
        '<section class="ms-about"><h2>このサイトの情報について</h2>'
        '<p>掲載している情報は、国土交通省の道の駅登録一覧・全国道の駅連絡会・各駅の公式サイトなどの'
        '一次情報で確認したものだけです。各駅のページに出典と確認日を明記し、確認できなかった項目は載せていません。%s</p></section>\n'
        % (e(SITE_NAME), e("・".join(p["name"] for p in STORE.prefectures.values())), total, e(CAUTION),
           pref_items, _genre_links(), e(CAUTION)))
    return _render(SITE_NAME, DESCRIPTION, SITE_URL + "/", content)


@app.route("/<pref_slug>/")
def prefecture(pref_slug):
    pref = STORE.prefectures.get(pref_slug)
    if pref is None:
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
    pref_name = STORE.prefectures[pref_slug]["name"]
    e = html.escape
    title = "道の駅 %s" % st["name"]
    desc = "%sの道の駅「%s」の基本情報です。住所・電話・営業時間・駐車場台数と、EV充電や温泉などの設備を公式の案内をもとにまとめました。" % (
        pref_name, st["name"])
    canonical = "%s/station/%s/" % (SITE_URL, slug)

    rows = ""
    if st["address"]:
        maps = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(st["address"])
        rows += ('<tr><th>住所</th><td><a href="%s" target="_blank" rel="noopener">📍 %s</a></td></tr>'
                 % (e(maps, True), e(st["address"])))
    if st["tel"]:
        rows += '<tr><th>電話</th><td><a href="tel:%s">📞 %s</a></td></tr>' % (e(st["tel"], True), e(st["tel"]))
    if st["hours"]:
        rows += '<tr><th>営業時間</th><td>%s</td></tr>' % e(st["hours"])
    if st["closed"]:
        rows += '<tr><th>休館日</th><td>%s</td></tr>' % e(st["closed"])
    parking = _parking_html(st)
    if parking:
        rows += '<tr><th>駐車場</th><td>%s</td></tr>' % parking

    content = ('<section class="hero"><h1>%s</h1>\n%s'
               '<p class="intro">%sの道の駅です。%s</p></section>\n'
               % (e(title), _crumbs_nav(("%sの道の駅" % pref_name, "/%s/" % pref_slug), (title, "/station/%s/" % slug)),
                  e(pref_name), e(CAUTION)))
    content += _chips(st)
    if rows:
        content += '<table class="ms-facts">%s</table>\n' % rows
    if st["official_url"]:
        content += ('<p class="ms-official-row"><a class="ms-official" href="%s" target="_blank" rel="noopener">公式サイト</a></p>\n'
                    % e(st["official_url"], True))
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
    urls = [SITE_URL + "/"]
    for pref_slug in STORE.prefectures:
        urls.append("%s/%s/" % (SITE_URL, pref_slug))
    for _p, st in STORE.all_stations():
        urls.append("%s/station/%s/" % (SITE_URL, st["slug"]))
    for slug in STORE.live_genres():
        urls.append("%s/genre/%s/" % (SITE_URL, slug))
    body = "".join("<url><loc>%s</loc></url>" % html.escape(u) for u in urls)
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
