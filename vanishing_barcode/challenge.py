"""Seeded carton pairs that vary artwork as well as assembly order."""

from dataclasses import replace
from random import Random

from .carton import WALL_ORDER, Carton, Rect
from .cases import ORDERS, Case, Option

COVER_EDGE_TOLERANCE_MM = 2
RELEASE_SEED = 41403


def varied_carton(rng):
    d = rng.randint(41, 44)
    return Carton(rng.randint(39, 43), d, rng.randint(38, 43),
                  flap_a=d-rng.randint(11, 13), flap_b=d-rng.randint(11, 13),
                  first_wall=rng.choice(WALL_ORDER), base_wall=rng.choice(WALL_ORDER))


def mark(carton, flap, near, far):
    panel = carton.flap(flap)
    mid = (panel.x0 + panel.x1) // 2
    return Rect(mid-10, -far, mid+10, -near)


def varied_cases(seed):
    rng = Random(seed)
    leading = rng.choice(("A", "B"))
    trailing = "B" if leading == "A" else "A"
    order = (leading, trailing)
    base = varied_carton(rng)
    edge = base.depth - (base.flap_a if trailing == "A" else base.flap_b)
    outside = mark(base, leading, 3, 8)
    partial = mark(base, leading, edge-4, edge+4)
    covered = mark(base, leading, edge+4, edge+10)
    on = replace(base, barcode_flap=leading, barcode=partial if seed % 2 else covered)
    other = replace(on, barcode=covered if seed % 2 else partial)
    visible = replace(base, barcode_flap=leading, barcode=outside)
    pairs = [
        [Case("order", on, o) for o in ORDERS],
        [Case("position", carton, order) for carton in (visible, other)],
    ]
    control_mark = mark(base, leading, edge+5, edge+11) if seed % 4 in (0, 3) else mark(base, leading, 4, 9)
    cosmetic = Case("color", replace(base, barcode_flap=leading, barcode=control_mark), order)
    pairs.append([cosmetic, replace(cosmetic, cosmetic=True)])

    for_repair = varied_carton(rng)
    r_edge = for_repair.depth - (for_repair.flap_a if trailing == "A" else for_repair.flap_b)
    mid = (for_repair.flap(trailing).x0 + for_repair.flap(trailing).x1) // 2
    labels = rng.sample(list("PQR"), 3)
    repairs = [
        Option(labels[0], leading, mark(for_repair, leading, 2, 8)),
        Option(labels[1], leading, mark(for_repair, leading, r_edge+4, r_edge+10)),
        Option(labels[2], trailing, Rect(mid-10, -3, mid+10, 3)),
    ]
    pairs.append([
        Case("repair-location", for_repair, order, "repair", options=tuple(repairs)),
        Case("repair-location", for_repair, order, "repair", options=(
            replace(repairs[0], bounds=mark(for_repair, leading, r_edge-3, r_edge+3)),
            *repairs[1:2], replace(repairs[2], bounds=mark(for_repair, trailing, 4, 10)),
        )),
    ])

    placement = varied_carton(rng)
    positions = [placement.wall(name) for name in rng.sample(list(WALL_ORDER), 2)]
    pairs.append([Case("face", placement, order, "placement",
                       diamond=((wall.x0+wall.x1)//2, placement.height//2-11)) for wall in positions])

    for pair in pairs:
        if pair[0].pair_id != "color":
            rng.shuffle(pair)
    return [case for pair in pairs for case in pair]
