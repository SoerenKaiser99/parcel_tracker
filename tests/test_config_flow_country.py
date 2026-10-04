"""Country setting (v0.3.13): DE, AT or CH; the postcode length follows the country."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from probatio import to_field_list
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import (
    CONF_COUNTRY,
    CONF_KEEP_DELIVERED_DAYS,
    CONF_POSTCODE,
    COUNTRIES,
    DEFAULT_COUNTRY,
    DOMAIN,
    entry_country,
)

SETUP = "custom_components.parcel_tracker.async_setup_entry"


def _field(result, name: str) -> dict:
    fields = to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    return next(field for field in fields if field["name"] == name)


async def _user_form(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def _options_form(hass, data=None, options=None):
    entry = MockConfigEntry(domain=DOMAIN, data=data or {}, options=options or {})
    entry.add_to_hass(hass)
    return entry, await hass.config_entries.options.async_init(entry.entry_id)


def test_the_three_countries():
    assert COUNTRIES == ("DE", "AT", "CH")
    assert DEFAULT_COUNTRY == "DE"


@pytest.mark.parametrize(
    ("data", "options", "country"),
    [
        ({}, {}, "DE"),
        ({CONF_COUNTRY: "AT"}, {}, "AT"),
        ({CONF_COUNTRY: "AT"}, {CONF_COUNTRY: "CH"}, "CH"),
        ({CONF_COUNTRY: "FR"}, {}, "DE"),
        ({}, {CONF_COUNTRY: None}, "DE"),
        ({}, {CONF_COUNTRY: ["AT"]}, "DE"),
    ],
)
def test_entry_country_falls_back_to_germany(data, options, country):
    entry = MockConfigEntry(domain=DOMAIN, data=data, options=options)
    assert entry_country(entry) == country


@pytest.mark.parametrize(
    ("ha_country", "prefilled"),
    [("DE", "DE"), ("AT", "AT"), ("CH", "CH"), ("FR", "DE"), ("US", "DE"), (None, "DE")],
)
async def test_user_form_prefills_the_country_of_home_assistant(hass, ha_country, prefilled):
    hass.config.country = ha_country
    field = _field(await _user_form(hass), CONF_COUNTRY)
    assert field["default"] == prefilled
    selector = field["selector"]["select"]
    assert selector["options"] == ["DE", "AT", "CH"]
    assert selector["translation_key"] == "country"
    assert selector["multiple"] is False


async def test_user_form_shows_the_country_right_before_the_postcode(hass):
    result = await _user_form(hass)
    names = [
        field["name"]
        for field in to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    ]
    assert names.index(CONF_COUNTRY) + 1 == names.index(CONF_POSTCODE)


@pytest.mark.parametrize(
    ("country", "postcode"), [("DE", "10115"), ("AT", "1010"), ("CH", "8001"), ("AT", "")]
)
async def test_user_flow_stores_country_and_postcode(hass, country, postcode):
    result = await _user_form(hass)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_COUNTRY: country, CONF_POSTCODE: postcode, CONF_KEEP_DELIVERED_DAYS: 3},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_COUNTRY] == country
    assert result["data"][CONF_POSTCODE] == postcode


async def test_user_flow_without_a_submitted_country_takes_the_prefilled_one(hass):
    hass.config.country = "AT"
    result = await _user_form(hass)
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_POSTCODE: "1010", CONF_KEEP_DELIVERED_DAYS: 3}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_COUNTRY] == "AT"


@pytest.mark.parametrize(
    ("country", "postcode", "error"),
    [
        ("DE", "1010", "invalid_postcode"),
        ("DE", "101150", "invalid_postcode"),
        ("DE", "1011a", "invalid_postcode"),
        ("AT", "10115", "invalid_postcode_4"),
        ("AT", "101", "invalid_postcode_4"),
        ("CH", "80010", "invalid_postcode_4"),
        ("CH", "CH-8001", "invalid_postcode_4"),
    ],
)
async def test_postcode_length_follows_the_submitted_country(hass, country, postcode, error):
    payload = {CONF_COUNTRY: country, CONF_POSTCODE: postcode, CONF_KEEP_DELIVERED_DAYS: 3}
    result = await _user_form(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], payload)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_POSTCODE: error}
    # The form comes back with the chosen country, not with the prefilled one.
    assert _field(result, CONF_COUNTRY)["default"] == country

    entry, result = await _options_form(hass)
    result = await hass.config_entries.options.async_configure(result["flow_id"], payload)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_POSTCODE: error}
    assert _field(result, CONF_COUNTRY)["default"] == country
    assert entry.options == {}


async def test_user_flow_rejects_an_unknown_country(hass):
    result = await _user_form(hass)
    with pytest.raises(Exception, match="country"):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_COUNTRY: "FR", CONF_POSTCODE: "", CONF_KEEP_DELIVERED_DAYS: 3},
        )


async def test_options_form_of_an_entry_without_country_shows_germany(hass):
    """An existing entry behaves as DE, whatever country Home Assistant is set to."""
    hass.config.country = "AT"
    _, result = await _options_form(hass, data={CONF_POSTCODE: "10115"})
    assert _field(result, CONF_COUNTRY)["default"] == "DE"


@pytest.mark.parametrize(
    ("data", "options", "shown"),
    [
        ({CONF_COUNTRY: "AT"}, {}, "AT"),
        ({CONF_COUNTRY: "AT"}, {CONF_COUNTRY: "CH"}, "CH"),
        ({}, {CONF_COUNTRY: "AT"}, "AT"),
    ],
)
async def test_options_form_shows_the_stored_country(hass, data, options, shown):
    _, result = await _options_form(hass, data=data, options=options)
    field = _field(result, CONF_COUNTRY)
    assert field["default"] == shown
    assert field["selector"]["select"]["translation_key"] == "country"


async def test_options_form_shows_the_country_right_before_the_postcode(hass):
    _, result = await _options_form(hass)
    fields = to_field_list(result["data_schema"], custom_serializer=cv.custom_serializer)
    names = [field["name"] for field in fields]
    assert names.index(CONF_COUNTRY) + 1 == names.index(CONF_POSTCODE)
    assert next(f for f in fields if f["name"] == CONF_COUNTRY).get("type") != "expandable"


async def test_options_change_country_and_postcode_together(hass):
    entry, result = await _options_form(hass, data={CONF_POSTCODE: "10115"})
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_COUNTRY: "AT", CONF_POSTCODE: "1010", CONF_KEEP_DELIVERED_DAYS: 3},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_COUNTRY] == "AT"
    assert entry.options[CONF_POSTCODE] == "1010"
    assert entry_country(entry) == "AT"


async def test_changing_the_country_never_wipes_a_stored_postcode_silently(hass):
    """Country changed, the prefilled 5-digit postcode left as it was: a form error."""
    stored = {CONF_COUNTRY: "DE", CONF_POSTCODE: "20095", CONF_KEEP_DELIVERED_DAYS: 3}
    entry, result = await _options_form(hass, options=dict(stored))
    assert _field(result, CONF_POSTCODE)["description"]["suggested_value"] == "20095"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_COUNTRY: "AT", CONF_POSTCODE: "20095", CONF_KEEP_DELIVERED_DAYS: 3},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_POSTCODE: "invalid_postcode_4"}
    assert _field(result, CONF_POSTCODE)["description"]["suggested_value"] == "20095"
    assert entry.options == stored


async def test_options_back_to_germany_is_stored_over_the_country_of_the_setup(hass):
    entry, result = await _options_form(hass, data={CONF_COUNTRY: "AT", CONF_POSTCODE: "1010"})
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_COUNTRY: "DE", CONF_POSTCODE: "10115", CONF_KEEP_DELIVERED_DAYS: 3},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_COUNTRY] == "DE"
    assert entry_country(entry) == "DE"


async def test_options_without_a_submitted_country_keep_the_stored_one(hass):
    entry, result = await _options_form(
        hass, options={CONF_COUNTRY: "CH", CONF_POSTCODE: "8001", CONF_KEEP_DELIVERED_DAYS: 3}
    )
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_POSTCODE: "8001", CONF_KEEP_DELIVERED_DAYS: 5}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_COUNTRY] == "CH"
    assert entry.options[CONF_POSTCODE] == "8001"


async def test_setup_hands_the_country_to_the_gls_lookup(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_COUNTRY: "DE"}, options={CONF_COUNTRY: "AT"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.carriers["gls"].url.endswith("/AT/de")
