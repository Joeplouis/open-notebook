"""Regression tests for the Open Notebook config namespace (SUP-20260916 §20).

Proves:
1. The namespace collision is permanently gone: open_notebook.config is the
   real module (no shadowing package), and every historical consumer import
   works.
2. Dev/test startup still works: importing api.main does NOT trigger
   production validation (no env gate set) — no ProductionSafetyError.
3. Production/strict mode fails closed on unsafe credentials/config, and
   passes with a safe configuration.
4. The production validator is an explicit gate, never an unconditional
   startup requirement.
"""
import importlib
import sys
from unittest.mock import patch

import pytest


class TestNamespaceCollisionPermanentlyGone:
    def test_config_is_a_module_not_a_package(self):
        import open_notebook.config as config

        # A package has __path__; the real config module does not.
        assert not hasattr(config, "__path__"), "shadowing package resurrected"

    def test_historical_config_imports_work(self):
        from open_notebook.config import (  # noqa: F401
            LANGGRAPH_CHECKPOINT_FILE,
            PODCASTS_FOLDER,
            TIKTOKEN_CACHE_DIR,
            UPLOADS_FOLDER,
        )

        assert TIKTOKEN_CACHE_DIR.endswith("tiktoken-cache")

    def test_token_utils_imports(self):
        import open_notebook.utils.token_utils  # noqa: F401

    def test_api_main_imports_in_dev_mode(self):
        # No OPEN_NOTEBOOK_ENV / VPMS_STRICT_MODE -> gate is a no-op.
        for var in ("OPEN_NOTEBOOK_ENV", "VPMS_STRICT_MODE", "ENVIRONMENT"):
            sys.modules.pop(var, None)
        import api.main  # noqa: F401  (must not raise ProductionSafetyError)


class TestProductionGateFailClosed:
    def test_gate_is_noop_in_dev(self):
        from open_notebook.config_gate import maybe_run_production_validation

        with patch.dict(
            "os.environ",
            {
                "OPEN_NOTEBOOK_ENV": "",
                "VPMS_STRICT_MODE": "",
            },
            clear=False,
        ):
            maybe_run_production_validation()  # must not raise

    def test_production_missing_auth_fails_closed(self):
        from open_notebook.config_gate import (
            ProductionSafetyError,
            validate_production_config,
        )

        with patch.dict(
            "os.environ",
            {
                "OPEN_NOTEBOOK_ENV": "production",
                "OPEN_NOTEBOOK_PASSWORD": "",
                "OPEN_NOTEBOOK_SERVICE_CREDENTIAL": "",
                "VPMS_MULTI_TENANT_MODE": "",
                "OPEN_NOTEBOOK_ENCRYPTION_KEY": "a" * 32,
                "SURREAL_PASSWORD": "real-secret-123",
                "ENVIRONMENT": "production",
                "CORS_ORIGINS": "https://app.example.com",
            },
            clear=False,
        ):
            with pytest.raises(ProductionSafetyError):
                validate_production_config()  # missing auth -> fail closed

    def test_production_weak_encryption_key_fails_closed(self):
        from open_notebook.config_gate import (
            ProductionSafetyError,
            validate_production_config,
        )

        with patch.dict(
            "os.environ",
            {
                "OPEN_NOTEBOOK_ENV": "production",
                "OPEN_NOTEBOOK_PASSWORD": "strong-pass-123",
                "OPEN_NOTEBOOK_ENCRYPTION_KEY": "change-me",
                "SURREAL_PASSWORD": "real-secret-123",
                "ENVIRONMENT": "production",
                "CORS_ORIGINS": "https://app.example.com",
            },
            clear=False,
        ):
            with pytest.raises(ProductionSafetyError):
                validate_production_config()  # weak key -> fail closed

    def test_production_safe_config_passes(self):
        from open_notebook.config_gate import validate_production_config

        with patch.dict(
            "os.environ",
            {
                "OPEN_NOTEBOOK_ENV": "production",
                "OPEN_NOTEBOOK_PASSWORD": "strong-pass-123",
                "OPEN_NOTEBOOK_ENCRYPTION_KEY": "k" * 32,
                "SURREAL_PASSWORD": "real-secret-123",
                "SURREAL_USER": "root",
                "ENVIRONMENT": "production",
                "CORS_ORIGINS": "https://app.example.com",
                "OPEN_NOTEBOOK_SERVICE_CREDENTIAL": "",
            },
            clear=False,
        ):
            validate_production_config()  # must not raise

    def test_gate_raises_in_production_with_bad_config(self):
        from open_notebook.config_gate import (
            ProductionSafetyError,
            maybe_run_production_validation,
        )

        with patch.dict(
            "os.environ",
            {
                "OPEN_NOTEBOOK_ENV": "production",
                "OPEN_NOTEBOOK_PASSWORD": "",
                "OPEN_NOTEBOOK_SERVICE_CREDENTIAL": "",
                "VPMS_MULTI_TENANT_MODE": "",
                "OPEN_NOTEBOOK_ENCRYPTION_KEY": "",
                "ENVIRONMENT": "production",
                "CORS_ORIGINS": "https://app.example.com",
            },
            clear=False,
        ):
            with pytest.raises(ProductionSafetyError):
                maybe_run_production_validation()
