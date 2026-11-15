"""道の駅ポチのテスト。ネットワーク不要。実データ（埼玉県21駅）で確認する。"""
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


def _write_store(tmp, stations):
    path = os.path.join(tmp, "data.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated": "2026-11-15",
                   "prefectures": {"saitama": {"name": "埼玉県", "stations": stations}}}, f, ensure_ascii=False)
    return appmod.StationStore(path)


class LoaderValidation(unittest.TestCase):
    def test_real_data_all_stations_load(self):
        store = appmod.StationStore()
        self.assertEqual(len(store.all_stations()), 21)
        self.assertEqual(list(store.prefectures), ["saitama"])

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

    def test_one_bad_station_does_not_sink_others(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _write_store(tmp, [_station(slug="a"), _station(slug="b", source_url=None),
                                       _station(slug="c")])
            self.assertEqual([s["slug"] for _p, s in store.all_stations()], ["a", "c"])


class Rendering(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = appmod.app.test_client()

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
        self.assertIn("2026年11月15日確認", text)
        self.assertIn("必ず各施設の公式ページで最新の情報をご確認ください", text)
        self.assertIn("BreadcrumbList", text)

    def test_station_page_omits_null_rows(self):
        code, text = self.get("/station/chichibu/")  # closed が null
        self.assertEqual(code, 200)
        self.assertNotIn("<dt>休館日</dt>", text)

    def test_genre_pages(self):
        for slug, count in (("ev", 7), ("onsen", 3), ("dogrun", 2), ("restaurant", 21), ("shop", 21)):
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
                                     "sushi", "cupmen", "hotel", "onsen", "ritou"])
            self.assertNotIn("michinoeki.netaful.jp", nav)
            self.assertNotIn("道の駅ポチ", nav)
            self.assertIn('<a href="https://ritou.netaful.jp/">離島宿ポチ<span class="lbl"> 島の空室を、すぐ探す</span></a>', nav)


class FeatureFilter(unittest.TestCase):
    """県ページの設備フィルタ（バー表示・data属性・スクリプト配信）。絞り込み自体はJS側の責務。"""

    @classmethod
    def setUpClass(cls):
        cls.client = appmod.app.test_client()

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
        self.assertIn('data-feats="ev restaurant shop"', text)               # あらかわ等
        self.assertIn('data-feats="ev onsen_ashiyu restaurant shop"', text)  # みなの
        self.assertIn('data-feats="dogrun restaurant shop"', text)           # はなぞの等

    def test_filter_script_is_served(self):
        r = self.client.get("/static/app.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("data-feats", r.get_data(as_text=True))


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
            self.assertTrue(exists("saitama", "index.html"))
            station_dirs = sorted(os.listdir(os.path.join(out, "station")))
            self.assertEqual(len(station_dirs), 21)
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
