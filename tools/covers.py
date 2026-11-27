#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给没有封面的游戏补图 → data/cover-override.json

策略（按顺序，谁先拿到用谁，绝不编）：
 1. Steam：拿 appid（先看 enrichment.json，再看记录里已有封面，最后按名字搜）→ header.jpg（横版，fit=cover）
 2. Wikipedia：REST summary 的 originalimage（多为竖版盒图，fit=contain）
 3. 都拿不到就跳过，UI 继续用渐变色块。

用法：
    python tools/covers.py --out ~/Documents/deepseek-harness/work/游戏档案
    python tools/covers.py --out ... --only "塞尔达传说 旷野之息,Fire Emblem 风花雪月"
    python tools/covers.py --out ... --all     # 连已经有封面的也重找（默认只补缺的）

产物：cover-override.json
    { "塞尔达传说 旷野之息": { "url": "https://upload.wikimedia.org/...", "fit": "contain", "src": "wikipedia" }, ... }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enrich  # 复用其中的 Steam 搜索 / 名字归一 / 相似度

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
STEAM_HOSTS = [
    "https://cdn.cloudflare.steamstatic.com",
    "https://cdn.akamai.steamstatic.com",
    "https://shared.akamai.steamstatic.com",
]
STEAM_HEADER = STEAM_HOSTS[0] + "/steam/apps/{appid}/header.jpg"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKI_SUMMARY_ZH = "https://zh.wikipedia.org/api/rest_v1/page/summary/{title}"


def log(*a):
    print(*a, flush=True)


def http_json(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def url_ok(url, timeout=20, tries=3):
    """确认这个图片地址真能下载（只读前 2KB，别把整张拖下来）。CDN 偶尔 429，重试几次。"""
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status != 200:
                    raise RuntimeError(f"status {r.status}")
                ctype = (r.headers.get("content-type") or "").lower()
                if not ctype.startswith("image/"):
                    return False
                r.read(2048)
                return True
        except Exception:
            time.sleep(0.8 * (n + 1))
    return False


# 中文维基标题和我们库里的名字对不上的，手动列一下（翻译差异，不是编）
WIKI_HINTS = {
    "Fire Emblem 风花雪月": "火焰之纹章 风花雪月",
    "ASTRAL CHAIN": "异界锁链",
    "宝可梦 晶灿钻石": "宝可梦 晶灿钻石／明亮珍珠",
    "METRO 2033 Redux": "地铁2033 (游戏)",
    "Jotunnslayer: Hordes of Hel": "Jotunnslayer: Hordes of Hel",
}


def wiki_cover(name):
    """用 Wikipedia 的 summary 接口拿盒图。试几种标题写法。"""
    base = name.strip()
    # 去掉「游戏名 - DLC 后缀」这类尾巴
    short = base.split(" - ")[0].strip()
    cands = [base, short]
    # 去掉版本后缀再试一次（Redux / Remastered / Deluxe Edition …）
    for suf in [" Redux", " Remastered", " - Deluxe Edition", " Deluxe Edition", ": Enhanced Edition",
                " - The Final Cut", " - Complete Edition", " Classic Collection"]:
        if short.endswith(suf):
            cands.append(short[: -len(suf)].strip())
        if base.endswith(suf):
            cands.append(base[: -len(suf)].strip())
    if "：" in base or ":" in base:
        cands.append(base.replace("：", ":"))
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in base)
    # 中文名：先查中文维基（标题就是中文名，命中率高）
    hinted = WIKI_HINTS.get(base)
    if has_cjk or hinted:
        for c in ([hinted] if hinted else []) + [base, short]:
            title = urllib.parse.quote(c.replace(" ", "_"), safe="()_%:,")
            for tpl in (WIKI_SUMMARY_ZH, WIKI_SUMMARY):
                try:
                    d = http_json(tpl.format(title=title))
                except Exception:
                    continue
                if d.get("type") == "disambiguation":
                    continue
                img = (d.get("originalimage") or {}).get("source") or (d.get("thumbnail") or {}).get("source")
                if img and "wikimedia.org" in urllib.parse.urlparse(img).hostname:
                    img = img.split("?")[0]
                    if url_ok(img):
                        return img
    for c in list(cands):
        cands.append(c + " (video game)")
    seen = set()
    for c in cands:
        if not c or c.lower() in seen:
            continue
        seen.add(c.lower())
        title = urllib.parse.quote(c.replace(" ", "_"), safe="()_%:,")
        try:
            d = http_json(WIKI_SUMMARY.format(title=title))
        except Exception:
            continue
        if d.get("type") == "disambiguation":
            continue
        img = (d.get("originalimage") or {}).get("source") or (d.get("thumbnail") or {}).get("source")
        if not img:
            continue
        # 只认维基自己的图床（白名单里加了 upload.wikimedia.org）
        if "wikimedia.org" not in urllib.parse.urlparse(img).hostname:
            continue
        img = img.split("?")[0]
        if url_ok(img):
            return img
    return None


def steam_cover(game, enrichment):
    appid = None
    en = enrichment.get(game.get("id") or "")
    if en and en.get("appid"):
        appid = en["appid"]
    if not appid:
        appid = enrich.appid_from_cover(game.get("cover") or "")
    if not appid:
        appid = enrich.search_appid(game.get("name") or "")
    if not appid:
        return None
    for host in STEAM_HOSTS:
        url = f"{host}/steam/apps/{appid}/header.jpg"
        if url_ok(url):
            return url
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="给缺封面的游戏补图")
    ap.add_argument("--out", default="", help="数据目录（含 records.json / enrichment.json）")
    ap.add_argument("--only", default="", help="只处理这些名字（逗号分隔）")
    ap.add_argument("--all", action="store_true", help="连已有封面的一起重找")
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    out = args.out or os.path.expanduser("~/Documents/deepseek-harness/work/游戏档案")
    rec_path = os.path.join(out, "records.json")
    if not os.path.isfile(rec_path):
        # 允许直接指向插件目录
        alt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "records.json")
        rec_path = alt if os.path.isfile(alt) else rec_path
    records = json.load(open(rec_path, encoding="utf-8"))
    en_path = os.path.join(out, "enrichment.json")
    enrichment = json.load(open(en_path, encoding="utf-8")) if os.path.isfile(en_path) else {}

    only = {x.strip().lower() for x in args.only.split(",") if x.strip()}
    games = records.get("games") or []
    targets = []
    for g in games:
        name = g.get("name") or ""
        if only and name.lower() not in only:
            continue
        if not args.all and g.get("cover"):
            continue
        targets.append(g)

    log(f"待补 {len(targets)} 款 · 数据目录 {out}")
    over_path = os.path.join(out, "cover-override.json")
    override = {}
    if os.path.isfile(over_path):
        try:
            override = json.load(open(over_path, encoding="utf-8"))
        except Exception:
            override = {}

    done = miss = 0
    for i, g in enumerate(targets, 1):
        name = g.get("name") or ""
        got = None
        url = steam_cover(g, enrichment)
        if url:
            got = {"url": url, "fit": "cover", "src": "steam"}
        else:
            url = wiki_cover(name)
            if url:
                got = {"url": url, "fit": "contain", "src": "wikipedia"}
        if got:
            override[name] = got
            done += 1
            log(f"[{i}/{len(targets)}] ✓ {name} ← {got['src']}")
        else:
            miss += 1
            log(f"[{i}/{len(targets)}] – {name}：两处都没找到")
        if i % 5 == 0:
            tmp = over_path + ".tmp"
            json.dump(override, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            os.replace(tmp, over_path)
        time.sleep(args.sleep)

    override.setdefault("_note", "名字 → {url, fit, src}；fit=contain 表示竖版盒图，卡片里留边显示")
    tmp = over_path + ".tmp"
    json.dump(override, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, over_path)
    log("")
    log(f"补上 {done} 款 / 没找到 {miss} 款 → {over_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
