#!/usr/bin/env python3
"""给「手动补录」的游戏（data/extra-games.json）补 封面 / M 站分 / 发售日 / 类型。

这些游戏不在任何平台接口里（任天堂老游戏、下架作品），所以走两条公开源：
  · 封面：维基百科 REST page/summary 的 originalimage
  · M 站分 / 发售日 / 类型：Metacritic 前端搜索接口（与 meta_score.py 同一套）

结果按 id 写进 enrichment.json（和 sync 抓来的记录同构），所以插件那边不用改逻辑：
merged 时会用 en[id] 补字段，明细表里的手动修改（manual.json）依然优先级最高。

用法：
    python3 tools/enrich_extra.py                       # 只补缺的
    python3 tools/enrich_extra.py --force               # 全部重抓
    python3 tools/enrich_extra.py --only extra-switch-odyssey
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from meta_score import genres_to_cn, norm, pick, search  # noqa: E402

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36")

DEFAULT_DIR = os.path.expanduser("~/Documents/deepseek-harness/work/游戏档案")


def jget(url: str, tries: int = 3, sleep: float = 2.0):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                return None
            time.sleep(sleep * (i + 2))
    return None


WIKI_FIX = {
    "Super Mario Odyssey": "Super Mario Odyssey",
    "Pokémon: Let's Go, Pikachu! / Eevee!": "Pokémon: Let's Go, Pikachu! and Let's Go, Eevee!",
    "Luigi's Mansion 3": "Luigi's Mansion 3",
    "Mario Tennis Aces": "Mario Tennis Aces",
}


def wiki_cover(name: str):
    page = WIKI_FIX.get(name, name)
    d = jget("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(page.replace(" ", "_")))
    src = ((d or {}).get("originalimage") or {}).get("source") or ""
    src = src.split("?")[0]
    # 竖版盒图（高 > 宽）用 contain，横版头图用 cover
    return src or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=DEFAULT_DIR, help="数据目录")
    ap.add_argument("--only", default="", help="只处理这些 id（逗号分隔）")
    ap.add_argument("--force", action="store_true", help="已补过的也重抓")
    ap.add_argument("--sleep", type=float, default=1.2)
    args = ap.parse_args()

    D = os.path.expanduser(args.dir)
    extra_p = os.path.join(D, "extra-games.json")
    enr_p = os.path.join(D, "enrichment.json")
    extra = json.load(open(extra_p, encoding="utf-8"))
    enrich = json.load(open(enr_p, encoding="utf-8")) if os.path.exists(enr_p) else {}

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    games = [g for g in extra.get("games", []) if g.get("id") and g.get("name")]
    if only:
        games = [g for g in games if g["id"] in only]

    print(f"[补录补全] 待处理 {len(games)} 款")
    changed = 0
    for i, g in enumerate(games, 1):
        gid, name, cn = g["id"], g["name"], g.get("cn") or ""
        row = enrich.get(gid) or {}
        todo = args.force or not (row.get("cover") and row.get("metacritic") and row.get("release"))
        if not todo:
            print(f"  {i:2d} · {cn or name}（已齐，跳过）")
            continue

        if args.force or not row.get("cover"):
            cv = wiki_cover(name)
            if cv:
                row["cover"] = cv
                row["coverSrc"] = "wiki"
                # 维基给的是竖版盒图（Steam 头图才是 16:9），前端用 contain + 虚化底
                row["coverFit"] = "contain"
            time.sleep(args.sleep)

        if args.force or not (row.get("metacritic") and row.get("release") and row.get("genre")):
            items = search(name) or []
            if not items and cn:
                items = search(cn) or []
            names = [name] + ([cn] if cn else []) + [WIKI_FIX.get(name, name)]
            best = pick(items, names, ["Switch"], None)
            if best:
                sc = ((best.get("criticScoreSummary") or {}).get("score")) or 0
                if sc:
                    row["metacritic"] = int(sc)
                rd = best.get("releaseDate") or ""
                if re.match(r"^\d{4}-\d{2}-\d{2}", rd):
                    row["release"] = rd[:10]
                else:
                    m = re.match(r"^([A-Z][a-z]+ \d{1,2}, (\d{4}))", rd)
                    if m:
                        t = time.strptime(m.group(1), "%b %d, %Y")
                        row["release"] = time.strftime("%Y-%m-%d", t)
                gs = best.get("genres") or []
                gg = genres_to_cn(gs)
                if gg:
                    row["genre"] = gg
                row["mcTitle"] = best.get("title") or ""
            time.sleep(args.sleep)

        enrich[gid] = row
        changed += 1
        print(f"  {i:2d} ✓ {cn or name} | 封面 {'有' if row.get('cover') else '无'} "
              f"| M{row.get('metacritic') or '-'} | {row.get('release') or '—'} | {row.get('genre') or '—'}")

    if changed:
        tmp = enr_p + ".tmp"
        json.dump(enrich, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        os.replace(tmp, enr_p)
    print(f"完成：更新 {changed} 条 → {enr_p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
