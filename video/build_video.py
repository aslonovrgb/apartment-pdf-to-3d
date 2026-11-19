#!/usr/bin/env python3
"""Demo video (60-90 s) built from the real build results.

    make && make demo DOOR=D03
    .venv/bin/python video/build_video.py

Order required by the SRS: PDF -> geometry match -> change -> Excel.
Every frame comes from the build: the source PDF, out/overlay.pdf, a Blender orbit of
out/apartment.blend, the captured output of `make demo DOOR=D03`, out_variant/compare_D03.png
and the cells of out_variant/apartment.xlsx. Voice-over: macOS `say` (Milena), text in
video/narration.txt. Needs ffmpeg and Blender.

Output: video/apartment_demo.mp4 (with voice) and video/apartment_demo_no_voice.mp4.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import fitz
import openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VID = os.path.join(ROOT, "video")
BUILD = os.path.join(VID, "build")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from aptplan.model import load_plan_unchecked  # noqa: E402

W, H, FPS = 1920, 1080, 30
LEAD, TAIL = 0.25, 0.55            # silence before / after each narration segment, s
VOICE, RATE = "Milena", "205"
BAR_H = 128                        # subtitle bar height

FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_B = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
MONO = "/System/Library/Fonts/SFNSMono.ttf"
if not os.path.exists(MONO):
    MONO = "/System/Library/Fonts/Supplemental/Courier New.ttf"

INK = (0.12, 0.13, 0.15)
BG = (0.965, 0.96, 0.95)
ACCENT = (0.93, 0.42, 0.05)
HILITE = (1.0, 0.93, 0.62)
STEPS = ["PDF", "геометрия", "изменение", "Excel"]

BLENDER = shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"


# --------------------------------------------------------------------------- helpers

def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def duration(path: str) -> float:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "csv=p=0", path])
    return float(out)


class Canvas:
    """A 1920x1080 page; 1 pt = 1 px when rendered at 72 dpi."""

    fonts = {"r": fitz.Font(fontfile=FONT), "b": fitz.Font(fontfile=FONT_B), "m": fitz.Font(fontfile=MONO)}

    def __init__(self, bg=BG):
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=W, height=H)
        for k, path in (("r", FONT), ("b", FONT_B), ("m", MONO)):
            self.page.insert_font(fontname=k, fontfile=path)
        if bg is not None:
            self.page.draw_rect(self.page.rect, color=None, fill=bg)

    def text(self, x, y, s, size=30, font="r", color=INK, opacity=1.0):
        self.page.insert_text(fitz.Point(x, y), s, fontsize=size, fontname=font, color=color,
                              fill_opacity=opacity)

    def width(self, s, size, font="r"):
        return self.fonts[font].text_length(s, fontsize=size)

    def rect(self, r, fill=None, color=None, width=1.0, radius=None, opacity=1.0):
        self.page.draw_rect(fitz.Rect(r), color=color, fill=fill, width=width, radius=radius,
                            fill_opacity=opacity, stroke_opacity=opacity)

    def image(self, r, path):
        self.page.insert_image(fitz.Rect(r), filename=path, keep_proportion=True)

    def save(self, path, alpha=False):
        self.page.get_pixmap(dpi=72, alpha=alpha).save(path)
        self.doc.close()


def wrap(c: Canvas, s: str, size: float, max_w: float, font="r"):
    lines, cur = [], ""
    for word in s.split():
        t = (cur + " " + word).strip()
        if c.width(t, size, font) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def caption_layer(path: str, step: int, label: str, subtitle: str) -> None:
    """Transparent overlay: step label, SRS breadcrumb and the subtitle bar."""
    c = Canvas(bg=None)
    if label:
        tw = c.width(label, 30, "b")
        c.rect((40, 34, 40 + tw + 44, 92), fill=INK, radius=0.5, opacity=0.9)
        c.text(62, 74, label, 30, "b", (1, 1, 1))
    # breadcrumb PDF -> геометрия -> изменение -> Excel (not on the closing card)
    parts, x = [], 0.0
    if step == 0:
        parts = []
    for i, name in enumerate(STEPS if step else []):
        parts.append((name, i + 1 == step))
        if i < len(STEPS) - 1:
            parts.append(("→", False))
    total = sum(c.width(n, 24, "b" if a else "r") + 14 for n, a in parts) + 30
    x = W - 40 - total
    if parts:
        c.rect((x, 38, W - 40, 88), fill=INK, radius=0.5, opacity=0.78)
    x += 22
    for name, active in parts:
        col = (1, 1, 1) if active else (0.62, 0.64, 0.68)
        c.text(x, 71, name, 24, "b" if active else "r", col)
        x += c.width(name, 24, "b" if active else "r") + 14
    if subtitle:
        c.rect((0, H - BAR_H, W, H), fill=INK, opacity=0.86)
        lines = wrap(c, subtitle, 33, W - 140)
        y0 = H - BAR_H / 2 - (len(lines) - 1) * 22 + 11
        for k, line in enumerate(lines):
            c.text((W - c.width(line, 33)) / 2, y0 + k * 44, line, 33, "r", (1, 1, 1))
    c.save(path, alpha=True)


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def window(cx, cy, w):
    h = w * H / W
    return fitz.Rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def lerp_rect(a: fitz.Rect, b: fitz.Rect, t: float) -> fitz.Rect:
    return fitz.Rect(a.x0 + (b.x0 - a.x0) * t, a.y0 + (b.y0 - a.y0) * t,
                     a.x1 + (b.x1 - a.x1) * t, a.y1 + (b.y1 - a.y1) * t)


def zoom_frames(src_pdf: str, keys, total: float, out_dir: str):
    """Frames of a PDF page seen through a moving 16:9 window. keys: [(time, Rect)]."""
    os.makedirs(out_dir, exist_ok=True)
    src = fitz.open(src_pdf)
    pr = src[0].rect
    n = int(round(total * FPS))
    files = []
    for i in range(n):
        t = i / FPS
        k = max(j for j in range(len(keys)) if keys[j][0] <= t) if t >= keys[0][0] else 0
        if k == len(keys) - 1:
            win = keys[-1][1]
        else:
            (t0, r0), (t1, r1) = keys[k], keys[k + 1]
            win = lerp_rect(r0, r1, ease((t - t0) / (t1 - t0)))
        c = Canvas(bg=(1, 1, 1))
        s = W / win.width
        clip = win & pr
        target = fitz.Rect((clip.x0 - win.x0) * s, (clip.y0 - win.y0) * s,
                           (clip.x1 - win.x0) * s, (clip.y1 - win.y0) * s)
        c.page.show_pdf_page(target, src, 0, clip=clip)
        f = os.path.join(out_dir, f"{i:04d}.png")
        c.save(f)
        files.append((f, 1.0 / FPS))
    src.close()
    return files


def fit_image(path_in: str, path_out: str, bg=BG, box=None, frame=False):
    c = Canvas(bg=bg)
    box = box or (60, 120, W - 60, H - BAR_H - 30)
    if frame:
        c.rect(box, fill=(1, 1, 1), color=(0.82, 0.82, 0.82), width=1.5)
        box = (box[0] + 16, box[1] + 16, box[2] - 16, box[3] - 16)
    c.image(box, path_in)
    c.save(path_out)
    return path_out


# --------------------------------------------------------------------------- segments

def seg_pdf(plan, d, out):
    """1 · PDF: full sheet, then zoom to the four calibration dimension lines (highlighted)."""
    marked = os.path.join(BUILD, "source_marked.pdf")
    doc = fitz.open(plan.source_path())
    pg = doc[0]
    for cal in plan.source["scale"]["calibration"]:
        a, b = fitz.Point(cal["pt_a"]), fitz.Point(cal["pt_b"])
        pg.draw_line(a, b, color=ACCENT, width=2.6, stroke_opacity=0.9)
        for p in (a, b):
            pg.draw_circle(p, 2.6, color=ACCENT, fill=ACCENT)
    doc.save(marked)
    full = window(595.3, 421.0, 842 * W / H * 1.03)
    near = window(410.0, 238.0, 560.0)
    keys = [(0.0, full), (2.6, full), (6.4, near)]
    return zoom_frames(marked, keys, d, os.path.join(out, "f"))


def seg_overlay(plan, d, out):
    """2 · geometry match: overlay on the PDF, zoom to the hall / doors, back out."""
    s = float(plan.source["scale"]["pt_per_m"]) / 1000.0
    ox, oy = plan.source["origin"]["pdf_pt"]
    pt = lambda x, y: (ox + x * s, oy - y * s)  # noqa: E731
    a, b = pt(-385, 9720), pt(12539, -200)
    # keep the plan above the subtitle bar: taller window, centre shifted down
    full = window((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 34, (b[1] - a[1] + 100) * W / H)
    cx, cy = pt(6650, 2450)
    near = window(cx, cy, 440.0)
    t_out = max(9.0, d - 4.2)
    keys = [(0.0, full), (3.4, full), (7.0, near), (t_out, near), (t_out + 3.0, full)]
    return zoom_frames(os.path.join(ROOT, "out", "overlay.pdf"), keys, d, os.path.join(out, "f"))


def seg_blender(plan, d, out):
    """2 · model: orbit around out/apartment.blend, then the top view."""
    top_hold = 3.0
    n = int(round((d - top_hold) * FPS))
    odir = os.path.join(out, "orbit")
    shutil.rmtree(odir, ignore_errors=True)
    run([BLENDER, "-b", "--factory-startup", os.path.join(ROOT, "out", "apartment.blend"),
         "--python", os.path.join(VID, "blender_orbit.py"), "--python-exit-code", "1", "--", odir, str(n)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    files = [(os.path.join(odir, f"{i:04d}.png"), 1.0 / FPS) for i in range(1, n + 1)]
    top = fit_image(os.path.join(ROOT, "out", "top.png"), os.path.join(out, "top.png"), bg=(1, 1, 1),
                    box=(60, 104, W - 60, H - BAR_H - 12))
    return files + [(top, top_hold)]


def terminal(lines, path, title="Терминал — make demo DOOR=D03"):
    c = Canvas(bg=BG)
    x0, y0, x1, y1 = 130, 112, W - 130, H - BAR_H - 26
    c.rect((x0, y0, x1, y1), fill=(0.11, 0.12, 0.14), radius=0.02)
    c.rect((x0, y0, x1, y0 + 46), fill=(0.20, 0.21, 0.24), radius=0.02)
    for k, col in enumerate(((1, 0.37, 0.34), (1, 0.74, 0.18), (0.16, 0.79, 0.25))):
        c.page.draw_circle(fitz.Point(x0 + 28 + 26 * k, y0 + 23), 8, color=None, fill=col)
    c.text((x0 + x1 - c.width(title, 22)) / 2, y0 + 31, title, 22, "r", (0.78, 0.79, 0.82))
    y = y0 + 92
    for text, style in lines:
        col = {"cmd": (1, 1, 1), "dim": (0.55, 0.57, 0.62), "ok": (0.45, 0.85, 0.45),
               "hit": (1.0, 0.82, 0.30), "": (0.86, 0.87, 0.89)}[style]
        c.text(x0 + 40, y, text, 25, "m", col)
        y += 37
    c.save(path)
    return path


def seg_change(plan, d, out, demo_out: str):
    """3 · change: `make demo DOOR=D03` output (captured), then the before/after crop."""
    raw = demo_out.splitlines()

    def section(start, stop=None):
        i = next(k for k, line in enumerate(raw) if line.startswith(start))
        j = next((k for k, line in enumerate(raw) if stop and k > i and line.startswith(stop)), len(raw))
        return raw[i:j]

    variant = [x for x in section("== Вариант", "Зона ") if x.strip()]
    changes = [x for x in section("== Что изменилось") if x.strip()]
    cmd = [("$ make demo DOOR=D03", "cmd"),
           (".venv/bin/python scripts/demo_change.py --opening D03 --delta 100 --with-blender", "dim")]
    step1 = cmd + [("", "")]
    step2 = cmd + [("== Исходный план … (сборка data/plan.json)", "dim")] + [(x, "") for x in variant]
    style = lambda x: ("hit" if "W21" in x else "ok" if "без изменений" in x else "")  # noqa: E731
    step3 = cmd + [("…", "dim")] + [(x, "") for x in variant[-2:]] + [("", "")] + \
        [(x, style(x)) for x in changes if not x.startswith("Результат")]
    f1 = terminal(step1, os.path.join(out, "t1.png"))
    f2 = terminal(step2, os.path.join(out, "t2.png"))
    f3 = terminal(step3, os.path.join(out, "t3.png"))
    cmp_ = fit_image(os.path.join(ROOT, "out_variant", "compare_D03.png"), os.path.join(out, "cmp.png"),
                     frame=True, box=(150, 112, W - 150, H - BAR_H - 26))
    # the table appears when the voice reaches "нетто обеих граней…"
    t3 = max(5.0, d - 1.4 - 1.8 - 2.7)
    return [(f1, 1.4), (f2, 1.8), (cmp_, 2.7), (f3, t3)]


# --- spreadsheet frames (values read from out_variant/apartment.xlsx)

SHEETS = ["Объёмы", "Стены по граням", "Проёмы", "Мебель", "Сверка с PDF", "Допущения", "Источник"]
STATUS = {"совпадает": (0.86, 0.94, 0.85), "проверить": (0.98, 0.94, 0.79), "расхождение": (0.96, 0.84, 0.82)}


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}".replace(".", ",")
    return str(v)


def sheet(path, active, columns, rows, note=None):
    """columns: [(header, width, align)]; rows: [(cells, fill or None, bold)]"""
    c = Canvas(bg=BG)
    x0, y0, x1, y1 = 70, 108, W - 70, H - BAR_H - 22
    c.rect((x0, y0, x1, y1), fill=(1, 1, 1), color=(0.80, 0.80, 0.80), width=1.2, radius=0.01)
    c.rect((x0, y0, x1, y0 + 44), fill=(0.93, 0.93, 0.92), radius=0.01)
    title = "apartment.xlsx — сгенерирован сборкой, вручную не правится"
    c.text((x0 + x1 - c.width(title, 21)) / 2, y0 + 29, title, 21, "r", (0.35, 0.36, 0.38))
    # column letters + header
    gx, rh, top = x0 + 56, 42, y0 + 60
    xs = [gx]
    for _, w, _ in columns:
        xs.append(xs[-1] + w)
    c.rect((x0 + 1, top, x1 - 1, top + 30), fill=(0.96, 0.96, 0.95))
    for k in range(len(columns)):
        letter = chr(ord("A") + k)
        c.text((xs[k] + xs[k + 1] - c.width(letter, 18)) / 2, top + 21, letter, 18, "r", (0.5, 0.5, 0.5))
    y = top + 30
    all_rows = [([h for h, _, _ in columns], (0.91, 0.90, 0.88), True)] + rows
    for r_i, (cells, fill, bold) in enumerate(all_rows):
        if fill:
            c.rect((gx, y, xs[-1], y + rh), fill=fill)
        c.text(x0 + 12, y + 28, str(r_i + 1), 18, "r", (0.55, 0.55, 0.55))
        for k, v in enumerate(cells):
            if isinstance(v, (int, float)) and not isinstance(v, bool) and columns[k][2] == "r" \
                    and columns[k][0] not in ("Ребро", "Количество") and r_i > 0:
                v = float(v)
            s = fmt(v) if not isinstance(v, tuple) else v[0]
            cell_fill = v[1] if isinstance(v, tuple) else None
            if cell_fill:
                c.rect((xs[k], y, xs[k + 1], y + rh), fill=cell_fill)
            size, font = 22, ("b" if bold else "r")
            while c.width(s, size, font) > columns[k][1] - 16 and len(s) > 3:
                s = s[:-2].rstrip() + "…"
            tx = xs[k] + 8 if columns[k][2] == "l" else xs[k + 1] - 8 - c.width(s, size, font)
            c.text(tx, y + 28, s, size, font, INK)
        c.page.draw_line(fitz.Point(gx, y + rh), fitz.Point(xs[-1], y + rh), color=(0.86, 0.86, 0.86), width=1)
        y += rh
    for x in xs:
        c.page.draw_line(fitz.Point(x, top), fitz.Point(x, y), color=(0.86, 0.86, 0.86), width=1)
    if note:
        ny = y + 26
        c.rect((gx, ny, xs[-1], ny + 64), fill=(1.0, 0.97, 0.88), color=ACCENT, width=1.5, radius=0.1)
        c.text(gx + 22, ny + 41, note, 25, "b", INK)
    # sheet tabs
    tx, ty = x0 + 20, y1 - 46
    c.page.draw_line(fitz.Point(x0, ty - 8), fitz.Point(x1, ty - 8), color=(0.82, 0.82, 0.82), width=1)
    for name in SHEETS:
        w = c.width(name, 20, "b" if name == active else "r") + 30
        if name == active:
            c.rect((tx, ty - 6, tx + w, ty + 32), fill=(1, 1, 1), color=(0.3, 0.55, 0.3), width=2)
        c.text(tx + 15, ty + 20, name, 20, "b" if name == active else "r", INK if name == active else (0.45, 0.45, 0.47))
        tx += w + 6
    c.save(path)
    return path


def seg_excel(plan, d, out):
    wb = openpyxl.load_workbook(os.path.join(ROOT, "out_variant", "apartment.xlsx"), data_only=True)
    base = json.load(open(os.path.join(ROOT, "out", "quantities.json"), encoding="utf-8"))
    var = json.load(open(os.path.join(ROOT, "out_variant", "quantities.json"), encoding="utf-8"))
    bface = {f["key"]: f for z in base["zones"] for f in z["faces"]}

    # Стены по граням: rows around D03
    ws = wb["Стены по граням"]
    data = [r for r in ws.iter_rows(min_row=2, values_only=True)]
    pick = [r for r in data if (r[0] == "Z2" and isinstance(r[1], int) and 8 <= r[1] <= 12)
            or (r[0] == "Z3" and isinstance(r[1], int) and 6 <= r[1] <= 9)]
    rows = []
    for r in pick:
        hit = r[2] == "W21"
        rows.append(([r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]], HILITE if hit else None, hit))
    cols = [("Зона", 90, "l"), ("Ребро", 90, "r"), ("Стена", 150, "l"), ("Длина, м", 130, "r"),
            ("Высота, м", 190, "r"), ("Брутто, м²", 150, "r"), ("Проёмы", 380, "l"), ("Вычет, м²", 130, "r"),
            ("Нетто, м²", 130, "r")]
    b1, b2 = bface["Z2/e10/W21"]["net_m2"], bface["Z3/e9/W21"]["net_m2"]
    note = (f"D03 1030 мм: Z2/e10/W21 {fmt(b1)} → {fmt(rows[[r[0][2] for r in rows].index('W21')][0][8])} м², "
            f"Z3/e9/W21 {fmt(b2)} → {fmt([r for r in rows if r[0][0] == 'Z3' and r[0][2] == 'W21'][0][0][8])} м²  (−0,21 каждая)")
    f1 = sheet(os.path.join(out, "x1.png"), "Стены по граням", cols, rows, note)

    # Объёмы: walls of Z2/Z3 and totals
    ws = wb["Объёмы"]
    data = [r for r in ws.iter_rows(min_row=2, values_only=True)]
    want = {("Z2", "Проёмы (вычет)"), ("Z2", "Стены нетто"), ("Z3", "Проёмы (вычет)"), ("Z3", "Стены нетто")}
    rows = []
    for r in data:
        key = (r[0], r[3])
        if key in want:
            rows.append(([r[0], r[1], r[3], r[4], r[5], r[6]], HILITE if r[3] == "Стены нетто" else None, False))
        elif r[1] == "ИТОГО квартира (без балкона)" and r[3] in ("Площадь пола", "Стены нетто"):
            rows.append((["", r[1], r[3], r[4], r[5], r[6]], (0.95, 0.95, 0.93), True))
        elif r[1] == "Количество" and r[3] == "Двери":
            rows.append((["", r[1], r[3], r[4], r[5], r[6]], None, False))
    cols = [("Зона", 90, "l"), ("Зона / итог", 420, "l"), ("Показатель", 300, "l"), ("Ед.", 70, "l"),
            ("Количество", 160, "r"), ("Примечание", 600, "l")]
    note = (f"Стены нетто квартиры: {fmt(base['interior_total']['walls_net_m2'])} → "
            f"{fmt(var['interior_total']['walls_net_m2'])} м² · пол {fmt(var['interior_total']['floor_m2'])} м² "
            f"и {var['counts']['doors']} дверей — без изменений")
    f2 = sheet(os.path.join(out, "x2.png"), "Объёмы", cols, rows, note)

    # Сверка с PDF
    ws = wb["Сверка с PDF"]
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[0] and str(r[0]).startswith("Z"):
            sched = f"{r[7]}: {fmt(r[8])}" if r[7] else "— нет строки"
            rows.append(([r[0], r[1], r[3], r[4], r[6], sched, (r[10], STATUS.get(r[10]))], None, False))
        elif r[1] and str(r[1]).startswith("ИТОГО"):
            rows.append((["", r[1], r[3], r[4], r[6], f"итог: {fmt(r[8])}" if r[8] else "", ""], (0.95, 0.95, 0.93), True))
        elif r[0] == "Контрольный размер":
            break
    cols = [("Зона", 80, "l"), ("Зона", 400, "l"), ("Расчёт, м²", 140, "r"), ("На плане, м²", 160, "r"),
            ("Δ, %", 110, "r"), ("Экспликация", 330, "l"), ("Статус", 200, "l")]
    note = "Экспликация (7 строк, 93,56 м²) — другая планировка: перегородки не добавлены, расхождение записано"
    f3 = sheet(os.path.join(out, "x3.png"), "Сверка с PDF", cols, rows, note)
    # "Сверка с PDF" appears when the voice starts talking about it
    t3 = max(5.0, d - 3.9 - 1.9)
    return [(f1, 3.9), (f2, 1.9), (f3, t3)]


def seg_outro(plan, d, out):
    c = Canvas(bg=(1, 1, 1))
    c.text(110, 190, "Один источник — plan.json", 60, "b", INK)
    c.text(112, 248, "Excel и модель собираются одной командой и всегда согласованы", 32, "r", (0.35, 0.36, 0.38))
    boxes = [("Обмерный план", "PDF, 1:50"), ("plan.json", "ручная разметка + проверки"),
             ("apartment.blend", "Blender"), ("apartment.xlsx", "ведомость объёмов")]
    bx, by, bw, bh = 110, 330, 300, 120
    for k, (t, sub) in enumerate(boxes):
        x = bx + k * (bw + 60)
        c.rect((x, by, x + bw, by + bh), fill=(0.97, 0.96, 0.94), color=(0.75, 0.74, 0.72), width=1.6, radius=0.12)
        c.text(x + (bw - c.width(t, 30, "b")) / 2, by + 52, t, 30, "b", INK)
        c.text(x + (bw - c.width(sub, 22)) / 2, by + 90, sub, 22, "r", (0.4, 0.4, 0.42))
        if k < len(boxes) - 1:
            c.text(x + bw + 14, by + 72, "→", 40, "b", ACCENT)
    bullets = ["make — одна команда из чистой папки: проверка, Excel, наложение на PDF, Blender",
               "25 автотестов; эталон 4 × 3 м: 12 / 14 / 39,20 / 37,31",
               "D03 + 100 мм → −0,21 м² на каждую затронутую грань",
               "Неизвестные высоты — на листе «Допущения», не выданы за обмеры"]
    for k, t in enumerate(bullets):
        c.page.draw_circle(fitz.Point(124, 540 + k * 62), 6, color=None, fill=ACCENT)
        c.text(146, 550 + k * 62, t, 28, "r", INK)
    c.image((1380, 500, 1840, 840), os.path.join(ROOT, "out", "iso.png"))
    f = os.path.join(out, "outro.png")
    c.save(f)
    return [(f, d)]


SEGMENTS = [
    # (builder, step for the breadcrumb, label, subtitle)
    (seg_pdf, 1, "1 · PDF",
     "Обмерный план, A3, 1:50 · масштаб по 4 размерным линиям → 56,693 pt/м, отклонение < 0,01 %"),
    (seg_overlay, 2, "2 · Совпадение геометрии",
     "plan.json: 6 зон, 31 стена, 10 проёмов, 22 предмета мебели · 21 из 22 контрольных размеров совпали"),
    (seg_blender, 2, "2 · Модель Blender",
     "Из того же plan.json: коллекции Walls · Floors · Windows · Doors · Furniture, проёмы пустые"),
    (seg_change, 3, "3 · Изменение",
     "Дверь D03 + 100 мм на копии входа → нетто каждой из двух граней −0,21 м²; пол, периметр и число дверей те же"),
    (seg_excel, 4, "4 · Excel",
     "Вычет D03 в обеих гранях, итоги пересчитаны · каждая зона сверена с подписью на плане и экспликацией"),
    (seg_outro, 0, "", ""),
]


def tts(n_segments):
    txt = open(os.path.join(VID, "narration.txt"), encoding="utf-8").read()
    body = "\n".join(line for line in txt.splitlines() if not line.startswith("#"))
    segs = [s.strip() for s in body.split("\n\n") if s.strip()]
    assert len(segs) == n_segments, f"в narration.txt {len(segs)} сегментов, нужно {n_segments}"
    out = []
    for i, s in enumerate(segs, 1):
        tf, af = os.path.join(BUILD, f"seg{i}.txt"), os.path.join(BUILD, f"seg{i}.aiff")
        with open(tf, "w", encoding="utf-8") as fh:
            fh.write(s)
        run(["say", "-v", VOICE, "-r", RATE, "-o", af, "-f", tf])
        out.append((af, duration(af)))
    return out


def encode_segment(i, frames, caption, audio, d, path):
    lst = os.path.join(BUILD, f"seg{i}_list.txt")
    with open(lst, "w", encoding="utf-8") as fh:
        for f, dur in frames:
            fh.write(f"file '{f}'\nduration {dur:.5f}\n")
        fh.write(f"file '{frames[-1][0]}'\n")
    fade = 0.35
    vf = (f"[0:v]fps={FPS},scale={W}:{H},format=rgba[b];[b][1:v]overlay=0:0:shortest=1,"
          f"fade=t=in:st=0:d={fade},fade=t=out:st={d - fade:.3f}:d={fade},format=yuv420p[v]")
    af = (f"[2:a]aresample=48000,aformat=channel_layouts=stereo,adelay={int(LEAD * 1000)}|{int(LEAD * 1000)},"
          f"volume=4dB,alimiter=limit=0.89,apad,atrim=0:{d:.3f},"
          f"afade=t=out:st={d - 0.25:.3f}:d=0.25[a]")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-loop", "1", "-i", caption,
         "-i", audio, "-filter_complex", vf + ";" + af, "-map", "[v]", "-map", "[a]", "-t", f"{d:.3f}",
         "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", path])


def main() -> int:
    for need in ("out/overlay.pdf", "out/apartment.blend", "out/top.png", "out/iso.png",
                 "out_variant/apartment.xlsx", "out_variant/compare_D03.png"):
        if not os.path.exists(os.path.join(ROOT, need)):
            print(f"нет {need}: сначала `make && make demo DOOR=D03`")
            return 1
    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(BUILD)
    plan = load_plan_unchecked(os.path.join(ROOT, "data", "plan.json"))

    print("озвучка…")
    audio = tts(len(SEGMENTS))
    print("вывод make demo DOOR=D03…")
    demo = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "demo_change.py"), "--opening", "D03",
                           "--delta", "100", "--with-blender"], cwd=ROOT, capture_output=True, text=True, check=True)

    parts = []
    for i, ((builder, step, label, subtitle), (af, adur)) in enumerate(zip(SEGMENTS, audio), 1):
        d = round(LEAD + adur + TAIL, 3)
        out = os.path.join(BUILD, f"s{i}")
        os.makedirs(out)
        print(f"сегмент {i}: {label or 'итог'} — {d:.1f} с")
        frames = builder(plan, d, out, demo.stdout) if builder is seg_change else builder(plan, d, out)
        cap = os.path.join(out, "caption.png")
        caption_layer(cap, step, label, subtitle)
        mp4 = os.path.join(BUILD, f"seg{i}.mp4")
        encode_segment(i, frames, cap, af, d, mp4)
        parts.append(mp4)

    lst = os.path.join(BUILD, "concat.txt")
    with open(lst, "w", encoding="utf-8") as fh:
        fh.writelines(f"file '{p}'\n" for p in parts)
    final = os.path.join(VID, "apartment_demo.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
         "-movflags", "+faststart", final])
    run(["ffmpeg", "-y", "-v", "error", "-i", final, "-an", "-c:v", "copy", "-movflags", "+faststart",
         os.path.join(VID, "apartment_demo_no_voice.mp4")])
    print(f"готово: video/apartment_demo.mp4 — {duration(final):.1f} с")
    return 0


if __name__ == "__main__":
    sys.exit(main())
