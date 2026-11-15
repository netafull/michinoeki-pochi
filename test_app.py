"""道の駅ポチのテスト。ネットワーク不要。実データ（埼玉県21駅）で確認する。"""
import json
import os
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
        self.assertNotIn("<th>休館日</th>", text)

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


if __name__ == "__main__":
    unittest.main()
