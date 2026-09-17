"""VPMS-facing canonical package endpoint for the Open Notebook fork.

SUP-20260916 workstream 1 (fork side): surfaces the frozen canonical package
``open-notebook.podcast-package.v1`` through the existing FastAPI router set.
The endpoint is read-only: it exports the existing native PodcastEpisode
lifecycle - it never creates a second episode lifecycle inside the fork.

Endpoints:
    GET /api/podcasts/episodes/{episode_id}/vpms-package
        -> 200 OpenNotebookPodcastPackageV1
        -> 404 unknown episode
        -> 422 speaker / voice / source-mode contract violations
           (unknown speaker in transcript, missing explicit voice_id,
            invalid source_mode)
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from loguru import logger

from api.podcast_service import PodcastService
from api.vpms_package import (
    OpenNotebookPodcastPackageV1,
    PACKAGE_SCHEMA_VERSION,
    build_package,
)
from open_notebook.exceptions import OpenNotebookError

router = APIRouter()

# Source modes the VPMS contract accepts (quadran | research | script |
# hybrid). The fork's native generation pipeline does not yet persist a
# source-mode field on episodes, so the endpoint surface accepts the mode
# explicitly and records it in the package provenance. This keeps the fork's
# DB schema untouched while the contract carries the truthful value.
VALID_SOURCE_MODES = ("quadran", "research", "script", "hybrid")


@router.get(
    "/podcasts/episodes/{episode_id}/vpms-package",
    response_model=OpenNotebookPodcastPackageV1,
    response_model_exclude_none=True,
)
async def get_episode_vpms_package(
    episode_id: str,
    source_mode: str = "script",
    vpms_job_id: Optional[str] = None,
    source_ref: Optional[str] = None,
):
    """Export the canonical VPMS-facing podcast package for an episode.

    Query parameters (all optional; documented for the VPMS adapter):
    - source_mode: quadran | research | script | hybrid (default: script).
      Recorded in package provenance. The fork's native pipeline does not
      store a source-mode field on episodes yet, so the caller declares the
      mode this episode was produced under.
    - vpms_job_id: the VPMS job id that requested this episode (echoed in the
      package for lifecycle lineage).
    - source_ref: an evidence/source reference id to preserve in provenance
      (repeat the query parameter for multiple refs).
    """
    try:
        episode = await PodcastService.get_episode(episode_id)
    except HTTPException:
        raise
    except OpenNotebookError:
        raise
    except Exception as e:
        logger.error(f"Error fetching podcast episode {episode_id}: {e}")
        raise HTTPException(status_code=404, detail="Episode not found")

    if source_mode not in VALID_SOURCE_MODES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid source_mode '{source_mode}'. Must be one of: "
                + ", ".join(VALID_SOURCE_MODES)
            ),
        )

    speakers_snapshot = episode.speaker_profile or {}
    speaker_entries = speakers_snapshot.get("speakers") or []
    if not isinstance(speaker_entries, list):
        speaker_entries = []

    topic = (
        episode.name
        or (episode.episode_profile or {}).get("name")
        or f"Episode {episode.id}"
    )

    source_refs = [r for r in [source_ref] if r]

    try:
        package = build_package(
            episode_id=str(episode.id),
            topic=topic,
            speakers_snapshot=speaker_entries,
            transcript=episode.transcript,
            source_mode=source_mode,
            vpms_job_id=vpms_job_id,
            outline_artifact_id=str(episode.id) + ":outline",
            source_refs=source_refs,
            snapshot=speakers_snapshot,
            provenance_note=(
                "Package exported by the Open Notebook fork "
                f"({PACKAGE_SCHEMA_VERSION}); real B-roll / infographic / "
                "chart cues require the visual-intelligence pipeline "
                "(see VPMS_CONTRACT_FREEZE_2026-09-16.md)."
            ),
        )
    except ValueError as e:
        # Contract violations (unknown speaker, missing voice, bad mode)
        # surface as explicit 4xx with a useful message - never silently
        # inferred defaults (SUP-20260916 workstream 2 / workstream 4).
        logger.warning(f"VPMS package build failed for episode {episode_id}: {e}")
        raise HTTPException(status_code=422, detail=str(e))

    logger.info(
        f"Exported VPMS package for episode {episode_id}: "
        f"{len(package.speakers)} speaker(s), {len(package.turn_manifest)} "
        f"turn(s), source_mode={source_mode}"
    )
    return package
