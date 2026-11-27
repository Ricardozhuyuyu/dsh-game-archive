#!/usr/bin/env python3
"""把全库导成一张表（CSV + XLSX），方便交给别的 AI / 自己填。

    python3 tools/export_table.py

产物（默认写到 ~/Documents/deepseek-harness/work/）：
    游戏档案-字段总表.csv / .xlsx      当前数据
    游戏档案-字段总表.baseline.csv     空白底本，import_manual.py 靠它判断你改了哪些格子

填完表后：
    python3 tools/import_manual.py 游戏档案-字段总表.csv
    然后重启 DSH。
"""
import argparse
import csv
import json
import re
import os
import sys


NOT_A_GAME = re.compile(r"(^|[^a-z])(demo|试玩|预览版|friend's pass)([^a-z]|$)", re.I)


def load(out):
    try:
        banned = json.load(open(os.path.join(out, "exclude.json"), encoding="utf-8"))
    except Exception:
        banned = {}
    rec = json.load(open(os.path.join(out, "records.json"), encoding="utf-8"))
    try:
        enr = json.load(open(os.path.join(out, "enrichment.json"), encoding="utf-8"))
    except Exception:
        enr = {}
    try:
        name_cn = json.load(open(os.path.join(out, "name-cn.json"), encoding="utf-8"))
    except Exception:
        name_cn = {}
    try:
        manual = json.load(open(os.path.join(out, "manual.json"), encoding="utf-8"))
    except Exception:
        manual = {}
    try:
        extra = json.load(open(os.path.join(out, "extra-games.json"), encoding="utf-8"))
    except Exception:
        extra = {}
    games = list(rec.get("games") or [])
    # 手动补录的游戏（任天堂老游戏这类）也要进总表，否则没法回填
    for g in (extra.get("games") or []):
        if not (g and g.get("id") and g.get("name")):
            continue
        games.append({
            "id": g["id"],
            "name": g["name"],
            "platform": g.get("platform") or "Switch",
            "hours": g.get("hours") or 0,
            "progress": g.get("progress"),
            "ach": g.get("ach") or "",
            "last": g.get("last") or ((g.get("months") or {}).get("to") or ""),
            "cn": g.get("cn") or "",
        })
    rows = []
    for g in games:
        nm0 = g.get("name") or ""
        if NOT_A_GAME.search(nm0):
            continue
        if nm0 in (banned.get(g.get("platform")) or []):
            continue
        gid = g.get("id")
        e = enr.get(gid) or {}
        man = manual.get(gid) or {}
        nm = g.get("name") or ""
        price = man.get("price") or e.get("price") or {}
        release = str(man.get("release") or e.get("release") or "").strip()
        if not release[:4].isdigit():
            release = ""
        cn = man.get("cn") or name_cn.get(nm) or e.get("cn") or ""
        en = man.get("en") or e.get("en") or ("" if any("\u4e00" <= c <= "\u9fff" for c in nm) else nm)
        miss = []
        if not cn:
            miss.append("中文名")
        if not en:
            miss.append("英文名")
        if not release:
            miss.append("发售日")
        if not (man.get("metacritic") or e.get("metacritic")):
            miss.append("M站分")
        if not (man.get("genre") or e.get("genre")):
            miss.append("类型")
        if not price:
            miss.append("发售价")
        rows.append({
            "id": gid, "平台": g.get("platform"), "原名": nm, "中文名": cn, "英文名": en,
            "发售日": release,
            "M站分": man.get("metacritic") or e.get("metacritic") or "",
            "类型": man.get("genre") or e.get("genre") or "",
            "发售价": price.get("initial", ""), "币种": price.get("currency", ""),
            "现价": price.get("final", ""),
            "时长h": round(g.get("hours") or 0, 1),
            "完成度%": g.get("progress") if g.get("progress") is not None else "",
            "最后游玩": g.get("last") or "",
            "缺字段": "、".join(miss),
        })
    rows.sort(key=lambda r: -(r["时长h"] or 0))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expanduser("~/Documents/deepseek-harness/work/游戏档案"))
    ap.add_argument("--dest", default=os.path.expanduser("~/Documents/deepseek-harness/work"))
    args = ap.parse_args()
    rows = load(args.out)
    cols = list(rows[0].keys())
    os.makedirs(args.dest, exist_ok=True)
    base = os.path.join(args.dest, "游戏档案-字段总表")
    with open(base + ".csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    with open(base + ".baseline.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = "全部游戏"
        ws.append(cols)
        for r in rows:
            ws.append([r[c] for c in cols])
        fill = PatternFill("solid", fgColor="1F2937")
        for i, c in enumerate(cols, 1):
            cell = ws.cell(row=1, column=i)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = fill
            ws.column_dimensions[cell.column_letter].width = max(9, min(34, len(c) * 2 + 6))
        ws.freeze_panes = "C2"
        ws.auto_filter.ref = ws.dimensions
        wb.save(base + ".xlsx")
    except ImportError:
        print("（没装 openpyxl，只写了 CSV）")
    print(f"{len(rows)} 款 → {base}.csv / .xlsx / .baseline.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
