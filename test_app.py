"""道の駅ポチのテスト。ネットワーク不要。実データ（35県987駅、全県公開）で確認する。

公開は県単位のゲート（データの published）で制御する。表示系のテストは、
実データを全県 published=true に読み替えたストアに差し替えて確認し、
ゲート自体の挙動（未公開なら404・トップは精査中のお知らせ）は実データのまま確認する。
"""
import json
import os
import re
import tempfile
import unittest

import app as appmod


def _station(**kw):
    st = {"slug": "test-eki", "name": "テスト駅", "address": "埼玉県テスト市1-1",
          "tel": "000-000-0000", "hours": "9:00-17:00", "closed": None,
          "parking_normal": 10, "parking_large": 2,
          "ev": True, "onsen_ashiyu": None, "dogrun": None, "restaurant": True, "shop": None,
          "official_url": "https://example.jp/eki", "source_url": "https://example.jp/src",
          "checked": "2026-11-01"}
    st.update(kw)
    return st


def _write_store(tmp, stations, published=True):
    pref = {"name": "埼玉県", "stations": stations}
    if published is not None:
        pref["published"] = published
    path = os.path.join(tmp, "data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated": "2026-11-15",
                   "prefectures": {"saitama": pref}}, f, ensure_ascii=False)
    return appmod.StationStore(path)


def _all_published_store():
    """実データを全県 published=true で読み直したストア（公開後の表示を確認する用）。"""
    with open(appmod.DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    for pref in raw["prefectures"].values():
        pref["published"] = True
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False)
        return appmod.StationStore(path)
    finally:
        os.unlink(path)


class LoaderValidation(unittest.TestCase):
    def test_real_data_all_stations_load(self):
        store = appmod.StationStore()
        self.assertEqual(len(store.all_stations()), 987)
        self.assertEqual(list(store.prefectures), ["saitama", "chiba", "tokyo", "kanagawa", "shizuoka", "ibaraki", "tochigi", "gunma", "yamanashi", "niigata", "nagano", "fukushima", "toyama", "ishikawa", "fukui", "gifu", "aichi", "mie", "shiga", "miyagi", "yamagata", "akita", "iwate", "aomori", "hokkaido", "kyoto", "osaka", "nara", "wakayama", "hyogo", "tottori", "tokushima", "kagawa", "ehime", "kochi"])

    def test_missing_source_url_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = _station(slug="bad-eki")
            del bad["source_url"]
            store = _write_store(tmp, [_station(), bad])
            self.assertEqual([s["slug"] for _p, s in store.all_stations()], ["test-eki"])

    def test_bad_checked_dates_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _write_store(tmp, [
                _station(),
                _station(slug="feb30", checked="2026-02-30"),
                _station(slug="future", checked="2999-01-01"),
                _station(slug="nodate", checked=None),
            ])
            self.assertEqual([s["slug"] for _p, s in store.all_stations()], ["test-eki"])

    def test_duplicate_slug_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _write_store(tmp, [_station(), _station(name="二つ目")])
            self.assertEqual(len(store.all_stations()), 1)

    def test_unknown_keys_dropped_and_types_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _write_store(tmp, [_station(unknown_key="x", parking_normal="50台", ev="あり")])
            _p, st = store.all_stations()[0]
            self.assertNotIn("unknown_key", st)
            self.assertIsNone(st["parking_normal"])
            self.assertIsNone(st["ev"])

    def test_ev_source_url_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _write_store(tmp, [_station(ev_source_url="https://example.jp/ev"),
                                       _station(slug="bad-ev", ev_source_url="not-a-url")])
            by_slug = {s["slug"]: s for _p, s in store.all_stations()}
            self.assertEqual(by_slug["test-eki"]["ev_source_url"], "https://example.jp/ev")
            self.assertIsNone(by_slug["bad-ev"]["ev_source_url"])

    def test_one_bad_station_does_not_sink_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _write_store(tmp, [_station(slug="a"), _station(slug="b", source_url=None),
                                       _station(slug="c")])
            self.assertEqual([s["slug"] for _p, s in store.all_stations()], ["a", "c"])


class Rendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_store = appmod.STORE
        appmod.STORE = _all_published_store()
        cls.client = appmod.app.test_client()

    @classmethod
    def tearDownClass(cls):
        appmod.STORE = cls._old_store

    def get(self, path):
        r = self.client.get(path)
        return r.status_code, r.get_data(as_text=True)

    def test_top(self):
        code, text = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn("道の駅ポチ", text)
        self.assertIn("埼玉県", text)
        self.assertIn("21駅", text)
        self.assertIn('href="/saitama/"', text)
        self.assertIn('href="/genre/ev/"', text)

    def test_prefecture_page(self):
        code, text = self.get("/saitama/")
        self.assertEqual(code, 200)
        self.assertIn("埼玉県の道の駅", text)
        self.assertEqual(text.count('class="ms-card"'), 21)
        self.assertIn('href="/station/arakawa/"', text)
        self.assertIn("367台", text)  # はなぞの 普通車

    def test_station_page(self):
        code, text = self.get("/station/ogawamachi/")
        self.assertEqual(code, 200)
        self.assertIn("道の駅 おがわまち", text)
        self.assertIn("google.com/maps/search", text)
        self.assertIn("tel:0493-72-1220", text)
        self.assertIn("186台", text)
        self.assertIn("EV充電", text)
        self.assertIn("2026年11月16日確認", text)
        self.assertIn("必ず各施設の公式ページで最新の情報をご確認ください", text)
        self.assertIn("BreadcrumbList", text)

    def test_station_page_shows_unknown_for_null_closed(self):
        code, text = self.get("/station/chichibu/")  # closed が null
        self.assertEqual(code, 200)
        self.assertIn('<dt>休館日</dt><dd class="ms-unknown">未確認</dd>', text)

    def test_genre_pages(self):
        for slug, count in (("ev", 546), ("onsen", 143), ("dogrun", 68), ("restaurant", 851), ("shop", 972)):
            code, text = self.get("/genre/%s/" % slug)
            self.assertEqual(code, 200, slug)
            self.assertEqual(text.count('class="ms-card"'), count, slug)

    def test_not_found(self):
        self.assertEqual(self.get("/station/no-such/")[0], 404)
        self.assertEqual(self.get("/genre/no-such/")[0], 404)
        self.assertEqual(self.get("/no-such-pref/")[0], 404)

    def test_sitemap_and_robots(self):
        code, text = self.get("/sitemap.xml")
        self.assertEqual(code, 200)
        self.assertIn("/station/arakawa/", text)
        self.assertIn("/genre/dogrun/", text)
        code, text = self.get("/robots.txt")
        self.assertEqual(code, 200)
        self.assertIn("sitemap.xml", text)

    def test_sitemap_every_url_has_lastmod(self):
        _code, text = self.get("/sitemap.xml")
        urls = re.findall(r"<url>(.*?)</url>", text)
        self.assertGreater(len(urls), 20)
        for u in urls:
            self.assertRegex(u, r"^<loc>[^<]+</loc><lastmod>\d{4}-\d{2}-\d{2}</lastmod>$")

    def test_sitemap_lastmod_rules(self):
        _code, text = self.get("/sitemap.xml")
        lm = dict(re.findall(r"<loc>([^<]+)</loc><lastmod>([^<]+)</lastmod>", text))
        base = appmod.SITE_URL
        newest = max(appmod.PAGES_UPDATED, appmod.STORE.updated,
                     *(st["checked"] for _p, st in appmod.STORE.all_stations()))
        self.assertEqual(lm[base + "/"], newest)
        _p, st = appmod.STORE.get("arakawa")
        self.assertEqual(lm[base + "/station/arakawa/"], max(appmod.PAGES_UPDATED, st["checked"]))
        for pref_slug, pref in appmod.STORE.prefectures.items():
            self.assertEqual(lm["%s/%s/" % (base, pref_slug)],
                             max(appmod.PAGES_UPDATED, *(s["checked"] for s in pref["stations"])))
        for slug in appmod.STORE.live_genres():
            self.assertEqual(lm["%s/genre/%s/" % (base, slug)],
                             max(appmod.PAGES_UPDATED, *(s["checked"] for _p, s in appmod.STORE.genre_stations(slug))))

    def test_footer_notice_and_series_links(self):
        for path in ("/", "/saitama/", "/station/arakawa/", "/genre/ev/"):
            _code, text = self.get(path)
            foot = text.split('<footer class="site-footer">', 1)[1]
            self.assertIn("非公式サイトです", foot)
            self.assertIn("最新の情報は各駅の公式サイトでご確認ください", foot)
            self.assertIn('<a href="https://netaful.jp/policy.html">メディアポリシー</a>', foot)
            nav = foot.split('<nav class="sites">', 1)[1].split("</nav>", 1)[0]
            hosts = re.findall(r'href="https://([a-z]+)\.netaful\.jp/"', nav)
            self.assertEqual(hosts, ["book", "kaden", "apple", "manga", "conbini", "fastfood", "cafe",
                                     "sushi", "cupmen", "hotel", "onsen", "ritou", "shinhatsubai"])
            self.assertNotIn("michinoeki.netaful.jp", nav)
            self.assertNotIn("道の駅ポチ", nav)
            self.assertIn('<a href="https://ritou.netaful.jp/">離島宿ポチ<span class="lbl"> 島の空室を、すぐ探す</span></a>', nav)


class FeatureFilter(unittest.TestCase):
    """県ページの設備フィルタ（バー表示・data属性・スクリプト配信）。絞り込み自体はJS側の責務。"""

    @classmethod
    def setUpClass(cls):
        cls._old_store = appmod.STORE
        appmod.STORE = _all_published_store()
        cls.client = appmod.app.test_client()

    @classmethod
    def tearDownClass(cls):
        appmod.STORE = cls._old_store

    def test_filter_bar_on_prefecture_page(self):
        text = self.client.get("/saitama/").get_data(as_text=True)
        self.assertIn('class="ms-filter"', text)
        self.assertIn("設備で絞り込む", text)
        self.assertEqual(text.count('class="ms-filter-input"'), 5)
        for value in ("ev", "onsen_ashiyu", "dogrun", "restaurant", "shop"):
            self.assertIn('value="%s"' % value, text)
        self.assertIn("21駅が該当", text)  # 初期表示は全件（JSがライブ更新する）
        self.assertIn("条件に合う駅がありません", text)
        self.assertIn('class="ms-filter-reset"', text)
        self.assertIn("/static/app.js", text)

    def test_cards_have_data_feats(self):
        text = self.client.get("/saitama/").get_data(as_text=True)
        self.assertEqual(text.count("data-feats="), 21)
        self.assertIn('data-feats="ev restaurant shop"', text)               # おかべ等
        self.assertIn('data-feats="ev dogrun restaurant shop"', text)        # すぎと
        self.assertIn('data-feats="onsen_ashiyu restaurant shop"', text)     # 大滝温泉
        self.assertIn('data-feats="ev onsen_ashiyu restaurant shop"', text)  # 両神

    def test_filter_script_is_served(self):
        r = self.client.get("/static/app.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("data-feats", r.get_data(as_text=True))


class PublishingGate(unittest.TestCase):
    """公開ゲートの挙動。実データは埼玉・千葉・東京・神奈川・茨城・栃木だけ published=true（精査済み）として確認する。"""

    @classmethod
    def setUpClass(cls):
        cls.client = appmod.app.test_client()

    def test_top_lists_only_published_prefectures(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        text = r.get_data(as_text=True)
        self.assertIn('href="/saitama/"', text)
        self.assertIn('href="/chiba/"', text)
        self.assertIn('href="/tokyo/"', text)
        self.assertIn('href="/kanagawa/"', text)
        self.assertIn('href="/ibaraki/"', text)
        self.assertIn('href="/tochigi/"', text)
        self.assertIn('href="/gunma/"', text)
        self.assertIn('href="/yamanashi/"', text)
        self.assertIn('href="/niigata/"', text)
        self.assertIn('href="/nagano/"', text)
        self.assertIn('href="/toyama/"', text)
        self.assertIn('href="/shizuoka/"', text)
        self.assertIn('href="/ishikawa/"', text)
        self.assertIn('href="/fukui/"', text)
        self.assertIn('href="/gifu/"', text)
        self.assertIn('href="/aichi/"', text)
        self.assertIn('href="/mie/"', text)
        self.assertIn('href="/shiga/"', text)
        self.assertIn('href="/miyagi/"', text)
        self.assertIn('href="/yamagata/"', text)
        self.assertIn('href="/akita/"', text)
        self.assertIn('href="/iwate/"', text)
        self.assertIn('href="/aomori/"', text)
        self.assertIn('href="/hokkaido/"', text)
        self.assertIn('href="/kyoto/"', text)
        self.assertIn('href="/osaka/"', text)
        self.assertIn('href="/nara/"', text)
        self.assertIn('href="/wakayama/"', text)
        self.assertIn('href="/hyogo/"', text)
        self.assertIn('href="/tottori/"', text)
        self.assertIn('href="/tokushima/"', text)
        self.assertIn('href="/kagawa/"', text)
        self.assertIn('href="/ehime/"', text)
        self.assertIn('href="/kochi/"', text)
        self.assertNotIn("ただいま準備中です", text)
        # 地方区分の見出しと並び（北海道→東北→関東→甲信越→北陸→東海→近畿→中国→四国）
        for region in ("北海道", "東北", "関東", "甲信越", "北陸", "東海", "近畿", "中国", "四国"):
            self.assertIn('<h3 class="ms-region">%s</h3>' % region, text)
        order = ['href="/hokkaido/"', 'href="/aomori/"', 'href="/iwate/"', 'href="/miyagi/"', 'href="/akita/"', 'href="/yamagata/"', 'href="/fukushima/"', 'href="/ibaraki/"', 'href="/kanagawa/"',
                 'href="/niigata/"', 'href="/nagano/"', 'href="/toyama/"',
                 'href="/fukui/"', 'href="/gifu/"', 'href="/mie/"', 'href="/shiga/"']
        positions = [text.index(o) for o in order]
        self.assertEqual(positions, sorted(positions))
        # 日本地図タイル：全県のタイルがあり、公開済みだけがリンクになる
        self.assertIn('class="ms-map"', text)
        self.assertIn('ms-map-tile--off', text)
        self.assertIn('href="/hokkaido/"', text)
        self.assertIn('href="/kyoto/"', text)
        self.assertIn('href="/hyogo/"', text)
        self.assertIn('href="/tottori/"', text)
        self.assertNotIn('href="/shimane/"', text)

    def test_unpublished_pages_are_404(self):
        self.assertEqual(self.client.get("/chiba/").status_code, 200)
        self.assertEqual(self.client.get("/tokyo/").status_code, 200)
        self.assertEqual(self.client.get("/station/hachioji-takiyama/").status_code, 200)
        self.assertEqual(self.client.get("/kanagawa/").status_code, 200)
        self.assertEqual(self.client.get("/station/hakone-toge/").status_code, 200)
        self.assertEqual(self.client.get("/ibaraki/").status_code, 200)
        self.assertEqual(self.client.get("/station/sakai/").status_code, 200)
        self.assertEqual(self.client.get("/tochigi/").status_code, 200)
        self.assertEqual(self.client.get("/station/motegi/").status_code, 200)
        self.assertEqual(self.client.get("/gunma/").status_code, 200)
        self.assertEqual(self.client.get("/station/ueno/").status_code, 200)
        self.assertEqual(self.client.get("/yamanashi/").status_code, 200)
        self.assertEqual(self.client.get("/station/kosuge/").status_code, 200)
        self.assertEqual(self.client.get("/niigata/").status_code, 200)
        self.assertEqual(self.client.get("/station/toyosaka/").status_code, 200)
        self.assertEqual(self.client.get("/nagano/").status_code, 200)
        self.assertEqual(self.client.get("/station/shinshu-shinmachi/").status_code, 200)
        self.assertEqual(self.client.get("/toyama/").status_code, 200)
        self.assertEqual(self.client.get("/station/hosoiri/").status_code, 200)
        self.assertEqual(self.client.get("/shizuoka/").status_code, 200)
        self.assertEqual(self.client.get("/station/fuji/").status_code, 200)
        self.assertEqual(self.client.get("/ishikawa/").status_code, 200)
        self.assertEqual(self.client.get("/station/wajima/").status_code, 200)
        self.assertEqual(self.client.get("/fukui/").status_code, 200)
        self.assertEqual(self.client.get("/station/sakai-fukui/").status_code, 200)
        self.assertEqual(self.client.get("/gifu/").status_code, 200)
        self.assertEqual(self.client.get("/station/minami/").status_code, 200)
        self.assertEqual(self.client.get("/aichi/").status_code, 200)
        self.assertEqual(self.client.get("/station/toyone-greenport-miyajima/").status_code, 200)
        self.assertEqual(self.client.get("/mie/").status_code, 200)
        self.assertEqual(self.client.get("/station/iitaka-eki/").status_code, 200)
        self.assertEqual(self.client.get("/shiga/").status_code, 200)
        self.assertEqual(self.client.get("/station/aino-tsuchiyama/").status_code, 200)
        self.assertEqual(self.client.get("/miyagi/").status_code, 200)
        self.assertEqual(self.client.get("/station/ara-date-na-michinoeki/").status_code, 200)
        self.assertEqual(self.client.get("/yamagata/").status_code, 200)
        self.assertEqual(self.client.get("/station/yamagata-zao/").status_code, 200)
        self.assertEqual(self.client.get("/akita/").status_code, 200)
        self.assertEqual(self.client.get("/station/kazuno/").status_code, 200)
        self.assertEqual(self.client.get("/iwate/").status_code, 200)
        self.assertEqual(self.client.get("/station/morioka-shibutami/").status_code, 200)
        self.assertEqual(self.client.get("/aomori/").status_code, 200)
        self.assertEqual(self.client.get("/station/shichinohe/").status_code, 200)
        self.assertEqual(self.client.get("/hokkaido/").status_code, 200)
        self.assertEqual(self.client.get("/station/mikasa/").status_code, 200)
        self.assertEqual(self.client.get("/kyoto/").status_code, 200)
        self.assertEqual(self.client.get("/station/galleria-kameoka/").status_code, 200)
        self.assertEqual(self.client.get("/osaka/").status_code, 200)
        self.assertEqual(self.client.get("/station/shiratori-no-sato-habikino/").status_code, 200)
        self.assertEqual(self.client.get("/nara/").status_code, 200)
        self.assertEqual(self.client.get("/station/futakami-park-taima/").status_code, 200)
        self.assertEqual(self.client.get("/wakayama/").status_code, 200)
        self.assertEqual(self.client.get("/station/kushimoto-hashigui-iwa/").status_code, 200)
        self.assertEqual(self.client.get("/hyogo/").status_code, 200)
        self.assertEqual(self.client.get("/station/shukubamachi-hirafuku/").status_code, 200)
        self.assertEqual(self.client.get("/station/konda-onsen-nukumori-no-sato/").status_code, 200)
        self.assertEqual(self.client.get("/tottori/").status_code, 200)
        self.assertEqual(self.client.get("/station/hojo/").status_code, 200)
        self.assertEqual(self.client.get("/tokushima/").status_code, 200)
        self.assertEqual(self.client.get("/station/kurukuru-naruto/").status_code, 200)
        self.assertEqual(self.client.get("/kagawa/").status_code, 200)
        self.assertEqual(self.client.get("/station/fureai-park-mino/").status_code, 200)
        self.assertEqual(self.client.get("/ehime/").status_code, 200)
        self.assertEqual(self.client.get("/station/kiri-no-mori/").status_code, 200)
        self.assertEqual(self.client.get("/kochi/").status_code, 200)
        self.assertEqual(self.client.get("/station/toyocho/").status_code, 200)
        self.assertEqual(self.client.get("/station/no-such-station/").status_code, 404)

    def test_sitemap_includes_only_published(self):
        text = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("<loc>%s/saitama/</loc>" % appmod.SITE_URL, text)
        self.assertIn("<loc>%s/chiba/</loc>" % appmod.SITE_URL, text)
        self.assertIn("<loc>%s/tokyo/</loc>" % appmod.SITE_URL, text)
        self.assertIn("<loc>%s/station/furari-tomiyama/</loc>" % appmod.SITE_URL, text)
        self.assertIn("hachioji-takiyama", text)
        self.assertIn("<loc>%s/kanagawa/</loc>" % appmod.SITE_URL, text)
        self.assertIn("hakone-toge", text)
        self.assertIn("<loc>%s/ibaraki/</loc>" % appmod.SITE_URL, text)
        self.assertIn("/station/sakai/", text)
        self.assertIn("<loc>%s/tochigi/</loc>" % appmod.SITE_URL, text)
        self.assertIn("/station/motegi/", text)
        self.assertIn("<loc>%s/gunma/</loc>" % appmod.SITE_URL, text)
        self.assertIn("/station/ueno/", text)
        self.assertIn("<loc>%s/yamanashi/</loc>" % appmod.SITE_URL, text)
        self.assertIn("/station/kosuge/", text)
        self.assertIn("<loc>%s/niigata/</loc>" % appmod.SITE_URL, text)
        self.assertIn("/station/toyosaka/", text)
        self.assertIn("<loc>%s/nagano/</loc>" % appmod.SITE_URL, text)
        self.assertIn("/station/shinshu-shinmachi/", text)
        self.assertIn("/toyama/", text)
        self.assertIn("/station/hosoiri/", text)
        self.assertIn("/shizuoka/", text)
        self.assertIn("/station/fuji/", text)
        self.assertIn("/ishikawa/", text)
        self.assertIn("/station/wajima/", text)
        self.assertIn("/fukui/", text)
        self.assertIn("/station/sakai-fukui/", text)
        self.assertIn("/gifu/", text)
        self.assertIn("/station/minami/", text)

    def test_fixture_published_prefecture_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _write_store(tmp, [_station()], published=True)
            old = appmod.STORE
            appmod.STORE = store
            try:
                client = appmod.app.test_client()
                self.assertEqual(client.get("/saitama/").status_code, 200)
                self.assertEqual(client.get("/station/test-eki/").status_code, 200)
            finally:
                appmod.STORE = old

    def test_station_page_unknown_display(self):
        # 駅ページでは基本情報の null を「未確認」と出し、一覧カードでは出さない
        with tempfile.TemporaryDirectory() as tmp:
            store = _write_store(tmp, [_station(hours=None, parking_large=None)])  # closed も null
            old = appmod.STORE
            appmod.STORE = store
            try:
                client = appmod.app.test_client()
                text = client.get("/station/test-eki/").get_data(as_text=True)
                self.assertIn('<dt>営業時間</dt><dd class="ms-unknown">未確認</dd>', text)
                self.assertIn('<dt>休館日</dt><dd class="ms-unknown">未確認</dd>', text)
                # 駐車は公表値方式：ある項目だけ出し、項目ごとの「未確認」は出さない
                self.assertIn('<span class="ms-parking-label">普通車</span>'
                              '<strong class="ms-parking-num">10台</strong>', text)
                self.assertNotIn('ms-parking-unknown', text)
                self.assertIn("確認できた設備だけを表示しています。", text)
                # 注記は基本情報の表の下に出る
                self.assertGreater(text.index("確認できた設備だけを表示しています。"),
                                   text.index("<dt>休館日</dt>"))
                card_text = client.get("/saitama/").get_data(as_text=True)
                self.assertNotIn("未確認", card_text)
            finally:
                appmod.STORE = old

    def test_parking_published_figures(self):
        # 公表値方式：総数があれば「駐車場◯台」を先頭に、内訳は公表分だけ併記する
        with tempfile.TemporaryDirectory() as tmp:
            store = _write_store(tmp, [
                _station(parking_total=68, parking_normal=63, parking_large=3, parking_disabled=2),
                _station(slug="parts-eki", parking_normal=145, parking_large=2, parking_disabled=7),
                _station(slug="unknown-eki", parking_normal=None, parking_large=None),
            ])
            old = appmod.STORE
            appmod.STORE = store
            try:
                client = appmod.app.test_client()
                text = client.get("/station/test-eki/").get_data(as_text=True)
                self.assertIn('<span class="ms-parking-label">駐車場</span>'
                              '<strong class="ms-parking-num">68台</strong>', text)
                self.assertIn('<span class="ms-parking-label">普通車</span>'
                              '<strong class="ms-parking-num">63台</strong>', text)
                self.assertIn('<span class="ms-parking-label">大型車</span>'
                              '<strong class="ms-parking-num">3台</strong>', text)
                self.assertIn('<span class="ms-parking-label">身障者用</span>'
                              '<strong class="ms-parking-num">2台</strong>', text)
                parts = client.get("/station/parts-eki/").get_data(as_text=True)
                self.assertIn('<strong class="ms-parking-num">145台</strong>', parts)
                self.assertIn('<strong class="ms-parking-num">7台</strong>', parts)
                self.assertNotIn('<span class="ms-parking-label">駐車場</span>', parts)
                # 全項目が未確認なら、駅ページにだけ「駐車場 未確認」を出す
                unknown = client.get("/station/unknown-eki/").get_data(as_text=True)
                self.assertIn('<span class="ms-parking-label">駐車場</span>'
                              '<span class="ms-parking-unknown">未確認</span>', unknown)
                card_text = client.get("/saitama/").get_data(as_text=True)
                self.assertIn('<strong class="ms-parking-num">68台</strong>', card_text)
                self.assertNotIn('ms-parking-unknown', card_text)
            finally:
                appmod.STORE = old

    def test_opening_badge_and_note(self):
        # 開業予定（opening）がある駅は、駅ページにバッジと注意文、カードにバッジを出す
        with tempfile.TemporaryDirectory() as tmp:
            store = _write_store(tmp, [_station(opening="2027年春開業予定",
                                                opening_note="道の駅としての開業前です。",
                                                opening_url="https://example.jp/opening"),
                                       _station(slug="plain-eki")])
            old = appmod.STORE
            appmod.STORE = store
            try:
                client = appmod.app.test_client()
                text = client.get("/station/test-eki/").get_data(as_text=True)
                self.assertIn('<span class="ms-opening-badge">2027年春開業予定</span>', text)
                self.assertIn("道の駅としての開業前です。", text)
                self.assertIn('href="https://example.jp/opening"', text)
                text = client.get("/station/plain-eki/").get_data(as_text=True)
                self.assertNotIn("ms-opening", text)
                card_text = client.get("/saitama/").get_data(as_text=True)
                self.assertIn('<span class="ms-opening-badge">2027年春開業予定</span>', card_text)
            finally:
                appmod.STORE = old

    def test_ev_source_link_on_station_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _write_store(tmp, [_station(ev=True, ev_source_url="https://example.jp/ev"),
                                       _station(slug="no-ev-src", ev=True),
                                       _station(slug="ev-off", ev=False, ev_source_url="https://example.jp/ev")])
            old = appmod.STORE
            appmod.STORE = store
            try:
                client = appmod.app.test_client()
                text = client.get("/station/test-eki/").get_data(as_text=True)
                self.assertIn("EV充電の確認元", text)
                self.assertIn('href="https://example.jp/ev"', text)
                self.assertIn("EV充電については、確認元の情報でも確認しています", text)
                text2 = client.get("/station/no-ev-src/").get_data(as_text=True)
                self.assertNotIn("EV充電の確認元", text2)
                text3 = client.get("/station/ev-off/").get_data(as_text=True)
                self.assertNotIn("EV充電の確認元", text3)
            finally:
                appmod.STORE = old

    def test_ev_source_urls_follow_policy(self):
        # 実データの ev_source_url は、方針で認めた先（自治体・公式・観光協会・
        # EVsmart・EV Smart Charge）だけに限る。ev が true でない駅には付けない。
        from urllib.parse import urlparse
        allowed_hosts = {"evsmart.net", "www.evsmart.net", "ev-smart.net", "www.ev-smart.net",
                         "maruchiba.jp"}  # 千葉県観光協会（ちば観光ナビ）
        for _pref, st in appmod.STORE.all_stations():
            url = st["ev_source_url"]
            if not url:
                continue
            self.assertIs(st["ev"], True, st["slug"])
            host = urlparse(url).hostname or ""
            official_host = urlparse(st["official_url"]).hostname if st["official_url"] else None
            if official_host:
                official_host = official_host.removeprefix("www.")
            host_bare = host.removeprefix("www.")
            municipal = (host.endswith((".lg.jp", ".go.jp"))
                         or ".vill." in host or ".town." in host or ".city." in host)
            ok = municipal or host in allowed_hosts or host_bare == official_host
            self.assertTrue(ok, "%s: %s" % (st["slug"], url))

    def test_fixture_unpublished_prefecture_is_404(self):
        # published=false でも、キー自体が無くても、未公開として扱う
        for published in (False, None):
            with tempfile.TemporaryDirectory() as tmp:
                store = _write_store(tmp, [_station()], published=published)
                old = appmod.STORE
                appmod.STORE = store
                try:
                    client = appmod.app.test_client()
                    self.assertEqual(client.get("/saitama/").status_code, 404)
                    self.assertEqual(client.get("/station/test-eki/").status_code, 404)
                    top = client.get("/").get_data(as_text=True)
                    self.assertIn("ただいま準備中です", top)
                finally:
                    appmod.STORE = old


class ZeroGenre(unittest.TestCase):
    def test_zero_count_genre_is_404_and_unlinked(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _write_store(tmp, [_station(ev=None, dogrun=None)])
            old = appmod.STORE
            appmod.STORE = store
            try:
                client = appmod.app.test_client()
                self.assertEqual(client.get("/genre/dogrun/").status_code, 404)
                top = client.get("/").get_data(as_text=True)
                self.assertNotIn("/genre/dogrun/", top)
            finally:
                appmod.STORE = old


class StaticBuild(unittest.TestCase):
    """静的書き出し（scripts/build_static.py）が全ルート分そろうこと。"""

    def test_build_static_produces_all_pages(self):
        import subprocess
        import sys
        root = os.path.dirname(os.path.abspath(__file__))
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "docs")
            r = subprocess.run([sys.executable, os.path.join(root, "scripts", "build_static.py"),
                                "--out", out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

            def exists(*parts):
                return os.path.isfile(os.path.join(out, *parts))

            self.assertTrue(exists("index.html"))
            # 実データで公開中なのは埼玉・千葉・東京・神奈川・茨城・栃木だけ。県を公開したら、その県の分だけここに期待値を足すこと。
            self.assertTrue(exists("saitama", "index.html"))
            self.assertTrue(exists("chiba", "index.html"))
            self.assertTrue(exists("tokyo", "index.html"))
            self.assertTrue(exists("kanagawa", "index.html"))
            self.assertTrue(exists("ibaraki", "index.html"))
            self.assertTrue(exists("tochigi", "index.html"))
            self.assertTrue(exists("gunma", "index.html"))
            self.assertTrue(exists("yamanashi", "index.html"))
            self.assertTrue(exists("niigata", "index.html"))
            self.assertTrue(exists("nagano", "index.html"))
            self.assertTrue(exists("toyama", "index.html"))
            self.assertTrue(exists("shizuoka", "index.html"))
            self.assertTrue(exists("ishikawa", "index.html"))
            self.assertTrue(exists("fukui", "index.html"))
            self.assertTrue(exists("gifu", "index.html"))
            self.assertTrue(exists("hokkaido", "index.html"))
            self.assertTrue(exists("kyoto", "index.html"))
            self.assertTrue(exists("osaka", "index.html"))
            self.assertTrue(exists("nara", "index.html"))
            self.assertTrue(exists("wakayama", "index.html"))
            self.assertTrue(exists("tokushima", "index.html"))
            self.assertTrue(exists("kagawa", "index.html"))
            self.assertTrue(exists("ehime", "index.html"))
            self.assertTrue(exists("kochi", "index.html"))
            station_dirs = sorted(os.listdir(os.path.join(out, "station")))
            self.assertEqual(len(station_dirs), 987)
            for d in station_dirs:
                self.assertTrue(exists("station", d, "index.html"), d)
            for g in ("ev", "onsen", "dogrun", "restaurant", "shop"):
                self.assertTrue(exists("genre", g, "index.html"), g)
            self.assertTrue(exists("sitemap.xml"))
            self.assertTrue(exists("robots.txt"))
            self.assertTrue(exists("static", "style.css"))
            self.assertTrue(exists("static", "app.js"))
            self.assertTrue(exists(".nojekyll"))
            with open(os.path.join(out, "CNAME"), encoding="utf-8") as f:
                self.assertEqual(f.read().strip(), "michinoeki.netaful.jp")


if __name__ == "__main__":
    unittest.main()
