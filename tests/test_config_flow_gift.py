"""Geschenkmodus: the option "Wer darf Geschenke sehen?" (``gift_viewers``)."""

from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import (
    CONF_GIFT_SECTION,
    CONF_GIFT_VIEWERS,
    DOMAIN,
)

from .test_config_flow_untouched import (
    DATA,
    OPTIONS,
    _entry,
    _fields,
    _frontend_initial,
    _save,
)

ANNA = "person.anna"
BEN = "person.ben"
CARA = "person.cara"


def _chosen(*persons):
    def build(fields):
        initial = _frontend_initial(fields)
        return {**initial, CONF_GIFT_SECTION: {CONF_GIFT_VIEWERS: list(persons)}}

    return build


async def test_untouched_form_stores_no_gift_viewers(hass):
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    initial = _frontend_initial(_fields(result))
    assert initial[CONF_GIFT_SECTION] == {CONF_GIFT_VIEWERS: []}
    result, checks = await _save(hass, entry, _frontend_initial)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    for check in checks:
        check.assert_not_called()
    assert entry.data == DATA
    assert entry.options == OPTIONS
    assert CONF_GIFT_VIEWERS not in entry.options


async def test_two_persons_are_stored_as_a_list_and_prefilled_again(hass):
    entry = _entry(hass)
    result, _ = await _save(hass, entry, _chosen(ANNA, BEN))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {**OPTIONS, CONF_GIFT_VIEWERS: [ANNA, BEN]}
    result = await hass.config_entries.options.async_init(entry.entry_id)
    initial = _frontend_initial(_fields(result))
    assert initial[CONF_GIFT_SECTION] == {CONF_GIFT_VIEWERS: [ANNA, BEN]}
    result, _ = await _save(hass, entry, _frontend_initial)
    assert entry.options == {**OPTIONS, CONF_GIFT_VIEWERS: [ANNA, BEN]}


async def test_stored_viewers_survive_a_section_left_out_and_can_be_emptied(hass):
    options = {**OPTIONS, CONF_GIFT_VIEWERS: [ANNA]}
    entry = MockConfigEntry(domain=DOMAIN, data=dict(DATA), options=dict(options))
    entry.add_to_hass(hass)

    def without(fields):
        initial = _frontend_initial(fields)
        initial.pop(CONF_GIFT_SECTION)
        return initial

    await _save(hass, entry, without)
    assert entry.options == options
    await _save(hass, entry, _chosen())
    assert entry.options == {**OPTIONS, CONF_GIFT_VIEWERS: []}


async def _coordinator(hass, viewers):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"dhl_api_key": "k"},
        options={"postcode": "10115", CONF_GIFT_VIEWERS: viewers},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_viewer_user_ids_come_from_the_persons(hass):
    hass.states.async_set(ANNA, "home", {"user_id": "uid-anna"})
    hass.states.async_set(BEN, "home", {"user_id": "uid-ben"})
    hass.states.async_set(CARA, "home", {})  # a person without a user
    coordinator = await _coordinator(hass, [ANNA, BEN, CARA, "person.gone"])
    assert coordinator.gift_viewer_user_ids() == {"uid-anna", "uid-ben"}
    assert coordinator.is_gift_viewer("uid-anna") is True
    assert coordinator.is_gift_viewer("uid-other") is False
    assert coordinator.is_gift_viewer(None) is False
    assert "gift_viewers" not in hass.states.get("sensor.pakete_heute").attributes


async def test_nobody_is_a_viewer_by_default(hass):
    coordinator = await _coordinator(hass, [])
    assert coordinator.gift_viewer_user_ids() == set()
    assert coordinator.is_gift_viewer(None) is False


async def test_diagnostics_give_only_the_number_of_viewers(hass):
    from custom_components.parcel_tracker.diagnostics import async_get_config_entry_diagnostics

    hass.states.async_set(ANNA, "home", {"user_id": "uid-anna"})
    hass.states.async_set(BEN, "home", {"user_id": "uid-ben"})
    coordinator = await _coordinator(hass, [ANNA, BEN])
    diag = await async_get_config_entry_diagnostics(hass, coordinator.entry)
    assert diag["gift_viewers"] == 2
    text = str(diag)
    assert "uid-anna" not in text and "person.anna" not in text
