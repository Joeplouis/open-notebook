# VPMS Handoff — Open Notebook

VPMS_WORKSTREAM_ID: `VPMS-P4-OPENNOTEBOOK`  
PROJECT_NAME: Open Notebook  
REPOSITORY: `Joeplouis/open-notebook`  
TARGET_BRANCH: `feat/vpms-production-hardening`  
BASELINE_SHA: `9bd5f89c5985ffd277cfacece995a75c3ff2ea2a`  
CURRENT_BRANCH_HEAD_AT_HANDOFF_CREATION: `c3285ffdcc1a0523013953fd4146eacb31c0f35e`  
GOVERNING_PHASE: Phase 4D — Open Notebook podcast intelligence  
GOVERNING_SPEC: VPMS v2.1 master PRD + Open Notebook native AGENTS/VISION/architecture + cross-repo handoff contract  
PROGRAM_COORDINATOR: VPMS Program Coordinator  
IMPLEMENTATION_AGENT: UNASSIGNED  
EVALUATOR: UNASSIGNED; must differ from implementer  
SESSION_SUPERVISOR: ChatGPT VPMS Active Session Supervisor  
STATUS: HARDENING_PRESENT / WAITING_FOR_DEPENDENCY_VALID_BOUNDED_ASSIGNMENT

## Native project rules remain authoritative internally

Open Notebook's existing `AGENTS.md`, `VISION.md`, architecture docs and ADRs remain authoritative for its internal implementation. VPMS integration may add/extend contracts but must not break Open Notebook's async-first architecture or turn it into a video renderer.

## Ownership

OWNERSHIP_WRITE_PATHS: only Open Notebook paths explicitly granted by the bounded VPMS workstream.  
READ_ONLY_DEPENDENCIES: VPMS podcast/source contracts, SpeakerProfileV1/DialogueTurnV1/visual cue schema, Quadran evidence contract.  
SHARED_FILES_REQUIRING_COORDINATOR_OWNERSHIP: canonical cross-repo contract versions and VPMS schemas.

## Required VPMS role

Open Notebook is the mandatory podcast intelligence engine for VPMS podcast/long-form flows. It must accept `quadran | research | script | hybrid` inputs and produce a canonical package containing source synthesis, outline, 1–4 speaker dialogue, stable `turn_id` + `speaker_id`, chapter/segment structure, facts/data for visual use, visual/B-roll cues and downstream-ready metadata.

It does NOT own:

- VPMS global lifecycle;
- FishAudio speaker voice execution;
- Avatar-Webinar/H3 rendering;
- VMF/OpenMontage composition;
- publishing.

INPUT_CONTRACTS: `PodcastSourcePackageV1`, `SpeakerProfileV1`, evidence/research inputs.  
OUTPUT_CONTRACTS: `OpenNotebookPodcastPackageV1`, `DialogueTurnV1` sequence and visual intelligence package.  
UPSTREAM_HANDOFFS: source app / Quadran / VPMS.  
DOWNSTREAM_HANDOFFS: script evaluator, FishAudio, visual director, VPMS.

TEST_REQUIREMENTS: 1/2/3/4-speaker deterministic identity contract tests, source-mode tests, async worker path tests, schema validation, regression suite.  
EVIDENCE_REQUIREMENTS: exact SHA, test outputs, sample canonical packages, no identity inference from array position.  
FORBIDDEN_REFACTORS: no unrelated product redesign; no rendering/provider orchestration that belongs to other VPMS workers.  
FORBIDDEN_ACTIONS: no provider spend unless authorized; no self-evaluation.

LAST_COMPLETED_ITEM: production hardening commit `c3285ffdcc1a0523013953fd4146eacb31c0f35e`.  
CURRENT_TASK: no new Phase-4 implementation until dependency-valid assignment.  
IMPLEMENTATION_SHA: none for the Phase-4 canonical package workstream  
EVALUATOR_VERDICT: none  
SUPERVISOR_VERDICT: pending future workstream  
UNRESOLVED_DEFECTS: exact governed stable `turn_id`/`speaker_id` VPMS package not yet production-proven.  
BLOCKERS: Phase-3/common-contract gates and bounded assignment.  
NEXT_DEPENDENCY_VALID_ITEM: podcast contract alignment/implementation after coordinator releases the Phase-4 workstream.  
LAST_UPDATED_AT: 2026-09-14
