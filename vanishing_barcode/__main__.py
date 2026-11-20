"""Command-line entry point."""

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .cases import DEFAULT_SEED
from .challenge import RELEASE_SEED
from .dataset import (
    artifact_path,
    build_pack,
    generate,
    json_bytes,
    read_replies,
    verify,
    write_bytes,
)
from .evaluation import DEFAULT_BASE_URL, replay, run, score
from .prototype import export_prototype


def print_score(report, path):
    totals = report["scores"]
    print(f"{report['source']} | items {totals['correct_items']}/{totals['items']} "
          f"({totals['item_accuracy']:.0%}) | pairs {totals['correct_pairs']}/{totals['pairs']} "
          f"({totals['pair_accuracy']:.0%})")
    print(f"Parse errors {totals['parse_error']} | request errors {totals['request_error']} "
          f"| missing replies {totals['missing_reply']}")
    v = report["visibility_outcomes"]
    print(f"Visibility false passes {v['false_pass']}/{v['covered_cases']} | "
          f"false rejects {v['false_reject']}/{v['clear_cases']} | manual review {v['manual_review']}")
    if len(report["by_task_type"]) > 1:
        for kind, summary in report["by_task_type"].items():
            print(f"  {kind}: {summary['correct_items']}/{summary['items']} items, "
                  f"{summary['correct_pairs']}/{summary['pairs']} pairs")
    print(f"Report at {path}")


def main():
    parser = argparse.ArgumentParser(description="The Vanishing Barcode sample benchmark")
    parser.add_argument("--output", type=Path, default=Path("output"), help="artifact root (default: output)")
    parser.add_argument("--dataset", choices=("sample", "evaluation", "release"), default="sample")
    parser.add_argument("--seed", type=int, help="seed for evaluation layouts")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="generate, verify, and score synthetic sample replies")
    commands.add_parser("prototype", help="export a portable browser demo of the signature and evaluation packs")
    commands.add_parser("generate", help="generate the selected diagrams, references, and A4 sheets")
    commands.add_parser("verify", help="recheck the saved pack and print automated validation evidence")
    offline = commands.add_parser("score", help="score an external JSON object mapping task IDs to replies")
    offline.add_argument("replies", type=Path)
    offline.add_argument("--report", type=Path, required=True)
    saved = commands.add_parser("replay", help="Re-score raw replies in a saved benchmark report")
    saved.add_argument("source", type=Path)
    saved.add_argument("--report", type=Path, required=True)
    live = commands.add_parser("run", help="evaluate a model using an authorized API or the Codex CLI")
    live.add_argument("--backend", choices=("api", "codex"), default="api")
    live.add_argument("--model", required=True)
    live.add_argument("--generate", action="store_true", help="regenerate and verify before the model run")
    live.add_argument("--text-only", action="store_true")
    live.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Chat Completions API base URL")
    live.add_argument("--max-tokens", type=int, default=512, help="API completion token budget")
    live.add_argument("--effort", choices=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
                      default="low", help="Codex reasoning effort")
    live.add_argument("--report", type=Path, help="path for the scored report")
    live.add_argument("--resume", action="store_true", help="resume the checkpoint next to --report")
    live.add_argument("--request-limit", type=int, help="maximum new requests for this invocation")
    args = parser.parse_args()
    root = args.output
    seed = args.seed if args.seed is not None else RELEASE_SEED if args.dataset == "release" else DEFAULT_SEED

    try:
        if args.command == "run":
            if args.resume and (args.report is None or args.generate):
                raise ValueError("Resume requires the original --report path and an already verified pack")
            if args.request_limit is not None and (args.request_limit < 1 or args.report is None):
                raise ValueError("Set a positive request limit and a --report path")
        if args.command == "prototype":
            print(f"Browser prototype at {export_prototype(root, DEFAULT_SEED if args.seed is None else seed).resolve()}")
            return 0
        pack = build_pack(args.dataset, seed)
        if args.command in ("generate", "demo") or getattr(args, "generate", False):
            generate(root, pack)
        validation = verify(root, pack)
        if args.command == "verify":
            print(json.dumps(validation, indent=2))
            return 0
        if args.command == "generate":
            print(f"Generated and verified {len(pack.tasks)} tasks at {root / pack.dataset}")
            return 0
        if args.command == "demo":
            print(f"Generated and verified {len(pack.tasks)} tasks at {root / pack.dataset}")
            replies = {task.id: {"raw_reply": task.reference["allowed_replies"][0]} for task in pack.tasks}
            report = score(pack, replies, source="synthetic_smoke_test", model=None,
                           settings={"strategy": "always select the first allowed reply for the task type"})
            report_path = artifact_path(root, f"{pack.dataset}/scores-smoke.json")
        else:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            report_path = args.report or artifact_path(root, f"runs/{stamp}.json")
            if report_path.suffix.lower() != ".json" or report_path.exists() or report_path.is_symlink():
                raise ValueError("Choose a new .json path for the score report")
            if args.command == "score":
                report = score(pack, read_replies(args.replies), source="supplied_replies", model=None, settings={})
            elif args.command == "replay":
                report = replay(pack, args.source)
            else:
                if not 1 <= args.max_tokens <= 4096:
                    raise ValueError("--max-tokens must be between 1 and 4096")
                checkpoint = report_path.with_suffix(".run")
                report = run(pack, args.model, args.backend, args.text_only, args.base_url, args.effort, args.max_tokens,
                             checkpoint=checkpoint, resume=args.resume, request_limit=args.request_limit)
                missing = report["scores"]["missing_reply"]
                if missing:
                    print(f"Paused with {missing} tasks remaining. Resume with the same --report {report_path}")
                    return int(report["scores"]["request_error"] > 0)
        write_bytes(report_path, json_bytes(report), replace_existing=args.command == "demo")
        print_score(report, report_path)
        return int(report["scores"]["request_error"] > 0)
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
