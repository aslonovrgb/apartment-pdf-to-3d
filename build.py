#!/usr/bin/env python3
"""One-command build: plan.json -> apartment.xlsx, apartment.blend, renders, PDF overlay.

    python build.py                       # data/plan.json -> out/
    python build.py --plan X.json --out Y # any plan / output folder

Nothing is published on a blocking error: the build runs in <out>.tmp and
replaces <out> only after every step succeeded.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from typing import List, Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))

from aptplan.issues import errors, warnings  # noqa: E402
from aptplan.quantities import compute, m, m2  # noqa: E402
from aptplan.report import summary  # noqa: E402
from aptplan.validate import load_and_validate  # noqa: E402

MARKER = ".aptplan-build"
BLENDER_SCRIPT = os.path.join(ROOT, "blender", "build_scene.py")


def find_blender() -> Optional[str]:
    for c in (os.environ.get("BLENDER"), shutil.which("blender"),
              "/Applications/Blender.app/Contents/MacOS/Blender"):
        if c and os.path.exists(c):
            return c
    return None


def publish(tmp: str, out: str) -> None:
    if os.path.exists(out):
        if not os.path.exists(os.path.join(out, MARKER)):
            raise SystemExit(f"Папка {out} существует и создана не этим скриптом — не перезаписываю.")
        shutil.rmtree(out)
    os.replace(tmp, out)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", default=os.path.join(ROOT, "data", "plan.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "out"))
    ap.add_argument("--skip-blender", action="store_true", help="только проверка, Excel и наложение")
    ap.add_argument("--no-render", action="store_true", help="собрать .blend без PNG-рендеров")
    args = ap.parse_args(argv)

    plan_path = os.path.abspath(args.plan)
    out = os.path.abspath(args.out)
    print(f"[1/5] Проверка {os.path.relpath(plan_path)}")
    plan, issues = load_and_validate(plan_path)
    if plan is not None:
        q = compute(plan)
        issues += q.issues
    for i in issues:
        print("   ", i)
    errs = errors(issues)
    if errs:
        print(f"Сборка остановлена: {len(errs)} блокирующих ошибок. Результат не опубликован.")
        return 1
    print(f"    ок: зон {len(plan.zones)}, стен {len(plan.walls)}, проёмов {len(plan.openings)}, "
          f"мебели {len(plan.furniture)}; предупреждений {len(warnings(issues))}")

    tmp = out + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    open(os.path.join(tmp, MARKER), "w").close()

    print("[2/5] Ведомость объёмов → apartment.xlsx")
    from aptplan.excel import write_workbook
    write_workbook(plan, q, issues, os.path.join(tmp, "apartment.xlsx"))
    with open(os.path.join(tmp, "quantities.json"), "w", encoding="utf-8") as fh:
        json.dump(summary(plan, q), fh, ensure_ascii=False, indent=2)
    shutil.copyfile(plan_path, os.path.join(tmp, "plan.json"))

    src = plan.source_path()
    if src and os.path.exists(src):
        print("[3/5] Наложение разметки на PDF → overlay.pdf, overlay.png")
        from aptplan.overlay import render_overlay
        render_overlay(plan, q, os.path.join(tmp, "overlay.pdf"), os.path.join(tmp, "overlay.png"))
    else:
        print("[3/5] Наложение пропущено: нет файла источника")

    if args.skip_blender:
        print("[4/5] Blender пропущен (--skip-blender)")
    else:
        blender = find_blender()
        if not blender:
            print("Blender не найден: укажите путь в переменной BLENDER. Результат не опубликован.")
            return 1
        print(f"[4/5] Сцена Blender → apartment.blend, top.png, iso.png ({blender})")
        cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python", BLENDER_SCRIPT,
               "--", "--plan", plan_path, "--out", tmp]
        if args.no_render:
            cmd.append("--no-render")
        res = subprocess.run(cmd, capture_output=True, text=True)
        expected = ["apartment.blend"] + ([] if args.no_render else ["top.png", "iso.png"])
        missing = [f for f in expected if not os.path.exists(os.path.join(tmp, f))]
        if res.returncode != 0 or missing:
            print(res.stdout[-3000:])
            print(res.stderr[-3000:])
            print(f"Blender завершился с ошибкой (код {res.returncode}, нет: {missing}). Результат не опубликован.")
            return 1

    print(f"[5/5] Публикация → {os.path.relpath(out)}")
    publish(tmp, out)

    print()
    print(f"{'Зона':<6}{'Название':<26}{'Пол, м²':>9}{'Периметр, м':>13}{'Плинтус, м':>12}"
          f"{'Стены брутто':>14}{'нетто, м²':>11}")
    for zq in q.zones:
        print(f"{zq.zone.id:<6}{zq.zone.name[:25]:<26}{m2(zq.floor_area):>9.2f}{m(zq.perimeter):>13.2f}"
              f"{m(zq.plinth):>12.2f}{m2(zq.wall_gross):>14.2f}{m2(zq.wall_net):>11.2f}")
    print(f"Двери: {len(q.doors)}, окна: {len(q.windows)}, проёмы без заполнения: {len(q.doorways)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
