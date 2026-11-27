#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 data/tga-history.json —— 历年 TGA 全部奖项（获奖 + 提名）

数据源：Wikipedia 各年页面 https://en.wikipedia.org/wiki/The_Game_Awards_<YEAR>
（页面里主表格的形状：一行 <th> 放若干奖项名，紧跟一行 <td> 放对应结果；
  每个 <td> 里第一项是获奖者，后面是提名，用 <br> 分隔，条目形如「名字 – 开发商」。）

用法：
    python tools/build_tga_history.py                 # 抓 2014..2025 并写 data/tga-history.json
    python tools/build_tga_history.py --years 2025    # 只做某一年
    python tools/build_tga_history.py --cache /tmp    # 复用已下载的 html

产物结构：
    { "updated": "...", "source": "...", "years": [
        { "year": 2025, "categories": [
            { "category": "年度游戏", "categoryEn": "Game of the Year",
              "winner": "Clair Obscur: Expedition 33", "nominees": ["...", ...] } ] } ] }
"""

from __future__ import annotations

import argparse
import html as H
import json
import os
import re
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
SRC = "https://en.wikipedia.org/wiki/The_Game_Awards_{year}"

# 英文类别 → 中文（未知的保留英文）
CN = {
    "Game of the Year": "年度游戏",
    "Best Game Direction": "最佳游戏指导",
    "Best Narrative": "最佳叙事",
    "Best Art Direction": "最佳美术指导",
    "Best Score and Music": "最佳配乐",
    "Best Audio Design": "最佳音效设计",
    "Best Performance": "最佳演出",
    "Best Independent Game": "最佳独立游戏",
    "Best Debut Indie Game": "最佳新晋独立游戏",
    "Best Debut Game": "最佳新晋独立游戏",
    "Best Action Game": "最佳动作游戏",
    "Best Action/Adventure Game": "最佳动作冒险游戏",
    "Best Action / Adventure Game": "最佳动作冒险游戏",
    "Best Role Playing Game": "最佳角色扮演游戏",
    "Best RPG": "最佳角色扮演游戏",
    "Best Fighting Game": "最佳格斗游戏",
    "Best Family Game": "最佳家庭游戏",
    "Best Multiplayer Game": "最佳多人游戏",
    "Best Sports/Racing Game": "最佳体育竞速游戏",
    "Best Sports / Racing Game": "最佳体育竞速游戏",
    "Best Sim/Strategy Game": "最佳模拟策略游戏",
    "Best Strategy Game": "最佳策略游戏",
    "Best Sim / Strategy Game": "最佳模拟策略游戏",
    "Innovation in Accessibility": "无障碍创新奖",
    "Games for Impact": "最具影响力游戏",
    "Best Ongoing Game": "最佳持续运营游戏",
    "Best Community Support": "最佳社区支持",
    "Best VR / AR Game": "最佳 VR/AR 游戏",
    "Best VR/AR Game": "最佳 VR/AR 游戏",
    "Best Mobile Game": "最佳移动游戏",
    "Most Anticipated Game": "最受期待游戏",
    "Players' Voice": "玩家之声",
    "Best Esports Game": "最佳电竞游戏",
    "Best Esports Athlete": "最佳电竞选手",
    "Best Esports Team": "最佳电竞战队",
    "Best Esports Coach": "最佳电竞教练",
    "Best Esports Event": "最佳电竞赛事",
    "Content Creator of the Year": "年度内容创作者",
    "Best Adaptation": "最佳改编作品",
    "Industry Icon Award": "行业偶像奖",
    "Global Gaming Citizens": "全球游戏公民",
    "Trending Gamer": "年度趋势玩家",
    "Best Student Game": "最佳学生游戏",
    "Best Indie Game": "最佳独立游戏",
}


def log(*a):
    print(*a, flush=True)


def clean_lines(cell_html):
    """把 <td> 拆成干净文本行（每行一个条目 / 一个符号）。"""
    s = re.sub(r"<style.*?</style>", "", cell_html, flags=re.S)
    s = re.sub(r"<sup.*?</sup>", "", s, flags=re.S)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<li[^>]*>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = H.unescape(s)
    s = s.replace("\u00a0", " ").replace("\u2009", " ").replace("\u200b", "")
    s = re.sub(r"[ \t]+", " ", s)
    return [x.strip() for x in s.split("\n") if x.strip()]


def split_entries(lines, has_dagger):
    """把一行一行的文本，按「名字 – 开发商」聚合成 {name, nominee} 列表。"""
    entries = []
    buf = []
    for ln in lines:
        if ln in ("‡", "–", "-", "—", "/", "·"):
            continue
        if "‡" in ln:
            ln = ln.replace("‡", "").strip()
            has_dagger = True
        # 形如 "Name – Studio" 需要拆；但名字里也可能带 –
        buf.append(ln)
        joined = " ".join(buf)
        # 判断这一条是否结束：下一行是「开发商」还是新条目 —— 用 dash 判断
        entries.append(joined)
        buf = []

    out = []
    for e in entries:
        parts = re.split(r"\s+[–—]\s+", e, maxsplit=1)
        name = parts[0].strip()
        if not name or len(name) > 90:
            continue
        out.append(name)
    return out


def parse_year_html(html):
    """返回 [{category, categoryEn, winner, nominees}]"""
    blocks = re.split(r"<table", html)[1:]
    best = None
    for b in blocks:
        body = b.split("</table>", 1)[0]
        if "Game of the Year" not in body:
            continue
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", body, flags=re.S)
        parsed = {}
        pending = []
        for r in rows:
            ths = re.findall(r"<th[^>]*>(.*?)</th>", r, flags=re.S)
            tds = re.findall(r"<td[^>]*>(.*?)</td>", r, flags=re.S)
            if ths and not tds:
                pending = []
                for t in ths:
                    cell = " ".join(clean_lines(t))
                    if not cell or cell.lower() in ("award", "category", "nominees"):
                        continue
                    pending.append(cell)
                continue
            if tds and pending:
                for idx, td in enumerate(tds):
                    if idx >= len(pending):
                        break
                    cat = pending[idx]
                    lines = clean_lines(td)
                    if not lines:
                        continue
                    names = split_entries(lines, "‡" in td)
                    if not names:
                        continue
                    parsed.setdefault(cat, {"winner": names[0], "nominees": names[1:]})
                pending = []
        if parsed and (best is None or len(parsed) > len(best)):
            best = parsed
    if not best:
        return []
    out = []
    for cat, v in best.items():
        out.append({
            "category": CN.get(cat, cat),
            "categoryEn": cat,
            "winner": v["winner"],
            "nominees": v["nominees"],
        })
    return out


def fetch(year, cache_dir):
    path = os.path.join(cache_dir, f"tga_{year}.html") if cache_dir else ""
    if path and os.path.isfile(path) and os.path.getsize(path) > 10000:
        return open(path, encoding="utf-8", errors="ignore").read()
    url = SRC.format(year=year)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        html = r.read().decode("utf-8", "replace")
    if path:
        os.makedirs(cache_dir, exist_ok=True)
        open(path, "w", encoding="utf-8").write(html)
    return html


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 TGA 历年获奖/提名数据")
    ap.add_argument("--years", default="", help="逗号分隔的年份，默认 2014-2025")
    ap.add_argument("--cache", default="/tmp", help="html 缓存目录（默认 /tmp）")
    ap.add_argument("--out", default="data/tga-history.json", help="输出文件")
    args = ap.parse_args()

    years = ([int(x) for x in args.years.split(",") if x.strip()]
             if args.years else list(range(2014, 2026)))

    result = {"updated": time.strftime("%Y-%m-%d"), "source": SRC.format(year="<YEAR>"), "years": []}
    total = 0
    for y in years:
        try:
            html = fetch(y, args.cache)
        except Exception as e:
            log(f"✗ {y}：抓取失败 {type(e).__name__}")
            continue
        cats = parse_year_html(html)
        if not cats:
            log(f"✗ {y}：解析不到奖项（页面结构可能又变了）")
            continue
        result["years"].append({"year": y, "categories": cats})
        total += len(cats)
        log(f"✓ {y}：{len(cats)} 个奖项 · 年度游戏 = "
            f"{next((c['winner'] for c in cats if c['category'] == '年度游戏'), '?')}")
        time.sleep(0.6)

    result["years"].sort(key=lambda x: x["year"])
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    json.dump(result, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, out)
    log("")
    log(f"共 {len(result['years'])} 年 / {total} 个奖项 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
