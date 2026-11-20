"""Define the signature pair and seed fresh evaluation layouts."""

from dataclasses import dataclass, replace
from math import cos, pi, sin
from random import Random

from .carton import WALL_ORDER, Carton, Rect, checked_visibility, lid_grid

DEFAULT_SEED = 2026
ORDERS = (("B", "A"), ("A", "B"))
QUESTIONS = {
    "visibility": "After closing the carton as shown, is the entire barcode visible from outside?",
    "placement": "Which side wall will the diamond land on after assembly? Use your own left and right while facing the marked Front. Choose Front, Right, Back, or Left.",
    "repair": "Which marked rectangle would keep the entire barcode visible on the top of the closed carton? The barcode fills the rectangle. Choose P, Q, or R.",
}
CHOICES = {"visibility": ("yes", "no"), "placement": tuple(name.lower() for name in WALL_ORDER),
           "repair": ("p", "q", "r")}


@dataclass(frozen=True)
class Option:
    label: str
    flap: str
    bounds: Rect


@dataclass(frozen=True)
class Case:
    pair_id: str
    carton: Carton
    order: tuple[str, str]
    task_type: str = "visibility"
    cosmetic: bool = False
    diamond: tuple[int, int] | None = None
    options: tuple[Option, ...] = ()


def make_cases(dataset, seed):
    if dataset == "sample":
        return [Case("carton-01", Carton(), order) for order in ORDERS]
    if dataset != "evaluation":
        raise ValueError("Unknown carton dataset")

    rng = Random(seed)
    w, d, h = rng.randint(44, 48), rng.randint(35, 39), rng.randint(36, 43)
    a, b = d - rng.randint(13, 16), d - rng.randint(8, 10)
    mid = w // 2
    partial = Carton(w, d, h, flap_a=a, flap_b=b, first_wall="Back", base_wall="Back",
                     barcode_flap="B", barcode=Rect(mid - 12, a - 4 - d, mid + 12, a + 5 - d))

    w, d, h = rng.randint(37, 42), rng.randint(42, 46), rng.randint(37, 42)
    a, b = d - rng.randint(15, 16), d - rng.randint(12, 13)
    repair = Carton(w, d, h, flap_a=a, flap_b=b, first_wall="Left", base_wall="Right")
    x_a, x_b = repair.front_x + w // 2, repair.back_x + w // 2
    y0, y1 = d - b + 3, d - b + 9
    labels = list("PQR")
    rng.shuffle(labels)
    options = (Option(labels[0], "A", Rect(x_a - 11, -y1, x_a + 11, -y0)),
               Option(labels[1], "B", Rect(x_b - 11, y0 - d, x_b + 11, y1 - d)),
               Option(labels[2], "A", Rect(x_a - 11, -3, x_a + 11, 3)))

    w, d, h = rng.randint(43, 48), rng.randint(31, 34), rng.randint(37, 40)
    placement = Carton(w, d, h, flap_a=d - 9, flap_b=d - 8, first_wall="Right", base_wall="Left")
    wall = placement.wall(rng.choice(("Right", "Back", "Left")))
    point = ((wall.x0 + wall.x1) // 2, h // 2)
    placement_case = Case("carton-04", placement, rng.choice(ORDERS), "placement", diamond=point)
    return ([Case("carton-02", partial, order) for order in rng.sample(ORDERS, 2)] +
            [Case("carton-03", repair, order, "repair", options=options) for order in rng.sample(ORDERS, 2)] +
            [placement_case, replace(placement_case, cosmetic=True)])


def placed_face(carton, point):
    lid_grid(carton)
    x, y = point
    walls = list(carton.walls())
    for index, (name, region) in enumerate(walls):
        if region.x0 + 6 <= x <= region.x1 - 6 and 6 <= y <= carton.height - 6:
            # Turn the front-wall normal once per crease between it and the mark.
            front = next(i for i, (wall, _) in enumerate(walls) if wall == "Front")
            angle = (index - front) * pi / 2
            normal = (round(sin(angle)), -round(cos(angle)))
            normals = {(0, -1): "front", (1, 0): "right", (0, 1): "back", (-1, 0): "left"}
            face = normals[normal]
            if face != name.lower():
                raise ValueError("Folded wall normal and panel assignment disagree")
            return {"answer": face, "outward_normal_xy": normal}
    raise ValueError("The placement marker must sit fully on a side wall")


def check_repair(case, tolerance_mm=1):
    carton, order = case.carton, case.order
    if len(case.options) != 3 or {o.label for o in case.options} != set("PQR"):
        raise ValueError("Repair must offer one rectangle for each of P, Q and R")
    if any(a.bounds.overlap(b.bounds) for i, a in enumerate(case.options) for b in case.options[i+1:]):
        raise ValueError("Repair rectangles must not overlap")
    checked = {}
    for option in case.options:
        region = option.bounds
        if region.y0 < 0 < region.y1:
            lid = carton.flap(option.flap)
            if region.x0 < lid.x0 + 2 or region.x1 > lid.x1 - 2 or region.y0 < lid.y0 + 2 or region.y1 > carton.height - 2:
                raise ValueError("Fold-crossing option must be printed across the actual lid hinge")
            checked[option.label] = {"valid": False, "reason": "crosses crease"}
        else:
            result = checked_visibility(carton, order, option.flap, region, tolerance_mm)
            checked[option.label] = {"valid": result["answer"] == "yes",
                                     "covered_mm2": result["covered_mm2"],
                                     "grid_covered_mm2": result["grid_covered_mm2"]}
    valid = [label for label, result in checked.items() if result["valid"]]
    if len(valid) != 1:
        raise ValueError("Repair must have exactly one fully visible position")
    return {"answer": valid[0].lower(), "options": checked}


def solve(case, tolerance_mm=1):
    if case.task_type == "visibility":
        return checked_visibility(case.carton, case.order, case.carton.barcode_flap, case.carton.barcode, tolerance_mm)
    if case.task_type == "placement":
        return placed_face(case.carton, case.diamond)
    if case.task_type == "repair":
        return check_repair(case, tolerance_mm)
    raise ValueError("Unknown task type")
