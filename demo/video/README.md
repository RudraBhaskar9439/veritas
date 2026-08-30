# Veritas cinematic films

This folder contains the deterministic renderers for the Veritas opening film and its
focused Gmail-to-Google-Tasks use-case cut. Both are original motion-graphics sequences
using Veritas's dark-green evidence, lineage, repair, and certification visual language.

## Recommended judge opening — 48 seconds

`veritas_judge_intro.py` is the recommended opening for the four-minute submission video.
It uses an ordinary customer email as the emotional hook, shows the contradictory Google
Task, then explicitly zooms out: that route is only one consequence inside the larger
Sheets + Docs + Gmail → Docs + Slides + Gmail drafts + Tasks integrity platform.

| Time | Beat |
| --- | --- |
| 00:00–00:06 | A customer changes their mind through a normal email |
| 00:06–00:12 | Gmail and the existing Google Task now contradict each other |
| 00:12–00:18 | The film reveals that email → task is only one consequence route |
| 00:18–00:25 | Detect → Trace → Repair → Verify defines the complete product |
| 00:25–00:32 | Four claims, five artifacts, nine manifest paths, zero inferred paths |
| 00:32–00:39 | Native repairs span Docs, Slides, Gmail drafts, and Tasks |
| 00:39–00:45 | Independent verification issues a scoped certificate |
| 00:45–00:48 | Veritas product promise |

```bash
python3 demo/video/veritas_judge_intro.py \
  --music /absolute/path/to/mixkit-cat-walk-371.mp3 \
  --output /absolute/path/to/veritas-judge-intro-48s-1080p60.mp4 \
  --preview-frames /absolute/path/to/judge-storyboard-frames
```

## Definitive complete-product film

`veritas_cinematic_intro.py` presents Veritas as the continuous evidence-integrity runtime
it actually is. Gmail is one registered signal and Google Tasks is one downstream surface;
the story covers the complete lifecycle across Google Workspace.

| Time | Beat |
| --- | --- |
| 00:00–00:07 | Registered signals span Sheets metrics, Docs policy, and customer Gmail |
| 00:07–00:14.77 | Every meaningful change becomes authenticated, immutable evidence |
| 00:14.77–00:20 | A downstream claim silently remains stale |
| 00:20–00:26.5 | Docs, Slides, Gmail corrections, Tasks, and protected prose need different repairs |
| 00:26.5–00:32.5 | The cross-system integrity gap is quantified |
| 00:32.5–00:38.5 | The failure is shown between otherwise-correct tools |
| 00:38.5–00:44.5 | The Claim Manifest authorizes exact paths and excludes similarity guesses |
| 00:44.5–00:51.5 | Detect → Trace → Repair → Verify closes the consequence loop |
| 00:51.5–00:58.6 | Gemini reasons inside deterministic approval and revision boundaries |
| 00:58.6–01:04.5 | A separate read-only verifier checks every target and protected region |
| 01:04.5–01:09 | Every registered Workspace surface reaches a verified state |
| 01:09–01:12 | Veritas product reveal |

```bash
python3 demo/video/veritas_cinematic_intro.py \
  --music /absolute/path/to/mixkit-cat-walk-371.mp3 \
  --output /absolute/path/to/veritas-complete-product-intro-1080p60.mp4 \
  --preview-frames /absolute/path/to/product-storyboard-frames
```

## Focused Gmail-to-Tasks use case

`veritas_email_tasks_intro.py` tells one narrower customer-email → authenticated route →
owned Google Task → integrity certificate story. It is useful as a later demo chapter, but
is intentionally not the main product introduction.

Both renderers produce H.264, 1920×1080, 60 fps, AAC stereo, exactly 72 seconds. The supplied
`mixkit-cat-walk-371.mp3` track is not stored in this repository. Use `--start` and
`--duration` to render a short motion proof without changing absolute scene timing.
