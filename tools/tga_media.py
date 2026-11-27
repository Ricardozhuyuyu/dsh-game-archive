#!/usr/bin/env python3
"""给 TGA 陈列室补两样东西：中文名 + 封面图。

数据源（按优先级，先到先得，失败不覆盖已有值）：
  1. 自己库里的 records.json / enrichment.json / tga-alias.json —— 已有的直接复用
  2. Wikipedia langlinks（英文维基 → 中文维基标题），50 个标题一批，最快
  3. Steam 商店搜索（国区返回中文名）+ header 图

输出 tga-media.json：
  { "Clair Obscur: Expedition 33": {"cn": "光与影：33号远征队", "cover": "https://...", "src": "steam"} }

用法：
  python3 tools/tga_media.py --out ~/Documents/deepseek-harness/work/游戏档案
  python3 tools/tga_media.py --out ... --only "Clair Obscur" --force
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

STEAM_HOSTS = [
    "https://cdn.cloudflare.steamstatic.com",
    "https://cdn.akamai.steamstatic.com",
    "https://shared.akamai.steamstatic.com",
]
HEADER = "{host}/steam/apps/{appid}/header.jpg"
WIKI_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKI_LANGLINKS = ("https://en.wikipedia.org/w/api.php?action=query&format=json&prop=langlinks"
                  "&lllang=zh&lllimit=500&titles=")
WIKI_PAGEIMAGES = ("https://en.wikipedia.org/w/api.php?action=query&format=json&prop=pageimages"
                   "&piprop=original&pilimit=50&titles=")

SLEEP = 0.5


def log(*a):
    print(*a, flush=True)


def http_json(url, timeout=25, tries=4):
    last = None
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            last = e
            code = getattr(e, "code", 0) or 0
            time.sleep(4.0 * (n + 1) if code in (429, 503, 502) else 1.2 * (n + 1))
    raise last


def url_ok(url, timeout=15, tries=3):
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                if r.status != 200:
                    raise RuntimeError(r.status)
                if not (r.headers.get("content-type") or "").lower().startswith("image/"):
                    return False
                r.read(1024)
                return True
        except Exception:
            time.sleep(0.6 * (n + 1))
    return False


try:  # 繁简转换是可选的：有就转成简体，没有就用维基原样
    import zhconv as _zhconv
except Exception:
    _zhconv = None


def to_simp(txt):
    if not txt:
        return txt
    if _zhconv:
        try:
            return _zhconv.convert(txt, "zh-cn")
        except Exception:
            return txt
    return txt


def has_cjk(s):
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(s or ""))


def collect_names(history):
    """把 12 年里出现过的所有名字去重收一遍（获奖者在前，顺序稳定）。"""
    seen, out = set(), []
    for y in history.get("years", []):
        for c in y.get("categories", []):
            for n in [c.get("winner")] + list(c.get("nominees") or []):
                n = (n or "").strip()
                if n and n not in seen:
                    seen.add(n)
                    out.append(n)
    return out


def wiki_title(name):
    """名字 → 维基标题的几种猜法。"""
    base = name.strip()
    cands = [base]
    for suf in [" Redux", " Remastered", " - Deluxe Edition", " Deluxe Edition",
                ": Enhanced Edition", " - The Final Cut", " - Complete Edition"]:
        if base.endswith(suf):
            cands.append(base[: -len(suf)].strip())
    # 「游戏名: 副标题」也试一次主标题
    if ": " in base:
        cands.append(base.split(": ")[0].strip())
    return cands


def wiki_langlinks(names, batch=50):
    """批量拿中文标题：{英文名: 中文名}。"""
    out = {}
    for i in range(0, len(names), batch):
        chunk = names[i:i + batch]
        url = WIKI_LANGLINKS + urllib.parse.quote("|".join(chunk))
        try:
            data = http_json(url)
        except Exception as e:
            log(f"  · langlinks 批 {i//batch+1} 失败：{e}")
            time.sleep(1.0)
            continue
        for page in (data.get("query", {}).get("pages", {}) or {}).values():
            title = (page.get("title") or "").strip()
            for ll in page.get("langlinks") or []:
                if ll.get("lang") == "zh" and ll.get("*"):
                    cn = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", ll["*"]).strip()
                    cn = to_simp(cn)
                    if has_cjk(cn):
                        out[title] = cn
                        break
        log(f"  · langlinks {min(i+batch, len(names))}/{len(names)}，已有 {len(out)}")
        time.sleep(max(1.2, SLEEP))
    return out


def wiki_covers_batch(pairs, batch=50):
    """pairs = [(维基标题, 我们的名字)]，一次 50 个拿原图：{我们的名字: url}。"""
    out = {}
    for i in range(0, len(pairs), batch):
        chunk = pairs[i:i + batch]
        url = WIKI_PAGEIMAGES + urllib.parse.quote("|".join(t for t, _ in chunk))
        try:
            data = http_json(url)
        except Exception as e:
            log(f"  · pageimages 批 {i//batch+1} 失败：{e}")
            time.sleep(2.0)
            continue
        by_title = {t: n for t, n in chunk}
        for page in (data.get("query", {}).get("pages", {}) or {}).values():
            t = (page.get("title") or "").strip()
            src = ((page.get("original") or {}).get("source") or "").strip()
            n = by_title.get(t)
            if n and src:
                out[n] = src
        log(f"  · pageimages {min(i+batch, len(pairs))}/{len(pairs)}，拿到 {len(out)}")
        time.sleep(max(0.6, min(SLEEP, 1.5)))
    return out


def wiki_cover(name):
    """维基上拿这张图，默认不额外校验（upload.wikimedia.org 很稳，省一次请求）。"""
    for t in wiki_title(name):
        try:
            d = http_json(WIKI_SUMMARY.format(title=urllib.parse.quote(t.replace(" ", "_"))))
        except Exception:
            continue
        img = (d.get("originalimage") or {}).get("source") or ""
        if img:
            return img
        time.sleep(0.1)
    return ""


def steam_lookup(name, enrich):
    """Steam 搜索：返回 (appid, 命中名, cover)。"""
    appid, hit, score = enrich.search_appid(name)
    if not appid:
        return None, hit, ""
    for host in STEAM_HOSTS:
        url = HEADER.format(host=host, appid=appid)
        if url_ok(url):
            return appid, hit, url
    return appid, hit, ""


def main() -> int:
    global SLEEP
    ap = argparse.ArgumentParser(description="给 TGA 陈列室补中文名与封面")
    ap.add_argument("--out", default=os.path.expanduser("~/Documents/deepseek-harness/work/游戏档案"))
    ap.add_argument("--history", default="", help="tga-history.json 路径，默认取 --out 下的")
    ap.add_argument("--only", default="", help="只处理这些名字（逗号分隔，子串匹配）")
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少个")
    ap.add_argument("--force", action="store_true", help="已有值的也重新抓")
    ap.add_argument("--sleep", type=float, default=SLEEP)
    ap.add_argument("--jobs", type=int, default=5, help="并发数，默认 5")
    ap.add_argument("--renames", action="store_true",
                    help="只去 Steam 重查中文名（沿用维基译名的那些，Steam 国区名通常更贴中文习惯）")
    args = ap.parse_args()
    SLEEP = max(0.1, args.sleep)

    out_dir = os.path.abspath(os.path.expanduser(args.out))
    hist_path = args.history or os.path.join(out_dir, "tga-history.json")
    with open(hist_path, encoding="utf-8") as f:
        history = json.load(f)

    names = collect_names(history)
    log(f"陈列室共 {len(names)} 个不同的名字")

    media_path = os.path.join(out_dir, "tga-media.json")
    media = {}
    if os.path.exists(media_path):
        try:
            with open(media_path, encoding="utf-8") as f:
                media = json.load(f)
        except Exception:
            media = {}

    # ---------- 1. 先吃本地已有的 ----------
    rec_path = os.path.join(out_dir, "records.json")
    game_cover = {}
    if os.path.exists(rec_path):
        with open(rec_path, encoding="utf-8") as f:
            for g in json.load(f).get("games", []):
                if g.get("cover"):
                    game_cover.setdefault(g["name"], g["cover"])

    alias_path = os.path.join(out_dir, "tga-alias.json")
    alias = {}
    if os.path.exists(alias_path):
        with open(alias_path, encoding="utf-8") as f:
            alias = json.load(f)

    for n in names:
        rec = media.setdefault(n, {})
        if not rec.get("cn") and alias.get(n):
            rec["cn"] = to_simp(alias[n])
            rec.setdefault("src", "alias")
        if not rec.get("cover"):
            if game_cover.get(n):
                rec["cover"] = game_cover[n]
                rec.setdefault("src", "library")
            elif alias.get(n) and game_cover.get(alias[n]):
                rec["cover"] = game_cover[alias[n]]
                rec.setdefault("src", "library")

    if args.renames:
        need = [n for n in names if media.get(n, {}).get("src") != "steam"]
    else:
        need = [n for n in names if args.force or not (media[n].get("cn") and media[n].get("cover"))]
    if args.only:
        keys = [k.strip().lower() for k in args.only.split(",") if k.strip()]
        need = [n for n in need if any(k in n.lower() for k in keys)]
    if args.limit:
        need = need[: args.limit]

    if not need:
        log("都齐了，不用抓。")
    else:
        log(f"要补 {len(need)} 个名字")

        # ---------- 2. Wikipedia langlinks：一次拿一批中文名 ----------
        cn_left = [n for n in need if args.force or not media[n].get("cn")]
        if cn_left:
            log(f"[中文名] 维基批量：{len(cn_left)} 个")
            titles = {}
            for n in cn_left:
                for t in wiki_title(n):
                    titles.setdefault(t, n)
            got = wiki_langlinks(list(titles.keys()))
            filled = 0
            for t, cn in got.items():
                n = titles.get(t)
                if n and (args.force or not media[n].get("cn")):
                    media[n]["cn"] = cn
                    if args.force or not media[n].get("src"):
                        media[n]["src"] = "wiki"

                    filled += 1
            log(f"[中文名] 维基补上 {filled} 条")

        # ---------- 3. Steam 搜索：补名字 + 封面 ----------
        try:
            import enrich
        except Exception as e:
            enrich = None
            log(f"（enrich.py 载入失败，跳过 Steam 那步：{e}）")

        if enrich:
            steam_left = [n for n in need
                          if not (media[n].get("cn") and media[n].get("cover"))]
            log(f"[Steam] 要查 {len(steam_left)} 个，{args.jobs} 个并发")
            lock = threading.Lock()
            counter = {"n": 0, "full": 0}

            def one(n):
                try:
                    appid, hit, cover = steam_lookup(n, enrich)
                except Exception:
                    appid, hit, cover = None, None, ""
                with lock:
                    rec = media[n]
                    # Steam 国区名比维基译名更贴中文习惯，能拿到就盖过去
                    if hit and has_cjk(hit) and (args.force or not rec.get("cn") or rec.get("src") != "steam"):
                        newcn = to_simp(hit)
                        if newcn != rec.get("cn"):
                            rec["cn"] = newcn
                            rec["src"] = "steam"

                    if cover and (args.force or not rec.get("cover")):
                        rec["cover"] = cover
                        rec.setdefault("src", "steam")
                    if appid and not rec.get("appid"):
                        rec["appid"] = appid
                    if rec.get("cn") and rec.get("cover"):
                        counter["full"] += 1
                    counter["n"] += 1
                    if counter["n"] % 40 == 0:
                        log(f"  · {counter['n']}/{len(steam_left)}，已齐全 {counter['full']}")
                        with open(media_path + ".tmp", "w", encoding="utf-8") as f:
                            json.dump(media, f, ensure_ascii=False, indent=1)
                        os.replace(media_path + ".tmp", media_path)

            with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
                list(ex.map(one, steam_left))

        # ---------- 4. 还没有封面的，回维基要盒图 ----------
        no_cover = [n for n in need if not media[n].get("cover")]
        if no_cover:
            log(f"[封面] 维基盒图：{len(no_cover)} 个（批量取）")
            pairs, seen_t = [], set()
            for n in no_cover:
                for t in wiki_title(n):
                    if t not in seen_t:
                        seen_t.add(t)
                        pairs.append((t, n))
                        break
            got = wiki_covers_batch(pairs)
            filled = 0
            for n, img in got.items():
                if not media[n].get("cover"):
                    media[n]["cover"] = img
                    media[n]["fit"] = "contain"
                    media[n]["src"] = media[n].get("src") if media[n].get("cn") else "wiki"
                    filled += 1
            log(f"[封面] 批量补上 {filled} 条")

            still = [n for n in no_cover if not media[n].get("cover")]
            if still:
                log(f"[封面] 还差 {len(still)} 个，逐个走 REST")
                lock2 = threading.Lock()
                cnt = {"n": 0}

                def one_cover(n):
                    img = wiki_cover(n)
                    with lock2:
                        if img:
                            media[n]["cover"] = img
                            media[n]["fit"] = "contain"
                            media[n].setdefault("src", "wiki")
                        cnt["n"] += 1

                with ThreadPoolExecutor(max_workers=max(1, min(6, args.jobs))) as ex:
                    list(ex.map(one_cover, still))

    with open(media_path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(media, f, ensure_ascii=False, indent=1)
    os.replace(media_path + ".tmp", media_path)

    have_cn = sum(1 for n in media if media[n].get("cn"))
    have_cv = sum(1 for n in media if media[n].get("cover"))
    log(f"完成：{len(media)} 条，有中文名 {have_cn}，有封面 {have_cv} → {media_path}")

    # 打印几个样本，方便肉眼抽查
    for n in names[:6]:
        r = media.get(n, {})
        log(f"  · {n} → {r.get('cn') or '—'} / {'有图' if r.get('cover') else '无图'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
