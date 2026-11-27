#!/usr/bin/env python3
"""按你的库推荐「没玩过的好游戏」，只留 2017 年及以后发售的。

思路（不联网猜、只认能查到的数）：
  1. 候选池 = 2017–2025 的 TGA 获奖 + 年度游戏提名（data/tga-history.json 里有 1395 条）
     —— 拿过奖 = 有公认质量，避免推一堆没人评过的；
  2. 用 Metacritic 前端接口补：M 站分 / 发售日 / 类型；
  3. 剔掉库里已有的（按原名、中文名、别名、Steam 名四种写法归一比对）；
  4. 打分：TGA 档次(40) + M 站口碑(35) + 类型契合度(25)
     类型契合度 = 你玩得最多的几个类型有没有交集，看的是「投入小时数占比」而不是款数；
  5. 输出 data/recommend.json，前端「推荐」tab 直接读，不会自动更新。

    python3 tools/recommend.py                      # 全量跑（约 5–10 分钟）
    python3 tools/recommend.py --min-year 2019      # 只看 2019 后的
    python3 tools/recommend.py --limit 80           # 只要前 80 条
    python3 tools/recommend.py --no-mc              # 不查 M 站，纯 TGA 排名（几秒钟）
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import date

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0 Safari/537.36"}
MC_KEY = "1MOZgmNFxvmljaQR1X9KAij9Mo4xAY3u"
SLEEP = 1.0

# 只认这 21 个奖（和插件里 HONOR_ACCEPT 一致）
KEEP = {"年度游戏", "最佳游戏指导", "最佳叙事", "最佳艺术指导", "最佳配乐与音乐", "最佳配乐",
        "最佳音效设计", "最佳动作游戏", "最佳动作/冒险游戏", "最佳角色扮演游戏", "玩家之声",
        "最佳持续运营", "最佳社区支持", "最佳格斗游戏", "最佳家庭游戏", "最佳模拟/策略游戏",
        "最佳体育/竞速游戏", "最佳VR/AR游戏", "最佳多人游戏", "最佳独立游戏",
        "最佳独立游戏处女作", "最具影响力游戏"}


try:  # 跟 meta_score.py 共用一份「英文类型 → 中文」的映射
    from meta_score import GENRE_CN
except Exception:  # 单独拷出去跑时退化
    GENRE_CN = {}


def genre_cn(name):
    return GENRE_CN.get(str(name).strip().lower(), name)


# 维基 langlinks 给的中文名常是台译（碧血狂杀/快打旋风/黑帝斯），这里手动钉死国区译名
MANUAL_CN = {
    "Red Dead Redemption 2": "荒野大镖客 2",
    "Hades": "哈迪斯",
    "Hades II": "哈迪斯 II",
    "Street Fighter 6": "街头霸王 6",
    "Marvel's Spider-Man 2": "漫威蜘蛛侠 2",
    "Devil May Cry 5": "鬼泣 5",
    "Mario Kart 8 Deluxe": "马力欧卡丁车 8 豪华版",
    "Super Mario 3D World + Bowser's Fury": "超级马力欧 3D 世界 + 狂怒世界",
    "Monster Hunter World: Iceborne": "怪物猎人世界：冰原",
    "Astro Bot": "宇宙机器人",
    "The Last of Us Part II": "最后生还者 第二部",
    "Baldur's Gate 3": "博德之门 3",
    "Metaphor: ReFantazio": "暗喻幻想：ReFantazio",
    "The Legend of Zelda: Ocarina of Time": "塞尔达传说：时之笛",
    "Donkey Kong Bananza": "咚奇刚 蕉力全开",
}

TW_HINTS = ("碧血", "快打", "黑帝斯", "惡靈", "瑪利歐", "魔物", "戰神", "薩爾達", "潛龍", "太空戰士")


def steam_cn(name):
    """Steam 国区简中名（发行商做了本地化才有），顺手拿 appid。"""
    r = jget("https://store.steampowered.com/api/storesearch/?term=" + urllib.parse.quote(name) + "&l=english&cc=us")
    items = (r or {}).get("items") or []
    hit = next((it for it in items[:8] if norm(it.get("name")) == norm(name)), None)
    if not hit:
        return None, None
    time.sleep(0.8)
    d = jget(f"https://store.steampowered.com/api/appdetails?appids={hit['id']}&l=schinese&cc=cn")
    data = ((d or {}).get(str(hit["id"])) or {}).get("data") or {}
    nm = data.get("name") or ""
    return (nm if nm and re.search(r"[\u4e00-\u9fff]", nm) and nm != name else None), hit["id"]


def guess_cover(name, appid=None):
    """封面：先 Steam header，再维基英文页原图。"""
    if not appid:
        r = jget("https://store.steampowered.com/api/storesearch/?term=" + urllib.parse.quote(name) + "&l=english&cc=us")
        items = (r or {}).get("items") or []
        hit = next((it for it in items[:8] if norm(it.get("name")) == norm(name)), None)
        appid = hit["id"] if hit else None
    if appid:
        return f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
    d = jget("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(name.replace(" ", "_")))
    src = ((d or {}).get("originalimage") or {}).get("source") or ""
    return (src.split("?")[0] or None) if src else None


def norm(s):
    s = str(s or "").lower()
    s = re.sub(r"[\u2122\u00ae\u2120]", "", s)
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", s)
    return s


def jget(url, tries=3, timeout=20):
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=timeout).read().decode("utf-8", "replace"))
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(1.5 * (i + 1))
    return None


def mc_lookup(name):
    """Metacritic 前端接口：一次搜索给 score / releaseDate / genres。"""
    url = ("https://backend.metacritic.com/finder/metacritic/search/"
           + urllib.parse.quote(name) + f"/web?apiKey={MC_KEY}")
    d = jget(url)
    items = (((d or {}).get("data") or {}).get("items")) or []
    # 返回的是扁平对象：{title, criticScoreSummary:{score}, releaseDate, genres:[{name}], platforms:[{name}]}
    hit = None
    for it in items:
        if it.get("type") not in (None, "game-title", "game"):
            continue
        if norm(it.get("title")) != norm(name):
            continue
        if (it.get("criticScoreSummary") or {}).get("score") is None:
            continue
        hit = it
        break
    if not hit:
        return None
    return {
        "score": int((hit.get("criticScoreSummary") or {}).get("score") or 0) or None,
        "release": str(hit.get("releaseDate") or "")[:10] or None,
        "genres": [g.get("name") for g in (hit.get("genres") or []) if isinstance(g, dict) and g.get("name")],
        "platforms": [x.get("name") for x in (hit.get("platforms") or []) if isinstance(x, dict) and x.get("name")],
    }


def cand_names_hint(alias, media):
    """别名表里的所有写法（中英都算），用来判「这个我是不是已经有了」。"""
    out = set()
    for k, v in (alias or {}).items():
        out.add(k)
        if isinstance(v, str):
            out.add(v)
    for k, v in (media or {}).items():
        out.add(k)
        if isinstance(v, dict) and v.get("cn"):
            out.add(v["cn"])
    return out


def library_index(games):
    """库里已有的所有写法 → 一套归一集合。"""
    seen = set()
    for g in games:
        for k in ("name", "cn", "en"):
            v = g.get(k)
            if v:
                seen.add(norm(v))
    return seen


# 奖项权重（T0–T4）。「年度游戏」满分 40，往里依次递减，
# 运营类/技术类封顶 5 分——拿一打「最佳社区支持」也顶不过一个年度游戏。
AWARD_W = {
    # T0 定义年度
    "年度游戏": 40, "最佳游戏指导": 30,
    # T1 核心创作
    "最佳叙事": 24, "最佳艺术指导": 23, "最佳动作冒险游戏": 20, "最佳角色扮演游戏": 18,
    # T2 特殊影响力
    "玩家之声": 14, "最佳独立游戏": 12, "最佳独立游戏首秀": 10,
    # T3 类型专项
    "最佳动作游戏": 8, "最佳格斗游戏": 6, "最佳家庭游戏": 6,
    "最佳模拟策略游戏": 6, "最佳体育竞速游戏": 6, "最佳VR/AR游戏": 5, "最佳多人游戏": 5,
    # T4 运营/技术向（都 ≤5）
    "最佳持续运营": 4, "最佳配乐": 4, "最佳社区支持": 3, "最佳音效设计": 3,
}
AWARD_ALIAS = {          # 历年奖项改过名，归到同一档
    "最佳策略游戏": "最佳模拟策略游戏", "最佳模拟策略游戏": "最佳模拟策略游戏",
    "最佳VR游戏": "最佳VR/AR游戏", "最佳独立游戏处女作": "最佳独立游戏首秀",
    "最佳配乐与音乐": "最佳配乐", "最佳原声": "最佳配乐",
}


def award_points(won_cats, nom_cats):
    """奖项折算成分数（0–48）。单项取最高，其余按递减系数加成，避免刷奖。"""
    def w(cat):
        return AWARD_W.get(AWARD_ALIAS.get(cat, cat), 0)

    ws = sorted((w(x) for x in won_cats), reverse=True)
    if ws and ws[0] > 0:
        best, rest = ws[0], sum(ws[1:])
        pts = best + 8 * (1 - 1 / (1 + rest / 25))     # 纯年度游戏=40，多拿最多 +8
        label = next((x for x in won_cats if w(x) == best), "TGA 获奖")
        return round(pts, 1), "TGA %s" % label

    ns = sorted((w(x) * 0.25 for x in nom_cats), reverse=True)
    if ns and ns[0] > 0:
        best, rest = ns[0], sum(ns[1:])
        pts = min(16, 10 * (1 - 1 / (1 + best / 10)) + 5 * (1 - 1 / (1 + rest / 40)))
        label = next((x for x in nom_cats if w(x) * 0.25 == best), "TGA 提名")
        return round(pts, 1), "TGA %s 提名" % label
    return 0.0, ""


# 类型归族：M 站/Steam 的标签太细（「欧美角色扮演」「平台动作」），
# 直接按字符串比对会跟你的口味画像（「角色扮演」「动作」）永远对不上。
# 顺序即优先级：越具体的写在前面，先命中先算（「平台动作」不并进「动作」——
# 你玩平台跳跃和玩动作游戏是两回事，混在一起会让《宇宙机器人》这类虚高）
FAMILIES = ["平台动作", "开放世界动作", "动作角色扮演", "日式角色扮演", "大型多人在线",
            "足球模拟", "音乐", "恐怖", "解谜", "派对", "生存", "沙盒", "放置",
            "角色扮演", "策略", "模拟", "动作", "冒险", "体育", "竞速", "社交"]


def family(genre: str) -> str:
    g = str(genre or "").strip()
    for f in FAMILIES:
        if f in g:
            return f
    return g


def genre_profile(games):
    """按「类型家族」统计投入小时数占比，返回 ({族: 占比}, 前 6 名)。"""
    hours, total = {}, 0.0
    for g in games:
        h = float(g.get("hours") or 0)
        if h <= 0:
            continue
        total += h
        fams = {family(x) for x in str(g.get("genre") or "").split("/") if x.strip()}
        for k in fams:
            if k:
                hours[k] = hours.get(k, 0) + h
    if not total:
        return {}, []
    prof = {k: v / total for k, v in hours.items()}
    top = sorted(prof.items(), key=lambda kv: -kv[1])[:6]
    return prof, top


def main():
    global SLEEP
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.expanduser("~/Documents/deepseek-harness/work/游戏档案"))
    ap.add_argument("--min-year", type=int, default=2017)
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--no-mc", action="store_true", help="不查 Metacritic（快，但没分数）")
    ap.add_argument("--allow-unknown", action="store_true", help="没查到发售日的也留着（默认剔掉）")
    ap.add_argument("--no-cover", action="store_true", help="不补封面（省时间，前端显示色块）")
    ap.add_argument("--refresh-mc", action="store_true", help="忽略 mc-cache.json，重新查 Metacritic")
    args = ap.parse_args()
    SLEEP = args.sleep

    D = args.dir
    games = json.load(open(os.path.join(D, "records.json"))).get("games", [])
    enrich = json.load(open(os.path.join(D, "enrichment.json"))) if os.path.exists(os.path.join(D, "enrichment.json")) else {}
    manual = json.load(open(os.path.join(D, "manual.json"))) if os.path.exists(os.path.join(D, "manual.json")) else {}
    # 类型 / M 站分不在 records 里，在 enrichment（按 id）和 manual 里 —— 补进来才好算契合度
    for g in games:
        en = enrich.get(g.get("id")) or {}
        man = manual.get(g.get("id")) or {}
        g["genre"] = man.get("genre") or en.get("genre") or g.get("genre")
        g["metacritic"] = man.get("metacritic") or en.get("metacritic")
        g["cn"] = man.get("cn") or g.get("cn")
        g["en"] = man.get("en") or en.get("en") or g.get("en")
    extra = (json.load(open(os.path.join(D, "extra-games.json"))).get("games", [])
             if os.path.exists(os.path.join(D, "extra-games.json")) else [])
    tga = json.load(open(os.path.join(D, "tga-history.json")))
    media = json.load(open(os.path.join(D, "tga-media.json"))) if os.path.exists(os.path.join(D, "tga-media.json")) else {}
    alias = json.load(open(os.path.join(D, "tga-alias.json"))) if os.path.exists(os.path.join(D, "tga-alias.json")) else {}

    owned = library_index(games + extra)
    prof, top = genre_profile(games)
    print("[库] %d 款，投入最多的类型：%s" % (len(games), "、".join(f"{k} {v*100:.0f}%" for k, v in top)))

    # ---- 0) 上一版榜单：封面兜底（--no-cover 时不至于把图全清掉）----
    prev_covers = {}
    old_p = os.path.join(D, "recommend.json")
    if os.path.exists(old_p):
        try:
            for it in (json.load(open(old_p)) or {}).get("items", []):
                if it.get("cover"):
                    prev_covers[norm(it.get("name"))] = it["cover"]
        except Exception:  # noqa: BLE001
            prev_covers = {}

    # ---- 1) 从 TGA 汇总候选 ----
    def variants(name):
        """候选名的各种写法：英文原名、别名表里的中文、陈列室抓到的中文名。"""
        out = {name}
        v = alias.get(name)
        if isinstance(v, str):
            out.add(v)
        m = media.get(name)
        if isinstance(m, dict) and m.get("cn"):
            out.add(m["cn"])
        return out

    def owned_already(name):
        return any(norm(v) in owned for v in variants(name) if v)

    cand = {}
    def add(name, year, cat, won):
        if not name or name == "TBD":
            return
        key = norm(name)
        if not key or owned_already(name):
            return
        cn = MANUAL_CN.get(name, "")
        if not cn:
            mv = media.get(name)
            if isinstance(mv, dict):
                cn = mv.get("cn") or ""
        if not cn and isinstance(alias.get(name), str):
            cn = alias[name]
        # 台译看着别扭的，再问一次 Steam 国区
        if cn and any(t in cn for t in TW_HINTS) and name not in MANUAL_CN:
            got, _ = steam_cn(name)
            if got:
                cn = got
        # 中文名质量兜底：维基偶尔给「XX系列」「XX列表」，宁可不显示
        if cn and (len(cn) > 18 or re.search(r"系列|列表|游戏界|年電子|公司|股份有限公司", cn)):
            cn = ""
        c = cand.setdefault(key, {"name": name, "cn": cn, "year": year, "won": [], "nom": []})
        (c["won"] if won else c["nom"]).append({"year": year, "cat": cat})
        c["year"] = max(c["year"], year)

    for y in tga.get("years", []):
        yr = int(y.get("year") or 0)
        if yr < args.min_year:
            continue
        for c in y.get("categories", []):
            cat = c.get("category")
            if cat not in KEEP:
                continue
            if c.get("winner"):
                add(c["winner"], yr, cat, True)
            for n in (c.get("nominees") or []):
                add(n, yr, cat, False)
    print("[候选] TGA %d 年起、剔掉库里的，剩 %d 个名字" % (args.min_year, len(cand)))

    # ---- 2) 补 M 站（结果缓存，重打分不用再联网）----
    cache_p = os.path.join(D, "mc-cache.json")
    cache = json.load(open(cache_p)) if os.path.exists(cache_p) else {}
    mc_hits = 0

    def mc_cached(name):
        nonlocal mc_hits
        key = norm(name)
        if key in cache and not args.refresh_mc:
            return cache[key]
        info = mc_lookup(name)
        if info:
            cache[key] = info
            mc_hits += 1
        return info

    rows = []
    for i, (k, c) in enumerate(sorted(cand.items(), key=lambda kv: -kv[1]["year"]), 1):
        info = None
        if not args.no_mc:
            info = mc_cached(c["name"])
            time.sleep(SLEEP)
        if not args.allow_unknown and not (info or {}).get("release"):
            continue          # 查不到发售日 → 没法确认是不是 2017 年后，直接不推
        if info and info.get("release"):
            ry = int(info["release"][:4])
            if ry < args.min_year:
                continue
            c["release"] = info["release"]
        c["metacritic"] = (info or {}).get("score")
        c["genres"] = [genre_cn(g) for g in ((info or {}).get("genres") or [])]
        c["platforms"] = (info or {}).get("platforms") or []
        rows.append(c)
        if args.no_mc is False and i % 20 == 0:
            print(f"  ...M 站 {i}/{len(cand)}")

    # ---- 3) 打分 ----
    GOTY = {"年度游戏"}
    out = []
    for c in rows:
        won_cats = {x["cat"] for x in c["won"]}
        nom_cats = {x["cat"] for x in c["nom"]}
        c["won"] = [dict(t) for t in {(x["year"], x["cat"]): x for x in c["won"]}.values()]
        aw, aw_txt = award_points(won_cats, nom_cats)

        mc = c.get("metacritic") or 0
        s_mc = max(0.0, min(1.0, (mc - 70) / 25)) if mc else 0.35

        fams = {family(g) for g in c.get("genres", []) if g}
        hit = sorted((f for f in fams if prof.get(f)), key=lambda f: -prof[f])
        # 取最贴合的那一类，不求和：多挂几个标签不该比单挂多得分
        s_genre = min(1.0, prof[hit[0]] * 2.2) if hit else 0.0

        score = aw + s_mc * 35 + s_genre * 25

        why = [f"{aw_txt}（奖项 {aw} 分）" if aw else "无 TGA 记录（奖项 0 分）"]
        if mc:
            why.append(f"M 站 {mc}")
        if hit:
            why.append("你常玩的：" + "、".join(hit[:3]))
        if c.get("release"):
            why.append(f"{c['release'][:4]} 年发售")
        cover = c.get("cover") or None
        if not cover and not args.no_cover:
            cover = guess_cover(c["name"], c.get("appid"))
            time.sleep(SLEEP * 0.6)
        if not cover:
            cover = prev_covers.get(norm(c["name"]))
        out.append({**c, "score": round(score, 1), "why": why, "awardPts": aw, "cover": cover})

    out.sort(key=lambda x: -x["score"])
    out = out[:args.limit]

    doc = {
        "updated": date.today().isoformat(),
        "basis": {
            "minYear": args.min_year,
            "library": len(games) + len(extra),
            "topGenres": [{"genre": k, "share": round(v, 3)} for k, v in top],
            "source": "TGA 2017–2025 获奖与年度游戏提名 + Metacritic",
        },
        "items": out,
    }
    if mc_hits:
        with open(cache_p + ".tmp", "w") as fp:
            json.dump(cache, fp, ensure_ascii=False)
        os.replace(cache_p + ".tmp", cache_p)
    path = os.path.join(D, "recommend.json")
    json.dump(doc, open(path + ".tmp", "w"), ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)
    print(f"完成：推荐 {len(out)} 条 → {path}")
    for r in out[:12]:
        print(f"  {r['score']:>5} {r['name'][:38]:<40} M{r.get('metacritic') or '-':<4} {r['why'][0]}")


if __name__ == "__main__":
    main()
