#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 TGA 名单里的英文游戏名配一个中文名 → data/tga-alias.json

为什么需要：陈列室的数据是英文（Wikipedia），你库里是中文名（Steam 国区/小黑盒），
不配一份对照表，就标不出「这款我库里有」。

做法：
 1. 先吃现成的双语来源：awards.json 里每条 {names:[英文, 中文…]}、gotyNominees，
    以及 enrichment.json 的 name ↔ nameOnSteam（Steam 国区名 vs 英文名）。
 2. 剩下的走 zh.wikipedia 的 langlinks（一次 50 个标题，省事）：英文标题 → 中文标题。
 3. 输出 { "英文名": "中文名", ... }，只留真配上的。

用法：
    python tools/build_tga_alias.py --out ~/Documents/deepseek-harness/work/游戏档案
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
API = "https://en.wikipedia.org/w/api.php"


def log(*a):
    print(*a, flush=True)


def http_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def zh_title(en_names):
    """批量把英文标题换成中文标题（langlinks）。返回 {en: zh}。"""
    out = {}
    batch = 50
    titles = list(en_names)
    for i in range(0, len(titles), batch):
        chunk = titles[i:i + batch]
        q = urllib.parse.urlencode({
            "action": "query",
            "format": "json",
            "prop": "langlinks",
            "lllang": "zh",
            "redirects": "1",
            "titles": "|".join(chunk),
        })
        d = None
        for attempt in range(3):
            try:
                d = http_json(f"{API}?{q}")
                break
            except Exception as e:
                log(f"  ! 批次 {i // batch + 1} 第 {attempt + 1} 次失败：{type(e).__name__}")
                time.sleep(2.5 * (attempt + 1))
        if d is None:
            continue
        # 处理 redirects / normalized，把结果映回原英文名
        back = {}
        for k in ("normalized", "redirects"):
            for m in d.get("query", {}).get(k, []) or []:
                back[m["to"]] = m["from"]
        for page in d.get("query", {}).get("pages", {}).values():
            title = page.get("title") or ""
            links = page.get("langlinks") or []
            if not links:
                continue
            zh = links[0].get("*") or links[0].get("title")
            if not zh:
                continue
            # 还原成请求时的名字
            orig = title
            seen = set()
            while orig in back and orig not in seen:
                seen.add(orig)
                orig = back[orig]
            out[orig] = zh
        log(f"  · 批次 {i // batch + 1}：{len(chunk)} 个标题，累计配上 {len(out)}")
        time.sleep(0.5)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 TGA 英文名 → 中文名对照表")
    ap.add_argument("--out", default="", help="数据目录（含 tga-history.json）")
    args = ap.parse_args()

    out_dir = args.out or os.path.expanduser("~/Documents/deepseek-harness/work/游戏档案")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def load(name):
        for base in (out_dir, os.path.join(here, "data")):
            p = os.path.join(base, name)
            if os.path.isfile(p):
                return json.load(open(p, encoding="utf-8"))
        return {}

    tga = load("tga-history.json")
    awards = load("awards.json")
    enrich = load("enrichment.json")

    alias = {}

    # 1) awards.json 里本来就带中英双名
    for row in awards.get("awards") or []:
        names = row.get("names") or []
        if len(names) >= 2 and names[0] and names[1]:
            alias[names[0]] = names[1]
    for row in awards.get("gotyNominees") or []:
        names = row.get("names") or []
        if len(names) >= 2 and names[0] and names[1]:
            alias[names[0]] = names[1]
    log(f"双名来源：{len(alias)} 条")

    # 2) Steam 国区名 ↔ 英文名
    for v in enrich.values():
        cn = v.get("name")
        en = v.get("nameOnSteam")
        if cn and en and cn != en:
            alias.setdefault(en, cn)
    log(f"加上 Steam 对照：{len(alias)} 条")

    # 3) 剩下走 zh.wikipedia
    need = set()
    for y in tga.get("years") or []:
        for c in y.get("categories") or []:
            for n in [c.get("winner")] + (c.get("nominees") or []):
                if n and n not in alias:
                    need.add(n)
    log(f"还要查维基的：{len(need)} 个")
    if need:
        got = zh_title(sorted(need))
        # 维基给的中文标题常带「 (游戏)」这类消歧义尾巴，砍掉
        clean = {}
        for en, zh in got.items():
            z = zh
            for suf in (" (游戏)", " (電子遊戲)", " (电子游戏)", "（游戏）"):
                if z.endswith(suf):
                    z = z[: -len(suf)]
            clean[en] = z
        alias.update(clean)
        log(f"维基补上：{len(clean)} 条")

    # 4) 还缺的走 Steam 商店搜索（国区返回中文名），这条最准
    try:
        import enrich as steam
    except Exception:
        steam = None
    if steam:
        left = [n for n in sorted(need) if n not in alias]
        log(f"再用 Steam 搜索补：{len(left)} 个")
        filled = 0
        for i, en in enumerate(left, 1):
            try:
                appid, cn, score = steam.search_appid(en)
            except Exception:
                continue
            if appid and cn and score >= 0.72 and cn != en and any("\u4e00" <= ch <= "\u9fff" for ch in cn):
                alias[en] = cn
                filled += 1
            if i % 40 == 0:
                log(f"  · {i}/{len(left)}，已补 {filled}")
            time.sleep(0.6)
        log(f"Steam 补上：{filled} 条")

    path = os.path.join(out_dir, "tga-alias.json")
    tmp = path + ".tmp"
    json.dump(alias, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)
    log("")
    log(f"共 {len(alias)} 条 → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
