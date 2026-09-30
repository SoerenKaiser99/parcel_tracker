import ssl
from unittest.mock import patch

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
    client = _mailbox(both)
    assert (client.host, client.user) == ("imap.mailbox.org", "u")
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
        options={CONF_IMAP_USER: "pakete@example.org"},
    )
    entry.add_to_hass(hass)
    with patch(FETCH):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.runtime_data.mailbox.user == "pakete@example.org"


def test_mailbox_uses_verifying_tls_context():
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_IMAP_PASSWORD: "p"}, options={CONF_IMAP_USER: "u"}
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
