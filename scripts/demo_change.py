#!/usr/bin/env python3
"""End-to-end change check (SRS phase 4) on a COPY of the input.

    python scripts/demo_change.py --opening D01 --delta 100 [--with-blender]

1. copies data/plan.json, widens the opening by --delta mm (offset kept, so it grows
   towards the wall end);
2. builds the copy into out_variant/ (the primary out/ is not touched);
3. prints what changed: affected faces must lose delta x height each; floor area,
   perimeter and the door count must stay the same;
4. saves out_variant/compare_<ID>.png — the opening on both overlays side by side.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

import build  # noqa: E402


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default=os.path.join(ROOT, "data", "plan.json"))
    ap.add_argument("--opening", required=True, help="ID проёма, например D01")
    ap.add_argument("--delta", type=float, default=100.0, help="изменение ширины, мм")
    ap.add_argument("--out", default=os.path.join(ROOT, "out_variant"))
    ap.add_argument("--with-blender", action="store_true", help="пересобрать и .blend (для видео)")
    args = ap.parse_args()

    base_plan = os.path.abspath(args.plan)
    raw = load(base_plan)
    variant = copy.deepcopy(raw)
    hits = [o for o in variant["openings"] if o["id"] == args.opening]
    if not hits:
        print(f"Проём {args.opening} не найден")
        return 1
    o = hits[0]
    old_w = o["width_mm"]
    o["width_mm"] = old_w + args.delta
    o["note"] = (o.get("note", "") + f" [вариант: ширина {old_w:.0f} → {o['width_mm']:.0f} мм]").strip()

    os.makedirs(args.out + ".input", exist_ok=True)
    var_path = os.path.join(args.out + ".input", "plan_variant.json")
    # keep the source PDF reachable from the new location
    src = variant.get("source", {}).get("file")
    if src:
        abs_src = os.path.normpath(os.path.join(os.path.dirname(base_plan), src))
        variant["source"]["file"] = os.path.relpath(abs_src, os.path.dirname(var_path))
    with open(var_path, "w", encoding="utf-8") as fh:
        json.dump(variant, fh, ensure_ascii=False, indent=2)

    base_out = os.path.join(ROOT, "out_base_for_demo")
    flags = [] if args.with_blender else ["--skip-blender"]
    print("== Исходный план")
    if build.main(["--plan", base_plan, "--out", base_out, "--skip-blender"]) != 0:
        return 1
    print(f"\n== Вариант: {args.opening} шире на {args.delta:.0f} мм")
    if build.main(["--plan", var_path, "--out", args.out] + flags) != 0:
        return 1

    before_all = load(os.path.join(base_out, "quantities.json"))
    after_all = load(os.path.join(args.out, "quantities.json"))
    before = {z["id"]: z for z in before_all["zones"]}
    after = {z["id"]: z for z in after_all["zones"]}

    print("\n== Что изменилось")
    print(f"{'Грань / показатель':<34}{'было':>9}{'стало':>9}{'Δ':>9}")
    for zid, za in after.items():
        zb = before[zid]
        fb = {f["key"]: f for f in zb["faces"]}
        for f in za["faces"]:
            if abs(f["net_m2"] - fb[f["key"]]["net_m2"]) > 1e-9:
                print(f"{f['key'] + ' нетто, м²':<34}{fb[f['key']]['net_m2']:>9.2f}{f['net_m2']:>9.2f}"
                      f"{f['net_m2'] - fb[f['key']]['net_m2']:>+9.2f}")
        for key, label in (("floor_m2", "пол, м²"), ("perimeter_m", "периметр, м")):
            if za[key] != zb[key]:
                print(f"!! {zid} {label} изменился: {zb[key]} → {za[key]}")
    same_floor = all(after[z]["floor_m2"] == before[z]["floor_m2"] for z in after)
    same_perim = all(after[z]["perimeter_m"] == before[z]["perimeter_m"] for z in after)
    same_doors = after_all["counts"]["doors"] == before_all["counts"]["doors"]
    print(f"\nПол без изменений: {'да' if same_floor else 'НЕТ'}; периметр без изменений: "
          f"{'да' if same_perim else 'НЕТ'}; число дверей без изменений: {'да' if same_doors else 'НЕТ'}")
    base_pdf = os.path.join(base_out, "overlay.pdf")
    var_pdf = os.path.join(args.out, "overlay.pdf")
    if os.path.exists(base_pdf) and os.path.exists(var_pdf):
        from aptplan.model import parse_plan
        from aptplan.overlay import compare_opening
        png = os.path.join(args.out, f"compare_{args.opening}.png")
        compare_opening(base_pdf, var_pdf, parse_plan(variant, os.path.dirname(var_path)), args.opening,
                        [f"было: {args.opening} {old_w:.0f} мм", f"стало: {args.opening} {o['width_mm']:.0f} мм"], png)
        print(f"Сравнение проёма: {os.path.relpath(png)}")
    print(f"Результат варианта: {os.path.relpath(args.out)}  (основной out/ не изменён)")
    return 0 if (same_floor and same_perim and same_doors) else 1


if __name__ == "__main__":
    sys.exit(main())
