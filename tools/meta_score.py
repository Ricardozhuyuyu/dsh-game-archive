#!/usr/bin/env python3
"""从 Metacritic 官方前端接口补 M 站评分（顺带补发售日/类型）。

    python3 tools/meta_score.py                 # 只补缺的
    python3 tools/meta_score.py --force         # 全部重查
    python3 tools/meta_score.py --limit 20      # 先跑 20 个试试

接口：backend.metacritic.com/finder/metacritic/search/<关键词>/web?apiKey=...（网页自己在用）
返回的 items 里就带 criticScoreSummary.score / releaseDate / genres / platforms，一次搜索全拿到。
"""
import argparse
import difflib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://backend.metacritic.com/finder/metacritic/search/{q}/web?apiKey=1MOZgmNFxvmljaQR1X9KAij9Mo4xAY3u"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/158.0.0.0 Safari/537.36")
SLEEP = 0.6
PLAT_MAP = {
    "Steam": ["PC"],
    "Epic": ["PC"],
    "PSN": ["PlayStation 5", "PlayStation 4", "PlayStation 3"],
    "Xbox": ["Xbox Series X", "Xbox One", "Xbox 360"],
    "Switch": ["Nintendo Switch"],
}
NOISE = re.compile(r"™|®|©|\b(goty|goty edition|definitive edition|remastered|deluxe edition|"
                   r"complete edition|enhanced edition|director'?s cut)\b", re.I)



# Metacritic 的类型是英文，存档前换成中文（插件里其它平台的类型都是中文）
GENRE_CN = {
    "open world": "开放世界",
    "stealth": "潜行",
    "tactical rpg": "战棋",
    "rhythm": "音游",
    "roguelike": "Roguelike",
    "metroidvania": "类银河战士恶魔城",
    "survival": "生存",
    "horror": "恐怖",
    "racing": "竞速",
    "third-person shooter": "第三人称射击",
    "3d platformer": "平台动作",
    "action": "动作", "action rpg": "动作角色扮演", "open-world action": "开放世界动作",
    "action adventure": "动作冒险", "adventure": "冒险", "jrpg": "日式角色扮演",
    "western rpg": "欧美角色扮演", "rpg": "角色扮演", "party": "派对",
    "soccer sim": "足球模拟", "basketball sim": "篮球模拟", "auto racing sim": "赛车模拟",
    "auto racing": "竞速", "skiing": "滑雪", "action puzzle": "动作解谜", "puzzle": "解谜",
    "moba": "MOBA", "2d platformer": "2D 平台跳跃", "platformer": "平台跳跃",
    "tycoon": "经营", "strategy": "策略", "command rts": "即时战略", "tactical fps": "战术射击",
    "first-person shooter": "第一人称射击", "shooter": "射击", "virtual life": "虚拟生活",
    "sandbox": "沙盒", "first-person adventure": "第一人称冒险", "compilation": "合集",
    "fighting": "格斗", "sports": "体育", "simulation": "模拟", "music": "音乐",
    "misc": "其他", "educational": "教育", "board game": "桌面游戏",
}


def genre_cn(name: str) -> str:
    key = (name or "").strip().lower()
    if not key:
        return ""
    if key in GENRE_CN:
        return GENRE_CN[key]
    for k, v in GENRE_CN.items():
        if k in key:
            return v
    return ""


def genres_to_cn(items) -> str:
    out = []
    for x in items or []:
        n = x.get("name") if isinstance(x, dict) else x
        c = genre_cn(n)
        if c and c not in out:
            out.append(c)
    return " / ".join(out)[:60]


def norm(s: str) -> str:
    s = (s or "").lower()
    s = NOISE.sub(" ", s)
    s = re.sub(r"[\u2019'`´]", "", s)
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def search(q: str):
    try:
        return (get(API.format(q=urllib.parse.quote(q))).get("data") or {}).get("items") or []
    except Exception:
        return []


def pick(items, names, platforms, year):
    """从搜索结果里挑最像的那一个；挑不到返回 None。"""
    wants = [norm(n) for n in names if n]
    want_plats = []
    for p in platforms:
        want_plats += PLAT_MAP.get(p, [])
    best, best_score = None, 0.0
    for it in items:
        if it.get("type") != "game-title":
            continue
        t = norm(it.get("title"))
        if not t:
            continue
        sim = max((difflib.SequenceMatcher(None, t, w).ratio() for w in wants), default=0)
        if t in wants:
            sim = 1.0
        if sim < 0.84:
            continue
        it_plats = [p.get("name") for p in (it.get("platforms") or [])]
        if want_plats and it_plats and not set(want_plats) & set(it_plats):
            sim -= 0.12
        it_year = it.get("premiereYear")
        if year and it_year and abs(int(year) - int(it_year)) > 1:
            sim -= 0.10
        if sim > best_score:
            best, best_score = it, sim
    return best if best_score >= 0.84 else None


def main() -> int:
    global SLEEP
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expanduser("~/Documents/deepseek-harness/work/游戏档案"))
    ap.add_argument("--sleep", type=float, default=SLEEP)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--missing-only", action="store_true", default=True)
    args = ap.parse_args()
    SLEEP = args.sleep

    with open(os.path.join(args.out, "records.json"), encoding="utf-8") as fh:
        records = json.load(fh).get("games") or []
    enr_path = os.path.join(args.out, "enrichment.json")
    enr = {}
    if os.path.exists(enr_path):
        with open(enr_path, encoding="utf-8") as fh:
            enr = json.load(fh)
    try:
        with open(os.path.join(args.out, "name-cn.json"), encoding="utf-8") as fh:
            name_cn = json.load(fh)
    except Exception:
        name_cn = {}
    try:
        with open(os.path.join(args.out, "manual.json"), encoding="utf-8") as fh:
            manual = json.load(fh)
    except Exception:
        manual = {}

    targets = []
    for g in records:
        gid = g.get("id")
        e = enr.get(gid) or {}
        man = manual.get(gid) or {}
        if not args.force and (man.get("metacritic") or e.get("metacritic")):
            continue
        names = [man.get("en"), e.get("en"), g.get("name"), man.get("cn"), name_cn.get(g.get("name"))]
        targets.append((g, e, [n for n in dict.fromkeys(names) if n]))
    if args.limit:
        targets = targets[: args.limit]
    print(f"待查 {len(targets)} 款（总 {len(records)}）")

    ok = miss = 0
    for i, (g, e, names) in enumerate(targets, 1):
        year = None
        rel = str((manual.get(g.get('id')) or {}).get("release") or e.get("release") or "")
        m = re.match(r"(\d{4})", rel)
        if m:
            year = m.group(1)
        hit = None
        for q in names[:2]:
            items = search(q)
            hit = pick(items, names, [g.get("platform")], year)
            if hit:
                break
            time.sleep(SLEEP)
        gid = g.get("id")
        rec = enr.setdefault(gid, {})
        if hit:
            score = (hit.get("criticScoreSummary") or {}).get("score")
            if score and int(score) > 0:   # 0 表示"还没出分"，不是零分
                rec["metacritic"] = int(score)
            if not rec.get("release") and hit.get("releaseDate"):
                rec["release"] = str(hit["releaseDate"])[:10]
            if not rec.get("genre") and hit.get("genres"):
                rec["genre"] = genres_to_cn(hit["genres"])
            if not rec.get("en"):
                rec["en"] = hit.get("title")
            ok += 1
            print(f"  [{i}/{len(targets)}] {g.get('name')} → {score} · {hit.get('title')}")
        else:
            miss += 1
            print(f"  [{i}/{len(targets)}] {g.get('name')} → 没找到")
        if i % 15 == 0:
            with open(enr_path + ".tmp", "w", encoding="utf-8") as fh:
                json.dump(enr, fh, ensure_ascii=False, indent=1)
            os.replace(enr_path + ".tmp", enr_path)
        time.sleep(SLEEP)

    with open(enr_path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(enr, fh, ensure_ascii=False, indent=1)
    os.replace(enr_path + ".tmp", enr_path)
    print(f"完成：命中 {ok} · 没找到 {miss}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
