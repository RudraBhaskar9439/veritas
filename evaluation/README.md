# Veritas evaluation suite

The Phase 11 benchmark contains exactly forty versioned scenarios. Every scenario invokes production Veritas decision code; the dataset does not contain pre-filled model outputs or an `actual` field.

| Stratum | Cases | Production boundary exercised |
|---|---:|---|
| Semantic delta | 8 | baseline, duplicate, cosmetic, and meaningful classification |
| Registered lineage | 8 | source-to-claim-to-artifact blast radius |
| Repair policy | 8 | operation and approval/draft/block disposition |
| Three-way merge | 8 | apply, already-applied, human conflict, invalid target |
| Certification | 8 | complete coverage and six false-certificate attempts |

Run:

```bash
uv run python scripts/run_evaluation.py --check
```

The command verifies the dataset checksum, recomputes all metrics, compares them with [`results.json`](results.json), enforces [`thresholds.json`](thresholds.json), and applies a one-second offline runtime budget. The evaluation performs no external API calls and therefore has zero external API cost.

These are deterministic implementation metrics—not substitutes for production performance claims. Real Workspace generation, event handling, repair, verification, and recovery have now been demonstrated in the preview project; see [`../docs/submission/live-proof-report.md`](../docs/submission/live-proof-report.md). A defensible p50/p95, exact Gemini usage, Cloud cost, and five consecutive clean production runs remain partial.
