"""VPMS-facing canonical podcast package export for the Open Notebook fork.

SUP-20260916 (workstream 1 fork side + workstream 4 contract): this module
produces the frozen canonical package shape ``open-notebook.podcast-package.v1``
that the VPMS adapter (OpenNotebookPodcastPackageV1) and Avatar-Webinar target.

Guarantees enforced here (and locked by tests in tests/test_vpms_package.py):

* Stable, canonical ``speaker_id`` and ``turn_id`` values are ALWAYS present.
  Speaker identity is derived deterministically from the speaker's display
  name (never from array position), so the same snapshot always yields the
  same ids and reordering the speaker array cannot re-identify a speaker.
* Speakers carry explicit voice configuration (``voice.voice_id`` + resolved
  ``voice.provider``) or the package build fails closed with a useful error.
* A transcript turn referencing a speaker that is not part of the snapshot
  fails closed (no identity is inferred).
* Provenance is always present; source/evidence references are preserved
  verbatim when the caller can supply them.

The builder is intentionally pure (no DB, no I/O): it operates on the existing
open-notebook domain snapshot of a PodcastEpisode so the fork keeps ONE
lifecycle - the native episode - and this module only renders the canonical
export view of it.
"""

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Canonical contract version frozen in docs/agents/VPMS_CONTRACT_FREEZE_2026-09-16.md
PACKAGE_SCHEMA_VERSION = "open-notebook.podcast-package.v1"

SourceMode = Literal["quadran", "research", "script", "hybrid"]
VALID_SOURCE_MODES: tuple = ("quadran", "research", "script", "hybrid")


class VPMSVisualCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cue_type: str = Field(..., max_length=32)
    description: str = Field(..., max_length=512)
    derived: bool = Field(default=True)
    source_evidence_ref: Optional[str] = Field(None, max_length=128)


class VPMSDialogueTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str = Field(..., max_length=64)
    sequence: int = Field(0, ge=0)
    speaker_id: str = Field(..., max_length=64)
    text: str = Field(..., max_length=50000)
    caption_text: Optional[str] = Field(None, max_length=50000)
    visual_cues: List[VPMSVisualCue] = Field(default_factory=list)


class VPMSVoiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(..., max_length=32)
    voice_id: str = Field(..., max_length=64)


class VPMSSpeaker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker_id: str = Field(..., max_length=64)
    display_name: str = Field(..., max_length=256)
    avatar_ref: Optional[str] = Field(None, max_length=128)
    voice: VPMSVoiceConfig


class VPMSResearchEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_evidence_refs: List[str] = Field(default_factory=list)
    evidence_artifact_id: Optional[str] = Field(None, max_length=128)


class VPMSProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_by: str = "open-notebook"
    generated_at: str = Field(...)
    package_version: str = PACKAGE_SCHEMA_VERSION
    source_mode: str = Field(...)
    source_refs: List[str] = Field(default_factory=list)
    note: Optional[str] = Field(None, max_length=1024)


class OpenNotebookPodcastPackageV1(BaseModel):
    """Fork-side canonical package export (frozen 2026-09-16).

    Field names mirror the VPMS OpenNotebookPodcastPackageV1 contract
    (vpms/core/podcast_schemas.py) and additionally inline the turn manifest
    (``turn_manifest``) and ``provenance`` so downstream consumers do not need
    a second round trip to consume the full package.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = PACKAGE_SCHEMA_VERSION
    vpms_job_id: Optional[str] = Field(None, max_length=64)
    episode_id: str = Field(..., max_length=64)
    topic: str = Field(..., max_length=1024)
    source_mode: str = Field(...)
    speakers: List[VPMSSpeaker] = Field(..., min_length=1, max_length=4)
    research: VPMSResearchEvidence = Field(default_factory=VPMSResearchEvidence)
    outline_artifact_id: Optional[str] = Field(None, max_length=128)
    turn_manifest_artifact_id: Optional[str] = Field(None, max_length=128)
    visual_intelligence_artifact_id: Optional[str] = Field(None, max_length=128)
    manifest_sha256: Optional[str] = Field(None, max_length=64)
    turn_manifest: List[VPMSDialogueTurn] = Field(default_factory=list)
    provenance: VPMSProvenance


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return slug or "speaker"


def _stable_speaker_ids(speaker_names: List[str]) -> Dict[str, str]:
    """Map display name -> stable canonical speaker_id.

    Deterministic and position-free: the id derives from the display name.
    Collisions (duplicate display names in one profile) are resolved by a
    deterministic suffix in snapshot order, which keeps ids stable for the
    same snapshot.
    """
    used: Dict[str, str] = {}
    counts: Dict[str, int] = {}
    result: Dict[str, str] = {}
    for name in speaker_names:
        base = _slugify(name)
        counts[base] = counts.get(base, 0) + 1
        candidate = base if counts[base] == 1 else f"{base}_{counts[base]}"
        # Absolute safety net (slug collisions beyond suffixing are still
        # deterministic): hash-suffix only when the candidate is taken.
        while candidate in used.values():
            digest = hashlib.sha1(f"{name}|{candidate}".encode("utf-8")).hexdigest()[:8]
            candidate = f"{base}_{digest}"
        used[name] = candidate
        result[name] = f"spk_{candidate}"
    return result


def _resolve_voice_provider(
    speaker_entry: Dict[str, Any], snapshot: Dict[str, Any]
) -> str:
    """Resolve the TTS provider for one speaker entry.

    Precedence: per-speaker override (tts_provider/voice_model) -> snapshot
    voice_model resolution fields -> snapshot tts_provider -> 'unset'.
    The package builder never invents a random/default voice id; if the
    voice_id itself is missing the build fails (see build_package).
    """
    per_speaker = speaker_entry.get("tts_provider")
    if per_speaker:
        return per_speaker
    snapshot_provider = (
        snapshot.get("voice_model_provider")
        or snapshot.get("tts_provider")
    )
    return snapshot_provider or "unset"


def build_package(
    *,
    episode_id: str,
    topic: str,
    speakers_snapshot: List[Dict[str, Any]],
    transcript: Optional[Dict[str, Any]],
    source_mode: str,
    vpms_job_id: Optional[str] = None,
    outline_artifact_id: Optional[str] = None,
    turn_manifest_artifact_id: Optional[str] = None,
    visual_intelligence_artifact_id: Optional[str] = None,
    source_refs: Optional[List[str]] = None,
    snapshot: Optional[Dict[str, Any]] = None,
    generated_at: Optional[str] = None,
    provenance_note: Optional[str] = None,
) -> OpenNotebookPodcastPackageV1:
    """Build the canonical VPMS package export from an episode's data.

    Raises:
        ValueError: with a useful, caller-safe message when (a) a speaker entry
            has no explicit voice_id, (b) the speaker list is empty or larger
            than 4, (c) a transcript turn references a speaker that is not in
            the snapshot (unknown speaker), or (d) the source_mode is invalid.
    """
    if source_mode not in VALID_SOURCE_MODES:
        raise ValueError(
            f"Invalid source_mode '{source_mode}'. Must be one of: "
            + ", ".join(VALID_SOURCE_MODES)
        )
    if not speakers_snapshot or len(speakers_snapshot) > 4:
        raise ValueError(
            f"Speaker snapshot must contain between 1 and 4 speakers, "
            f"got {len(speakers_snapshot)}"
        )

    snapshot = snapshot or {}
    display_names = [str(s.get("name") or s.get("display_name") or f"Speaker {i+1}")
                     for i, s in enumerate(speakers_snapshot)]
    speaker_id_by_name = _stable_speaker_ids(display_names)

    speakers: List[VPMSSpeaker] = []
    for entry, display_name in zip(speakers_snapshot, display_names):
        voice_id = entry.get("voice_id") or entry.get("voiceId")
        if not voice_id:
            raise ValueError(
                f"Speaker '{display_name}' has no explicit voice_id configured. "
                "Every speaker must carry an explicit voice configuration; "
                "no default/random voice fallback is allowed at the VPMS "
                "package boundary (SUP-20260916 workstream 4)."
            )
        speakers.append(
            VPMSSpeaker(
                speaker_id=speaker_id_by_name[display_name],
                display_name=display_name,
                avatar_ref=entry.get("avatar_ref") or entry.get("avatar"),
                voice=VPMSVoiceConfig(
                    provider=_resolve_voice_provider(entry, snapshot),
                    voice_id=str(voice_id),
                ),
            )
        )

    speaker_ids = {s.speaker_id for s in speakers}
    valid_speaker_names = set(display_names)

    turns: List[VPMSDialogueTurn] = []
    transcript_entries = []
    if transcript and isinstance(transcript, dict):
        raw = transcript.get("transcript") or transcript.get("turns") or []
        if isinstance(raw, list):
            transcript_entries = raw
    for sequence, entry in enumerate(transcript_entries):
        if not isinstance(entry, dict):
            continue
        speaker_name = str(entry.get("speaker") or entry.get("speaker_name") or "")
        if speaker_name not in valid_speaker_names:
            raise ValueError(
                f"Unknown speaker '{speaker_name}' in transcript turn {sequence}: "
                "the turn references a speaker that is not part of this "
                "episode's speaker profile. No speaker identity is inferred "
                "from array position (SUP-20260916 workstream 1)."
            )
        text = str(entry.get("dialogue") or entry.get("text") or "")
        turns.append(
            VPMSDialogueTurn(
                turn_id=f"turn_{sequence:04d}",
                sequence=sequence,
                speaker_id=speaker_id_by_name[speaker_name],
                text=text,
                caption_text=text or None,
                # The fork's generation pipeline is audio-only today; the only
                # visual cue it can truthfully contribute is the derived
                # lipsync cue consumed by VPMS/avatar renderers. Real B-roll /
                # infographic / chart cues require the visual-intelligence
                # pipeline (see VPMS_CONTRACT_FREEZE_2026-09-16.md).
                visual_cues=[
                    VPMSVisualCue(
                        cue_type="speaker_lipsync",
                        description=f"Derived lipsync cue for {speaker_name}",
                        derived=True,
                    )
                ],
            )
        )

    package = OpenNotebookPodcastPackageV1(
        schema_version=PACKAGE_SCHEMA_VERSION,
        vpms_job_id=vpms_job_id,
        episode_id=episode_id,
        topic=topic[:1024],
        source_mode=source_mode,
        speakers=speakers,
        research=VPMSResearchEvidence(
            source_evidence_refs=list(source_refs or []),
            evidence_artifact_id=None,
        ),
        outline_artifact_id=outline_artifact_id,
        turn_manifest_artifact_id=turn_manifest_artifact_id,
        visual_intelligence_artifact_id=visual_intelligence_artifact_id,
        turn_manifest=turns,
        provenance=VPMSProvenance(
            generated_by="open-notebook",
            generated_at=generated_at or datetime.now(timezone.utc).isoformat(),
            package_version=PACKAGE_SCHEMA_VERSION,
            source_mode=source_mode,
            source_refs=list(source_refs or []),
            note=provenance_note,
        ),
    )
    payload = package.model_dump(mode="json")
    # Deterministic manifest: exclude wall-clock provenance fields so the
    # same episode content always yields the same manifest hash (the
    # generated_at timestamp is informative but not part of the content
    # fingerprint). SUP-20260916 workstream 4 contract.
    fingerprint = dict(payload)
    fingerprint.pop("provenance", None)
    package.manifest_sha256 = hashlib.sha256(
        str(fingerprint).encode("utf-8")
    ).hexdigest()
    return package
