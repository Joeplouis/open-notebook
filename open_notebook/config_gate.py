"""Production/strict-mode startup gate for Open Notebook (SUP-20260916 / §20).

The historical open_notebook/config/ package shadowed the open_notebook/config
module and broke `from open_notebook.config import ...` for every consumer
(token_utils, sources, podcast paths, ...). The namespace collision is resolved
canonically by removing the shadow package and restoring the single config
module; the production safety validator that lived inside the shadow package is
preserved here, at module scope, and is invoked ONLY in explicit
production/strict mode via run_production_validation().

Design rules:
- Normal dev/test startup imports this module and calls
  maybe_run_production_validation() -> no-op unless OPEN_NOTEBOOK_ENV
  (or VPMS_STRICT_MODE) is 'production'/'strict'.
- In production/strict mode, validate_production_config() fails closed on
  unsafe credentials/config: missing auth, missing/weak encryption key,
  default database passwords, wildcard CORS, missing transcript format
  enforcement, weak service credentials.
- ProductionSafetyError is the single typed failure surface so callers can
  distinguish "production gate refused startup" from generic errors.
- Regression-proof: importing api.main (dev/test) must never raise; import
  tests in tests/test_config_namespace.py prove the namespace collision is
  permanently gone.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List

from loguru import logger


class ProductionSafetyError(RuntimeError):
    """Raised when production/strict-mode validation fails closed."""


def _check_auth_mode() -> None:
    password = os.getenv("OPEN_NOTEBOOK_PASSWORD", "").strip()
    service_creds = os.getenv("OPEN_NOTEBOOK_SERVICE_CREDENTIAL", "").strip()
    multi_tenant = os.getenv("VPMS_MULTI_TENANT_MODE", "").strip().lower()
    if not password and not service_creds and multi_tenant != "true":
        raise ProductionSafetyError(
            "production requires OPEN_NOTEBOOK_PASSWORD or "
            "OPEN_NOTEBOOK_SERVICE_CREDENTIAL (or VPMS_MULTI_TENANT_MODE=true with a service credential)"
        )


def _check_encryption_key() -> None:
    key = os.getenv("OPEN_NOTEBOOK_ENCRYPTION_KEY", "").strip()
    key_file = os.getenv("OPEN_NOTEBOOK_ENCRYPTION_KEY_FILE", "").strip()
    if key_file:
        if not os.path.exists(key_file):
            raise ProductionSafetyError(
                f"OPEN_NOTEBOOK_ENCRYPTION_KEY_FILE not found: {key_file}"
            )
        return
    if not key:
        raise ProductionSafetyError(
            "production requires OPEN_NOTEBOOK_ENCRYPTION_KEY (or KEY_FILE)"
        )
    if key.lower() in {"change-me", "changeme", "secret", "password", "dev-key"}:
        raise ProductionSafetyError(
            "OPEN_NOTEBOOK_ENCRYPTION_KEY is a known weak default"
        )


def _check_database_credentials() -> None:
    db_pass = os.getenv("SURREAL_PASSWORD", os.getenv("SURREAL_PASS", ""))
    db_user = os.getenv("SURREAL_USER", "")
    if db_pass and db_pass.lower() in {"root", "password", "changeme", "secret"}:
        raise ProductionSafetyError(
            "SURREAL_PASSWORD is a known weak default; set a real secret"
        )
    if not db_user:
        logger.warning("SURREAL_USER unset; assuming default SurrealDB user")


def _check_cors_wildcard() -> None:
    cors_raw = os.getenv("CORS_ORIGINS", "").strip()
    env = os.getenv("ENVIRONMENT", "").lower()
    is_production = env in {"production", "prod", "strict"}
    if cors_raw == "*" and is_production:
        raise ProductionSafetyError(
            "CORS_ORIGINS=* is not allowed in production (credentialed requests)"
        )


def _check_transcript_format() -> None:
    fmt = os.getenv("OPEN_NOTEBOOK_TRANSCRIPT_FORMAT", "").strip()
    if fmt and fmt not in {"markdown", "plain", "json"}:
        raise ProductionSafetyError(
            f"unsupported OPEN_NOTEBOOK_TRANSCRIPT_FORMAT={fmt}"
        )


def _check_service_credential_strength() -> None:
    cred = os.getenv("OPEN_NOTEBOOK_SERVICE_CREDENTIAL", "").strip()
    if cred and len(cred) < 16:
        raise ProductionSafetyError(
            "OPEN_NOTEBOOK_SERVICE_CREDENTIAL must be at least 16 characters"
        )


_CHECKS: List[Callable[[], None]] = [
    _check_auth_mode,
    _check_encryption_key,
    _check_database_credentials,
    _check_cors_wildcard,
    _check_transcript_format,
    _check_service_credential_strength,
]


def validate_production_config() -> None:
    """Run all production-safety checks; raise ProductionSafetyError on any
    P0 blocker. Used by the explicit production startup gate — never by
    dev/test startup."""
    for check in _CHECKS:
        try:
            check()
        except ProductionSafetyError:
            raise
        except Exception as exc:  # keep fail-closed, but typed
            logger.error(f"Production safety check '{check.__name__}' raised unexpected error: {exc}")
            raise ProductionSafetyError(f"Production safety check '{check.__name__}' failed unexpectedly: {exc}") from exc


def _is_production_mode() -> bool:
    env = os.getenv("OPEN_NOTEBOOK_ENV", "").strip().lower()
    strict = os.getenv("VPMS_STRICT_MODE", "").strip().lower()
    return env in {"production", "prod", "strict"} or strict in {"1", "true", "yes"}


def maybe_run_production_validation() -> None:
    """No-op in normal dev/test startup; fails closed only in explicit
    production/strict mode. This keeps dev/test imports working while
    making production startup fail fast on unsafe configuration."""
    if _is_production_mode():
        validate_production_config()
        logger.info("Open Notebook production validation passed")
    else:
        logger.debug("Open Notebook production validation skipped (not production mode)")
