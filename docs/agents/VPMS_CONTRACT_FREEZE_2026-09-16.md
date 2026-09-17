# VPMS Contract Freeze — 2026-09-16 (SUP-20260916 Workstream 4)

**Repository:** Joeplouis/open-notebook · **Branch:** feat/vpms-production-hardening
**Authority:** SUP-20260916-AVATAR-OPENNOTEBOOK-PRODUCTION-CLOSURE (fetched from the VPMS repo); Chairman Joseph Louis.
**Purpose:** freeze the canonical cross-repo package contract that the VPMS adapter (`vpms/adapters/open_notebook/worker.py`), the Open Notebook fork (this repo), and Avatar-Webinar all target.

## Canonical contract version

**schema_version: `open-notebook.podcast-package.v1`** — exposed read-only at:

```
GET /api/podcasts/episodes/{episode_id}/vpms-package
    ?source_mode=quadran|research|script|hybrid   (default: script)
    &vpms_job_id=<vpms job id>                    (optional, echoed for lineage)
    &source_ref=<evidence/source ref>              (optional, repeatable; preserved in provenance)
```

Responses:
- `200` — canonical `OpenNotebookPodcastPackageV1`
- `404` — unknown episode
- `422` — invalid source_mode / unknown speaker in transcript / missing explicit voice_id (useful message, never silent fallback)

The endpoint is a **read-only export view** over the fork's native `PodcastEpisode` lifecycle — it never creates a second episode lifecycle (VPMS owns global state; the fork owns podcast intelligence).

## Contract shape (frozen)

| Field | Type | Notes |
|---|---|---|
| schema_version | str | `open-notebook.podcast-package.v1` |
| episode_id | str | native fork episode id |
| vpms_job_id | str\|null | echoed from query param |
| topic | str | episode name / derived topic |
| source_mode | quadran\|research\|script\|hybrid | declared by caller; recorded in provenance |
| speakers[] | SpeakerProfileV1 | **stable `speaker_id`** derived deterministically from display-name slug (`spk_<slug>`) — NEVER array position; reordering the array cannot re-identify a speaker |
| speakers[].voice | {provider, voice_id} | **explicit voice_id required**; missing → 422/ValueError (no default/random fallback); provider resolved or `"unset"` (never invented) |
| turn_manifest[] | DialogueTurnV1 | **stable `turn_id`** `turn_0000..N`; `speaker_id` references canonical ids only; unknown transcript speaker → fail closed |
| research | {source_evidence_refs[], evidence_artifact_id} | provenance preserved verbatim |
| outline_artifact_id / turn_manifest_artifact_id / visual_intelligence_artifact_id | str\|null | derived from episode id (`<id>:outline` etc.) |
| manifest_sha256 | str | **content-deterministic** — hashes the package payload EXCLUDING wall-clock `provenance.generated_at`; same episode content ⇒ same hash |
| provenance | {generated_by, generated_at, package_version, source_mode, source_refs, note} | `generated_at` is informative only (not in fingerprint) |

## Known contract gaps vs the VPMS `OpenNotebookPodcastPackageV1` (documented, not hidden)

1. **Avatar assets** — `SpeakerProfileV1.avatar` (VPMS) requires an `avatar_id`; the fork has no avatar asset pipeline. The VPMS adapter must treat a missing/omitted avatar as "no avatar render" (or Avatar-Webinar supplies the avatar reference at submission). **Requires:** avatar asset pipeline (Avatar-Webinar side) to complete.
2. **Visual/B-roll cues** — the fork exports only truthful `speaker_lipsync` cues derived from turns. Real infographic/chart/B-roll cues require the visual-intelligence pipeline. **Requires:** visual-intelligence pipeline to complete. The package `note` field documents this on every export.
3. **Source-mode persistence** — the fork's native generation does not persist a source-mode field on episodes; the endpoint accepts it as a caller-declared query param and records it in provenance. The VPMS adapter always passes the mode it received in the job request (truthful end-to-end lineage).

## Health contract

- `GET /health` is **truthful**: probes SurrealDB (`RETURN 1`) and the command/queue store (2s timeouts). All reachable → `200 {"status":"ok","checks":{...}}`; any subsystem unreachable → `503 {"status":"degraded","checks":{...}}`. Never `healthy` by construction.
- The VPMS adapter (`vpms/adapters/open_notebook/worker.py`) requires the fork's `/health` to return 200 before dispatch; otherwise it fails closed (503/FAILED).

## Boundary (paid provider, documented per Workstream 6)

The package export + health + tests are entirely no-cost. One REAL `POST /api/podcasts/generate` job (via `surreal_commands` → podcast-creator: outline LLM + per-segment transcript LLM + TTS) is the charge boundary: **honest max cost ≈ US$2–3 per canary episode** (LLM $0.05–0.15 + TTS $0.20–2.00 for a 15–20 min script). No generation was run during this closure program — the canary is the single bounded spend request to Joseph/ChatGPT when authorized.

## Test evidence (exact SHAs)

- Baseline at `c3285ff`: native suite could NOT collect (33 collection errors — system python lacked project deps; `pip install -e .` fails upstream `resolution-too-deep` / `ResolutionImpossible` on the fork's own declared manifest).
- At the new SHA (below): **683 passed, 3 warnings** in the project venv (`/opt/empire/workspaces/open-notebook-venv`), including **28/28 new `tests/test_vpms_package.py`** contract tests (1/2/3/4 speakers stable ids, position-independence, determinism, unknown-speaker 422, missing-voice 422, 4 source modes, provenance, health truthfulness).
- Fork-internal fix required to make the app importable at all: `open_notebook/config/` package (empty `__init__.py`, unused `production_validator.py`) **shadowed the tracked `config.py` module** and broke every `from open_notebook.config import ...` — removed (zero references existed) and CORS test re-probed via `/` because `/health` is now truthful (503 without SurrealDB).
