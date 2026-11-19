"""Overlay of plan.json on the source PDF page (visual check for FR03)."""
from __future__ import annotations

from typing import Callable, List, Optional

import os

import fitz  # PyMuPDF

from . import geometry as g
from .layout import door_swings, wall_end_extensions, wall_footprint
from .model import Plan
from .quantities import Quantities, m2

# Fonts with Cyrillic glyphs, first found wins; MuPDF's built-in CJK font is the fallback
# (it covers Cyrillic, with wider spacing).
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
ZONE_COLORS = [(0.95, 0.55, 0.10), (0.15, 0.60, 0.25), (0.20, 0.45, 0.85), (0.80, 0.20, 0.55),
               (0.55, 0.35, 0.85), (0.10, 0.65, 0.70), (0.75, 0.60, 0.05), (0.45, 0.45, 0.45)]
RED = (0.85, 0.10, 0.10)
BLUE = (0.05, 0.35, 0.95)
GREEN = (0.05, 0.55, 0.25)


def mm_to_pt(plan: Plan) -> Callable[[g.Point], fitz.Point]:
    s = float(plan.source["scale"]["pt_per_m"]) / 1000.0
    ox, oy = plan.source["origin"]["pdf_pt"]
    return lambda p: fitz.Point(ox + p[0] * s, oy - p[1] * s)


def cyrillic_font(page: fitz.Page) -> str:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            page.insert_font(fontname="cyr", fontfile=path)
            return "cyr"
    return "japan"


def _poly(shape, pts: List[fitz.Point]) -> None:
    shape.draw_polyline(pts + [pts[0]])


def render_overlay(plan: Plan, q: Quantities, out_pdf: str, out_png: str, dpi: int = 220) -> None:
    src = plan.source_path()
    doc = fitz.open(src)
    page_no = int(plan.source.get("page", 1)) - 1
    if page_no > 0 or doc.page_count > 1:
        doc.select([page_no])
    page = doc[0]
    T = mm_to_pt(plan)
    shape = page.new_shape()

    for i, zq in enumerate(q.zones):
        z = zq.zone
        col = ZONE_COLORS[i % len(ZONE_COLORS)]
        _poly(shape, [T(p) for p in z.polygon])
        shape.finish(color=col, fill=col, fill_opacity=0.16, stroke_opacity=0.9, width=0.7, closePath=True)

    ext = wall_end_extensions(plan)
    for w in plan.walls:
        _poly(shape, [T(p) for p in wall_footprint(w, ext[w.id])])
        shape.finish(color=RED, width=0.45, stroke_opacity=0.95, closePath=True)
        shape.draw_line(T(w.start), T(w.end))
        shape.finish(color=RED, width=0.2, dashes="[2 2] 0", stroke_opacity=0.7)

    walls = plan.walls_by_id
    for o in plan.openings:
        w = walls.get(o.wall_id)
        if w is None:
            continue
        a, b = w.point_at(o.offset), w.point_at(o.offset + o.width)
        shape.draw_line(T(a), T(b))
        shape.finish(color=BLUE, width=2.2, stroke_opacity=0.75)
        if o.type == "door":
            for sw in door_swings(w, o):
                arc = [T(p) for p in sw.sector[1:]]  # skip the centre point
                shape.draw_polyline(arc)
                shape.finish(color=BLUE, width=0.5, stroke_opacity=0.9)
                shape.draw_line(T(sw.hinge), T(g.add(sw.hinge, g.mul(sw.open_dir, sw.radius))))
                shape.finish(color=BLUE, width=0.8, stroke_opacity=0.9)

    for f in plan.furniture:
        _poly(shape, [T(p) for p in f.footprint()])
        shape.finish(color=GREEN, fill=GREEN, fill_opacity=0.10, width=0.5, closePath=True)

    shape.commit()
    font = cyrillic_font(page)

    # area shown in the PNG: all walls and zones plus a margin
    pts: List[g.Point] = []
    for w in plan.walls:
        pts += wall_footprint(w)
    for z in plan.zones:
        pts += z.polygon
    x0, y0, x1, y1 = g.bbox(pts)
    a, b = T((x0, y1)), T((x1, y0))
    crop = fitz.Rect(a.x - 40, a.y - 40, b.x + 40, b.y + 40) & page.rect

    for i, zq in enumerate(q.zones):
        z = zq.zone
        p = T(g.label_point(z.polygon))
        text = f"{z.id}: {m2(zq.floor_area):.2f}"
        page.insert_text(fitz.Point(p.x - 18, p.y + 24), text, fontsize=5.5, color=ZONE_COLORS[i % len(ZONE_COLORS)],
                         fontname=font)

    # legend in the top-right corner of the cropped area
    legend = [("контуры зон: ID и расчётная площадь, кв. м", ZONE_COLORS[0]), ("стены: грани и оси", RED),
              ("проёмы и открывание дверей", BLUE), ("мебель", GREEN)]
    lx, ly = crop.x1 - 185, crop.y0 + 16
    page.draw_rect(fitz.Rect(lx - 4, ly - 9, lx + 175, ly + 9 * len(legend)), color=(0.6, 0.6, 0.6),
                   fill=(1, 1, 1), fill_opacity=0.85, width=0.4)
    for k, (label, col) in enumerate(legend):
        y = ly + 9 * k
        page.draw_line(fitz.Point(lx, y - 2), fitz.Point(lx + 14, y - 2), color=col, width=1.6)
        page.insert_text(fitz.Point(lx + 20, y), label, fontsize=6, color=(0.1, 0.1, 0.1), fontname=font)

    doc.save(out_pdf, garbage=3, deflate=True)
    doc.close()

    # PNG of the marked-up area, rendered from the saved file
    # (page objects are not reliable after a garbage-collecting save)
    out = fitz.open(out_pdf)
    out[0].get_pixmap(dpi=dpi, clip=crop).save(out_png)
    out.close()


def compare_opening(base_pdf: str, variant_pdf: str, plan: Plan, opening_id: str, labels: List[str],
                    out_png: str, half_mm: float = 1700.0, dpi: int = 400) -> None:
    """Side-by-side crops of two overlays around one opening (before / after a change)."""
    o = next(x for x in plan.openings if x.id == opening_id)
    w = plan.walls_by_id[o.wall_id]
    c = mm_to_pt(plan)(w.point_at(o.offset + o.width / 2.0))
    r = half_mm * float(plan.source["scale"]["pt_per_m"]) / 1000.0
    clip = fitz.Rect(c.x - r, c.y - r, c.x + r, c.y + r)
    gap, top = 12.0, 26.0
    doc = fitz.open()
    page = doc.new_page(width=2 * clip.width + 3 * gap, height=clip.height + top + gap)
    font = cyrillic_font(page)
    for k, (src, label) in enumerate(zip((base_pdf, variant_pdf), labels)):
        with fitz.open(src) as sdoc:
            x0 = gap + k * (clip.width + gap)
            rect = fitz.Rect(x0, top, x0 + clip.width, top + clip.height)
            page.show_pdf_page(rect, sdoc, 0, clip=clip)
            page.draw_rect(rect, color=(0.6, 0.6, 0.6), width=0.4)
            page.insert_text(fitz.Point(x0, top - 8), label, fontsize=10, color=(0.1, 0.1, 0.1), fontname=font)
    page.get_pixmap(dpi=dpi).save(out_png)
    doc.close()
