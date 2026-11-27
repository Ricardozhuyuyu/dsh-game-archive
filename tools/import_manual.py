#!/usr/bin/env python3
"""把「游戏档案-字段总表.csv」里填好的内容导入 manual.json（插件里优先级最高的那层）。

用法：
    python3 tools/import_manual.py ~/Documents/deepseek-harness/work/游戏档案-字段总表.csv
    python3 tools/import_manual.py 表格.csv --out ~/Documents/deepseek-harness/work/游戏档案

规则：
  · 只认 id 这一列；空单元格不会覆盖已有值，想清空就把那格写成 -（减号）
  · 发售价/币种/现价 三个都空就不写价格
  · 填完重启 DSH 就生效；这个文件不会被同步覆盖
"""
import argparse
import csv
import json
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="填好的 CSV（游戏档案-字段总表.csv）")
    ap.add_argument("--out", default=os.path.expanduser("~/Documents/deepseek-harness/work/游戏档案"),
                    help="数据目录（默认 ~/Documents/deepseek-harness/work/游戏档案）")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"找不到 {args.csv}")
        return 2

    target = os.path.join(args.out, "manual.json")
    old = {}
    if os.path.exists(target):
        try:
            old = json.load(open(target, encoding="utf-8")) or {}
        except Exception:
            old = {}

    # 当前生效值（records + enrichment + name-cn），只把「填得跟现在不一样」的格子记成人工值，
    # 这样没动的字段还能继续跟着自动同步走。
    rec_path = os.path.join(args.out, "records.json")
    enr_path = os.path.join(args.out, "enrichment.json")
    cn_path = os.path.join(args.out, "name-cn.json")
    records = {}
    try:
        for g in (json.load(open(rec_path, encoding="utf-8")).get("games") or []):
            records[g.get("id")] = g
    except Exception:
        pass
    try:
        enr = json.load(open(enr_path, encoding="utf-8")) or {}
    except Exception:
        enr = {}
    try:
        name_cn = json.load(open(cn_path, encoding="utf-8")) or {}
    except Exception:
        name_cn = {}

    def current(gid):
        g = records.get(gid) or {}
        e = enr.get(gid) or {}
        nm = g.get("name") or ""
        has_cjk = any('\u4e00' <= ch <= '\u9fff' for ch in nm)
        cur = {
            "cn": name_cn.get(nm) or e.get("cn") or (nm if has_cjk else ""),
            "en": e.get("en") or ("" if has_cjk else nm),
            "release": e.get("release") or "",
            "metacritic": e.get("metacritic") or "",
            "genre": e.get("genre") or "",
        }
        pr = e.get("price") or {}
        cur["发售价"] = pr.get("initial", "") if pr else ""
        return cur

    n = 0
    with open(args.csv, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            gid = (row.get("id") or "").strip()
            if not gid:
                continue
            rec = dict(old.get(gid) or {})
            now = current(gid)
            changed = False
            for key, col in (("cn", "中文名"), ("en", "英文名"), ("release", "发售日"),
                             ("metacritic", "M站分"), ("genre", "类型")):
                val = (row.get(col) or "").strip()
                if not val:
                    continue
                if val == "-":
                    if key in rec:
                        rec.pop(key)
                        changed = True
                    continue
                if str(now.get(key, "")).strip() == val:
                    continue                      # 跟现在一致，不算人工改动
                rec[key] = int(val) if key == "metacritic" and val.isdigit() else val
                changed = True
            price_val = (row.get("发售价") or "").strip()
            cur = (row.get("币种") or "CNY").strip() or "CNY"
            final = (row.get("现价") or "").strip()
            if (price_val and float(price_val or 0) > 0) or final:
                try:
                    rec["price"] = {
                        "currency": cur,
                        "initial": float(price_val or 0),
                        "final": float(final or price_val or 0),
                        "free": float(price_val or 0) <= 0,
                    }
                except ValueError:
                    print(f"  ! {gid} 价格不是数字，跳过价格")
            if rec and (changed or gid in old):
                old[gid] = rec
                n += 1

    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(old, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, target)
    print(f"写入 {target}：{n} 条（共 {len(old)} 条人工数据）")
    print("重启 DSH 生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
