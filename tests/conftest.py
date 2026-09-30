"""Shared test fixtures."""

import email
import inspect
import json
from email import policy
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import Mock

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

FIXTURES = Path(__file__).parent / "fixtures"
# 12:00 in Berlin: outside the 22–6 night window in which poll intervals stretch to 60 min.
DAYTIME = "2026-09-29 10:00:00+00:00"


def _patch_aioresponses_for_new_aiohttp() -> None:
    """Compat shim: aioresponses 0.7.9 predates aiohttp's required
    ``stream_writer`` kwarg on ``ClientResponse.__init__``. Without this,
    every mocked aioresponses request raises
    ``TypeError: ClientResponse.__init__() missing 1 required
    keyword-only argument: 'stream_writer'`` under aiohttp>=3.14. This
    only patches the mock's response construction, never production
    request/response handling.
    """
    from aiohttp.client_reqrep import ClientResponse
    from aioresponses.core import RequestMatch

    if "stream_writer" not in inspect.signature(ClientResponse.__init__).parameters:
        return

    original = RequestMatch._build_response

    def _patched(self, *args, **kwargs):
        response_class = kwargs.get("response_class")
        if response_class is None:
            kwargs["response_class"] = lambda *a, **kw: ClientResponse(
                *a, **{**kw, "stream_writer": Mock()}
            )
        return original(self, *args, **kwargs)

    RequestMatch._build_response = _patched


try:
    _patch_aioresponses_for_new_aiohttp()
except ImportError:
    pass


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom_components in every test."""
    return


def load_fixture(name: str) -> dict:
    """Load a JSON fixture from tests/fixtures."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_mail(name: str) -> EmailMessage:
    """Parse an anonymised mail from tests/fixtures/mail."""
    raw = (FIXTURES / "mail" / name).read_bytes()
    return email.message_from_bytes(raw, policy=policy.default)


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """Isolated temp config dir so tests never touch the shared testing_config."""
    return hass_tmp_config_dir
