"""A millimetre-scale carton net and two independent visibility calculations."""

from dataclasses import dataclass
from math import cos, radians, sin

WALL_ORDER = ("Front", "Right", "Back", "Left")


@dataclass(frozen=True)
class Rect:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def area(self):
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def overlap(self, other):
        width = max(0, min(self.x1, other.x1) - max(self.x0, other.x0))
        height = max(0, min(self.y1, other.y1) - max(self.y0, other.y0))
        return width * height

    def inset(self, amount):
        return Rect(self.x0 + amount, self.y0 + amount, self.x1 - amount, self.y1 - amount)


@dataclass(frozen=True)
class Carton:
    width: int = 44
    depth: int = 36
    height: int = 46
    tab: int = 10
    flap_a: int = 27
    flap_b: int = 27
    first_wall: str = "Front"
    base_wall: str = "Front"
    barcode_flap: str = "A"
    # Coordinates in the flat net. Negative y extends out from the lid hinge.
    barcode: Rect = Rect(9, -23, 35, -13)

    def walls(self):
        start = WALL_ORDER.index(self.first_wall)
        x = 0
        for name in WALL_ORDER[start:] + WALL_ORDER[:start]:
            width = self.width if name in ("Front", "Back") else self.depth
            yield name, Rect(x, 0, x + width, self.height)
            x += width

    def wall(self, name):
        return dict(self.walls())[name]

    @property
    def front_x(self):
        return self.wall("Front").x0

    @property
    def back_x(self):
        return self.wall("Back").x0

    @property
    def strip_width(self):
        return 2 * (self.width + self.depth)

    @property
    def net_width(self):
        return self.strip_width + self.tab

    def flap(self, name):
        if name == "A":
            wall = self.wall("Front")
            return Rect(wall.x0, -self.flap_a, wall.x1, 0)
        if name == "B":
            wall = self.wall("Back")
            return Rect(wall.x0, -self.flap_b, wall.x1, 0)
        raise ValueError(f"Unknown flap {name!r}")

    def base(self):
        wall = self.wall(self.base_wall)
        reach = self.depth if self.base_wall in ("Front", "Back") else self.width
        return Rect(wall.x0, self.height, wall.x1, self.height + reach)

    def closed(self, flap, rect):
        """Transform a flap or marking into the top view, from Front to Back."""
        if flap == "A":
            return Rect(rect.x0 - self.front_x, -rect.y1, rect.x1 - self.front_x, -rect.y0)
        return Rect(
            self.back_x + self.width - rect.x1, self.depth + rect.y0,
            self.back_x + self.width - rect.x0, self.depth + rect.y1,
        )


def visible_area(carton, order, flap, region):
    """The upper layer is the flap placed last. Intersect any later flap."""
    barcode = carton.closed(flap, region)
    cover = order[1]
    covered = 0
    if cover != flap:
        covered = barcode.overlap(carton.closed(cover, carton.flap(cover)))
    return {
        "answer": "yes" if covered == 0 else "no",
        "covered_mm2": covered,
        "visible_mm2": barcode.area - covered,
    }


def sampled_projection(carton, flap, region, angle):
    """Rotate flat-net cell centres about the erected hinge, independently of Rect overlap."""
    turn = radians(angle)
    front_x, back_x = carton.front_x, carton.back_x
    for flat_x in range(region.x0, region.x1):
        for flat_y in range(region.y0, region.y1):
            reach = -(flat_y + 0.5)
            x = flat_x + 0.5
            y = reach * sin(turn)
            z = carton.height + reach * cos(turn)
            if flap == "B":
                x = back_x + carton.width - x
                y = carton.depth - y
            else:
                x -= front_x
            yield x, y, z


def closed_cells(carton, flap, region):
    # For this family, every fully closed edge lies on the integer grid.
    return {(int(x), int(y)) for x, y, _ in sampled_projection(carton, flap, region, 90)}


def lid_grid(carton):
    if min(carton.width, carton.depth) <= 0 or carton.height <= 8 or carton.tab <= 4:
        raise ValueError("The carton and its clipped tab need positive dimensions")
    # Each flap stops before the opposite hinge at every angle. Until it is
    # horizontal, its free edge is above the seated flap. Both folds can finish.
    if not 0 < min(carton.flap_a, carton.flap_b) <= max(carton.flap_a, carton.flap_b) < carton.depth:
        raise ValueError("Each lid must reach less than the distance to the opposite hinge")
    if min(carton.depth - max(carton.flap_a, carton.flap_b), carton.flap_a + carton.flap_b - carton.depth) < 2:
        raise ValueError("Allow at least 2 mm of lid overlap and clearance at the opposite hinge")
    footprint = {(x, y) for x in range(carton.width) for y in range(carton.depth)}
    closed_flaps = {flap: closed_cells(carton, flap, carton.flap(flap)) for flap in ("A", "B")}
    if closed_flaps["A"] | closed_flaps["B"] != footprint:
        raise ValueError("The two seated lid flaps must close the entire opening")
    return closed_flaps


def checked_visibility(carton, order, flap, region):
    if tuple(order) not in (("A", "B"), ("B", "A")):
        raise ValueError("The lid order must contain each flap once")
    if (region.x0 >= region.x1 or region.y0 >= region.y1 or
            region.overlap(carton.flap(flap).inset(2)) != region.area):
        raise ValueError("The marking needs at least 2 mm clearance from the flap edges")
    closed_flaps = lid_grid(carton)
    surface = {cell: name for name in order for cell in closed_flaps[name]}
    barcode_cells = closed_cells(carton, flap, region)
    covered = sum(surface[cell] != flap for cell in barcode_cells)
    expected = visible_area(carton, order, flap, region)
    if covered != expected["covered_mm2"] or len(barcode_cells) != region.area:
        raise ValueError(f"Layer grid and rectangle oracle disagree for {order}")
    if flap != order[-1]:
        cover = carton.closed(order[-1], carton.flap(order[-1]))
        mark = carton.closed(flap, region)
        if any(bool(mark.overlap(cover.inset(delta))) != bool(covered) for delta in (-1, 1)):
            raise ValueError("Visibility can flip with a 1 mm change to the covering flap edge")
    return {"order": list(order), "grid_covered_mm2": covered, **expected}


def verify_geometry(carton, orders):
    """Check the signature flip and record the closed lid geometry."""
    if {tuple(order) for order in orders} != {("A", "B"), ("B", "A")} or len(orders) != 2:
        raise ValueError("Both opposite closure orders are required")
    closed_flaps = lid_grid(carton)
    observations = [checked_visibility(carton, order, carton.barcode_flap, carton.barcode) for order in orders]
    if {row["answer"] for row in observations} != {"yes", "no"}:
        raise ValueError("The closure-order pair must contain exactly one Yes")
    return {
        "hinge_clearance_mm": {"A": carton.depth - carton.flap_a, "B": carton.depth - carton.flap_b},
        "opening_mm2": carton.width * carton.depth,
        "flap_overlap_mm2": len(closed_flaps["A"] & closed_flaps["B"]),
        "barcode_mm2": carton.barcode.area,
        "order_checks": observations,
    }
