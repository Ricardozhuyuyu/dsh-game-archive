#!/usr/bin/env python3
"""给 TGA 陈列室里还没有封面的条目补图。

来源优先级：Steam 商店 header（460×215，最稳）→ 维基百科英文页原图（盒图/海报）。
演员、公司、DLC 这类本来就没有「盒图」的条目会被识别出来标 skip，不重复尝试。

    python3 tools/fill_tga_covers.py                 # 补当前缺的
    python3 tools/fill_tga_covers.py --retry-skip    # 连之前标过 skip 的也再试一次
    python3 tools/fill_tga_covers.py --limit 50
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request

UA = {"User-Agent": "dsh-game-archive/1.0 (https://github.com/Ricardozhuyuyu/dsh-game-archive) python-urllib"}
D = os.path.expanduser("~/Documents/deepseek-harness/work/游戏档案")
SLEEP = 1.0

# 明显不是「一款游戏」的条目
NOT_GAME = re.compile(
    r"(\bas\b|Studios?$|Interactive|Entertainment|Productions|"
    r"In[c]?\.|Ltd\.?$|Corporation|Company$|Team$|Games$|Softworks|Nintendo$|Valve$|"
    r"Capcom$|Square Enix|Blizzard|Ubisoft|Rockstar$|Santa Monica|Naughty Dog|"
    r"Season (One|Two|Three|1|2|3)$|Act I$|Episode \d|DLC|Expansion|Mod Kit|Soundtrack|"
    r"^TBD$|\(feature film\)|\(television series\)|\(animated film\)|\(film\)|"
    r"Series\)$|Consoles?$|Arcade$|Mobile$)",
    re.I,
)


def log(m):
    print(m, flush=True)


NET_FAIL = {"n": 0}


def jget(url, tries=4, sleep=2.5):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                NET_FAIL["n"] += 1
                return None
            time.sleep(sleep * (i + 2))


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"[\u2122\u00ae\u2120]", "", s)
    s = re.sub(r"\b(deluxe|ultimate|gold|complete|definitive|standard|edition|remastered|goty|enhanced)\b", " ", s)
    return re.sub(r"[^0-9a-z]", "", s)


def from_steam(name):
    r = jget("https://store.steampowered.com/api/storesearch/?term="
             + urllib.parse.quote(name) + "&l=english&cc=us")
    items = (r or {}).get("items") or []
    hit = next((it for it in items[:8] if norm(it.get("name")) == norm(name)), None)
    if not hit:
        return None
    appid = hit["id"]
    return f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"


def from_wiki(name):
    u = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(name.replace(" ", "_"))
    d = jget(u)
    if not d or d.get("type") == "disambiguation":
        return None
    src = ((d.get("originalimage") or {}).get("source") or "")
    if not src:
        return None
    src = src.split("?")[0]
    # 太窄的多半是竖版海报/人物照，勉强能用；太宽的多半是横幅，也留
    return src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=D)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--retry-skip", action="store_true", help="之前标了 skip 的也重新试")
    args = ap.parse_args()

    media_path = os.path.join(args.dir, "tga-media.json")
    media = json.load(open(media_path, encoding="utf-8"))
    hist = json.load(open(os.path.join(args.dir, "tga-history.json"), encoding="utf-8"))

    names = []
    for y in hist.get("years", []):
        for c in y.get("categories", []):
            if c.get("winner"):
                names.append(c["winner"])
            names.extend(c.get("nominees") or [])
    names = list(dict.fromkeys([n for n in names if n]))

    todo = []
    for n in names:
        m = media.get(n) if isinstance(media.get(n), dict) else {}
        if m.get("cover"):
            continue
        if m.get("skip") and not args.retry_skip:
            continue
        if re.search(r"\bas\b", n) or re.search(r"\((film|feature film|television series|animated series|anime series|animated film)\)$", n):
            media.setdefault(n, {})["skip"] = True
            continue
        if NOT_GAME.search(n):
            media.setdefault(n, {})["skip"] = True
            continue
        todo.append(n)

    if args.limit:
        todo = todo[:args.limit]
    log(f"[TGA 封面] 待补 {len(todo)} 条")

    ok = miss = 0
    for i, n in enumerate(todo, 1):
        src_url, src = from_steam(n), "steam"
        if not src_url:
            time.sleep(args.sleep * 0.5)
            src_url, src = from_wiki(n), "wiki"
        rec = media.setdefault(n, {})
        before = NET_FAIL["n"]
        if src_url:
            rec.update({"cover": src_url, "src": src})
            rec.pop("skip", None)
            ok += 1
            log(f"  {i:3d} ✓ {n}  ({src})")
        else:
            # 网络抖动导致的失败不标 skip，下次还能再试
            if NET_FAIL["n"] > before:
                log(f"  {i:3d} ~ {n}（网络失败，未标 skip）")
            else:
                rec["skip"] = True
            miss += 1
        if i % 10 == 0:
            json.dump(media, open(media_path + ".tmp", "w"), ensure_ascii=False, indent=1)
            os.replace(media_path + ".tmp", media_path)
        time.sleep(args.sleep)

    json.dump(media, open(media_path + ".tmp", "w"), ensure_ascii=False, indent=1)
    os.replace(media_path + ".tmp", media_path)
    have = sum(1 for n in names if isinstance(media.get(n), dict) and media[n].get("cover"))
    log(f"完成：补上 {ok} · 没找到 {miss} · 现在 {have}/{len(names)} 有封面")


if __name__ == "__main__":
    main()
