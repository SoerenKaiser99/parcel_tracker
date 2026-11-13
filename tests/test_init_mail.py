import ssl
from unittest.mock import patch

import pytest
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker import _mailbox
from custom_components.parcel_tracker.const import (
    CONF_IMAP_HOST,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_USER,
    CONF_POSTCODE,
    DOMAIN,
)

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"


def test_mailbox_needs_user_and_password():
    assert _mailbox(MockConfigEntry(domain=DOMAIN, data={}, options={})) is None
    only_user = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_IMAP_USER: "u"})
    assert _mailbox(only_user) is None
    only_password = MockConfigEntry(domain=DOMAIN, data={CONF_IMAP_PASSWORD: "p"}, options={})
    assert _mailbox(only_password) is None
    both = MockConfigEntry(
        domain=DOMAIN, data={CONF_IMAP_PASSWORD: "p"}, options={CONF_IMAP_USER: "u"}
    )
    # no stored host: no silent fallback to a provider, so no client either
    assert _mailbox(both) is None
    custom = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IMAP_PASSWORD: "p"},
        options={CONF_IMAP_USER: "u", CONF_IMAP_HOST: "imap.example.org"},
    )
    assert _mailbox(custom).host == "imap.example.org"


async def test_setup_hands_mailbox_to_coordinator(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "p"},
        options={CONF_IMAP_USER: "pakete@example.org", CONF_IMAP_HOST: "imap.example.org"},
    )
    entry.add_to_hass(hass)
    with patch(FETCH):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.runtime_data.mailbox.user == "pakete@example.org"


def test_mailbox_uses_verifying_tls_context():
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_IMAP_PASSWORD: "p"},
        options={CONF_IMAP_USER: "u", CONF_IMAP_HOST: "imap.example.org"},
    )
    received = []

    def factory(host, port, ssl_context=None, timeout=None):
        received.append(ssl_context)
        raise OSError("stop here")

    client = _mailbox(entry)
    client._factory = factory
    try:
        client.check_login()
    except Exception:  # noqa: BLE001 - only the handed-over context matters
        pass
    assert received[0].verify_mode == ssl.CERT_REQUIRED
    assert received[0].check_hostname is True


async def test_setup_without_mailbox_clears_mail_issues_and_password(hass):
    for issue in ("imap_auth", "amazon_unrecognized"):
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue,
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=issue,
        )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "p"},
        options={CONF_IMAP_USER: ""},
    )
    entry.add_to_hass(hass)
    with patch(FETCH):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.runtime_data.mailbox is None
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, "imap_auth") is None
    assert registry.async_get_issue(DOMAIN, "amazon_unrecognized") is None
    assert CONF_IMAP_PASSWORD not in entry.data
    assert entry.data[CONF_POSTCODE] == "10115"


async def test_refresh_service_forces_mail_import(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "p"},
        options={CONF_IMAP_USER: "pakete@example.org"},
    )
    entry.add_to_hass(hass)
    calls = []

    def fake_fetch():
        calls.append(1)
        return []

    with patch(FETCH):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coord = entry.runtime_data
        coord.mailbox.fetch_unseen = fake_fetch
        await coord.async_refresh()
        assert len(calls) == 1  # regular schedule, next one is 5 minutes away
        await coord.async_refresh()
        assert len(calls) == 1
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        assert len(calls) == 2


def test_mailbox_reads_inbox_unless_a_folder_is_stored():
    data = {CONF_IMAP_PASSWORD: "p"}
    before = MockConfigEntry(
        domain=DOMAIN, data=data, options={CONF_IMAP_USER: "u", CONF_IMAP_HOST: "h.example.org"}
    )
    assert (_mailbox(before).folder, _mailbox(before).custom_folder) == ("INBOX", False)
    for stored, folder in (("", "INBOX"), ("inbox", "INBOX"), ("Pakete/DHL", "Pakete/DHL")):
        entry = MockConfigEntry(
            domain=DOMAIN,
            data=data,
            options={CONF_IMAP_USER: "u", CONF_IMAP_HOST: "h.example.org", "imap_folder": stored},
        )
        assert _mailbox(entry).folder == folder


# ----- v0.3.32: port, kind of connection and the hint about an unverified connection -----

ISSUE = "imap_insecure"


def _mail_entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "p"},
        options={CONF_IMAP_USER: "u", CONF_IMAP_HOST: "imap.example.org", **options},
    )


def test_mailbox_is_tls_on_993_unless_something_else_is_stored():
    before = _mailbox(_mail_entry())
    assert (before.port, before.security, before.custom_port) == (993, "ssl", False)
    assert before._ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert before._ssl_context.check_hostname is True
    noverify = _mailbox(_mail_entry(imap_port=10993, imap_security="ssl_noverify"))
    assert (noverify.port, noverify.security, noverify.custom_port) == (10993, "ssl_noverify", True)
    # Home Assistant's shared context without verification, handed in from outside.
    assert noverify._ssl_context.verify_mode == ssl.CERT_NONE
    assert noverify._ssl_context.check_hostname is False
    plain = _mailbox(_mail_entry(imap_port=143, imap_security="plain"))
    assert (plain.port, plain.security, plain._ssl_context) == (143, "plain", None)
    odd = _mailbox(_mail_entry(imap_port="x", imap_security="x"))
    assert (odd.port, odd.security) == (993, "ssl")
    assert odd._ssl_context.verify_mode == ssl.CERT_REQUIRED


async def _set_up(hass, entry):
    entry.add_to_hass(hass)
    with patch(FETCH):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("options", "warned"),
    [
        ({}, False),
        ({"imap_security": "ssl", CONF_IMAP_HOST: "imap.example.org"}, False),
        ({"imap_security": "ssl_noverify", CONF_IMAP_HOST: "imap.example.org"}, True),
        ({"imap_security": "plain", CONF_IMAP_HOST: "imap.example.org"}, True),
        ({"imap_security": "plain"}, True),  # the default host is a provider on the internet
        ({"imap_security": "plain", CONF_IMAP_HOST: "8.8.8.8"}, True),
        ({"imap_security": "ssl_noverify", CONF_IMAP_HOST: "192.168.178.20"}, False),
        ({"imap_security": "plain", CONF_IMAP_HOST: "dovecot"}, False),
        ({"imap_security": "plain", CONF_IMAP_HOST: "mail.fritz.box"}, False),
        ({"imap_security": "ssl_noverify", CONF_IMAP_HOST: "fd00::20"}, False),
    ],
)
async def test_unverified_connection_to_a_public_host_raises_a_hint(hass, options, warned):
    await _set_up(hass, _mail_entry(**options))
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ISSUE)
    assert (issue is not None) is warned
    if warned:
        assert issue.severity is ir.IssueSeverity.WARNING
        assert issue.is_fixable is False
        assert issue.translation_key == ISSUE
        # Nothing of the server or the login goes into the issue.
        assert not issue.translation_placeholders


@pytest.mark.parametrize(
    "better",
    [
        {"imap_security": "ssl", CONF_IMAP_HOST: "imap.example.org"},
        {"imap_security": "plain", CONF_IMAP_HOST: "10.0.0.5"},
        {CONF_IMAP_USER: ""},
    ],
    ids=["verified-again", "host-local", "import-off"],
)
async def test_the_hint_goes_when_the_reason_is_gone(hass, better):
    entry = _mail_entry(imap_security="plain", **{CONF_IMAP_HOST: "imap.example.org"})
    await _set_up(hass, entry)
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, ISSUE) is not None
    with patch(FETCH):
        hass.config_entries.async_update_entry(entry, options={**entry.options, **better})
        await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, ISSUE) is None


async def test_a_dismissed_hint_stays_dismissed_over_a_reload(hass):
    entry = _mail_entry(imap_security="plain", **{CONF_IMAP_HOST: "imap.example.org"})
    await _set_up(hass, entry)
    registry = ir.async_get(hass)
    registry.async_ignore(DOMAIN, ISSUE, True)
    assert registry.async_get_issue(DOMAIN, ISSUE).dismissed_version is not None
    with patch(FETCH):
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, ISSUE).dismissed_version is not None


async def test_setup_migrates_legacy_entry_without_host(hass, caplog):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "p"},
        options={CONF_IMAP_USER: "pakete@example.org"},
    )
    entry.add_to_hass(hass)
    with patch(FETCH):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.options[CONF_IMAP_HOST] == "imap.mailbox.org"
    assert entry.runtime_data.mailbox.host == "imap.mailbox.org"
    assert entry.runtime_data.mailbox.user == "pakete@example.org"
    assert "pakete@example.org" not in caplog.text
    assert "imap.mailbox.org" not in caplog.text


async def test_setup_migration_runs_once_without_reload(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "p"},
        options={CONF_IMAP_USER: "pakete@example.org"},
    )
    entry.add_to_hass(hass)
    with (
        patch(FETCH),
        patch(
            "custom_components.parcel_tracker.ParcelCoordinator.async_config_entry_first_refresh"
        ) as refresh,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert refresh.await_count == 1
    assert entry.options[CONF_IMAP_HOST] == "imap.mailbox.org"


async def test_setup_without_import_stores_no_host(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"}, options={})
    entry.add_to_hass(hass)
    with patch(FETCH):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert CONF_IMAP_HOST not in entry.options


async def test_setup_keeps_stored_host(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "p"},
        options={CONF_IMAP_USER: "u", CONF_IMAP_HOST: "imap.example.org"},
    )
    entry.add_to_hass(hass)
    with patch(FETCH):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.options[CONF_IMAP_HOST] == "imap.example.org"


def test_no_silent_mailbox_org_fallback_in_code():
    from pathlib import Path

    root = Path(__file__).parent.parent / "custom_components" / "parcel_tracker"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if path.name == "diagnostics.py" and path.parent == root:
            continue  # lists public providers, never connects
        if path.name == "const.py" and path.parent == root:
            assert "DEFAULT_IMAP_HOST" not in text
            continue
        assert "DEFAULT_IMAP_HOST" not in text, path.name
        assert "imap.mailbox.org" not in text, path.name


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({CONF_IMAP_USER: "", CONF_IMAP_HOST: "imap.mailbox.org"}, None),
        ({CONF_IMAP_HOST: "imap.mailbox.org"}, None),
        ({CONF_IMAP_USER: "", CONF_IMAP_HOST: "imap.example.org"}, "imap.example.org"),
        ({CONF_IMAP_USER: "u"}, "imap.mailbox.org"),
        ({CONF_IMAP_USER: "u", CONF_IMAP_HOST: "imap.mailbox.org"}, "imap.mailbox.org"),
        ({CONF_IMAP_USER: "u", CONF_IMAP_HOST: "imap.example.org"}, "imap.example.org"),
    ],
)
async def test_setup_migration_rules(hass, options, expected):
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "p"}, options=options
    )
    entry.add_to_hass(hass)
    with patch(FETCH):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.options.get(CONF_IMAP_HOST) == expected
