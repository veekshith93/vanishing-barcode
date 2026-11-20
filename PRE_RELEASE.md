# Pre-release and packaging pilot sign-offs

## Hackathon sign-off

- [x] The factory generates and verifies a corrected ten-task batch with fold-order, artwork-position, color, repair and marked-face pairs. Archived packs still regenerate byte for byte.
- [x] The checker and independent rotated-cell grid agree on fully visible, partly covered and fully covered outcomes. Partial cover scores No. Edge contact has zero nominal area and requires review when the tolerance can change its label.
- [x] The corrected cases use a 2 mm relative covering-edge tolerance. Repair options are unique, preserve the required face and can be valid on either lid layer. Placement drawings retain a Front reference.
- [x] The scored synthetic release includes image and text-only runs, raw replies, pair scores, false passes, false rejects and a manual-review count. The image run was paused at three requests and resumed from its checkpoint. [Recorded runs](RESULTS.md)
- [x] Tests cover malformed replies, timeouts, quota failures, concurrent ownership, filesystem integrity, and an image containing an instruction to the model.
- [x] A fresh Python environment passed 37 tests, generated and verified a new seed, and reproduced the corrected vision and text-only scores. Chrome exercised fixed-order visibility, both corresponding print sheets, the saved-score view and the mobile layout.
- [x] The local share candidates passed the common credential pattern and relative-link checks. The dependency audit found no known advisories in the four pinned Python packages. Recheck the GitHub history when updating the remote.
- [ ] Have teammates solve a mixed blind batch from the model inputs. Record answers and objections against each task ID.
- [ ] Check print scale, cut and crease marks, print side, hinges and lid order on paper. Photograph both signature outcomes and representative partial-cover and repair outcomes. Repeat with representative carton stock before extrapolating to real packaging. [Physical checks](PHYSICAL_CHECK.md)
- [ ] Recheck the participant portal rules, the shared GitHub history, public links, demo recording and deck before submission.

## Real-world pilot sign-off

- [ ] Observe how packaging or warehouse staff approve artwork, assemble cartons and investigate a scan failure. Identify the decision owner and record the baseline time, rework and consequences of a missed case.
- [ ] Collect approved real cartons and print runs across relevant materials and settings. Record measured cut, crease, position and material offsets. Use actual assembled samples and independently known pass and fail labels.
- [ ] Verify print and scan performance separately with the intended symbology, stock, scanner and scan angles. Record grade, contrast, quiet zones, label size, curvature, wrinkles and glare as relevant. Use the applicable verifier criteria when a barcode-quality claim is required. [GS1 guidance on measuring printed barcode quality](https://support.gs1.org/support/solutions/articles/43000734152-how-can-i-measure-the-quality-of-my-printed-barcodes-)
- [ ] Agree with the process owner on acceptable false-pass, false-reject, manual-review and turnaround thresholds, sample counts, and the process for adjudicating disagreements.
- [ ] Agree on what may leave the partner network, which provider may receive it, who may access it, and retention and deletion dates. Keep raw customer material and credentials out of routine logs.
- [ ] Run alongside the existing approval process with a human retaining authority. Investigate false passes first. Define when to stop, who can revoke access, and how to return to the existing workflow after a tooling, stock, scanner or artwork change.

## Security and score interpretation

The browser demo runs offline. The evaluator sends generated raster images and a short prompt. Reports omit custom endpoints and the API runner checks for echoed credentials. Private evidence and checkpoints are git-ignored. A shared service would require tests of account and storage boundaries, HTTPS, upload controls and quotas. [OWASP ASVS](https://asvs.owasp.org/)

A false pass is a Yes on a partly or fully covered barcode. A false reject is a No for a fully visible barcode. Missing, malformed and failed responses are counted as manual review and stay in the accuracy denominator. The benchmark measures geometric visibility. Scan quality is verified on real printed samples.
