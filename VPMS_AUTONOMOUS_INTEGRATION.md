# VPMS Autonomous Integration Assignment

This repository participates in the full VPMS Autonomous Completion Program owned by `Joeplouis/video-production-management-system` umbrella issue #4.

## Role
Open Notebook remains the mandatory podcast intelligence/research service. VPMS orchestrates it; Open Notebook does not become the VPMS global state owner or final visual renderer.

## Required target
- accept VPMS source modes: `quadran | research | script | hybrid`;
- produce canonical source synthesis + outline;
- produce dynamic 1–4 speaker dialogue;
- produce stable `turn_id` and `speaker_id` values, never identity-by-array-position;
- produce segment/chapter structure;
- produce facts/data suitable for infographics;
- produce visual/B-roll cues;
- expose a canonical `OpenNotebookPodcastPackageV1`-compatible payload;
- expose truthful async request/status/result behavior suitable for a VPMS adapter;
- preserve source provenance/fidelity;
- keep provider/model internals inside Open Notebook.

## Autonomous execution
Implementation may continue without waiting for ChatGPT after every small task. Use bounded commits and independent evaluation (`IMPLEMENTER != EVALUATOR`). Evaluator PASS should advance directly to the next dependency-valid item.

## Dependency rule
Connector/contract implementation and tests may be prepared in parallel. Production integration/qualification must not bypass the governing VPMS dependency gates.

## Hard stops
Escalate only for a P0 architecture/security contradiction, destructive data action, missing secret/credential that cannot be resolved from authorized config, or new paid provider spend requiring Joseph's authorization.

## Evidence
Every completed workstream must write pushed SHA, test results, contract examples and evaluator verdict to GitHub so Joseph never needs to relay results manually between sessions.
