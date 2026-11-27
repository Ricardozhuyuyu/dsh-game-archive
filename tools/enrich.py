#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""游戏档案 · 补充资料（发售日 / M 站评分 / 类型 / 发售价）

数据源：Steam 公开接口
  - https://store.steampowered.com/api/storesearch/  名字 → appid
  - https://store.steampowered.com/api/appdetails/    appid → 发售日 / Metacritic / 类型 / 价格

用法（在插件目录里）：
    python tools/enrich.py --out ~/Documents/deepseek-harness/work/游戏档案
    python tools/enrich.py --out <DIR> --only Steam --limit 10      # 先试几款
    python tools/enrich.py --out <DIR> --force                      # 全部重抓
    python tools/enrich.py --out <DIR> --missing-only                # 只补还缺字段的

设计要点
  * 增量：enrichment.json 里已有的字段不会被覆盖，除非 --force
  * 失败不写坏数据：抓取失败的条目保持原样，只在日志里报
  * appid 确定方式：先从封面 URL 里认 steam/apps/<id>，认不到再按名字搜
  * 一切拿不到的字段留空，绝不猜
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
API_DETAIL = "https://store.steampowered.com/api/appdetails?appids={appid}&cc=cn&l=schinese"
API_SEARCH = "https://store.steampowered.com/api/storesearch/?term={term}&cc=cn&l=schinese"
SLEEP = 1.2          # 每个请求之间歇一下，别把接口顶炸
TIMEOUT = 25
THRESHOLD = 0.62     # 名字相似度低于这个就不认


# ── 基础工具 ────────────────────────────────────────────────
def log(*a):
    print(*a, flush=True)


def http_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read()
    return json.loads(raw.decode("utf-8", "replace"))


def norm(s):
    """名字归一：小写、去掉标点/空格/™®/副标题尾巴。"""
    s = str(s or "").lower()
    s = re.sub(r"[™®©]", "", s)
    s = re.sub(r"[\s\-_:：·、,，.。'\"!?！？（）()\[\]【】/\\]+", "", s)
    return s


def base_name(s):
    """「对马岛之魂：导演剪辑版」→「对马岛之魂」这种，砍掉副标题。"""
    s = str(s or "")
    for sep in ("：", ":", " - ", "—", "（", "("):
        if sep in s:
            head = s.split(sep, 1)[0].strip()
            if len(head) >= 3:
                return head
    return s


def similarity(a, b):
    """粗糙但够用的相似度：归一后相等=1，一方包含另一方=按长度比，否则字符二元组 Jaccard。"""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return min(len(na), len(nb)) / max(len(na), len(nb))
    grams = lambda x: {x[i:i + 2] for i in range(max(1, len(x) - 1))}
    ga, gb = grams(na), grams(nb)
    inter = len(ga & gb)
    return inter / max(1, len(ga | gb))


def parse_release(txt):
    """「2013 年 7 月 9 日」/「9 Jul, 2013」/「2013」→ 2023-07-09 / 2023-07 / 2013"""
    s = str(txt or "").strip()
    if not s:
        return ""
    m = re.match(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"(\d{1,2})\s+([A-Za-z]{3,})\w*,?\s+(\d{4})", s)
    if m:
        months = {x: i for i, x in enumerate(
            ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
        mi = months.get(m.group(2)[:3].lower())
        if mi:
            return f"{int(m.group(3)):04d}-{mi:02d}-{int(m.group(1)):02d}"
    m = re.match(r"([A-Za-z]{3,})\w*\s+(\d{1,2}),?\s+(\d{4})", s)
    if m:
        months = {x: i for i, x in enumerate(
            ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
        mi = months.get(m.group(1)[:3].lower())
        if mi:
            return f"{int(m.group(3)):04d}-{mi:02d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{4})\s*年?", s)
    if m:
        return m.group(1)
    return ""


# ── Steam ───────────────────────────────────────────────────
def appid_from_cover(url):
    m = re.search(r"steam/apps/(\d+)/", str(url or ""))
    return int(m.group(1)) if m else None


def appid_from_records(game):
    for key in ("appid", "steam_appid"):
        v = game.get(key)
        if isinstance(v, int) and v > 0:
            return v
    return appid_from_cover(game.get("cover"))


def search_appid(name):
    """按名字搜 Steam，返回 (appid, 命中名, 相似度) 或 (None, None, 0)。"""
    tries = []
    for t in (name, base_name(name), re.sub(r"[^\x00-\x7F]", " ", name).strip()):
        t = (t or "").strip()
        if t and t not in tries:
            tries.append(t)
    best = (None, None, 0.0)
    for term in tries:
        try:
            data = http_json(API_SEARCH.format(term=urllib.parse.quote(term)))
        except Exception:
            time.sleep(SLEEP)
            continue
        for item in (data.get("items") or [])[:8]:
            nm = item.get("name") or ""
            sim = similarity(name, nm)
            if sim > best[2]:
                best = (int(item.get("id")), nm, sim)
        time.sleep(SLEEP)
    if best[2] >= THRESHOLD:
        return best
    return (None, best[1], best[2])


def detail(appid):
    """抓一款的详情，返回 dict（拿不到的字段为 None）。"""
    data = http_json(API_DETAIL.format(appid=appid))
    node = (data or {}).get(str(appid)) or {}
    if not node.get("success"):
        return None
    d = node.get("data") or {}
    rel = parse_release((d.get("release_date") or {}).get("date"))
    mc = (d.get("metacritic") or {}).get("score")
    genres = [g.get("description") for g in (d.get("genres") or []) if g.get("description")]
    price = None
    if d.get("is_free"):
        price = {"currency": "", "initial": 0, "final": 0, "discount": 0, "free": True, "kind": "免费"}
    else:
        po = d.get("price_overview") or {}
        if po:
            price = {
                "currency": po.get("currency") or "",
                "initial": (po.get("initial") or 0) / 100.0,
                "final": (po.get("final") or 0) / 100.0,
                "discount": po.get("discount_percent") or 0,
                "free": False,
                "kind": "折扣" if (po.get("discount_percent") or 0) > 0 else "原价",
            }
    return {
        "release": rel or None,
        "metacritic": mc if isinstance(mc, int) else None,
        "genre": " / ".join(genres) if genres else None,
        "price": price,
        "nameOnSteam": d.get("name"),
    }


# ── 主流程 ──────────────────────────────────────────────────
def main() -> int:
    global SLEEP
    ap = argparse.ArgumentParser(description="补全发售日 / M 站评分 / 类型 / 发售价")
    ap.add_argument("--out", required=True, help="数据目录（enrichment.json 写这里）")
    ap.add_argument("--records", default="", help="records.json 路径（默认 <out>/records.json）")
    ap.add_argument("--only", default="", help="只处理这些平台，逗号分隔，如 Steam,PSN")
    ap.add_argument("--skip", default="", help="跳过这些平台")
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少款（试跑用）")
    ap.add_argument("--force", action="store_true", help="已抓到的也重抓")
    ap.add_argument("--missing-only", action="store_true", help="只处理还缺字段的")
    ap.add_argument("--sleep", type=float, default=SLEEP, help="请求间隔秒数")
    args = ap.parse_args()

    SLEEP = max(0.2, args.sleep)
    out_dir = os.path.abspath(os.path.expanduser(args.out))
    records_path = os.path.abspath(os.path.expanduser(args.records or os.path.join(out_dir, "records.json")))
    enrich_path = os.path.join(out_dir, "enrichment.json")

    if not os.path.isfile(records_path):
        log(f"❌ 找不到 records.json：{records_path}")
        return 2

    records = json.load(open(records_path, encoding="utf-8"))
    games = records.get("games") or []
    store = {}
    if os.path.isfile(enrich_path):
        try:
            store = json.load(open(enrich_path, encoding="utf-8"))
        except Exception:
            log("⚠️ enrichment.json 读不动，当作空的重来（旧文件已备份）")
            os.replace(enrich_path, enrich_path + ".bak")
            store = {}

    only = {x.strip().lower() for x in args.only.split(",") if x.strip()}
    skip = {x.strip().lower() for x in args.skip.split(",") if x.strip()}

    todo = []
    for g in games:
        plat = str(g.get("platform") or "")
        if only and plat.lower() not in only:
            continue
        if plat.lower() in skip:
            continue
        cur = store.get(g["id"]) or {}
        complete = bool(cur.get("release") and cur.get("genre") and cur.get("_done"))
        if args.missing_only and complete:
            continue
        if complete and not args.force:
            continue
        todo.append(g)
    if args.limit:
        todo = todo[: args.limit]

    log(f"数据目录 {out_dir}")
    log(f"共 {len(games)} 款，这次处理 {len(todo)} 款")
    hit = miss = fail = 0
    t0 = time.time()

    for i, g in enumerate(todo, 1):
        name = g.get("name") or ""
        rec = store.get(g["id"]) or {"name": name, "platform": g.get("platform")}
        rec["name"] = name
        rec["platform"] = g.get("platform")

        appid = appid_from_records(g)
        matched = None
        if not appid:
            appid, matched, sim = search_appid(name)
            if appid:
                rec["matchScore"] = round(sim, 2)
                rec["matchName"] = matched

        if not appid:
            rec["_done"] = True
            rec["_note"] = "Steam 上找不到同名条目"
            store[g["id"]] = rec
            miss += 1
            log(f"[{i}/{len(todo)}] — {g.get('platform')} · {name}：无 appid")
            continue

        rec["appid"] = appid
        try:
            d = detail(appid)
        except urllib.error.HTTPError as e:
            rec["_note"] = f"HTTP {e.code}"
            store[g["id"]] = rec
            fail += 1
            log(f"[{i}/{len(todo)}] ✗ {name}：HTTP {e.code}")
            time.sleep(SLEEP)
            continue
        except Exception as e:
            rec["_note"] = f"{type(e).__name__}"
            store[g["id"]] = rec
            fail += 1
            log(f"[{i}/{len(todo)}] ✗ {name}：{type(e).__name__}")
            time.sleep(SLEEP)
            continue

        if not d:
            rec["_note"] = "appdetails 没返回数据"
            store[g["id"]] = rec
            fail += 1
            time.sleep(SLEEP)
            continue

        for k in ("release", "metacritic", "genre", "price"):
            if d.get(k) not in (None, "", []):
                rec[k] = d[k]
        if d.get("nameOnSteam"):
            rec["nameOnSteam"] = d["nameOnSteam"]
        rec["_done"] = True
        rec.pop("_note", None)
        rec["_ts"] = int(time.time())
        store[g["id"]] = rec
        hit += 1

        bits = [rec.get("release") or "—", f"M{rec['metacritic']}" if rec.get("metacritic") else "M—",
                (rec.get("genre") or "—")[:18],
                (f"{rec['price']['initial']}{rec['price']['currency']}" if rec.get("price") else "价格—")]
        log(f"[{i}/{len(todo)}] ✓ {name}：{' · '.join(bits)}")

        if i % 15 == 0:
            tmp = enrich_path + ".tmp"
            json.dump(store, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            os.replace(tmp, enrich_path)
        time.sleep(SLEEP)

    tmp = enrich_path + ".tmp"
    json.dump(store, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, enrich_path)

    filled = sum(1 for v in store.values() if v.get("release"))
    log("")
    log(f"完成：成功 {hit} · 无 appid {miss} · 失败 {fail} · 用时 {time.time() - t0:.0f}s")
    log(f"enrichment.json 共 {len(store)} 条，其中 {filled} 条拿到发售日")
    log(f"→ {enrich_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
