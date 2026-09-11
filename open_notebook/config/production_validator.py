"""
Production safety validator — fail-fast on dangerous misconfiguration.

Run at startup before the API begins accepting requests. Raises
RuntimeError on any P0 production blocker so the container exits
immediately rather than running with a compromised security posture.

VPMS Phase 1A: Stage 7
"""

from __future__ import annotations

import os
import re
import secrets as stdlib_secrets
from typing import ClassVar

from loguru import logger


class ProductionSafetyError(RuntimeError):
    """Raised when a P0 production safety check fails."""

    code: ClassVar[str] = "VPMS-P0"
    # Subclasses set their specific defect code
    defect_code: ClassVar[str] = "UNKNOWN"

    def __init__(self, message: str):
        self.message = message
        super().__init__(f"[{self.code}/{self.defect_code}] {message}")


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------


def _check_auth_mode() -> None:
    """
    ONBAPI-001 P0: Multi-tenant deployments MUST use service auth.
    Single shared password auth provides zero tenant isolation.
    """
    password = os.getenv("OPEN_NOTEBOOK_PASSWORD", "").strip()
    service_creds = os.getenv("OPEN_NOTEBOOK_SERVICE_CREDENTIAL", "").strip()
    multi_tenant = os.getenv("VPMS_MULTI_TENANT_MODE", "").strip().lower()

    if multi_tenant in ("1", "true"):
        # Multi-tenant deployments require service auth OR service creds to be set
        # (service creds without multi_tenant flag is acceptable but not enforced)
        if password and not service_creds:
            raise ProductionSafetyError(
                "VPMS_MULTI_TENANT_MODE is enabled but OPEN_NOTEBOOK_PASSWORD is set "
                "without OPEN_NOTEBOOK_SERVICE_CREDENTIAL. Service credential is required "
                "for multi-tenant deployments to prevent cross-tenant data access. "
                "Set OPEN_NOTEBOOK_SERVICE_CREDENTIAL to a VPMS-managed service secret "
                "and remove OPEN_NOTEBOOK_PASSWORD (or keep it only for single-tenant "
                "standalone deployments)."
            )


def _check_encryption_key() -> None:
    """
    ONBAPI-001 P0: Encryption key must be set and cryptographically random.
    Weak /dev/null / placeholder keys leave API keys in plaintext.
    """
    key = os.getenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", "").strip()
    key_file = os.getenv("OPEN_NOTEBOOK_ENCRYPTION_KEY_FILE", "").strip()

    if key_file:
        try:
            with open(key_file) as f:
                key = f.read().strip()
        except OSError as e:
            raise ProductionSafetyError(
                f"OPEN_NOTEBOOK_ENCRYPTION_KEY_FILE points to '{key_file}' but the "
                f"file could not be read: {e}"
            )

    if not key:
        raise ProductionSafetyError(
            "OPEN_NOTEBOOK_ENCRYPTION_KEY is not set. "
            "API key encryption is disabled; credentials will be stored in plaintext. "
            "Set OPEN_NOTEBOOK_ENCRYPTION_KEY to any secret string (it is hashed to a "
            "Fernet key internally). Example: "
            "OPEN_NOTEBOOK_ENCRYPTION_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
        )

    # Reject known-weak values
    WEAK_KEY_PATTERNS = (
        "dev",
        "test",
        "null",
        "none",
        "changeme",
        "changethis",
        "placeholder",
        "insecure",
        "secret",
        "secretkey",
    )
    key_lower = key.lower()
    if key_lower in WEAK_KEY_PATTERNS or any(
        k in key_lower for k in WEAK_KEY_PATTERNS
    ):
        raise ProductionSafetyError(
            f"OPEN_NOTEBOOK_ENCRYPTION_KEY appears to be a weak or placeholder value "
            f"(got: '{key}'). Generate a proper key with: "
            "python3 -c 'import secrets; print(secrets.token_hex(32))'"
        )


def _check_database_credentials() -> None:
    """
    ONBAPI-001 P0: Default SurrealDB credentials root:root are insecure in production.
    """
    db_pass = os.getenv("SURREAL_PASSWORD", os.getenv("SURREAL_PASS", ""))
    db_user = os.getenv("SURREAL_USER", "")

    is_default_user = db_user in ("", "root")
    is_default_pass = db_pass in ("", "root")

    if is_default_user and is_default_pass:
        raise ProductionSafetyError(
            "SurrealDB is using default credentials (SURREAL_USER=root, "
            "SURREAL_PASSWORD=root or unset). This is insecure in any network-visible "
            "deployment. Set SURREAL_USER and SURREAL_PASSWORD to strong, unique values."
        )

    if is_default_user and not is_default_pass:
        logger.warning(
            "SURREAL_USER is unset (defaults to 'root'). "
            "Consider setting it explicitly to a non-root username."
        )

    if is_default_pass and not is_default_user:
        raise ProductionSafetyError(
            "SURREAL_PASSWORD is unset (or 'root'). "
            "SurrealDB requires a strong password. "
            "Set SURREAL_PASSWORD to a strong unique value."
        )


def _check_cors_wildcard() -> None:
    """
    ONBAPI-006 P1: Wildcard CORS in production allows any origin to make
    credentialed requests to the API.
    """
    cors_raw = os.getenv("CORS_ORIGINS", "").strip()

    # Allow empty (will default to *) only in explicit dev mode
    if not cors_raw:
        env = os.getenv("ENVIRONMENT", "").lower()
        if env in ("production", "prod"):
            raise ProductionSafetyError(
                "ENVIRONMENT=production is set but CORS_ORIGINS is not configured. "
                "Wildcard CORS ('*') is forbidden in production. "
                "Set CORS_ORIGINS to your frontend origin(s), e.g. "
                "CORS_ORIGINS=https://app.example.com"
            )
        logger.warning(
            "CORS_ORIGINS is not set — defaulting to wildcard ('*'). "
            "This is only safe in development. Set CORS_ORIGINS for production."
        )


def _check_transcript_format() -> None:
    """
    ONBAPI-003 P1: Verify podcast_creator is installed and provides structured
    DialogueTurnV1 format (Dialogue model with speaker + dialogue fields).
    """
    try:
        from podcast_creator import Dialogue

        # Verify the Dialogue model has the required DialogueTurnV1 fields
        assert hasattr(Dialogue, "model_fields"), "Dialogue missing model_fields"
        fields = set(Dialogue.model_fields.keys())
        required = {"speaker", "dialogue"}
        missing = required - fields
        if missing:
            raise ProductionSafetyError(
                f"podcast_creator Dialogue model is missing required "
                f"DialogueTurnV1 fields: {missing}. Transcript structure "
                f"does not match the VPMS contract."
            )
        logger.info("podcast_creator DialogueTurnV1 contract verified OK")
    except ImportError:
        logger.warning(
            "podcast_creator is not installed. "
            "Podcast generation will fail if used. "
            "Install with: pip install podcast-creator"
        )


def _check_service_credential_strength() -> None:
    """
    VPMS service credential must be sufficiently random if set.
    """
    cred = os.getenv("OPEN_NOTEBOOK_SERVICE_CREDENTIAL", "").strip()
    if cred and len(cred) < 32:
        raise ProductionSafetyError(
            "OPEN_NOTEBOOK_SERVICE_CREDENTIAL is set but is shorter than 32 "
            "characters. VPMS service credentials must be at least 32 chars "
            "of cryptographic randomness. Generate with: "
            "python3 -c 'import secrets; print(secrets.token_hex(32))'"
        )


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------

_PRODUTION_CHECKS = [
    _check_auth_mode,
    _check_encryption_key,
    _check_database_credentials,
    _check_cors_wildcard,
    _check_transcript_format,
    _check_service_credential_strength,
]


def validate_production_config() -> None:
    """
    Run all production safety checks in order.

    Raises ProductionSafetyError (subclass of RuntimeError) on the first failure.
    Call at FastAPI lifespan startup, before the app begins accepting requests.
    """
    for check in _PRODUTION_CHECKS:
        try:
            check()
        except ProductionSafetyError:
            raise
        except Exception as exc:
            # Unexpected errors in validators are treated as safety failures
            # to avoid silent misconfiguration
            logger.error(f"Production safety check '{check.__name__}' raised unexpected error: {exc}")
            raise ProductionSafetyError(
                f"Production safety check '{check.__name__}' failed unexpectedly: {exc}"
            ) from exc

    logger.info("All production safety checks passed")
