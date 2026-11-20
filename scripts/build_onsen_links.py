#!/usr/bin/env python3
"""道の駅 × 日帰り温泉 対応表（data/onsen_links.json）を作る。

定義（2026-11-20 オーナー決定、モル提案）:
- 距離 = 駅から、その温泉地の日帰り施設のうち一番近いものまでの直線距離（haversine）
- 10km以内・近い順・最大3件（駅→温泉地、温泉地→駅の両方向とも）

入力:
- data/michinoeki.json（駅。lat/lng を持つ駅はそれを使う）
- data/onsen_higaeri_areas.json（温泉宿ポチ /higaeri/ の64温泉地。モルの書き出しスナップショット）
- data/station_coords_geocoded.json（駅座標が無い駅のジオコーディング結果キャッシュ。
  無い駅があれば住所から地理院APIで補ってキャッシュに足す）

出力: data/onsen_links.json
"""
import json, math, re, time, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MAX_KM = 10.0
MAX_ITEMS = 3


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def geocode(address):
    """地理院APIで住所→座標。取れなければ段階的に短くして再試行。"""
    candidates = [address]
    m = re.split(r"\d", address, maxsplit=1)
    if m and m[0] != address:
        candidates.append(m[0])
    m2 = re.match(r"(.+?[市区町村])", address)
    if m2:
        candidates.append(m2.group(1))
    for q in candidates:
        url = "https://msearch.gsi.go.jp/address-search/AddressSearch?q=" + urllib.parse.quote(q)
        req = urllib.request.Request(url, headers={"User-Agent": "michinoeki-pochi-onsen-links/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                data = json.load(res)
        except Exception:
            data = []
        if data:
            lng, lat = data[0]["geometry"]["coordinates"]
            return lat, lng, q
        time.sleep(0.35)
    return None, None, None


def main():
    areas = json.loads((DATA / "onsen_higaeri_areas.json").read_text())["areas"]
    stations_data = json.loads((DATA / "michinoeki.json").read_text())
    cache_path = DATA / "station_coords_geocoded.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    stations = [s for pref in stations_data["prefectures"].values() for s in pref["stations"]]

    need = [s for s in stations if not (s.get("lat") and s.get("lng")) and s["slug"] not in cache]
    for s in need:
        lat, lng, used = geocode(s["address"])
        if lat is not None:
            cache[s["slug"]] = {"lat": lat, "lng": lng, "from": used, "address": s["address"]}
        time.sleep(0.35)
    if need:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1))

    def coords(s):
        if s.get("lat") and s.get("lng"):
            return s["lat"], s["lng"], "data"
        c = cache.get(s["slug"])
        if c:
            return c["lat"], c["lng"], "geocoded"
        return None, None, None

    station_links = {}
    area_links = {}
    for s in stations:
        lat, lng, how = coords(s)
        if lat is None:
            continue
        rows = []
        for a in areas:
            best = None
            for f in a["facilities"]:
                d = haversine_km(lat, lng, f["lat"], f["lng"])
                if best is None or d < best[0]:
                    best = (d, f["name"])
            if best and best[0] <= MAX_KM:
                rows.append({
                    "area_slug": a["slug"],
                    "area_name": a["name"],
                    "url": a["url"],
                    "distance_km": round(best[0], 1),
                    "nearest_facility": best[1],
                })
        rows.sort(key=lambda r: r["distance_km"])
        rows = rows[:MAX_ITEMS]
        if rows:
            station_links[s["slug"]] = {
                "station_name": s["name"],
                "url": f"https://michinoeki.netaful.jp/station/{s['slug']}/",
                "coord_source": how,
                "areas": rows,
            }
            for r in rows:
                area_links.setdefault(r["area_slug"], []).append({
                    "station_slug": s["slug"],
                    "station_name": s["name"],
                    "url": f"https://michinoeki.netaful.jp/station/{s['slug']}/",
                    "distance_km": r["distance_km"],
                    "nearest_facility": r["nearest_facility"],
                })

    area_by_slug = {a["slug"]: a for a in areas}
    areas_out = {}
    for slug, rows in area_links.items():
        rows.sort(key=lambda r: r["distance_km"])
        a = area_by_slug[slug]
        areas_out[slug] = {"area_name": a["name"], "url": a["url"], "stations": rows[:MAX_ITEMS]}

    out = {
        "generated": "2026-11-20",
        "definition": "駅から温泉地の日帰り施設のうち最寄りのものまでの直線距離が10km以内、近い順に最大3件",
        "max_km": MAX_KM,
        "max_items": MAX_ITEMS,
        "stations": station_links,
        "areas": areas_out,
    }
    (DATA / "onsen_links.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"stations with links: {len(station_links)}, areas with links: {len(areas_out)} / {len(areas)}")


if __name__ == "__main__":
    main()
