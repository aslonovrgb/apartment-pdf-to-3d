"""Excel workbook (FR05, FR06). Generated only — never edited by hand."""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .issues import Issue
from .model import Plan
from .quantities import Quantities, m, m2
from .report import area_checks, control_checks

HEADER_FILL = PatternFill("solid", fgColor="E7E6E1")
TOTAL_FILL = PatternFill("solid", fgColor="F4F3EF")
STATUS_FILL = {
    "совпадает": PatternFill("solid", fgColor="DCEFD9"),
    "OK": PatternFill("solid", fgColor="DCEFD9"),
    "проверить": PatternFill("solid", fgColor="FBEFC9"),
    "расхождение": PatternFill("solid", fgColor="F6D5D1"),
    "нет подписи": PatternFill("solid", fgColor="EDEDED"),
}
THIN = Side(style="thin", color="C9C7C0")
BOTTOM = Border(bottom=THIN)
BOLD = Font(bold=True)
NUM2 = "0.00"

SOURCE_RU = {"pdf_dimension": "размер PDF", "scaled": "измерено по масштабу", "assumption": "допущение"}
KIND_RU = {"interior": "квартира", "balcony": "балкон"}
TYPE_RU = {"door": "дверь", "window": "окно", "doorway": "проём без заполнения"}


def _sheet(wb: Workbook, title: str, headers: Sequence[str], widths: Sequence[int]):
    ws = wb.create_sheet(title)
    ws.append(list(headers))
    for col, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = w
        cell = ws.cell(row=1, column=col)
        cell.font = BOLD
        cell.fill = HEADER_FILL
        cell.border = BOTTOM
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    return ws


def _row(ws, values: Iterable, num_cols: Sequence[int] = (), bold: bool = False, fill: Optional[PatternFill] = None):
    ws.append(list(values))
    r = ws.max_row
    for c in num_cols:
        ws.cell(row=r, column=c).number_format = NUM2
    if bold or fill:
        for c in range(1, ws.max_column + 1):
            cell = ws.cell(row=r, column=c)
            if bold:
                cell.font = BOLD
            if fill:
                cell.fill = fill
    return r


def write_workbook(plan: Plan, q: Quantities, issues: List[Issue], path: str) -> None:
    wb = Workbook()
    wb.remove(wb.active)

    # ------------------------------------------------------------------ Объёмы
    ws = _sheet(wb, "Объёмы", ["Зона ID", "Зона", "Тип", "Показатель", "Ед.", "Количество", "Примечание"],
                [9, 26, 11, 34, 6, 12, 60])
    for zq in q.interior + q.balcony:
        z = zq.zone
        src_ru = SOURCE_RU.get(z.height_source, z.height_source)
        multi = len(zq.ceiling_parts) > 1
        rows = [
            ("Площадь пола", "м²", m2(zq.floor_area), "площадь контура зоны"),
            ("Периметр пола", "м", m(zq.perimeter), "сумма рёбер контура"),
            ("Площадь потолка", "м²", m2(zq.ceiling_area),
             "горизонтальная проекция" + ("; вертикальные грани перепадов не добавлены" if multi else "")),
        ]
        if multi:
            for h, a, lbl in zq.ceiling_parts:
                rows.append((f"   в т.ч. потолок H = {m(h):.3f} м", "м²", m2(a), lbl))
        rows += [
            ("Высота потолка (основная)", "м", m(z.height),
             src_ru + ("; участки с другой высотой — см. строки выше" if multi else "")),
            ("Стены брутто (внутренние грани)", "м²", m2(zq.wall_gross),
             "Σ длина грани × высота потолка над гранью (лист «Стены по граням»)"),
            ("Проёмы (вычет)", "м²", m2(zq.openings_area),
             ", ".join(sorted({d.opening_id for f in zq.faces for d in f.deductions})) or "—"),
            ("Стены нетто", "м²", m2(zq.wall_net), "брутто − проёмы"),
        ]
        for name, unit, val, note in rows:
            _row(ws, [z.id, z.name, KIND_RU[z.kind], name, unit, val, note], num_cols=[6])
        ws.append([])

    def totals(label: str, zs, with_walls: bool = True):
        if not zs:
            return
        _row(ws, ["", label, "", "", "", None, ""], bold=True, fill=TOTAL_FILL)
        data = [("Площадь пола", "м²", sum(m2(z.floor_area) for z in zs)),
                ("Площадь потолка", "м²", sum(m2(z.ceiling_area) for z in zs))]
        if with_walls:
            data += [("Стены брутто", "м²", sum(m2(z.wall_gross) for z in zs)),
                     ("Проёмы (вычет)", "м²", sum(m2(z.openings_area) for z in zs)),
                     ("Стены нетто", "м²", sum(m2(z.wall_net) for z in zs))]
        for name, unit, val in data:
            _row(ws, ["", label, "", name, unit, val, ""], num_cols=[6], fill=TOTAL_FILL)

    totals("ИТОГО квартира (без балкона)", q.interior)
    totals("ИТОГО балкон", q.balcony)
    if q.balcony:
        _row(ws, ["", "Справочно: пол квартиры с балконом", "", "Площадь пола", "м²",
                  sum(m2(z.floor_area) for z in q.zones), "для сверки с суммой подписей на плане"],
             num_cols=[6])
    ws.append([])
    _row(ws, ["", "Количество", "", "", "", None, ""], bold=True, fill=TOTAL_FILL)
    for name, ids in (("Двери", q.doors), ("Окна", q.windows), ("Проёмы без заполнения", q.doorways)):
        _row(ws, ["", "Количество", "", name, "шт", len(ids), ", ".join(ids) or "—"])

    # ------------------------------------------------------------------ Стены по граням
    ws = _sheet(wb, "Стены по граням",
                ["Зона ID", "Ребро контура", "Стена", "Длина, м", "Высота, м", "Брутто, м²", "Проёмы",
                 "Вычет, м²", "Нетто, м²"],
                [9, 13, 14, 10, 16, 11, 30, 10, 10])
    for zq in q.zones:
        for f in zq.faces:
            ded = "; ".join(f"{d.opening_id} {m(d.width):.2f}×{m(d.height):.2f}" for d in f.deductions) or "—"
            hs = f.heights
            height = m(hs[0]) if len(hs) == 1 else " / ".join(f"{m(h):.3f}" for h in hs)
            wall = f"{f.wall_id} (торец)" if f.end_face else f.wall_id
            _row(ws, [f.zone_id, f.edge_index, wall, m(f.length), height, m2(f.gross), ded,
                      m2(f.openings_area), m2(f.net)], num_cols=[4, 5, 6, 8, 9])
        for s in zq.open_spans:
            _row(ws, [s.zone_id, s.edge_index, "—", m(s.length), None, 0,
                      f"открытая граница{' с ' + s.neighbour if s.neighbour else ''}: не стена", 0, 0],
                 num_cols=[4, 6, 8, 9])

    # ------------------------------------------------------------------ Проёмы
    ws = _sheet(wb, "Проёмы",
                ["ID", "Тип", "Стена", "Смещение, мм", "Ширина, мм", "Низ, мм", "Верх, мм", "Площадь, м²",
                 "Вычтено из граней", "Источник"],
                [7, 20, 8, 13, 11, 9, 9, 12, 34, 22])
    for o in sorted(plan.openings, key=lambda o: o.id):
        _row(ws, [o.id, TYPE_RU[o.type], o.wall_id, o.offset, o.width, o.sill, o.head,
                  m(o.width) * m(o.height), ", ".join(q.opening_faces.get(o.id, [])) or "—",
                  SOURCE_RU.get(o.source, o.source)], num_cols=[8])

    # ------------------------------------------------------------------ Мебель
    ws = _sheet(wb, "Мебель", ["ID", "Тип", "Зона", "Центр X, мм", "Центр Y, мм", "Ш × Г × В, мм", "Поворот, °",
                               "Группа", "Проверка"],
                [7, 14, 8, 12, 12, 18, 10, 10, 60])
    furn_issues = {}
    for i in issues:
        furn_issues.setdefault(i.ref, []).append(i.message)
    for f in sorted(plan.furniture, key=lambda f: f.id):
        _row(ws, [f.id, f.type, f.zone_id, f.center[0], f.center[1],
                  f"{f.width:.0f} × {f.depth:.0f} × {f.height:.0f}", f.rotation, f.group or "",
                  "; ".join(furn_issues.get(f.id, [])) or "OK: стены, мебель, двери"])

    # ------------------------------------------------------------------ Сверка с PDF
    ws = _sheet(wb, "Сверка с PDF",
                ["Зона ID", "Зона", "Тип", "Расчёт, м²", "На плане, м²", "Δ, м²", "Δ, %", "Экспликация: строка",
                 "Экспликация, м²", "Δ к экспликации, м²", "Статус", "Комментарий"],
                [9, 24, 10, 11, 12, 9, 8, 12, 12, 13, 13, 60])
    checks = area_checks(plan, q)
    for c in checks:
        r = _row(ws, [c.zone_id, c.name, KIND_RU[c.kind], c.calc_m2, c.plan_m2, c.diff_m2, c.diff_pct,
                      c.schedule_row, c.schedule_m2, c.schedule_diff_m2, c.status, c.note],
                 num_cols=[4, 5, 6, 7, 9, 10])
        ws.cell(row=r, column=11).fill = STATUS_FILL.get(c.status, TOTAL_FILL)

    def full_sum(vals):
        """Sum only if every zone of the subset has a reference value (partial sums mislead)."""
        return sum(vals) if vals and all(v is not None for v in vals) else None

    ref_totals = plan.raw.get("reference_totals", {}) or {}
    for label, subset, with_balcony in (
            ("ИТОГО квартира (без балкона)", [c for c in checks if c.kind == "interior"], False),
            ("ИТОГО с балконом", checks, True)):
        if not subset:
            continue
        calc = sum(c.calc_m2 for c in subset)
        plan_sum = full_sum([c.plan_m2 for c in subset])
        sched_sum = full_sum([c.schedule_m2 for c in subset])
        note = "сумма по зонам"
        if with_balcony:
            if ref_totals.get("plan_labels_total_m2") is not None:
                plan_sum = ref_totals["plan_labels_total_m2"]
            if ref_totals.get("schedule_total_m2") is not None:
                sched_sum = ref_totals["schedule_total_m2"]
                note = "итог экспликации — из источника (строки не совпадают с зонами 1:1)"
        _row(ws, ["", label, "", calc, plan_sum, None if plan_sum is None else calc - plan_sum,
                  None if not plan_sum else (calc - plan_sum) / plan_sum * 100.0, "",
                  sched_sum, None if sched_sum is None else calc - sched_sum, "", note],
             num_cols=[4, 5, 6, 7, 9, 10], bold=True, fill=TOTAL_FILL)

    ctrl = control_checks(plan)
    if ctrl:
        ws.append([])
        ws.append([])
        hdr = ["Контрольный размер", "Описание", "", "На чертеже, мм", "Модель, мм", "Δ, мм", "", "", "", "",
               "Статус", f"Порог пилота {plan.tol('control_dimension_mm'):.0f} мм (не строительный допуск)"]
        r = _row(ws, hdr, bold=True, fill=HEADER_FILL)
        for c in ctrl:
            r = _row(ws, [c.id, c.description, "", c.expected_mm, c.model_mm, c.diff_mm, "", "", "", "", c.status, ""])
            ws.cell(row=r, column=11).fill = STATUS_FILL["OK"] if c.status == "OK" else STATUS_FILL["расхождение"]

    # ------------------------------------------------------------------ Допущения
    ws = _sheet(wb, "Допущения", ["№", "Допущение / правило", "Источник"], [6, 110, 24])
    n = 0

    def add(text: str, src: str) -> None:
        nonlocal n
        n += 1
        ws.append([n, text, src])
        ws.cell(row=ws.max_row, column=2).alignment = Alignment(wrap_text=True, vertical="top")

    for a in plan.assumptions:
        add(a.get("text", ""), SOURCE_RU.get(a.get("source", ""), a.get("source", "")))
    for z in sorted(plan.zones, key=lambda z: z.id):
        txt = f"Зона {z.id}: основная высота потолка {m(z.height):.3f} м"
        if z.ceiling_regions:
            txt += "; участки: " + "; ".join(f"{m(r.height):.3f} м ({r.label or 'участок'}, "
                                              f"{SOURCE_RU.get(r.source, r.source)})" for r in z.ceiling_regions)
        add(txt, SOURCE_RU.get(z.height_source, z.height_source))
    if any(z.ceiling_regions for z in plan.zones) or len({z.height for z in plan.zones}) > 1:
        add("Есть перепады высот потолка: площадь потолка дана по высотам, вертикальные грани перепадов не добавлены; "
            "высота грани стены берётся по участку потолка, под которым она проходит", "правило расчёта")
    add("Площадь потолка = горизонтальная проекция контура зоны", "правило расчёта")
    add("Стены считаются по внутренним граням: часть ребра контура, лежащая на грани стены (осевая ± толщина/2, "
        f"допуск {plan.tol('face_match_mm'):.0f} мм) или на торце свободного конца стены (уступы, торцы перегородок). "
        "Границы зон без перегородки — не стены", "правило расчёта")
    add("Проём вычитается из каждой отделываемой грани, которую он пересекает; двери и окна считаются по уникальным ID",
        "правило расчёта")
    add(f"Сверка площадей: «совпадает» ≤ {plan.tol('area_ok_pct'):.0f}%, «проверить» ≤ {plan.tol('area_check_pct'):.0f}%, "
        "иначе «расхождение»", "правило сверки")
    add(f"Контрольные размеры отмечаются при отклонении > {plan.tol('control_dimension_mm'):.0f} мм — порог сверки пилота, "
        "не строительный допуск", "правило сверки")
    for i in issues:
        if i.level in ("warning",):
            add(f"Предупреждение проверки [{i.ref}]: {i.message}", "валидатор")

    # ------------------------------------------------------------------ Источник
    ws = _sheet(wb, "Источник", ["Параметр", "Значение"], [28, 90])
    src = plan.source
    rows = [
        ("Проект", plan.project.get("name", "")),
        ("Файл источника", src.get("file", "")),
        ("Страница", src.get("page", "")),
        ("SHA-256 источника", src.get("sha256", "—")),
        ("Масштаб, pt/м", src.get("scale", {}).get("pt_per_m", "")),
        ("Как определён масштаб", src.get("scale", {}).get("basis", "")),
        ("Начало координат", src.get("origin", {}).get("description", "")),
        ("Версия схемы plan.json", plan.schema_version),
        ("Единицы", "plan.json — мм; Blender — м; ведомость — м, м²"),
        ("Как получен файл", "Сгенерирован командой `make` (build.py) из plan.json. Вручную не редактируется."),
    ]
    for k, v in rows:
        ws.append([k, v])
        ws.cell(row=ws.max_row, column=1).font = BOLD

    wb.save(path)
