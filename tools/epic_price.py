#!/usr/bin/env python3
"""给 Epic 白嫖来的游戏标上「真实原价」。

Epic 每周免费/会免拿到的游戏，后台只会说「免费」，但它是资产，
账面价值应按这款游戏在商店的原价算。做法：按名字去 Steam 商店查
price_overview（中国区、人民币），把 initial 写进 manual.json；
查不到价或本来就 F2P（initial=0）的保持原样。

    python3 tools/epic_price.py                  # 补全库 Epic 里没价的
    python3 tools/epic_price.py --platform Xbox  # 换平台
    python3 tools/epic_price.py --dry-run        # 只看结果不写
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0 Safari/537.36"}
SLEEP = 1.2


def jget(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace"))
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1.5 * (i + 1))


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"[\u2122\u00ae\u2120]", "", s)
    s = re.sub(r"\b(deluxe|ultimate|gold|complete|definitive|standard|edition|remastered|goty)\b", " ", s)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", s)


def base_name(name):
    """砍掉 Epic 名字里常见的 DLC / 版本尾巴。"""
    n = re.split(r"\s+[-–—:]\s+|\s*\(", name)[0]
    return n.strip() or name


def appid_of(name):
    for q in (name, base_name(name)):
        r = jget("https://store.steampowered.com/api/storesearch/?term="
                 + urllib.parse.quote(q) + "&l=english&cc=us")
        items = (r or {}).get("items") or []
        # 只认「规范化之后完全一样」的，宁可漏也不认错（名字差一点就是另一个游戏/DLC）
        want = {norm(name), norm(base_name(name))}
        for it in items[:10]:
            if norm(it.get("name")) in want:
                return it["id"], it.get("name"), 1.0
        score = max([seq(norm(it.get("name")), norm(name)) for it in items[:8]] or [0.0])
        time.sleep(0.4)
    return None, None, 0.0


def seq(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return (2 * len(short)) / (len(short) + len(long_)) if short in long_ else 0.0


def price_of(appid):
    d = jget(f"https://store.steampowered.com/api/appdetails?appids={appid}&l=schinese&cc=cn")
    x = ((d or {}).get(str(appid)) or {}).get("data") or {}
    if x.get("is_free"):
        return {"currency": "CNY", "initial": 0, "final": 0, "discount": 0, "free": True}
    po = x.get("price_overview") or {}
    if not po:
        return None
    return {"currency": po.get("currency") or "CNY",
            "initial": round(po.get("initial", 0) / 100, 2),
            "final": round(po.get("final", 0) / 100, 2),
            "discount": po.get("discount_percent", 0), "free": False}


def main():
    global SLEEP
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.expanduser("~/Documents/deepseek-harness/work/游戏档案"))
    ap.add_argument("--platform", default="Epic")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=1.2)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    SLEEP = args.sleep

    rec_path = os.path.join(args.dir, "records.json")
    man_path = os.path.join(args.dir, "manual.json")
    recs = json.load(open(rec_path))["games"]
    man = json.load(open(man_path))

    # 只处理「平台那个」且价格缺失 / 被标成免费的
    todo = []
    for g in recs:
        if g.get("platform") != args.platform:
            continue
        cur = (man.get(g["id"]) or {}).get("price") or {}
        if Number(cur.get("initial")) and not cur.get("free"):
            continue
        todo.append(g)
    if args.limit:
        todo = todo[:args.limit]
    print(f"[{args.platform}] 待查价 {len(todo)} 款")

    ok = miss = 0
    for i, g in enumerate(todo, 1):
        aid, sname, score = appid_of(g["name"])
        if not aid:
            miss += 1
            print(f"  {i:3d} ✗ 没找到 {g['name']}")
            time.sleep(SLEEP)
            continue
        p = price_of(aid)
        if not p:
            miss += 1
            print(f"  {i:3d} ✗ 没价 {g['name']} (appid {aid})")
            time.sleep(SLEEP)
            continue
        if not p["initial"]:
            print(f"  {i:3d} - 本来就免费 {g['name']}")
            time.sleep(SLEEP)
            continue
        entry = man.setdefault(g["id"], {})
        entry["price"] = p
        ok += 1
        print(f"  {i:3d} ✓ {g['name']} → ¥{p['initial']:.0f}  (via {sname}, {score:.2f})")
        if not args.dry_run and ok % 5 == 0:
            json.dump(man, open(man_path + ".tmp", "w"), ensure_ascii=False, indent=1)
            os.replace(man_path + ".tmp", man_path)
        time.sleep(SLEEP)

    if not args.dry_run:
        json.dump(man, open(man_path + ".tmp", "w"), ensure_ascii=False, indent=1)
        os.replace(man_path + ".tmp", man_path)
    print(f"完成：补价 {ok} · 没找到/没价 {miss}")


def Number(v):
    try:
        return float(v)
    except Exception:
        return 0.0


if __name__ == "__main__":
    main()
