#!/usr/bin/env python3
"""Markup helper: dump the vector content of the source PDF.

    python tools/pdf_inspect.py data/source/projectfortest.pdf --out work/pdf

Writes page info, every text span with its position, every stroked/filled
segment (with line width and colour) and a PNG of the page. These numbers are
used to place plan.json coordinates precisely; they are NOT treated as
recognised walls — every wall/zone/opening is confirmed by hand on the overlay.

With --scale PT_PER_M --origin X Y the segments are also converted to plan
millimetres (x right, y up).
"""
from __future__ import annotations

import argparse
import collections
import json
import os

import fitz


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", default="work/pdf")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--scale", type=float, help="PDF points per metre")
    ap.add_argument("--origin", type=float, nargs=2, help="PDF point of plan (0, 0)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    doc = fitz.open(args.pdf)
    page = doc[args.page - 1]
    info = {"pages": doc.page_count, "rect": list(page.rect), "mediabox": list(page.mediabox),
            "rotation": page.rotation, "metadata": doc.metadata}
    print(json.dumps(info, ensure_ascii=False, indent=1))

    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                if s["text"].strip():
                    spans.append({"text": s["text"], "bbox": [round(v, 2) for v in s["bbox"]],
                                  "size": round(s["size"], 2), "font": s["font"],
                                  "dir": [round(v, 3) for v in line["dir"]]})
    with open(os.path.join(args.out, "text.json"), "w", encoding="utf-8") as fh:
        json.dump(spans, fh, ensure_ascii=False, indent=1)

    segs = []
    fills = []
    widths = collections.Counter()
    for path in page.get_drawings():
        w = round(path.get("width") or 0.0, 3)
        color = path.get("color")
        fill = path.get("fill")
        for item in path["items"]:
            kind = item[0]
            if kind == "l":
                p, q = item[1], item[2]
                segs.append([round(p.x, 3), round(p.y, 3), round(q.x, 3), round(q.y, 3), w,
                             None if color is None else [round(c, 3) for c in color], path.get("type")])
                widths[w] += 1
            elif kind == "re":
                r = item[1]
                pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
                for a, b in zip(pts, pts[1:] + pts[:1]):
                    segs.append([round(a[0], 3), round(a[1], 3), round(b[0], 3), round(b[1], 3), w,
                                 None if color is None else [round(c, 3) for c in color], path.get("type")])
                widths[w] += 4
            elif kind == "qu":
                quad = item[1]
                pts = [quad.ul, quad.ur, quad.lr, quad.ll]
                for a, b in zip(pts, pts[1:] + pts[:1]):
                    segs.append([round(a.x, 3), round(a.y, 3), round(b.x, 3), round(b.y, 3), w,
                                 None if color is None else [round(c, 3) for c in color], path.get("type")])
        if fill is not None:
            r = path["rect"]
            fills.append({"rect": [round(v, 2) for v in r], "fill": [round(c, 3) for c in fill],
                          "items": len(path["items"])})

    with open(os.path.join(args.out, "segments.json"), "w") as fh:
        json.dump(segs, fh)
    with open(os.path.join(args.out, "fills.json"), "w") as fh:
        json.dump(fills, fh, indent=0)
    print(f"text spans: {len(spans)}, segments: {len(segs)}, filled paths: {len(fills)}")
    print("line widths (pt -> count):", dict(sorted(widths.items())))

    if args.scale and args.origin:
        k = 1000.0 / args.scale
        ox, oy = args.origin
        mm = [[round((s[0] - ox) * k, 1), round((oy - s[1]) * k, 1), round((s[2] - ox) * k, 1),
               round((oy - s[3]) * k, 1), s[4]] for s in segs]
        with open(os.path.join(args.out, "segments_mm.json"), "w") as fh:
            json.dump(mm, fh)

    page.get_pixmap(dpi=args.dpi).save(os.path.join(args.out, "page.png"))
    print(f"written to {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
