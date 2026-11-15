#!/usr/bin/env python3
"""GitHub Pages 公開用の静的書き出し。

Flask の test_client でサーバーを起動せずに全ルートをレンダリングし、
docs/ に書き出す。docs/ をコミットすると GitHub Pages から公開される。

使い方:
  .venv/bin/python scripts/build_static.py [--out <出力先>]（既定: docs/）

ルート一覧は data/michinoeki.json（STORE）とアプリのジャンル定義から導出する。
どれか1つでも 200 以外が返ったら、docs/ には触れずにエラーで終了する
（不完全な書き出しを残さないため、先に全部レンダリングしてから書き出す）。
"""
import argparse
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import app as appmod  # noqa: E402

CNAME = "michinoeki.netaful.jp"


def collect_routes(store):
    """書き出すルートの一覧。データとジャンル定義から導出する（ハードコードしない）。"""
    routes = ["/"]
    for pref_slug in store.prefectures:
        routes.append("/%s/" % pref_slug)
    for _pref, st in store.all_stations():
        routes.append("/station/%s/" % st["slug"])
    for genre_slug in store.live_genres():
        routes.append("/genre/%s/" % genre_slug)
    routes += ["/sitemap.xml", "/robots.txt"]
    return routes


def dest_path(out_dir, route):
    """ルート -> 出力ファイルパス。ディレクトリ型は index.html に落とす。"""
    rel = route.lstrip("/")
    if rel == "" or rel.endswith("/"):
        rel += "index.html"
    return os.path.join(out_dir, rel)


def render_all(client, routes):
    """全ルートを先にレンダリングする。200 以外があれば (route, status) の一覧を返す。"""
    pages = {}
    errors = []
    for route in routes:
        resp = client.get(route)
        if resp.status_code != 200:
            errors.append((route, resp.status_code))
        else:
            pages[route] = resp.get_data()
    return pages, errors


def build(out_dir):
    store = appmod.STORE
    routes = collect_routes(store)
    client = appmod.app.test_client()
    pages, errors = render_all(client, routes)
    if errors:
        for route, status in errors:
            print("[build_static] エラー: %s -> HTTP %s" % (route, status), file=sys.stderr)
        print("[build_static] 書き出しを中止しました（出力先には触れていません）", file=sys.stderr)
        return 1

    # ここから書き出し。古い生成物は掃除してから書く。
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    for route, data in pages.items():
        path = dest_path(out_dir, route)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    # アプリが配信する静的ファイル（/static/ 配下）をそのままコピーする
    static_src = appmod.app.static_folder
    static_dst = os.path.join(out_dir, "static")
    static_files = []
    for root, _dirs, files in os.walk(static_src):
        for name in files:
            src = os.path.join(root, name)
            rel = os.path.relpath(src, static_src)
            dst = os.path.join(static_dst, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            static_files.append(rel)

    with open(os.path.join(out_dir, "CNAME"), "w", encoding="utf-8") as f:
        f.write(CNAME + "\n")
    open(os.path.join(out_dir, ".nojekyll"), "w").close()

    n_station = sum(1 for r in routes if r.startswith("/station/"))
    n_pref = sum(1 for r in routes if r.count("/") == 2 and not r.startswith(("/station/", "/genre/")))
    n_genre = sum(1 for r in routes if r.startswith("/genre/"))
    print("[build_static] 書き出し完了: %s" % out_dir)
    print("  ページ: %d（トップ1・県%d・駅%d・ジャンル%d・sitemap.xml・robots.txt）"
          % (len(pages), n_pref, n_station, n_genre))
    print("  静的ファイル: %d（%s）" % (len(static_files), "、".join(sorted(static_files))))
    print("  CNAME: %s / .nojekyll: あり" % CNAME)
    return 0


def main():
    parser = argparse.ArgumentParser(description="道の駅ポチの静的書き出し（GitHub Pages用）")
    parser.add_argument("--out", default=os.path.join(BASE_DIR, "docs"),
                        help="出力先ディレクトリ（既定: リポジトリ直下の docs/）")
    args = parser.parse_args()
    return build(args.out)


if __name__ == "__main__":
    sys.exit(main())
