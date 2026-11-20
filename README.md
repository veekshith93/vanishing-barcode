# The Vanishing Barcode

Innodata Frontier AI Hackathon 2026 · Track 2 · Visual Task Factory

The benchmark tests whether a vision model can read a flat carton drawing and predict which artwork will be exposed after assembly. In the signature pair the paper layout and barcode are identical. Close B then A and the barcode stays visible. Close A then B and the outer flap covers it. The benchmark measures placement and occlusion geometry. Print quality and scanner performance are outside its scope.

[Open the browser prototype](output/prototype.html) · [First pair and live results](RESULTS.md) · [Print the signature carton](output/pdf/carton.pdf) · [Blind and physical validation procedure](PHYSICAL_CHECK.md)

Download `output/prototype.html` and open it in a browser to try all four pairs, reveal geometry, and compare recorded model replies. The file works offline and includes the printable cartons. To export updated layouts, run `python -m vanishing_barcode --seed 2026 prototype` after setup.

## Run locally

Use Python 3.11 or newer. From the project directory, install the pinned dependencies and run the offline demo.

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m vanishing_barcode demo
```

`demo` regenerates and verifies the signature pair, prints the location of the A4 sheet, and scores synthetic replies. Always answering Yes earns 1/2 items and 0/1 pairs. Run the checks with `python -m unittest discover -s tests -v`.

### Generate and evaluate fresh layouts

The following command runs generation, verification, evaluation, and reporting. It uses the existing Codex CLI sign-in and sends each task in a new session. The default reasoning effort is `low`.

```sh
python -m vanishing_barcode --dataset evaluation --seed 2026 run --generate \
  --backend codex --model gpt-6.2-sol
```

Reuse the generated pack with `run` and omit `--generate`. Add `--text-only` to run the same questions without images. To use a different seed while preserving existing artifacts, select another output directory.

```sh
python -m vanishing_barcode --output output/seed-2027 --dataset evaluation --seed 2027 generate
python -m vanishing_barcode --output output/seed-2027 --dataset evaluation --seed 2027 verify
```

For an authorized Chat Completions endpoint, set `OPENAI_API_KEY` for OpenAI or `VB_API_KEY` for a custom HTTPS endpoint. The `--base-url` ends before `/chat/completions`. Set `--model` to a vision-capable model available to that account. The command prints the path to the report, which defaults to `output/runs/`. Supply a new path with `--report` to save a specific run.

```sh
python -m vanishing_barcode --dataset evaluation run --generate \
  --backend api --model "$VB_MODEL"
```

To score replies already collected, create a JSON object whose keys are task IDs and whose values are the raw reply strings. Use the same dataset and seed as the original run.

```sh
python -m vanishing_barcode --dataset evaluation --seed 2026 score replies.json \
  --report output/runs/replayed.json
```

## Task design

| Task | What changes | How the answer is checked |
| --- | --- | --- |
| Visibility | Two opposite closure orders, with an identical barcode in each image. In the seeded layout the barcode is on the back lid and occlusion is partial. | Fold both lid rectangles into the top plane and intersect the later flap with the barcode. A separate 1 mm grid rotates flat-net cell centres and recomputes the exposed layers. |
| Placement | The art and fold order stay fixed while two side-wall fills change. | Locate the diamond on the flat strip and compare its panel identity to the outward normal obtained from the turns relative to the marked Front wall. |
| Repair | The same three rectangles appear in both images. The order changes which candidate is covered. A third candidate crosses a crease. | Recompute each candidate’s visibility, reject rectangles that cross a crease, and require exactly one valid answer. |

Each seed generates three layouts beyond the fixed demo. The seam and base hinges differ between layouts. The seeded parameters change dimensions, lid reach, order, target wall, and repair option letters. Geometry rejects lids that leave a gap, fail clearance, or put a marking at risk of changing its visibility label when the covering edge moves 1 mm. The prototype assumes thin sheet material and two opaque lid flaps that fold inward in sequence.

The public manifest lists only task ID, image path, and question. The model receives the PNG, question, and a short reply-format instruction. Ground truth, dimensions, print sheets, and closed-carton reveals are available for judges to inspect separately. Every report keeps the exact raw reply, normalized answer, status, model, settings, seed, and pack fingerprint. Pair accuracy requires both answers to be correct. Wrong, missing, unparseable, and failed requests stay in the denominator.

## Files to inspect

| Artifact | Where to look |
| --- | --- |
| Signature questions and inputs | [Manifest](output/sample/tasks.jsonl) and [images](output/sample/images/) |
| Held-out questions and inputs | [Manifest](output/evaluation/tasks.jsonl) and [images](output/evaluation/images/) |
| Answer keys and closed-carton reveals | [Signature reference](output/sample/reference.json), [evaluation reference](output/evaluation/reference.json), and [evaluation reveals](output/evaluation/reveals/) |
| Automated validation and scoring evidence | [Signature checks](output/sample/validation.json), [evaluation checks](output/evaluation/validation.json), and [results](RESULTS.md) |
| Print and teammate evidence | [A4 signature sheet](output/pdf/carton.pdf), [held-out sheets](output/evaluation/print/), and [observation procedure](PHYSICAL_CHECK.md) |

## Security and integrity checks

- Verification rebuilds the selected pack and compares every required saved artifact byte for byte. The runner uses the in-memory render that was verified, avoiding a second read of editable inputs before transmission. Artifact reads reject symlinks, non-regular files, and unexpected byte lengths. Regenerate on the machine running the evaluation if a platform renders or encodes a PNG differently.
- Codex gets a new temporary directory with one generic `input.png` or an empty directory for text-only. The runner disables shell, browsing, apps, plugins, memory, and project instructions for that turn. Observed tool activity invalidates the reply. This is a benchmark harness for generated local packs and a trusted model client.
- API requests use HTTPS and refuse redirects. The runner uses credentials from the environment and redacts an echoed bearer token. API replies and supplied reply files have size limits. The scorer rejects unknown IDs and duplicate fields in a supplied reply file. Live and replay reports are created without overwriting an existing report.
- The automated tests exercise the geometry, artifact integrity, outbound request contents, credential handling, and error scoring. The dependency audit records the advisories found by `pip-audit` for the pinned Python requirements at the time of the check. [Audit output](output/qa/dependency-audit.json)

## First-round evidence

| Criterion | Evidence in this repository | Evidence to add before submission |
| --- | --- | --- |
| Implementation and repeatability · 25% | One-command pipeline, seeded replay, CLI tests, saved reports | Run the walkthrough from a clean checkout during the recorded demo |
| Validity · 25% | Independent area checks, hinge and pixel tests, printable sheets | Blind teammate answers and photos of both signature orders, a partial cover, and a repair |
| Meaningful variation · 20% | Visibility, placement, and repair on three layouts per seed | Add more independently reviewed layouts to broaden the evaluation |
| Originality and engineering judgment · 15% | Fold-order flips, cosmetic control, text-only comparison, documented limits | Use representative model replies and physical observations in the pitch |
| Impact and communication · 15% | Real placement failure that changes when the carton is closed | Record the disappearing-barcode demo and populate the official deck |

The generator, geometry, diagrams, and scoring code were written for this project. The rendering stack uses ReportLab, PDFium via pypdfium2, and Pillow. APPUMAX and IRIS were workflow references. The sample assets were generated without manual changes to the images or labels. The repair annotation was moved off a crease and the repair wording clarified in source before the recorded evaluation. [APPUMAX](https://github.com/Vigneshcit2006/Vision-Bench-AI) · [IRIS project plan](https://github.com/Saravana-Rajan/IRIS/tree/plan)

The public brief lists December 6, 2026 as the submission deadline. Use the registered team portal to get the current interface, submission form, and official deck template. The submission package calls for the prototype brief, tech stack, public repository, demo video link, and official deck. [Track 2 brief](https://hack2skill.com/event/innodata/?sectionid=6aee108b9be15aea67016065) · [Submission walkthrough](https://www.youtube.com/watch?v=X6lTYulY04M&t=1846s)
