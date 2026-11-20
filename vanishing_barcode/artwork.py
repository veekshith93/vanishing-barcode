"""Draw the same die lines on a print sheet and on both model images."""

from contextlib import closing
from io import BytesIO
from math import atan2, cos, sin

import pypdfium2
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from .carton import Rect

INK = "#142332"
MUTED = "#4A5E6C"
FOLD = "#436176"
LINE = "#D7E0E4"
WALL = "#F5F7F8"
LID_FILL = {"A": "#DDEFEA", "B": "#F9E9D9"}
LID_INK = {"A": "#175954", "B": "#8C4625"}
BARCODE = "110100101101011101001011010100111011001011"

MODEL_WIDTH = 620
MODEL_HEIGHT = 668
RASTER_SCALE = 2
CARD_TOP = 545
CARD_LEFT = 30
CARD_GAP = 9
CARD_WIDTH = (MODEL_WIDTH - 2 * CARD_LEFT - 3 * CARD_GAP) / 4


def label(pdf, x, y, value, size, color=INK, bold=False, centered=False):
    pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    pdf.setFillColor(color)
    write = pdf.drawCentredString if centered else pdf.drawString
    write(x, y, value)


def filled_rect(pdf, rect, color):
    pdf.setFillColor(color)
    pdf.rect(rect.x0, rect.y0, rect.x1 - rect.x0, rect.y1 - rect.y0, stroke=0, fill=1)


def stroke(pdf, color, width, dash=()):
    pdf.setStrokeColor(color)
    pdf.setLineWidth(width)
    pdf.setDash(dash)


def draw_net(pdf, case, x, y, scale):
    """Place the wall strip's upper left corner at (x, y)."""
    carton = case.carton
    h, end, tab = carton.height, carton.strip_width, carton.net_width
    walls = list(carton.walls())
    base = carton.base()
    pdf.saveState()
    pdf.translate(x, y)
    pdf.scale(scale, scale)

    side_fill = "#E3EAFE" if case.cosmetic else WALL
    for name, bounds in walls:
        filled_rect(pdf, bounds, side_fill if name in ("Right", "Left") else "#FFFFFF")
        if case.diamond is None or name == "Front":
            label(pdf, (bounds.x0 + bounds.x1) / 2, h / 2 + 1, name, 3.6, MUTED, bold=True, centered=True)
    filled_rect(pdf, base, WALL)
    label(pdf, (base.x0 + base.x1) / 2, (base.y0 + base.y1) / 2 + 1, "Base", 3.6, MUTED, bold=True, centered=True)
    for flap in ("A", "B"):
        bounds = carton.flap(flap)
        filled_rect(pdf, bounds, LID_FILL[flap])
        x_label = bounds.x0 + 5 if case.options else (bounds.x0 + bounds.x1) / 2
        label(pdf, x_label, -4, flap, 4.4, LID_INK[flap], True, True)

    if case.task_type == "visibility":
        draw_barcode(pdf, carton)
    if case.diamond is not None:
        draw_diamond(pdf, *case.diamond, 4)

    pdf.saveState()
    pdf.translate((end + tab) / 2, h / 2)
    pdf.rotate(-90)
    label(pdf, 0, 0.9, "Tape tab", 2.9, MUTED, centered=True)
    pdf.restoreState()

    # Only the outside perimeter is cut. The seven panel joins are scored.
    outline = []
    for name, bounds in walls:
        if name in ("Front", "Back"):
            reach = carton.flap_a if name == "Front" else carton.flap_b
            if bounds.x0:
                outline.append((bounds.x0, 0))
            outline.extend([(bounds.x0, -reach), (bounds.x1, -reach), (bounds.x1, 0)])
        elif bounds.x0 == 0:
            outline.append((0, 0))
    outline.extend([(end, 0), (tab, 4), (tab, h - 4), (end, h)])
    if base.x1 < end:
        outline.append((base.x1, h))
    outline.extend([(base.x1, base.y1), (base.x0, base.y1)])
    if base.x0:
        outline.extend([(base.x0, h), (0, h)])
    stroke(pdf, INK, 0.55)
    perimeter = pdf.beginPath()
    perimeter.moveTo(*outline[0])
    for point in outline[1:]:
        perimeter.lineTo(*point)
    perimeter.close()
    pdf.drawPath(perimeter)

    stroke(pdf, FOLD, 0.34, (1.6, 1.05))
    for _, bounds in walls:
        pdf.line(bounds.x1, 0, bounds.x1, h)
    pdf.lines([(carton.front_x, 0, carton.front_x + carton.width, 0),
               (carton.back_x, 0, carton.back_x + carton.width, 0), (base.x0, h, base.x1, h)])

    for option in case.options:
        region = option.bounds
        stroke(pdf, "#57278F", 0.5, (0.85, 0.6))
        pdf.rect(region.x0, region.y0, region.x1 - region.x0, region.y1 - region.y0, stroke=1, fill=0)
        offset = 4 if region.y0 < 0 < region.y1 else 1.2
        label(pdf, region.x1 + 2.5, (region.y0 + region.y1) / 2 + offset, option.label, 3.2,
              "#57278F", bold=True, centered=True)
    pdf.restoreState()


def draw_barcode(pdf, carton):
    code = carton.barcode
    filled_rect(pdf, code, "#FFFFFF")
    bar_width = (code.x1 - code.x0 - 3.5) / len(BARCODE)
    pdf.setFillColor(INK)
    for i, bit in enumerate(BARCODE):
        if bit == "1":
            bar_left = code.x0 + 1.75 + i * bar_width
            pdf.rect(bar_left, code.y0 + 1.2, bar_width, code.y1 - code.y0 - 2.4, stroke=0, fill=1)
    label(pdf, (code.x0 + code.x1) / 2, code.y0 - 1.25, "SAMPLE BARCODE", 1.9,
          LID_INK[carton.barcode_flap], True, True)


def draw_diamond(pdf, x, y, radius):
    pdf.saveState()
    pdf.translate(x, y)
    pdf.rotate(45)
    filled_rect(pdf, Rect(-radius, -radius, radius, radius), "#752449")
    pdf.restoreState()


def legend(pdf, x, y):
    stroke(pdf, INK, 1.7)
    pdf.line(x, y, x + 25, y)
    label(pdf, x + 33, y + 3.5, "Cut", 10.5, MUTED)
    stroke(pdf, FOLD, 1.1, (4.5, 3))
    pdf.line(x + 76, y, x + 101, y)
    label(pdf, x + 109, y + 3.5, "Fold 90 degrees", 10.5, MUTED)
    pdf.setDash()


def arrow(pdf, points, color):
    stroke(pdf, color, 1.7)
    path = pdf.beginPath()
    path.moveTo(*points[0])
    path.curveTo(*points[1], *points[2], *points[3])
    pdf.drawPath(path)
    x, y = points[-1]
    prev_x, prev_y = points[-2]
    angle = atan2(y - prev_y, x - prev_x)
    for side in (-0.55, 0.55):
        pdf.line(x, y, x - 6 * cos(angle + side), y - 6 * sin(angle + side))


def step_drawing(pdf, step, flap, base_wall):
    """Draw the wall wrap, base crease, or selected lid hinge."""
    stroke(pdf, MUTED, 1.4)
    if step == 1:
        # Cross-section looking down the tube. The tab meets the Front wall.
        pdf.rect(13, 7, 60, 33, fill=0, stroke=1)
        stroke(pdf, FOLD, 1.5, (2, 2))
        pdf.line(13, 36, 27, 36)
        arrow(pdf, [(39, 20), (32, 19), (24, 23), (23, 32)], FOLD)
        return

    left, right, top, bottom = 6, 80, 15, 43
    pdf.lines([(left, top, left, bottom), (right, top, right, bottom)])
    if step == 2:
        hinge, direction = (right, -1) if base_wall == "Back" else (left, 1)
        stroke(pdf, FOLD, 2.7)
        pdf.line(hinge, bottom, hinge, bottom + 9)
        points = [(hinge + direction * dx, bottom + dy) for dx, dy in ((8, 7), (16, 6), (26, 2), (28, -6))]
        arrow(pdf, points, FOLD)
        return

    pdf.line(left, bottom, right, bottom)
    hinge = left if flap == "A" else right
    inward = 1 if flap == "A" else -1
    color = LID_INK[flap]
    stroke(pdf, color, 2.7)
    pdf.line(hinge, top, hinge, top - 14)
    points = [(hinge + inward * dx, top + dy) for dx, dy in ((6, -12), (16, -13), (27, -9), (29, 1))]
    arrow(pdf, points, color)


def step_card(pdf, case, index, flap=None):
    x = CARD_LEFT + (index - 1) * (CARD_WIDTH + CARD_GAP)
    y = CARD_TOP
    accent = LID_INK.get(flap, MUTED)
    stroke(pdf, LINE, 0.9)
    pdf.setFillColor("#F7F9FA")
    pdf.roundRect(x, y, CARD_WIDTH, 97, 6, stroke=1, fill=1)
    pdf.setFillColor(accent)
    pdf.circle(x + 17, y + 16, 8.6, stroke=0, fill=1)
    label(pdf, x + 17, y + 19.5, str(index), 10, "#FFFFFF", bold=True, centered=True)
    title = {1: "Fold walls", 2: "Close base"}.get(index, f"Fold lid {flap}")
    label(pdf, x + 32, y + 20, title, 11, bold=True)
    pdf.saveState()
    pdf.translate(x + (CARD_WIDTH - 86) / 2, y + 28)
    step_drawing(pdf, index, flap, case.carton.base_wall)
    pdf.restoreState()
    seam_label = case.carton.first_wall if case.diamond is None else "first wall"
    instruction = {1: f"Tape tab behind {seam_label}", 2: "Tape free edges"}.get(
        index, "Front hinge" if flap == "A" else "Back hinge",
    )
    label(pdf, x + CARD_WIDTH / 2, y + 89, instruction, 9.4, MUTED, centered=True)


def rasterize(pdf_source, scale):
    with (closing(pypdfium2.PdfDocument(pdf_source)) as document,
          closing(document[0]) as page,
          closing(page.render(scale=scale, rev_byteorder=True)) as bitmap):
        return bitmap.to_pil().convert("RGB")


def net_transform(carton):
    lid_height = max(carton.flap_a, carton.flap_b)
    scale = min((MODEL_WIDTH - 74) / carton.net_width, 341 / (lid_height + carton.base().y1))
    return (MODEL_WIDTH - scale * carton.net_width) / 2, 129 + scale * lid_height, scale


def model_image(case):
    page = BytesIO()
    pdf = Canvas(page, pagesize=(MODEL_WIDTH, MODEL_HEIGHT), bottomup=0, invariant=True)
    label(pdf, 30, 43, "Carton assembly", 26, bold=True)
    label(pdf, 30, 68, "Flat net, printed side up. Keep the printed side facing out.", 12, MUTED)
    legend(pdf, 30, 97)
    key = {"placement": "The diamond marks the artwork.", "repair": "The dotted rectangles mark candidate barcode positions."}
    if case.task_type in key:
        label(pdf, 30, 119, key[case.task_type], 10.5, MUTED)
    draw_net(pdf, case, *net_transform(case.carton))
    label(pdf, 30, 506, "Fold in this order", 18, bold=True)
    label(pdf, 30, 527, "Fold inward. Keep the first lid flat while closing the second.", 11.5, MUTED)
    step_card(pdf, case, 1)
    step_card(pdf, case, 2)
    for index, flap in enumerate(case.order, start=3):
        step_card(pdf, case, index, flap)
    pdf.save()
    return rasterize(page.getvalue(), RASTER_SCALE)


def print_sheet(case):
    carton = case.carton
    if carton.net_width > 190 or carton.base().y1 > 89 or max(carton.flap_a, carton.flap_b) > 34:
        raise ValueError("Carton cut lines would exceed the printable A4 area")
    page = BytesIO()
    pdf = Canvas(page, pagesize=A4, bottomup=0, invariant=True)
    pdf.setTitle("The Vanishing Barcode - folding sample")
    label(pdf, 20 * mm, 20 * mm, "The Vanishing Barcode", 24, bold=True)
    label(pdf, 20 * mm, 29 * mm, "A4 folding sample", 12, MUTED)
    legend(pdf, 20 * mm, 41 * mm)
    draw_net(pdf, case, (A4[0] - carton.net_width * mm) / 2, 79 * mm, mm)

    # Measured between the centres of the end ticks.
    stroke(pdf, INK, 0.8)
    pdf.line(20 * mm, 174 * mm, 70 * mm, 174 * mm)
    for end in (20, 70):
        pdf.line(end * mm, 172.4 * mm, end * mm, 175.6 * mm)
    label(pdf, 74 * mm, 175.3 * mm, "50 mm at Actual Size (100%)", 10, MUTED)

    label(pdf, 20 * mm, 192 * mm, "Build the carton", 14, bold=True)
    setup = (
        "1. Print at Actual Size (100%). Check the scale bar with a ruler.",
        "2. Cut the solid outline. Crease the dashed folds with the printed side facing out.",
        "3. Fold the four walls into a tube. Tape the tab behind the leftmost wall on the net.",
        "4. Fold the Base inward and tape its free edges. Leave lids A and B untaped.",
    )
    for index, line in enumerate(setup):
        label(pdf, 20 * mm, (200 + index * 6) * mm, line, 10.5)

    label(pdf, 20 * mm, 234 * mm, "Try both lid orders", 14, bold=True)
    look_at = {"visibility": "Inspect the barcode from above.", "repair": "Inspect the marked rectangles from above.",
               "placement": "Inspect the diamond while facing Front."}[case.task_type]
    instructions = (
        f"Close B, then A. Keep the first lid flat. {look_at}",
        "Reopen both lids. Close A, then B. Inspect from the same view.",
        "If a lid springs up, hold a corner gently and keep fingers clear of the barcode.",
    )
    for index, line in enumerate(instructions):
        label(pdf, 20 * mm, (242 + index * 6) * mm, line, 10.5)
    label(pdf, 20 * mm, 271 * mm, "B then A", 10.5, bold=True)
    label(pdf, 106 * mm, 271 * mm, "A then B", 10.5, bold=True)
    stroke(pdf, FOLD, 0.6)
    pdf.lines([(39 * mm, 271 * mm, 95 * mm, 271 * mm),
               (125 * mm, 271 * mm, 190 * mm, 271 * mm)])
    pdf.save()
    return page.getvalue()


def reveal_top(pdf, carton, order, x, y, mark=None):
    scale = 2.5
    pdf.saveState()
    pdf.translate(x, y)
    pdf.scale(scale, scale)
    for flap in order:
        panel = carton.closed(flap, carton.flap(flap))
        filled_rect(pdf, panel, LID_FILL[flap])
        stroke(pdf, LID_INK[flap], 0.5)
        pdf.rect(panel.x0, panel.y0, panel.x1 - panel.x0, panel.y1 - panel.y0, stroke=1, fill=0)
    if mark:
        flap, region = mark
        target = carton.closed(flap, region)
        cover = carton.closed(order[-1], carton.flap(order[-1]))
        if flap != order[-1] and target.overlap(cover):
            clipped = Rect(max(target.x0, cover.x0), max(target.y0, cover.y0),
                           min(target.x1, cover.x1), min(target.y1, cover.y1))
            filled_rect(pdf, clipped, "#CF6E76")
        stroke(pdf, "#4C244B", 0.8, (1.6, 0.8))
        pdf.rect(target.x0, target.y0, target.x1 - target.x0, target.y1 - target.y0, stroke=1, fill=0)
    label(pdf, carton.width / 2, -2.5, "FRONT", 3.0, MUTED, bold=True, centered=True)
    pdf.restoreState()


def reveal_image(case, result):
    page = BytesIO()
    pdf = Canvas(page, pagesize=(620, 288), bottomup=0, invariant=True)
    carton, order = case.carton, case.order
    label(pdf, 28, 40, f"Reference answer  {result['answer'].title()}", 24, bold=True)
    if case.task_type == "placement":
        label(pdf, 28, 68, "Closed carton from above. Stand at Front and face toward the carton.", 11.5, MUTED)
        w, d = carton.width * 2.5, carton.depth * 2.5
        # View from above with the viewer standing at the bottom of the diagram.
        stroke(pdf, INK, 1.5)
        pdf.setFillColor(WALL)
        pdf.rect(249, 113, w, d, stroke=1, fill=1)
        label(pdf, 249 + w / 2, 103, "Back", 10, MUTED, centered=True)
        label(pdf, 249 + w / 2, 113 + d + 18, "Front", 10, MUTED, centered=True)
        label(pdf, 215, 116 + d / 2, "Left", 10, MUTED, centered=True)
        label(pdf, 281 + w, 116 + d / 2, "Right", 10, MUTED, centered=True)
        dx, dy = {"front": (w / 2, d), "right": (w, d / 2), "back": (w / 2, 0), "left": (0, d / 2)}[result["answer"]]
        draw_diamond(pdf, 249 + dx, 113 + dy, 4)
    else:
        label(pdf, 28, 68, f"Closed top view. Flap {order[-1]} is the outer layer.", 11.5, MUTED)
        if case.task_type == "visibility":
            label(pdf, 28, 92, f"Barcode area  {result['visible_mm2']} mm² visible, {result['covered_mm2']} mm² covered", 11, MUTED)
            reveal_top(pdf, carton, order, 30, 130, (carton.barcode_flap, carton.barcode))
        else:
            for index, option in enumerate(sorted(case.options, key=lambda option: option.label)):
                x = 30 + index * 191
                info = result["options"][option.label]
                status = "Fully visible" if info["valid"] else info.get("reason", "Covered").capitalize()
                label(pdf, x, 98, f"{option.label}   {status}", 12, bold=True)
                mark = None if info.get("reason") else (option.flap, option.bounds)
                if mark:
                    reveal_top(pdf, carton, order, x, 130, mark)
                else:
                    stroke(pdf, FOLD, 1, (4, 3))
                    pdf.line(x, 170, x + 106, 170)
                    stroke(pdf, "#57278F", 1.5)
                    pdf.rect(x + 29, 155, 52, 30, stroke=1, fill=0)
        label(pdf, 28, 270, "Dotted outline shows the barcode area. Red shows the part covered by the outer flap.", 10.5, MUTED)
    pdf.save()
    return rasterize(page.getvalue(), 1.5)


def signature_preview(entries):
    page = BytesIO()
    pdf = Canvas(page, pagesize=(690, 474), bottomup=0, invariant=True)
    label(pdf, 28, 42, "One carton. Two closure orders.", 25, bold=True)
    label(pdf, 28, 64, "The flat layout and barcode stay fixed. Steps 3 and 4 switch places.", 11.5, MUTED)
    width, height = 306, MODEL_HEIGHT * 306 / MODEL_WIDTH
    for index, (case, image, answer) in enumerate(entries):
        x = 28 + index * 328
        title = f"{case.order[0]} then {case.order[1]}"
        label(pdf, x, 102, title, 15, bold=True)
        visible = answer == "yes"
        outcome = "Barcode visible" if visible else "Barcode covered"
        text_width = pdf.stringWidth(outcome, "Helvetica-Bold", 13)
        label(pdf, x + width - text_width, 102, outcome, 13, "#175954" if visible else "#8C4625", bold=True)
        pdf.saveState()
        pdf.translate(x, 116 + height)
        pdf.scale(1, -1)
        pdf.drawImage(ImageReader(image), 0, 0, width=width, height=height)
        pdf.restoreState()
        stroke(pdf, LINE, 0.8)
        pdf.rect(x, 116, width, height, fill=0, stroke=1)
    pdf.save()
    return rasterize(page.getvalue(), 1.7)
