from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker import _dhl_key
from custom_components.parcel_tracker.const import (
    CONF_DHL_API_KEY,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_POSTCODE,
    DOMAIN,
)

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
    assert entry.data[CONF_DHL_API_KEY] == "options-key"
    assert CONF_DHL_API_KEY not in entry.options

    result = await entry.start_reauth_flow(hass)
    with patch(VALIDATE, return_value=True), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_DHL_API_KEY: "reauth-key"}
        )
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
