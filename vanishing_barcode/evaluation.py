"""Score reply text and send isolated, one-image model requests."""

import base64
import json
import os
import re
import subprocess
from collections import defaultdict
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .dataset import digest, read_json
from .journal import checkpoint as open_checkpoint

DEFAULT_BASE_URL = "https://api.openai.com/v1"
API_LIMIT = 1_000_000
FAILURES = ("incorrect", "parse_error", "request_error", "missing_reply")
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
CODEX_FLAGS = (
    "--json", "--color", "never", "--ephemeral", "--ignore-user-config", "--ignore-rules",
    "--sandbox", "read-only", "--skip-git-repo-check", "--disable", "memories",
    "--disable", "plugins", "--disable", "apps", "--disable", "shell_tool",
    "--disable", "image_generation", "--disable", "multi_agent",
    "--enable", "skip_host_skill_discovery", "-c", 'web_search="disabled"',
    "-c", "mcp_servers={}", "-c", "project_doc_max_bytes=0", "-c", 'approval_policy="never"',
)
CODEX_ENV = ("PATH", "HOME", "CODEX_HOME", "TMPDIR", "USER", "LOGNAME", "LANG", "LC_ALL", "SYSTEMROOT")


def format_instruction(kind):
    return "Reply with one word: Yes or No." if kind == "visibility" else "Reply with just one of the listed choices."


def parse_answer(reply, choices):
    match = re.fullmatch(r"([a-zA-Z]+)[.!]?", reply.strip()) if isinstance(reply, str) else None
    token = match.group(1).lower() if match else None
    return token if token in choices else None


def totals(items, pairs):
    correct_items = sum(item["status"] == "correct" for item in items)
    correct_pairs = sum(pair["correct"] for pair in pairs)
    return {"items": len(items), "correct_items": correct_items, "item_accuracy": correct_items / len(items) if items else 0,
            "pairs": len(pairs), "correct_pairs": correct_pairs, "pair_accuracy": correct_pairs / len(pairs) if pairs else 0,
            **{status: sum(item["status"] == status for item in items) for status in FAILURES}}


def visibility_outcomes(items):
    visibility = [row for row in items if row["task_type"] == "visibility"]
    covered = sum(row["expected"] == "no" for row in visibility)
    clear = len(visibility) - covered
    false_pass = sum(row["status"] == "incorrect" and row["expected"] == "no" for row in visibility)
    false_reject = sum(row["status"] == "incorrect" and row["expected"] == "yes" for row in visibility)
    review = sum(row["status"] in ("parse_error", "request_error", "missing_reply") for row in visibility)
    return {"false_pass": false_pass, "covered_cases": covered, "false_pass_rate": false_pass / covered if covered else None,
            "false_reject": false_reject, "clear_cases": clear, "false_reject_rate": false_reject / clear if clear else None,
            "manual_review": review, "visibility_cases": len(visibility)}


def score(pack, replies, **run_info):
    if set(replies) - {task.id for task in pack.tasks}:
        raise ValueError("Reply file contains an unknown task ID")
    items, groups = [], defaultdict(list)
    for task in pack.tasks:
        row = task.reference
        reply = replies.get(task.id, {})
        parsed = parse_answer(reply.get("raw_reply"), row["allowed_replies"])
        if reply.get("error"):
            status = "request_error"
        elif task.id not in replies:
            status = "missing_reply"
        elif parsed is None:
            status = "parse_error"
        else:
            status = "correct" if parsed == row["answer"] else "incorrect"
        item = {
            "raw_reply": None, **reply, "id": task.id, "pair_id": row["pair_id"], "pair_type": row["pair_type"],
            "task_type": row["task_type"], "image_sha256": row["image_sha256"], "expected": row["answer"],
            "parsed": parsed, "status": status,
        }
        items.append(item)
        groups[row["pair_id"]].append(item)

    pairs = []
    for pair_id, group in groups.items():
        if len(group) != 2:
            raise ValueError("Every pair must contain two tasks")
        pairs.append({"pair_id": pair_id, "task_ids": [item["id"] for item in group],
                      "type": group[0]["pair_type"], "task_type": group[0]["task_type"],
                      "correct": all(item["status"] == "correct" for item in group)})
    by_type = {kind: totals([item for item in items if item["task_type"] == kind],
                            [pair for pair in pairs if pair["task_type"] == kind])
               for kind in sorted({item["task_type"] for item in items})}
    return {**run_info, "dataset": pack.dataset, "seed": pack.seed, "pack_sha256": pack.sha256,
            "scores": totals(items, pairs), "visibility_outcomes": visibility_outcomes(items),
            "by_task_type": by_type, "items": items, "pairs": pairs}


def replay(pack, path):
    report = read_json(path, 12_000_000)
    if not isinstance(report, dict) or report.get("pack_sha256") != pack.sha256 or not isinstance(report.get("items"), list):
        raise ValueError("Saved report does not match this generated pack")
    known = {t.id: t.reference["image_sha256"] for t in pack.tasks}
    replies, seen = {}, set()
    for item in report["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("Invalid saved reply record")
        task_id = item["id"]
        if task_id not in known or task_id in seen or item.get("image_sha256") != known[task_id]:
            raise ValueError("Saved report contains a duplicate or mismatched task")
        seen.add(task_id)
        raw, error = item.get("raw_reply"), item.get("error")
        if any(value is not None and (not isinstance(value, str) or len(value) > 100_000) for value in (raw, error)):
            raise ValueError("Invalid saved reply text")
        if item.get("status") != "missing_reply" or raw is not None or error is not None:
            keys = ("raw_reply", "error", "seconds", "sent_image_sha256", "tool_item_types", "usage",
                    "reported_model", "finish_reason")
            replies[task_id] = {key: item[key] for key in keys if key in item}
    return score(pack, replies, source="saved_run_replay", model=report.get("model"), settings=report.get("settings", {}),
                 started_utc=report.get("started_utc"))


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def api_destination(base_url):
    if any(ord(char) <= 32 for char in base_url) or "\\" in base_url:
        raise ValueError("Model API URL contains invalid characters")
    base_url = base_url.rstrip("/")
    url = urlsplit(base_url)
    if url.scheme != "https" or not url.hostname or url.username is not None or url.query or url.fragment:
        raise ValueError("Model API URL must use HTTPS without URL credentials, query parameters, or a fragment")
    # Validate the port before using the endpoint. Keep its path out of the report.
    try:
        _ = url.port
    except ValueError:
        raise ValueError("Model API URL contains an invalid port") from None
    return base_url, f"https://{url.netloc}"


def chat_completion(url, key, model, max_tokens, prompt, png):
    content = [{"type": "text", "text": prompt}]
    if png is not None:
        uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": uri, "detail": "high"}})
    body = {"model": model, "messages": [{"role": "user", "content": content}],
            "max_completion_tokens": max_tokens}
    request = Request(url + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    request.add_unredirected_header("Authorization", f"Bearer {key}")
    try:
        with build_opener(NoRedirects()).open(request, timeout=90) as response:
            data = response.read(API_LIMIT + 1)
        if len(data) > API_LIMIT:
            return {"error": "Model API response exceeded the byte limit"}
        payload = json.loads(data)
        choice = payload["choices"][0]
        message = choice["message"]
        text, refusal, finish = message.get("content"), message.get("refusal"), choice.get("finish_reason")
        model_name = payload.get("model")
        if any(isinstance(value, str) and key in value for value in (text, refusal, finish, model_name)):
            return {"error": "Provider echoed a credential in its response", "raw_reply": "[redacted]"}
        raw = text if isinstance(text, str) else refusal if isinstance(refusal, str) else None
        reply = {"raw_reply": raw, "reported_model": model_name if isinstance(model_name, str) else None,
                 "finish_reason": finish if isinstance(finish, str) else None}
        if refusal or message.get("tool_calls") or finish in ("length", "content_filter", "tool_calls"):
            reply["error"] = "Completion was refused, truncated, or requested a tool"
        return reply
    except HTTPError as error:
        error.close()
        return {"error": f"HTTP {error.code}"}
    except OSError as error:
        return {"error": type(error).__name__}
    except (AttributeError, ValueError, KeyError, IndexError, TypeError):
        return {"error": "Unexpected chat completion response"}


def codex_events(stdout, code):
    try:
        if len(stdout) > 2_000_000:
            raise ValueError("Oversize event stream")
        events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        items = [event["item"] for event in events if event["type"].startswith("item.")]
        messages = [event["item"]["text"] for event in events
                    if event["type"] == "item.completed" and event["item"]["type"] == "agent_message"]
        if any(not isinstance(message, str) for message in messages):
            raise ValueError("Invalid Codex reply text")
        activity = sorted({item["type"] for item in items if item["type"] not in ("agent_message", "reasoning", "error")})
    except (AttributeError, ValueError, KeyError, TypeError):
        return {"error": "Unexpected Codex event stream"}

    completed = [event for event in events if event["type"] == "turn.completed"]
    response = {"raw_reply": "\n".join(messages) if messages else None, "tool_item_types": activity}
    if activity:
        return {**response, "error": "Tool activity observed in model turn"}
    if code or len(completed) != 1 or any(event["type"] in ("error", "turn.failed") for event in events):
        return {**response, "error": f"Codex turn failed (exit {code})"}
    usage = completed[0].get("usage")
    response["usage"] = {name: count for name, count in usage.items() if type(count) is int} if isinstance(usage, dict) else None
    return response


def codex_completion(model, effort, prompt, png):
    with TemporaryDirectory(prefix="vb-eval-") as folder:
        cmd = ["codex", "exec", *CODEX_FLAGS, "-m", model, "-c", f'model_reasoning_effort="{effort}"']
        if png is not None:
            (Path(folder) / "input.png").write_bytes(png)
            cmd.extend(("--image", "input.png"))
        cmd.extend(("--", "-"))
        env = {name: os.environ[name] for name in CODEX_ENV if name in os.environ}
        try:
            process = subprocess.run(cmd, cwd=folder, input=prompt, text=True, encoding="utf-8", errors="replace",
                                     env=env, capture_output=True, timeout=180, check=False)
        except subprocess.TimeoutExpired:
            return {"error": "Codex turn timed out"}
        except OSError as error:
            return {"error": type(error).__name__}
    return codex_events(process.stdout, process.returncode)


def run(pack, model, backend, text_only, base_url, effort, max_tokens, *, checkpoint=None, resume=False, request_limit=None):
    if not MODEL_ID.fullmatch(model):
        raise ValueError("Invalid model identifier")
    settings = {"backend": backend, "mode": "text-only" if text_only else "image+question",
                "format_instructions": {task.reference["task_type"]: format_instruction(task.reference["task_type"])
                                        for task in pack.tasks}}
    endpoint_fingerprint = None
    if backend == "api":
        base_url, origin = api_destination(base_url)
        key = os.getenv("VB_API_KEY") or (os.getenv("OPENAI_API_KEY") if base_url == DEFAULT_BASE_URL else None)
        if not key:
            raise ValueError("Set VB_API_KEY for your authorized model endpoint or OPENAI_API_KEY for OpenAI")
        if any(ord(char) <= 32 or ord(char) >= 127 for char in key) or key in model or key in base_url:
            raise ValueError("The API credential must be a bearer token supplied only through the environment")
        endpoint_fingerprint = digest(base_url.encode())
        settings.update(api_origin=origin if base_url == DEFAULT_BASE_URL else "custom HTTPS endpoint",
                        max_completion_tokens=max_tokens, image_detail=None if text_only else "high")

        def request(prompt, png):
            return chat_completion(base_url, key, model, max_tokens, prompt, png)
    else:
        version = subprocess.run(["codex", "--version"], check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        settings.update(cli_version=version, reasoning_effort=effort, cli_flags=list(CODEX_FLAGS))

        def request(prompt, png):
            return codex_completion(model, effort, prompt, png)

    identity = digest(json.dumps([pack.sha256, model, settings, endpoint_fingerprint], sort_keys=True).encode())
    local = {}
    log = (open_checkpoint(checkpoint, identity, {task.id for task in pack.tasks}, resume) if checkpoint is not None
           else nullcontext((local, local.__setitem__, datetime.now(UTC).isoformat(timespec="seconds"))))
    with log as (replies, record, started):
        pending = [task for task in pack.tasks if task.id not in replies]
        for task in pending[:request_limit]:
            png = None if text_only else task.png
            prompt = task.question + "\n\n" + format_instruction(task.reference["task_type"])
            start = monotonic()
            response = request(prompt, png)
            record(task.id, {**response, "seconds": round(monotonic() - start, 3),
                             "sent_image_sha256": None if png is None else digest(png)})
            if response.get("error") == "HTTP 429":
                break
    return score(pack, replies, source="model_run", model=model, settings=settings, started_utc=started)
