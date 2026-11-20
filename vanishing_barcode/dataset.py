"""Build canonical artifacts and admit only verified inputs to evaluation."""

import hashlib
import json
import os
import stat
from collections import defaultdict
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import ImageChops, ImageColor
from reportlab.lib.pagesizes import A4

from . import artwork
from .carton import verify_geometry
from .cases import CHOICES, DEFAULT_SEED, QUESTIONS, make_cases, solve
from .challenge import COVER_EDGE_TOLERANCE_MM, varied_cases

RELEASE_CHANGES = {"position": "artwork-position", "face": "marked-face", "repair-location": "repair-positions"}


@dataclass(frozen=True)
class Task:
    id: str
    question: str
    png: bytes
    reference: dict


@dataclass(frozen=True)
class Pack:
    dataset: str
    seed: int | None
    tasks: tuple[Task, ...]
    files: dict[str, bytes]
    validation: dict
    sha256: str


def digest(data):
    return hashlib.sha256(data).hexdigest()


def artifact_path(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Artifact path must stay inside the output directory")
    path = root
    if path.is_symlink():
        raise ValueError("Output root must be a directory without a symbolic link")
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"Artifact path contains a symbolic link: {relative}")
    return path


def read_limited(path, size):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    if path.is_symlink():
        raise ValueError(f"Expected a regular file at {path}")
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > size:
            raise ValueError(f"Expected a regular file of at most {size} bytes at {path}")
        data = stream.read(size + 1)
        if len(data) > size:
            raise ValueError(f"File exceeds the allowed size at {path}")
        return data


def write_bytes(path, data, *, replace_existing=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        staging = Path(stream.name)
        try:
            stream.write(data)
            stream.close()
            if replace_existing:
                staging.replace(path)
            else:
                os.link(staging, path)
        finally:
            staging.unlink(missing_ok=True)


def json_bytes(data):
    return (json.dumps(data, indent=2, allow_nan=False) + "\n").encode("utf-8")


def read_json(path, limit):
    def unique_fields(pairs):
        values = {}
        for key, value in pairs:
            if key in values:
                raise ValueError("Duplicate ID or field in reply file")
            values[key] = value
        return values

    def invalid_constant(value):
        raise ValueError(f"Invalid JSON constant {value}")

    return json.loads(read_limited(path, limit), object_pairs_hook=unique_fields, parse_constant=invalid_constant)


def read_replies(path):
    supplied = read_json(path, 100_000)
    if not isinstance(supplied, dict) or any(not isinstance(value, str) for value in supplied.values()):
        raise ValueError("Reply file must map task IDs to plain text replies")
    return {key: {"raw_reply": value} for key, value in supplied.items()}


def encode_png(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def validate_pair(entries, change=None):
    if len(entries) != 2:
        raise ValueError("Every pair must contain exactly two tasks")
    (first, left, a), (second, right, b) = entries
    if any(img.size != (artwork.MODEL_WIDTH * artwork.RASTER_SCALE, artwork.MODEL_HEIGHT * artwork.RASTER_SCALE)
           or img.mode != "RGB" or img.info for img in (left, right)):
        raise ValueError("Model inputs must be plain RGB rasters at the expected size")
    delta = ImageChops.difference(left, right)
    bbox = delta.getbbox()
    if not bbox:
        raise ValueError("Both images in a pair are identical")
    scale = artwork.RASTER_SCALE

    if change:
        if change == "artwork-position":
            normalized = replace(second, carton=replace(second.carton, barcode=first.carton.barcode))
        elif change == "marked-face":
            normalized = replace(second, diamond=first.diamond)
        else:
            normalized = replace(second, options=first.options)
        if first != normalized or a == b or bbox[1] < 129*scale or bbox[3] >= 500*scale:
            raise ValueError("An artwork pair must change only its indicated mark or positions and flip its answer")
        return {"type": change, "same_answer": False, "changed_pixel_bounds": list(bbox), "order_identical": True}

    if second.cosmetic:
        if first != replace(second, cosmetic=False) or a != b:
            raise ValueError("A cosmetic control changed the task geometry or answer")
        x, y, net_scale = artwork.net_transform(first.carton)
        for name in ("Right", "Left"):
            box = first.carton.wall(name)
            bounds = (int((x + box.x0 * net_scale) * scale) - 1, int(y * scale) - 1,
                      int((x + box.x1 * net_scale) * scale) + 2,
                      int((y + box.y1 * net_scale) * scale) + 2)
            if not delta.crop(bounds).getbbox():
                raise ValueError("Expected a cosmetic change in both side fills")
            delta.paste(0, bounds)
        if delta.getbbox():
            raise ValueError("The cosmetic control changed pixels outside the side fills")
        return {"type": "cosmetic", "same_answer": True, "changed_pixel_bounds": list(bbox)}

    if first != replace(second, order=first.order) or first.order == second.order or a == b:
        raise ValueError("A fold-order pair must change only the lid order and flip the answer")
    x_step = artwork.CARD_WIDTH + artwork.CARD_GAP
    x3 = artwork.CARD_LEFT + 2 * x_step
    split = x3 + artwork.CARD_WIDTH + artwork.CARD_GAP / 2
    if not (bbox[0] >= int(x3 * scale) and bbox[1] >= artwork.CARD_TOP * scale
            and bbox[0] < split * scale < bbox[2]
            and bbox[2] <= (artwork.MODEL_WIDTH - artwork.CARD_LEFT) * scale
            and bbox[3] <= (artwork.CARD_TOP + 97) * scale):
        raise ValueError("Only the lid-order cards may change in a fold-order pair")
    for case, image in ((first, left), (second, right)):
        for index, flap in enumerate(case.order):
            point = (int((x3 + index * x_step + 11) * scale), (artwork.CARD_TOP + 16) * scale)
            if image.getpixel(point) != ImageColor.getrgb(artwork.LID_INK[flap]):
                raise ValueError("The rendered lid card color disagrees with the recorded order")
    return {"type": "fold-order", "same_answer": False, "changed_pixel_bounds": list(bbox),
            "changes_limited_to_steps": [3, 4], "flat_net_pixel_identical": True}


def build_pack(dataset, seed=DEFAULT_SEED):
    if dataset not in ("sample", "evaluation", "release") or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("Choose a known dataset and an unsigned 32-bit seed")
    seed = None if dataset == "sample" else seed
    release = dataset == "release"
    cases = varied_cases(seed) if release else make_cases(dataset, seed)
    tolerance = COVER_EDGE_TOLERANCE_MM if release else 1
    tasks, groups, files = [], defaultdict(list), {}
    for case in cases:
        result = solve(case, tolerance)
        image = artwork.model_image(case)
        png = encode_png(image)
        variant = len(groups[case.pair_id])
        key_seed = (f"vanishing-barcode/v1/{case.pair_id}/{variant}" if seed is None
                    else f"vanishing-barcode/v2/{seed}/{case.pair_id}/{variant}")
        if release:
            key_seed = f"vanishing-barcode/v3/{seed}/{case.pair_id}/{variant}"
        key = digest(key_seed.encode("utf-8"))[:12]
        reference = {"id": key, "pair_id": case.pair_id, "task_type": case.task_type,
                     "pair_type": (RELEASE_CHANGES.get(case.pair_id, "cosmetic" if case.pair_id == "color" else "fold-order")
                                   if release else "cosmetic" if case.task_type == "placement" else "fold-order"),
                     "image_sha256": digest(png), "allowed_replies": CHOICES[case.task_type],
                     "case": asdict(case), **result}
        tasks.append(Task(key, QUESTIONS[case.task_type], png, reference))
        files[f"{dataset}/images/{key}.png"] = png
        files[f"{dataset}/reveals/{key}.png"] = encode_png(artwork.reveal_image(case, result))
        groups[case.pair_id].append((case, image, result["answer"]))

    if len({task.id for task in tasks}) != len(tasks):
        raise ValueError("Duplicate task ID")
    if release and len({(task.png, task.question) for task in tasks}) != len(tasks):
        raise ValueError("Duplicate model input in the release pack")
    pair_checks = {}
    for pair_id, entries in groups.items():
        change = RELEASE_CHANGES.get(pair_id) if release else None
        pair_checks[pair_id] = validate_pair(entries, change)
        for index, (case, _, _) in enumerate(entries if change else entries[:1], 1):
            pdf = artwork.print_sheet(case)
            with closing(artwork.pypdfium2.PdfDocument(pdf)) as document, closing(document[0]) as page:
                if len(document) != 1 or any(abs(a - b) > 0.01 for a, b in zip(page.get_size(), A4)):
                    raise ValueError("Each print sheet must be one A4 page")
            name = f"{pair_id}-{index}" if change else pair_id
            files["pdf/carton.pdf" if seed is None else f"{dataset}/print/{name}.pdf"] = pdf

    validation = {"dataset": dataset, "seed": seed, "same_question_within_pairs": True,
                  "inputs_have_no_embedded_metadata": True, "cover_edge_tolerance_mm": tolerance,
                  "print_page_mm": [210, 297], "pairs": pair_checks}
    if seed is None:
        validation["geometry"] = verify_geometry(cases[0].carton, [case.order for case in cases])
        if sorted(row["covered_mm2"] for row in validation["geometry"]["order_checks"]) != [0, cases[0].carton.barcode.area]:
            raise ValueError("The flagship barcode must go from fully visible to fully covered")
        files["sample/pair-preview.png"] = encode_png(artwork.signature_preview(groups[cases[0].pair_id]))

    manifest = [{"id": task.id, "image": f"images/{task.id}.png", "question": task.question} for task in tasks]
    task_bytes = "".join(json.dumps(item) + "\n" for item in manifest).encode("utf-8")
    ref_bytes = json_bytes({"dataset": dataset, "seed": seed, "tasks": [task.reference for task in tasks]})
    sha = digest(task_bytes + ref_bytes)
    validation["pack_sha256"] = sha
    files[f"{dataset}/reference.json"] = ref_bytes
    files[f"{dataset}/validation.json"] = json_bytes(validation)
    files[f"{dataset}/tasks.jsonl"] = task_bytes
    return Pack(dataset, seed, tuple(tasks), files, validation, sha)


def generate(root, pack):
    paths = [(artifact_path(root, relative), data) for relative, data in pack.files.items()]
    for path, data in paths:
        write_bytes(path, data)


def verify(root, pack):
    for relative, expected in pack.files.items():
        if read_limited(artifact_path(root, relative), len(expected)) != expected:
            raise ValueError(f"Artifact differs from the generated pack: {relative}")
    return pack.validation
