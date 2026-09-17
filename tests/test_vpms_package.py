"""VPMS contract tests for the Open Notebook fork (SUP-20260916, workstream 4).

Covers the frozen canonical package contract ``open-notebook.podcast-package.v1``
exposed at GET /api/podcasts/episodes/{episode_id}/vpms-package:

- 1/2/3/4 speaker packages always carry stable canonical speaker_id/turn_id
  (identity derives from the display name, never array position);
- unknown speaker in a transcript turn fails closed (no identity inference);
- missing explicit voice_id fails closed (no default/random voice fallback);
- provenance (source/evidence refs, source_mode) is preserved;
- /health is truthful (reports degraded when the database or the background
  queue store is unreachable - never healthy by construction).
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.vpms_package import (
    PACKAGE_SCHEMA_VERSION,
    build_package,
)


def make_speaker(name, voice_id="voice_alpha", **overrides):
    entry = {
        "name": name,
        "voice_id": voice_id,
        "backstory": f"Backstory for {name}",
        "personality": f"Personality for {name}",
    }
    entry.update(overrides)
    return entry


def make_transcript(speaker_names, dialogue_template="Hello from {name}"):
    return {
        "transcript": [
            {"speaker": name, "dialogue": dialogue_template.format(name=name)}
            for name in speaker_names
        ]
    }


def make_episode(speaker_names=("Ada", "Grace"), **overrides):
    from open_notebook.podcasts.models import PodcastEpisode

    defaults = dict(
        id="episode:vpms-test",
        name="VPMS Contract Episode",
        episode_profile={"name": "default"},
        speaker_profile={"name": "hosts", "speakers": [make_speaker(n) for n in speaker_names]},
        briefing="briefing",
        content="content",
        transcript=make_transcript(speaker_names),
        audio_file=None,
        command=None,
    )
    defaults.update(overrides)
    return PodcastEpisode(**defaults)


@pytest.fixture
def client():
    from api.main import app

    return TestClient(app)


def _patch_episode(episode):
    return patch(
        "api.routers.vpms_package.PodcastService.get_episode",
        new=AsyncMock(return_value=episode),
    )


def _get_package(client, episode, **params):
    with _patch_episode(episode):
        return client.get(
            f"/api/podcasts/episodes/{episode.id}/vpms-package", params=params
        )


def _build(episode, **kw):
    """Call the pure builder with the episode's snapshot, like the router."""
    entry_list = (episode.speaker_profile or {}).get("speakers") or []
    defaults = dict(
        episode_id=str(episode.id),
        topic=episode.name,
        speakers_snapshot=entry_list,
        transcript=episode.transcript,
        source_mode="script",
        source_refs=["source:evidence-1"],
    )
    defaults.update(kw)
    return build_package(**defaults)


# ---------------------------------------------------------------------------
# 1/2/3/4 speaker packages: stable canonical ids
# ---------------------------------------------------------------------------


class TestSpeakerCountsAndStableIds:
    @pytest.mark.parametrize("names", [
        ["Ada"],
        ["Ada", "Grace"],
        ["Ada", "Grace", "Maya"],
        ["Ada", "Grace", "Maya", "Alan"],
    ])
    def test_package_has_stable_ids_for_n_speakers(self, names):
        episode = make_episode(names)
        package = _build(episode)
        assert len(package.speakers) == len(names)
        assert package.schema_version == PACKAGE_SCHEMA_VERSION
        for speaker, name in zip(package.speakers, names):
            assert speaker.speaker_id.startswith("spk_")
            assert speaker.display_name == name
            assert speaker.voice.voice_id == "voice_alpha"
        assert [t.speaker_id for t in package.turn_manifest] == [
            s.speaker_id for s in package.speakers
        ]
        assert [t.turn_id for t in package.turn_manifest] == [
            f"turn_{i:04d}" for i in range(len(names))
        ]

    @pytest.mark.parametrize("names", [
        ["Ada"],
        ["Ada", "Grace"],
        ["Ada", "Grace", "Maya"],
        ["Ada", "Grace", "Maya", "Alan"],
    ])
    def test_endpoint_returns_stable_ids_for_n_speakers(self, client, names):
        episode = make_episode(names)
        response = _get_package(client, episode)
        assert response.status_code == 200
        body = response.json()
        assert body["schema_version"] == PACKAGE_SCHEMA_VERSION
        assert len(body["speakers"]) == len(names)
        assert len(body["turn_manifest"]) == len(names)
        # Canonical ids are always present, never inferred from position.
        expected_ids = {
            name: f"spk_{name.lower()}" for name in names
        }
        for speaker in body["speakers"]:
            assert speaker["speaker_id"] == expected_ids[speaker["display_name"]]
        for i, turn in enumerate(body["turn_manifest"]):
            assert turn["turn_id"] == f"turn_{i:04d}"
            # The turn's speaker_id matches the canonical id of the speaker
            # whose display name the turn text references.
            speaker_by_id = {
                s["speaker_id"]: s["display_name"] for s in body["speakers"]
            }
            assert turn["speaker_id"] in speaker_by_id
            assert speaker_by_id[turn["speaker_id"]] == names[i]

    def test_identity_never_inferred_from_array_position(self):
        """Reordering the speaker array must not re-identify a speaker."""
        first = _build(make_episode(["Ada", "Grace", "Maya"]))
        reordered = make_episode(["Grace", "Maya", "Ada"])
        second = _build(reordered)
        by_name_first = {s.display_name: s.speaker_id for s in first.speakers}
        by_name_second = {s.display_name: s.speaker_id for s in second.speakers}
        assert by_name_first == by_name_second
        assert by_name_first["Ada"] == "spk_ada"
        # Turn speaker lineage follows the speaker id, not the slot.
        assert first.turn_manifest[0].speaker_id == "spk_ada"
        assert second.turn_manifest[2].speaker_id == "spk_ada"

    def test_build_is_deterministic_across_calls(self):
        episode = make_episode(["Ada", "Grace"])
        a = _build(episode)
        b = _build(episode)
        assert a.model_dump()["speakers"] == b.model_dump()["speakers"]
        assert a.manifest_sha256 == b.manifest_sha256


# ---------------------------------------------------------------------------
# Unknown speaker fails closed
# ---------------------------------------------------------------------------


class TestUnknownSpeakerFailsClosed:
    def test_transcript_referencing_unknown_speaker_raises(self):
        episode = make_episode(["Ada", "Grace"])
        episode.transcript = make_transcript(["Ada", "Impostor"])
        with pytest.raises(ValueError, match="Unknown speaker 'Impostor'"):
            _build(episode)

    def test_endpoint_returns_422_for_unknown_speaker(self, client):
        episode = make_episode(["Ada", "Grace"])
        episode.transcript = make_transcript(["Ada", "Impostor"])
        response = _get_package(client, episode)
        assert response.status_code == 422
        assert "Unknown speaker" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Missing explicit voice fails closed
# ---------------------------------------------------------------------------


class TestMissingVoiceFailsClosed:
    def test_missing_voice_id_raises_with_useful_message(self):
        episode = make_episode(["Ada", "Grace"])
        episode.speaker_profile["speakers"][1] = make_speaker("Grace", voice_id=None)
        with pytest.raises(ValueError, match="no explicit voice_id"):
            _build(episode)

    def test_endpoint_returns_422_for_missing_voice(self, client):
        episode = make_episode(["Ada"])
        episode.speaker_profile["speakers"][0] = make_speaker("Ada", voice_id=None)
        response = _get_package(client, episode)
        assert response.status_code == 422
        assert "voice_id" in response.json()["detail"]

    def test_voice_config_is_explicit_and_unset_provider_is_flagged(self):
        """A voice without a resolvable provider must never claim a provider."""
        episode = make_episode(["Ada"])
        package = _build(episode)  # provider unresolved -> 'unset'
        assert package.speakers[0].voice.voice_id == "voice_alpha"
        assert package.speakers[0].voice.provider == "unset"


# ---------------------------------------------------------------------------
# Provenance and source modes
# ---------------------------------------------------------------------------


class TestProvenanceAndSourceModes:
    @pytest.mark.parametrize("mode", ["quadran", "research", "script", "hybrid"])
    def test_all_source_modes_are_supported(self, mode):
        episode = make_episode(["Ada"])
        package = _build(episode, source_mode=mode)
        assert package.source_mode == mode
        assert package.provenance.source_mode == mode

    def test_invalid_source_mode_rejected(self):
        episode = make_episode(["Ada"])
        with pytest.raises(ValueError, match="Invalid source_mode"):
            _build(episode, source_mode="deepfake")

    def test_endpoint_rejects_invalid_source_mode_with_422(self, client):
        episode = make_episode(["Ada"])
        response = _get_package(client, episode, source_mode="deepfake")
        assert response.status_code == 422
        assert "Invalid source_mode" in response.json()["detail"]

    def test_provenance_and_source_refs_preserved(self, client):
        episode = make_episode(["Ada"])
        response = _get_package(
            client, episode, source_mode="research",
            vpms_job_id="vpms_job:1234", source_ref="source:evidence-1",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["vpms_job_id"] == "vpms_job:1234"
        assert body["source_mode"] == "research"
        assert "source:evidence-1" in body["research"]["source_evidence_refs"]
        assert "source:evidence-1" in body["provenance"]["source_refs"]
        assert body["provenance"]["package_version"] == PACKAGE_SCHEMA_VERSION
        assert body["provenance"]["generated_by"] == "open-notebook"
        assert body["manifest_sha256"] and len(body["manifest_sha256"]) == 64

    def test_endpoint_404_for_unknown_episode(self, client):
        with patch(
            "api.routers.vpms_package.PodcastService.get_episode",
            new=AsyncMock(side_effect=Exception("boom")),
        ):
            response = client.get("/api/podcasts/episodes/episode:missing/vpms-package")
        assert response.status_code == 404

    def test_endpoint_accepts_vpms_job_id_and_echoes_episode_id(self, client):
        episode = make_episode(["Ada", "Grace"])
        response = _get_package(
            client, episode, vpms_job_id="vpms_job:42", source_mode="hybrid"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["vpms_job_id"] == "vpms_job:42"
        assert body["episode_id"] == str(episode.id)


# ---------------------------------------------------------------------------
# /health truthfulness
# ---------------------------------------------------------------------------


class TestHealthTruthfulness:
    def test_health_reports_degraded_when_database_down(self, client):
        with patch(
            "api.main.repo_query",
            new=AsyncMock(side_effect=RuntimeError("db unreachable")),
        ):
            response = client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["checks"]["database"] != "ok"

    def test_health_reports_degraded_when_queue_store_down(self, client):
        from unittest.mock import AsyncMock

        real_query = AsyncMock()
        real_query.side_effect = [
            [{"result": 1}],  # database probe ok
            RuntimeError("queue store unreachable"),  # queue probe fails
        ]

        with patch("api.main.repo_query", new=real_query):
            response = client.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["queue_store"] != "ok"

    def test_health_reports_ok_only_when_everything_reachable(self, client):
        real_query = AsyncMock()
        real_query.side_effect = [
            [{"result": 1}],  # database probe
            [],  # queue store probe (empty command table is healthy)
        ]
        with patch("api.main.repo_query", new=real_query):
            response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["checks"]["database"] == "ok"
        assert body["checks"]["queue_store"] == "ok"

    def test_health_never_claims_healthy_by_construction(self, client):
        """The hardcoded 'healthy'-by-construction behavior is gone: with no
        reachable subsystems the response must not report 'ok'."""
        with patch(
            "api.main.repo_query",
            new=AsyncMock(side_effect=RuntimeError("down")),
        ):
            response = client.get("/health")
        assert response.json()["status"] != "ok"
