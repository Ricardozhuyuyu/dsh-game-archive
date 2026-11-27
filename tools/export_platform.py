#!/usr/bin/env python3
"""按平台导出明细（默认 PSN + Switch）。

    python3 tools/export_platform.py                      # PSN、Switch
    python3 tools/export_platform.py --platforms PSN,Switch,Xbox
    python3 tools/export_platform.py --fmt csv            # 只出 CSV

产物：~/Documents/deepseek-harness/work/<平台>明细.csv / .xlsx
"""
import argparse
import csv
import datetime as dt
import json
import os
import re
import sys

STATUS_CN = {
    "playing": "在玩", "finished": "通关", "platinum": "白金",
    "shelved": "荒废", "dropped": "弃坑", "backlog": "还没碰过", "wish": "想玩",
}
NOT_A_GAME = re.compile(
    r"(^|[^a-z])(demo|trial|beta|试玩|体验版|体験版|预览|网络测试|ネットワークテスト|公测|friend's pass)([^a-z]|$)", re.I)
PLAT_CN = {"Steam": "Steam", "PSN": "PSN", "Switch": "Switch", "Xbox": "Xbox", "Epic": "Epic"}


def days_since(s):
    if not s:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(s))
    if not m:
        m2 = re.match(r"(\d{4})$", str(s))
        if m2:
            return (dt.date.today() - dt.date(int(m2.group(1)), 6, 15)).days
        return None
    try:
        return (dt.date.today() - dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days
    except ValueError:
        return None


FX = {"CNY": 1, "USD": 7.1, "HKD": 0.91, "JPY": 0.048, "EUR": 7.7, "TWD": 0.225, "GBP": 9.0}


def iso(d):
    s = str(d or "").strip()
    for pat, fmt in ((r"^(\d{4})-(\d{1,2})-(\d{1,2})", None), (r"^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})", None),
                     (r"^(\d{4})[/.](\d{1,2})[/.](\d{1,2})", None)):
        m = re.match(pat, s)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s if re.match(r"^\d{4}$", s) else ""


def cny(initial, cur):
    try:
        v = float(initial)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return 0
    return round(v * FX.get(str(cur or "CNY").upper(), 1), 2)


def status_of(g, man):
    manual = (man or {}).get("status")
    if manual:
        return STATUS_CN.get(manual, manual)
    h = g.get("hours") or 0
    if h < 0.1:
        return "还没碰过"
    if g.get("progress") is not None and g["progress"] >= 90:
        return "白金"
    d = days_since((man or {}).get("months", {}).get("to") if isinstance((man or {}).get("months"), dict) else g.get("last"))
    if d is None:
        d = days_since(g.get("last"))
    if d is not None and d <= 30:
        return "在玩"
    return "荒废"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expanduser("~/Documents/deepseek-harness/work/游戏档案"))
    ap.add_argument("--dest", default=os.path.expanduser("~/Documents/deepseek-harness/work"))
    ap.add_argument("--platforms", default="PSN,Switch")
    ap.add_argument("--fmt", default="both", choices=["csv", "xlsx", "both"])
    args = ap.parse_args()
    want = [p.strip() for p in args.platforms.split(",") if p.strip()]

    def load(name, fallback):
        p = os.path.join(args.out, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        return fallback

    records = load("records.json", {}).get("games") or []
    enr = load("enrichment.json", {})
    manual = load("manual.json", {})
    userdata = load("userdata.json", {})
    try:
        with open(os.path.join(args.out, "name-cn.json"), encoding="utf-8") as fh:
            name_cn = json.load(fh)
    except Exception:
        name_cn = {}

    os.makedirs(args.dest, exist_ok=True)
    made = []
    sheets = {}
    for plat in want:
        rows = []
        for g in records:
            if g.get("platform") != plat:
                continue
            if NOT_A_GAME.search(g.get("name") or ""):
                continue
            gid = g.get("id")
            e = enr.get(gid) or {}
            man = manual.get(gid) or {}
            ud = userdata.get(gid) or {}
            price = man.get("price") or e.get("price") or {}
            rows.append({
                "游戏": man.get("cn") or name_cn.get(g.get("name")) or g.get("name"),
                "英文名": (lambda en, disp: "" if (en or "").strip().lower() == (disp or "").strip().lower() else en)(
                    man.get("en") or e.get("en") or "",
                    man.get("cn") or name_cn.get(g.get("name")) or g.get("name")),
                "时长(h)": round(g.get("hours") or 0, 1),
                "状态": status_of(g, ud),
                "完成度%": g.get("progress") if g.get("progress") is not None else "",
                "奖杯/成就": g.get("ach") or "",
                "最后游玩": g.get("last") or "",
                "发售日": iso(man.get("release") or e.get("release") or ""),
                "M站分": (lambda v: int(float(v)) if v else "")(man.get("metacritic") or e.get("metacritic")),
                "类型": man.get("genre") or e.get("genre") or "",
                "发售价": price.get("initial", ""),
                "币种": price.get("currency", ""),
                "发售价(CNY)": cny(price.get("initial"), price.get("currency")),
                "备注": g.get("detail") or "",
            })
        rows.sort(key=lambda r: -(r["时长(h)"] or 0))
        sheets[plat] = rows
        if args.fmt in ("csv", "both"):
            path = os.path.join(args.dest, f"{plat}明细.csv")
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            made.append(path)
        print(f"{plat}: {len(rows)} 款 · {sum(r['时长(h)'] for r in rows):.1f} 小时")

    if args.fmt in ("xlsx", "both"):
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill
            wb = Workbook()
            wb.remove(wb.active)
            for plat, rows in sheets.items():
                ws = wb.create_sheet(plat)
                cols = list(rows[0].keys())
                ws.append(cols)
                for r in rows:
                    ws.append([r[c] for c in cols])
                fill = PatternFill("solid", fgColor="1F2937")
                for i, c in enumerate(cols, 1):
                    cell = ws.cell(row=1, column=i)
                    cell.font = Font(bold=True, color="FFFFFF")
                    cell.fill = fill
                ws.column_dimensions["A"].width = 30
                ws.column_dimensions["B"].width = 34
                ws.column_dimensions["C"].width = 30
                for letter in "DEFGHIJKLMN":
                    ws.column_dimensions[letter].width = 12
                ws.freeze_panes = "B2"
                ws.auto_filter.ref = ws.dimensions
            path = os.path.join(args.dest, "PSN-Switch明细.xlsx" if want == ["PSN", "Switch"] else "游戏明细.xlsx")
            wb.save(path)
            made.append(path)
        except ImportError:
            print("（没装 openpyxl，只写了 CSV）")
    print("产出：" + " / ".join(made))
    return 0


if __name__ == "__main__":
    sys.exit(main())
