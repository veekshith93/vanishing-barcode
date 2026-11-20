"""Export the verified benchmark as a single, offline HTML file."""

import base64
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .cases import DEFAULT_SEED
from .challenge import RELEASE_SEED
from .dataset import artifact_path, build_pack, read_limited, write_bytes
from .evaluation import MODEL_ID, score

TITLES = {
    "carton-01": "Fold-order demo",
    "carton-02": "Partial cover",
    "carton-03": "Repair",
    "carton-04": "Face placement",
    "order": "New fold-order pair",
    "position": "Move the barcode",
    "color": "Color control",
    "repair-location": "Repair placement",
    "face": "Move the marked face",
}


def data_uri(media_type, data):
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def recorded_runs(root, pack):
    for filename in ("scores-vision.json", "scores-terra-vision.json", "scores-text.json"):
        path = artifact_path(root, f"{pack.dataset}/{filename}")
        if not path.exists():
            continue
        report = json.loads(read_limited(path, 200_000))
        if report.get("source") != "model_run" or report.get("pack_sha256") != pack.sha256:
            continue

        model, mode = report.get("model"), report["settings"]["mode"]
        if not isinstance(model, str) or not MODEL_ID.fullmatch(model) or mode not in ("image+question", "text-only"):
            raise ValueError(f"Invalid run provenance in {filename}")
        entries = {item["id"]: item for item in report["items"]}
        if set(entries) != {task.id for task in pack.tasks} or len(entries) != len(report["items"]):
            raise ValueError(f"Run task IDs disagree with the pack in {filename}")

        replies = {task.id: {"raw_reply": entries[task.id]["raw_reply"], "error": entries[task.id].get("error")}
                   for task in pack.tasks}
        checked = score(pack, replies)
        if checked["scores"] != report["scores"]:
            raise ValueError(f"Saved scores disagree with the recorded replies in {filename}")
        yield {"model": model, "mode": mode, "dataset": pack.dataset, "scores": checked["scores"],
               "visibility_outcomes": checked["visibility_outcomes"],
               "items": {item["id"]: {"reply": item["raw_reply"], "status": item["status"]} for item in checked["items"]}}


def exercise_pairs(pack):
    groups = defaultdict(list)
    for task in pack.tasks:
        ref = task.reference
        groups[ref["pair_id"]].append({"id": task.id, "question": task.question, "choices": ref["allowed_replies"],
                                      "expected": ref["answer"], "image": data_uri("image/png", task.png),
                                      "reveal": data_uri("image/png", pack.files[f"{pack.dataset}/reveals/{task.id}.png"])})

    for key, tasks in groups.items():
        for i, task in enumerate(tasks, 1):
            sheet = "pdf/carton.pdf" if pack.dataset == "sample" else f"{pack.dataset}/print/{key}.pdf"
            if sheet not in pack.files:
                sheet = f"{pack.dataset}/print/{key}-{i}.pdf"
            task["sheet"] = data_uri("application/pdf", pack.files[sheet])
        yield {"id": key, "title": TITLES[key], "tasks": tasks}


def export_prototype(root, seed):
    release_seed = RELEASE_SEED if seed == DEFAULT_SEED else seed
    packs = [build_pack("sample", seed), build_pack("evaluation", seed), build_pack("release", release_seed)]
    payload = {"seed": seed, "pairs": [pair for pack in packs for pair in exercise_pairs(pack)],
               "runs": [run for pack in packs for run in recorded_runs(root, pack)]}
    template = Path(__file__).with_name("prototype.html").read_text(encoding="utf-8")
    for tag in ("style", "script"):
        content = template.split(f"<{tag}>", 1)[1].split(f"</{tag}>", 1)[0]
        fingerprint = base64.b64encode(hashlib.sha256(content.encode("utf-8")).digest()).decode("ascii")
        template = template.replace(f"@@{tag.upper()}_HASH@@", fingerprint)
    data = json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")
    output = artifact_path(root, "prototype.html")
    write_bytes(output, template.replace("@@PAYLOAD@@", data).encode("utf-8"))
    return output
