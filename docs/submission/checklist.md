# Final submission checklist

## Eligibility and positioning

- [ ] Entrant registration and country eligibility reconfirmed.
- [x] Primary track is written exactly as **The Taskmaster**.
- [x] Eligible additional prize positioning is limited to **Individual/Hobbyist** and **Best Architectural Design**; each project can receive at most one prize.
- [x] Build-period, AI-assistance, third-party component, and data disclosures are recorded in `disclosures.md`.
- [x] Gemini 3.5 Flash is bound through the Google Gen AI SDK on Vertex AI.

## Product proof

- [x] `cloud-proof-manifest.json` has no pending item; three incomplete claims are explicitly `partial`.
- [x] Public URL works in a signed-out browser and on phone width.
- [x] Accepted commit matches deployed image digests.
- [x] Production worker identity returned a schema-valid Gemini 3.5 Flash review from the deployed immutable image.
- [x] Real Workspace APIs generate and repair the packet.
- [x] Deterministic formatting-only, wrong-repair, duplicate-event, worker-interruption, and stale-source negatives pass.
- [x] Accessibility, keyboard, refresh, and responsive checks pass on the hosted URL.

## Optional strengthening — not eligibility blockers

- [ ] Record five consecutive clean live runs.
- [ ] Record every separate live failure injection beyond the proven Gemini outage/replay path.
- [ ] Publish stable live p50/p95 latency, token usage, and post-billing-delay Cloud cost.

## Four-minute video

- [ ] One continuous successful product run is visible.
- [ ] Source changes on screen from 4% to 9%.
- [ ] No prompt or manual trigger appears after the source edit.
- [ ] Blast radius shows 4 claims, 5 artifacts, and 9 paths.
- [ ] Human approval, immutable email correction, and preserved CFO paragraph are visible.
- [ ] Independent verification and scoped certificate are legible.
- [ ] Google Cloud architecture and green build appear briefly.
- [ ] Runtime is 3:58 or less; captions and 1080p playback checked.
- [ ] No secrets, personal data, billing data, or OAuth tokens are visible.

## Devpost page

- [x] Tagline explains consequence repair, not generic AI automation.
- [x] “What it does” matches the implemented product exactly; recheck against the final recording.
- [x] Google Cloud and Workspace services are named with real proof.
- [x] Benchmark language says deterministic/offline where appropriate.
- [ ] Repository access instructions work for judges.
- [x] Live URL, architecture diagram, and test instructions are linked in the submission package.
- [ ] Final video URL and selected screenshots are linked after upload.
- [x] No sentence claims universal truth or guaranteed correctness.

## Final freeze

- [x] Latest GitHub workflow is fully green.
- [x] Working tree was clean and a release tag was pushed after verification.
- [x] Submission was reread once as a Taskmaster judge and once as an architecture judge.
- [ ] Devpost preview was checked after saving.
- [ ] Submission confirmation and final URLs are archived.

## Entrant-only legal confirmations

- [ ] Entrant was above the age of majority in their jurisdiction when entering.
- [ ] Entrant's residence, sanctions status, employment, household, and government affiliations satisfy Section 3 of the official rules.
- [ ] Devpost registration/team list is complete and any employer approval is documented if applicable.
- [ ] The entrant has personally reviewed the ownership, privacy, third-party terms, and submission warranties.
