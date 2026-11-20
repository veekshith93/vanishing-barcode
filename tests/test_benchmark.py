import base64
import json
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, PngImagePlugin

from vanishing_barcode.artwork import rasterize
from vanishing_barcode.carton import (
    WALL_ORDER,
    Carton,
    Rect,
    checked_visibility,
    lid_grid,
    sampled_projection,
)
from vanishing_barcode.cases import (
    Case,
    Option,
    check_repair,
    make_cases,
    placed_face,
    solve,
)
from vanishing_barcode.dataset import (
    build_pack,
    generate,
    read_limited,
    read_replies,
    verify,
    write_bytes,
)
from vanishing_barcode.evaluation import (
    DEFAULT_BASE_URL,
    NoRedirects,
    api_destination,
    chat_completion,
    codex_completion,
    codex_events,
    parse_answer,
    run,
    score,
)


class GeometryTests(unittest.TestCase):
    def test_signature_visible_and_fully_covered(self):
        visible, covered = map(solve, make_cases("sample", None))
        self.assertEqual((visible["answer"], visible["visible_mm2"], visible["covered_mm2"]), ("yes", 260, 0))
        self.assertEqual((covered["answer"], covered["visible_mm2"], covered["covered_mm2"]), ("no", 0, 260))

    def test_partial_cover(self):
        carton = Carton()
        result = checked_visibility(carton, ("A", "B"), "A", Rect(9, -15, 35, -5))
        self.assertEqual((result["answer"], result["covered_mm2"], result["grid_covered_mm2"]), ("no", 156, 156))

    def test_clear_lower_layer_can_be_visible(self):
        result = checked_visibility(Carton(), ("A", "B"), "A", Rect(9, -6, 35, -3))
        self.assertEqual(result["answer"], "yes")

    def test_borderline_and_crossing_mark_rejected(self):
        carton = Carton()
        with self.assertRaisesRegex(ValueError, "1 mm"):
            checked_visibility(carton, ("A", "B"), "A", Rect(9, -9, 35, -4))
        with self.assertRaisesRegex(ValueError, "flap edges"):
            checked_visibility(carton, ("A", "B"), "A", Rect(9, -10, 35, 1))

    def test_gap_collision_and_repeated_lid_rejected(self):
        for carton in (Carton(flap_a=10, flap_b=10), Carton(flap_b=36)):
            with self.subTest(carton=carton), self.assertRaises(ValueError):
                lid_grid(carton)
        with self.assertRaisesRegex(ValueError, "each flap once"):
            checked_visibility(Carton(), ("A", "A"), "A", Carton().barcode)

    def test_both_lids_sweep_above_the_opening(self):
        carton = Carton()
        for flap in ("A", "B"):
            for angle in (0, 15, 45, 75, 89):
                cells = sampled_projection(carton, flap, carton.flap(flap), angle)
                self.assertTrue(all(0 <= y <= carton.depth and z > carton.height for _, y, z in cells))

    def test_placement_across_rotated_wall_order(self):
        for first in WALL_ORDER:
            carton = Carton(first_wall=first)
            for name, wall in carton.walls():
                with self.subTest(first=first, name=name):
                    self.assertEqual(placed_face(carton, ((wall.x0 + wall.x1) // 2, 23))["answer"], name.lower())
        with self.assertRaisesRegex(ValueError, "side wall"):
            placed_face(Carton(), (44, 23))

    def test_repair_rejects_zero_or_multiple_valid_options(self):
        options = (Option("P", "A", Rect(9, -23, 31, -17)), Option("Q", "A", Rect(9, -17, 31, -11)),
                   Option("R", "A", Rect(9, -3, 31, 3)))
        for order in (("A", "B"), ("B", "A")):
            with self.subTest(order=order), self.assertRaisesRegex(ValueError, "exactly one"):
                check_repair(Case("test", Carton(), order, "repair", options=options))

    def test_seeded_pairs_across_many_layouts(self):
        for seed in range(100):
            cases = make_cases("evaluation", seed)
            results = list(map(solve, cases))
            with self.subTest(seed=seed):
                self.assertEqual({row["answer"] for row in results[:2]}, {"yes", "no"})
                no = next(row for row in results[:2] if row["answer"] == "no")
                self.assertGreater(min(no["covered_mm2"], no["visible_mm2"]), 0)
                self.assertNotEqual(results[2]["answer"], results[3]["answer"])
                self.assertEqual(results[4]["answer"], results[5]["answer"])
                self.assertEqual(len({case.carton for case in cases}), 3)


class PackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = build_pack("sample")

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        generate(self.root, self.pack)

    def test_regeneration_and_answer_free_manifest(self):
        manifest = self.pack.files["sample/tasks.jsonl"]
        tasks = [json.loads(line) for line in manifest.splitlines()]
        self.assertEqual(verify(self.root, self.pack), self.pack.validation)
        self.assertEqual(self.pack.files, build_pack("sample").files)
        self.assertEqual({task["question"] for task in tasks}, {self.pack.tasks[0].question})
        for task in tasks:
            self.assertEqual(set(task), {"id", "question", "image"})
            with Image.open(self.root / "sample" / task["image"]) as image:
                self.assertEqual(image.info, {})

    def test_seed_is_reproducible_and_changes_geometry(self):
        a = build_pack("evaluation", 8)
        self.assertEqual(a.files, build_pack("evaluation", 8).files)
        self.assertNotEqual(a.tasks[0].reference["case"]["carton"],
                            build_pack("evaluation", 9).tasks[0].reference["case"]["carton"])
        self.assertEqual(a.validation["pairs"]["carton-04"]["type"], "cosmetic")

    def test_print_scale_bar_is_50_mm(self):
        from reportlab.lib.units import mm
        image = rasterize(self.pack.files["pdf/carton.pdf"], 5 / mm).convert("L")
        self.assertEqual(image.size[0], 1050)
        marks = [x for x in range(90, 360) if image.getpixel((x, 173 * 5)) < 180]
        self.assertAlmostEqual(min(marks), 20 * 5, delta=1)
        self.assertAlmostEqual(max(marks) - min(marks), 50 * 5, delta=2)

    def test_pair_preview_keeps_carton_net_upright(self):
        with Image.open(BytesIO(self.pack.files["sample/pair-preview.png"])) as image:
            # The top-left flap has a teal interior above the wall band.
            x = round((28 + 306 * 56 / 620) * 1.7)
            y = round((116 + 306 * 166 / 620) * 1.7)
            self.assertEqual(image.getpixel((x, y)), (221, 239, 234))

    def test_manifest_and_reference_tampering_rejected(self):
        for relative in ("sample/tasks.jsonl", "sample/reference.json"):
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(b"!" + original[1:])
            with self.assertRaisesRegex(ValueError, "differs"):
                verify(self.root, self.pack)
            path.write_bytes(original)

    def test_png_metadata_change_rejected(self):
        path = self.root / "sample/images" / (self.pack.tasks[0].id + ".png")
        with Image.open(path) as image:
            png = image.copy()
        info = PngImagePlugin.PngInfo()
        info.add_text("Example", "extra field")
        png.save(path, pnginfo=info)
        with self.assertRaises(ValueError):
            verify(self.root, self.pack)

    def test_symlinked_input_or_directory_rejected(self):
        path = self.root / "sample/tasks.jsonl"
        replacement = self.root / "copy.jsonl"
        path.rename(replacement)
        path.symlink_to(replacement)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            verify(self.root, self.pack)
        (self.root / "sample").rename(self.root / "elsewhere")
        (self.root / "sample").symlink_to(self.root / "elsewhere", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symbolic link"):
            generate(self.root, self.pack)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO requires POSIX")
    def test_non_regular_input_rejected(self):
        path = self.root / "pipe"
        os.mkfifo(path)
        with self.assertRaisesRegex(ValueError, "regular file"):
            read_limited(path, 10)

    def test_duplicate_external_reply_ids_rejected(self):
        path = self.root / "replies.json"
        path.write_text('{"item":"Yes","item":"No"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            read_replies(path)

    def test_atomic_report_writer_refuses_to_overwrite(self):
        path = self.root / "scores.json"
        write_bytes(path, b"first", replace_existing=False)
        with self.assertRaises(FileExistsError):
            write_bytes(path, b"second", replace_existing=False)
        self.assertEqual(path.read_bytes(), b"first")


class EvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pack = build_pack("sample")

    def test_parser_requires_one_admissible_choice(self):
        self.assertEqual(parse_answer("  YES.\n", ("yes", "no")), "yes")
        self.assertEqual(parse_answer("q!", ("p", "q", "r")), "q")
        for raw in ("yes or no", "Probably yes", "**yes**", "", "right", None):
            self.assertIsNone(parse_answer(raw, ("yes", "no")))

    def test_metrics_count_parse_request_and_missing_errors(self):
        first, second = self.pack.tasks
        options = (({"raw_reply": "Yes, I think"}, "parse_error"), ({"error": "HTTP 429"}, "request_error"),
                   (None, "missing_reply"), ({"raw_reply": "Yes"}, "incorrect"))
        for second_reply, status in options:
            replies = {first.id: {"raw_reply": "Yes"}}
            if second_reply is not None:
                replies[second.id] = second_reply
            with self.subTest(status=status):
                summary = score(self.pack, replies)["scores"]
                self.assertEqual((summary["items"], summary["correct_items"], summary["correct_pairs"]), (2, 1, 0))
                self.assertEqual(summary[status], 1)
        self.assertEqual(score(self.pack, {first.id: {"raw_reply": "Yes"}, second.id: {"raw_reply": "No"}})
                         ["scores"]["correct_pairs"], 1)
        with self.assertRaisesRegex(ValueError, "unknown task ID"):
            score(self.pack, {"unknown": {"raw_reply": "No"}})

    @patch("vanishing_barcode.evaluation.chat_completion", return_value={"raw_reply": "Yes"})
    def test_model_runner_sends_only_question_and_verified_png(self, request):
        with patch.dict(os.environ, {"VB_API_KEY": "sample-test-credential"}):
            run(self.pack, "example-model", "api", False, DEFAULT_BASE_URL, "low", 512)
        self.assertEqual(request.call_count, len(self.pack.tasks))
        for task, call in zip(self.pack.tasks, request.call_args_list):
            self.assertEqual(call.args[4], task.question + "\n\nReply with one word: Yes or No.")
            self.assertEqual(call.args[5], task.png)
        with patch.dict(os.environ, {"VB_API_KEY": "sample-test-credential"}):
            run(self.pack, "example-model", "api", True, DEFAULT_BASE_URL, "low", 512)
        self.assertTrue(all(call.args[5] is None for call in request.call_args_list[-2:]))

    @patch("vanishing_barcode.evaluation.build_opener")
    def test_http_body_has_no_reference_or_tool_fields(self, make_opener):
        open_request = make_opener.return_value.open
        payload = {"choices": [{"message": {"content": "No"}, "finish_reason": "stop"}], "model": "example-model"}
        open_request.return_value = BytesIO(json.dumps(payload).encode())
        task = self.pack.tasks[0]
        result = chat_completion(DEFAULT_BASE_URL, "sample-test-credential", "example-model", 512, task.question, task.png)
        self.assertEqual(result["raw_reply"], "No")
        request = open_request.call_args.args[0]
        body = json.loads(request.data)
        self.assertIsInstance(make_opener.call_args.args[0], NoRedirects)
        self.assertIsNone(make_opener.call_args.args[0].redirect_request())
        self.assertEqual(set(body), {"model", "messages", "max_completion_tokens"})
        content = body["messages"][0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": task.question})
        self.assertEqual(base64.b64decode(content[1]["image_url"]["url"].split(",", 1)[1]), task.png)

    @patch("vanishing_barcode.evaluation.build_opener")
    def test_api_redacts_echoed_key_and_rejects_malformed_or_oversize_responses(self, make_opener):
        key = "sample-test-credential"
        replies = (json.dumps({"choices": [{"message": {"content": key}}]}).encode(),
                   b'{"choices":[{"message":true}]}', b"x" * 1_000_001)
        for data in replies:
            make_opener.return_value.open.return_value = BytesIO(data)
            result = chat_completion(DEFAULT_BASE_URL, key, "example-model", 512, "Question", None)
            self.assertIn("error", result)
            self.assertNotIn(key, json.dumps(result))

    def test_endpoint_validation(self):
        self.assertEqual(api_destination(DEFAULT_BASE_URL), (DEFAULT_BASE_URL, "https://api.openai.com"))
        for url in ("http://example.test", "https://user@example.test", "https://example.test/?key=secret",
                    "https://example.test/#frag", "https://example.test:\n443/v1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                api_destination(url)

    def test_codex_rejects_tool_activity_and_malformed_event_stream(self):
        final = {"type": "item.completed", "item": {"type": "agent_message", "text": "Yes"}}
        complete = {"type": "turn.completed", "usage": {"input_tokens": 10}}
        events = "\n".join(json.dumps(event) for event in (final, complete))
        self.assertEqual(codex_events(events, 0)["raw_reply"], "Yes")
        action = json.dumps({"type": "item.started", "item": {"type": "command_execution"}})
        self.assertIn("Tool activity", codex_events(action + "\n" + events, 0)["error"])
        self.assertIn("Unexpected", codex_events("not json", 0)["error"])
        self.assertIn("Unexpected", codex_events(events.replace('"text": "Yes"', '"text": 1'), 0)["error"])

    @patch("vanishing_barcode.evaluation.subprocess.run")
    def test_codex_inputs_and_environment_are_isolated(self, subprocess_run):
        task = self.pack.tasks[0]

        def executed(args, **options):
            cwd = Path(options["cwd"])
            self.assertEqual(sorted(p.name for p in cwd.iterdir()), ["input.png"])
            self.assertEqual((cwd / "input.png").read_bytes(), task.png)
            self.assertNotIn("OPENAI_API_KEY", options["env"])
            self.assertEqual(options["input"], task.question)
            stdout = '{"type":"item.completed","item":{"type":"agent_message","text":"Yes"}}\n{"type":"turn.completed"}'
            return SimpleNamespace(stdout=stdout, returncode=0)

        subprocess_run.side_effect = executed
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sample-test-credential"}):
            self.assertEqual(codex_completion("example-model", "low", task.question, task.png)["raw_reply"], "Yes")


if __name__ == "__main__":
    unittest.main()
