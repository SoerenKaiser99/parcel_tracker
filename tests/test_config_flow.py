import ssl
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker import _dhl_key
from custom_components.parcel_tracker.const import (
    CONF_DHL_API_KEY,
    CONF_IMAP_HOST,
    CONF_IMAP_PASSWORD,
    CONF_IMAP_USER,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_MAIL_ENABLED,
    CONF_MAIL_INTERVAL,
    CONF_MAIL_SECTION,
    CONF_MOVE_PROCESSED,
    CONF_POSTCODE,
    CONF_READ_OTP,
    DOMAIN,
)
from custom_components.parcel_tracker.mail.imap import ImapAuthError, ImapUnavailable

VALIDATE = "custom_components.parcel_tracker.config_flow.DhlCarrier.validate_key"
SETUP = "custom_components.parcel_tracker.async_setup_entry"


async def test_user_flow_with_valid_key(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with patch(VALIDATE, return_value=True), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_DHL_API_KEY: "k", CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Paket Tracker"
    assert result["data"][CONF_DHL_API_KEY] == "k"


async def test_user_flow_invalid_key(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(VALIDATE, return_value=False):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_DHL_API_KEY: "bad", CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3},
        )
    assert result["errors"] == {CONF_DHL_API_KEY: "invalid_key"}


async def test_user_flow_without_key_and_bad_postcode(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_POSTCODE: "5380", CONF_KEEP_DELIVERED_DAYS: 3}
    )
    assert result["errors"] == {CONF_POSTCODE: "invalid_postcode"}
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_postcode_is_optional(hass):
    """Postcode may stay empty; it's only validated when non-empty."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POSTCODE: "", CONF_KEEP_DELIVERED_DAYS: 3}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_POSTCODE] == ""


async def test_single_instance(hass):
    MockConfigEntry(domain=DOMAIN, data={}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_reauth(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DHL_API_KEY: "old", CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with patch(VALIDATE, return_value=True), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DHL_API_KEY: "new"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_DHL_API_KEY] == "new"


async def test_options(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_POSTCODE: "53805", CONF_KEEP_DELIVERED_DAYS: 5},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_KEEP_DELIVERED_DAYS] == 5


async def test_options_keeps_existing_key(hass):
    """Options form keeps the existing DHL key (in entry.data) when the field is omitted."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DHL_API_KEY: "old", CONF_POSTCODE: "10115"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 5},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_DHL_API_KEY] == "old"
    assert CONF_DHL_API_KEY not in entry.options


async def test_options_keeps_key_on_empty_string(hass):
    """Options form keeps the existing key when an empty string is submitted."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DHL_API_KEY: "old", CONF_POSTCODE: "10115"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(VALIDATE) as mock_validate, patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_DHL_API_KEY: "", CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 5},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_DHL_API_KEY] == "old"
    assert CONF_DHL_API_KEY not in entry.options
    # validate_key should NOT have been called for empty string
    mock_validate.assert_not_called()


async def test_options_new_key_validated(hass):
    """A new key typed in options is validated and lands in entry.data, not options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DHL_API_KEY: "old", CONF_POSTCODE: "10115"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)

    # Test: new valid key
    with patch(VALIDATE, return_value=True) as mock_validate, patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_DHL_API_KEY: "new", CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 5},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_DHL_API_KEY] == "new"
    assert CONF_DHL_API_KEY not in entry.options
    mock_validate.assert_called_once()

    # Test: new invalid key
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(VALIDATE, return_value=False):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_DHL_API_KEY: "invalid", CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 5},
        )
    assert result["errors"] == {CONF_DHL_API_KEY: "invalid_key"}


async def test_user_flow_strips_key(hass):
    """A key with surrounding whitespace is saved stripped."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(VALIDATE, return_value=True), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_DHL_API_KEY: "  k  ", CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DHL_API_KEY] == "k"


async def test_reauth_strips_key(hass):
    """A reauth key with surrounding whitespace is saved stripped."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DHL_API_KEY: "old", CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    with patch(VALIDATE, return_value=True), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DHL_API_KEY: "  new  "}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_DHL_API_KEY] == "new"


async def test_options_clears_postcode(hass):
    """Submitting the options form without a postcode clears a previously stored one."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_POSTCODE: "", CONF_KEEP_DELIVERED_DAYS: 5},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    effective_postcode = entry.options.get(CONF_POSTCODE, entry.data.get(CONF_POSTCODE))
    assert not effective_postcode


async def test_options_single_update_when_key_changes(hass):
    """Saving a new key in options writes data and options in one call."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_DHL_API_KEY: "old", CONF_POSTCODE: "10115"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(VALIDATE, return_value=True), patch(SETUP, return_value=True):
        with patch(
            "homeassistant.config_entries.ConfigEntries.async_update_entry",
            wraps=hass.config_entries.async_update_entry,
        ) as mock_update:
            result = await hass.config_entries.options.async_configure(
                result["flow_id"],
                {CONF_DHL_API_KEY: "new", CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 5},
            )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.data[CONF_DHL_API_KEY] == "new"
    assert entry.options[CONF_KEEP_DELIVERED_DAYS] == 5
    # The explicit call carries both the new key and the new options together,
    # so the options-flow's own save of `data=new_options` is a no-op update
    # (options already match) and triggers no second reload.
    _, kwargs = mock_update.call_args_list[0]
    assert kwargs["data"][CONF_DHL_API_KEY] == "new"
    assert kwargs["options"][CONF_KEEP_DELIVERED_DAYS] == 5


async def test_reauth_effective_after_options_saved(hass):
    """Regression test: saving options must not shadow a later reauth key.

    Before the fix, the options flow wrote the DHL key into entry.options,
    which won the ``{**entry.data, **entry.options}`` merge used at setup.
    A later reauth only updated entry.data, so the stale options key kept
    being used. Now the key lives solely in entry.data.
    """
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_DHL_API_KEY: "old", CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(VALIDATE, return_value=True), patch(SETUP, return_value=True):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_DHL_API_KEY: "options-key", CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 5},
        )
        await hass.async_block_till_done()
    assert entry.data[CONF_DHL_API_KEY] == "options-key"
    assert CONF_DHL_API_KEY not in entry.options

    result = await entry.start_reauth_flow(hass)
    with patch(VALIDATE, return_value=True), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DHL_API_KEY: "reauth-key"}
        )
        await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_DHL_API_KEY] == "reauth-key"
    # This is exactly what async_setup_entry uses to build the carrier.
    assert _dhl_key(entry) == "reauth-key"


def test_dhl_key_reads_only_data():
    """`_dhl_key` reads only entry.data; there is no options fallback."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_DHL_API_KEY: "data-key"}, options={CONF_DHL_API_KEY: "opt-key"}
    )
    assert _dhl_key(entry) == "data-key"

    options_only = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_DHL_API_KEY: "opt-key"})
    assert _dhl_key(options_only) is None

    neither = MockConfigEntry(domain=DOMAIN, data={}, options={})
    assert _dhl_key(neither) is None

    neither = MockConfigEntry(domain=DOMAIN, data={}, options={})
    assert _dhl_key(neither) is None


CHECK_LOGIN = "custom_components.parcel_tracker.config_flow.MailboxClient.check_login"


def _mail_input(**mail):
    return {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3, CONF_MAIL_SECTION: mail}


async def test_options_mail_defaults_and_disabled_without_user(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert CONF_MAIL_SECTION in result["data_schema"].schema
    with patch(CHECK_LOGIN) as login, patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    login.assert_not_called()
    assert entry.options[CONF_IMAP_HOST] == "imap.mailbox.org"
    assert entry.options[CONF_IMAP_USER] == ""
    assert entry.options[CONF_MAIL_INTERVAL] == 5
    assert entry.options[CONF_MOVE_PROCESSED] is True
    assert entry.options[CONF_READ_OTP] is False
    assert CONF_IMAP_PASSWORD not in entry.data


async def test_options_mail_login_ok_stores_password_in_data(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(CHECK_LOGIN) as login, patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            _mail_input(
                imap_user=" pakete@example.org ",
                imap_password="geheim",
                move_processed=False,
                read_otp=True,
            ),
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    login.assert_called_once()
    assert entry.data[CONF_IMAP_PASSWORD] == "geheim"
    assert CONF_IMAP_PASSWORD not in entry.options
    assert entry.options[CONF_IMAP_USER] == "pakete@example.org"
    assert entry.options[CONF_MOVE_PROCESSED] is False
    assert entry.options[CONF_READ_OTP] is True


async def test_options_mail_login_rejected_or_unreachable(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(CHECK_LOGIN, side_effect=ImapAuthError("no")):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _mail_input(imap_user="u", imap_password="bad")
        )
    assert result["errors"] == {"base": "imap_auth"}
    with patch(CHECK_LOGIN, side_effect=ImapUnavailable("down")):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _mail_input(imap_user="u", imap_password="pw")
        )
    assert result["errors"] == {"base": "imap_cannot_connect"}
    assert CONF_IMAP_PASSWORD not in entry.data


async def test_options_mail_empty_password_keeps_stored_one(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "alt"},
        options={CONF_IMAP_USER: "u"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(CHECK_LOGIN) as login, patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _mail_input(imap_user="u", imap_password="")
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    login.assert_not_called()  # nothing about the login changed
    assert entry.data[CONF_IMAP_PASSWORD] == "alt"


async def test_options_mail_user_without_any_password(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(CHECK_LOGIN) as login:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _mail_input(imap_user="u")
        )
    assert result["errors"] == {"base": "imap_password_missing"}
    login.assert_not_called()


async def test_options_saving_postcode_skips_login_check(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "pw"},
        options={CONF_IMAP_HOST: "imap.example.org", CONF_IMAP_USER: "u"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with (
        patch(CHECK_LOGIN, side_effect=ImapUnavailable("down")) as login,
        patch(SETUP, return_value=True),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                CONF_POSTCODE: "20095",
                CONF_KEEP_DELIVERED_DAYS: 3,
                CONF_MAIL_SECTION: {CONF_IMAP_HOST: "imap.example.org", CONF_IMAP_USER: "u"},
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    login.assert_not_called()
    assert entry.options[CONF_POSTCODE] == "20095"
    assert entry.data[CONF_IMAP_PASSWORD] == "pw"


@pytest.mark.parametrize(
    "mail",
    [
        {CONF_IMAP_HOST: "imap.other.org", CONF_IMAP_USER: "u"},
        {CONF_IMAP_HOST: "imap.example.org", CONF_IMAP_USER: "v"},
        {CONF_IMAP_HOST: "imap.example.org", CONF_IMAP_USER: "u", CONF_IMAP_PASSWORD: "neu"},
    ],
)
async def test_options_changed_login_is_checked(hass, mail):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "pw"},
        options={CONF_IMAP_HOST: "imap.example.org", CONF_IMAP_USER: "u"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(CHECK_LOGIN, side_effect=ImapUnavailable("down")) as login:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3, CONF_MAIL_SECTION: mail},
        )
    login.assert_called_once()
    assert result["errors"] == {"base": "imap_cannot_connect"}


async def test_options_mail_off_removes_user_and_password(hass):
    """Only the explicit switch turns the mail import off."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "pw"},
        options={CONF_IMAP_USER: "u"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(CHECK_LOGIN) as login, patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _mail_input(mail_enabled=False, imap_user="u")
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    login.assert_not_called()
    assert CONF_IMAP_PASSWORD not in entry.data
    assert entry.options[CONF_IMAP_USER] == ""
    assert CONF_MAIL_ENABLED not in entry.options
    assert CONF_MAIL_ENABLED not in entry.data


@pytest.mark.parametrize("mail", [{"imap_user": ""}, {}, {"mail_enabled": True}])
async def test_options_empty_or_missing_user_keeps_mail_import(hass, mail):
    """An emptied user field (the frontend then omits it) is no longer "off"."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "pw"},
        options={CONF_IMAP_USER: "u"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(CHECK_LOGIN) as login, patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _mail_input(**mail)
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    login.assert_not_called()
    assert entry.data[CONF_IMAP_PASSWORD] == "pw"
    assert entry.options[CONF_IMAP_USER] == "u"


async def test_options_mail_switch_defaults_to_whether_a_user_is_stored(hass):
    def switch_default(result):
        section = result["data_schema"].schema[CONF_MAIL_SECTION].schema.schema
        marker = next(key for key in section if key == CONF_MAIL_ENABLED)
        return marker.default()

    empty = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    empty.add_to_hass(hass)
    assert switch_default(await hass.config_entries.options.async_init(empty.entry_id)) is False
    await hass.config_entries.async_remove(empty.entry_id)
    configured = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "pw"},
        options={CONF_IMAP_USER: "u"},
    )
    configured.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(configured.entry_id)
    assert switch_default(result) is True
    section = result["data_schema"].schema[CONF_MAIL_SECTION].schema.schema
    user = next(key for key in section if key == CONF_IMAP_USER)
    assert user.default() == "u"  # visibly prefilled, not a suggested value
    assert not user.description


async def test_options_mail_enabled_without_any_user_configures_nothing(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(CHECK_LOGIN) as login, patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _mail_input(mail_enabled=True)
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    login.assert_not_called()
    assert entry.options[CONF_IMAP_USER] == ""
    assert CONF_IMAP_PASSWORD not in entry.data


async def test_options_new_user_sets_mail_import_up_even_with_switch_off(hass):
    """Nothing stored yet: the switch (default off) must not swallow a new login."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(CHECK_LOGIN) as login, patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _mail_input(mail_enabled=False, imap_user="u", imap_password="pw")
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    login.assert_called_once()
    assert entry.options[CONF_IMAP_USER] == "u"
    assert entry.data[CONF_IMAP_PASSWORD] == "pw"


async def test_options_login_check_uses_verifying_tls(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with (
        patch("custom_components.parcel_tracker.config_flow.MailboxClient") as client,
        patch(SETUP, return_value=True),
    ):
        await hass.config_entries.options.async_configure(
            result["flow_id"], _mail_input(imap_user="u", imap_password="pw")
        )
    context = client.call_args.kwargs["ssl_context"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


async def test_options_saves_mail_interval(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], _mail_input(**{CONF_MAIL_INTERVAL: 15})
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_MAIL_INTERVAL] == 15


@pytest.mark.parametrize("minutes", [0, 61])
async def test_options_rejects_mail_interval_out_of_range(hass, minutes):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(
            result["flow_id"], _mail_input(**{CONF_MAIL_INTERVAL: minutes})
        )


async def test_options_changing_only_interval_skips_login_check(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_POSTCODE: "10115", CONF_IMAP_PASSWORD: "pw"},
        options={CONF_IMAP_HOST: "imap.example.org", CONF_IMAP_USER: "u"},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    with (
        patch(CHECK_LOGIN, side_effect=ImapUnavailable("down")) as login,
        patch(SETUP, return_value=True),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            _mail_input(
                **{CONF_IMAP_HOST: "imap.example.org", CONF_IMAP_USER: "u", CONF_MAIL_INTERVAL: 30}
            ),
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    login.assert_not_called()
    assert entry.options[CONF_MAIL_INTERVAL] == 30
