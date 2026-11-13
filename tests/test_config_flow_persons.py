"""Options "Personen": addresses and notify targets per person, "Unklare Pakete gehören"."""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.parcel_tracker.const import (
    CONF_DEFAULT_OWNER,
    CONF_NOTIFY_TARGETS,
    CONF_PERSONS,
    CONF_SHARED_ADDRESSES,
    DOMAIN,
)
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.models import PersonConfig, shared_addresses
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import open_options
from .test_config_flow_untouched import (
    DATA,
    OPTIONS,
    _fields,
    _frontend_initial,
    _save,
)

SETUP = "custom_components.parcel_tracker.async_setup_entry"
ANNA = "person.anna"
BEN = "person.ben"
ANNA_CONFIG = {
    "person": ANNA,
    "addresses": ["anna@example.org", "pakete+anna@example.org"],
    "notify_targets": ["notify.tablet"],
}


@pytest.fixture(autouse=True)
def _persons(hass):
    hass.states.async_set(ANNA, "home", {"friendly_name": "Anna"})
    hass.states.async_set(BEN, "home", {"friendly_name": "Ben"})
    hass.states.async_set("notify.tablet", "unknown", {"friendly_name": "Tablet"})


def _entry(hass, **options) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=dict(DATA), options={**OPTIONS, **options})
    entry.add_to_hass(hass)
    return entry


async def _step(hass, flow_id, user_input):
    with patch(SETUP, return_value=True):
        result = await hass.config_entries.options.async_configure(flow_id, user_input)
        await hass.async_block_till_done()
    return result


async def _open_persons(hass, entry):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    return await _step(hass, result["flow_id"], {"next_step_id": "persons"})


async def _open_person(hass, entry, person, default_owner="all"):
    result = await _open_persons(hass, entry)
    assert result["step_id"] == "persons"
    return await _step(
        hass, result["flow_id"], {"person": person, CONF_DEFAULT_OWNER: default_owner}
    )


async def _save_person(hass, entry, person, user_input, default_owner="all"):
    result = await _open_person(hass, entry, person, default_owner)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "person"
    if callable(user_input):
        user_input = user_input(_fields(result))
    return await _step(hass, result["flow_id"], user_input)


def _owner_options(result) -> list[str]:
    field = next(f for f in _fields(result) if f["name"] == CONF_DEFAULT_OWNER)
    return [option["value"] for option in field["selector"]["select"]["options"]]


async def test_options_start_with_a_menu(hass):
    entry = _entry(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert result["menu_options"] == ["settings", "persons"]


async def test_settings_from_the_menu_are_the_known_form(hass):
    entry = _entry(hass)
    result = await open_options(hass, entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"


async def test_untouched_persons_form_stores_nothing(hass):
    entry = _entry(hass)
    result = await _open_persons(hass, entry)
    assert result["type"] is FlowResultType.FORM
    result = await _step(hass, result["flow_id"], _frontend_initial(_fields(result)))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == OPTIONS


async def test_untouched_settings_keep_persons_and_default_owner(hass):
    entry = _entry(
        hass,
        **{
            CONF_PERSONS: [ANNA_CONFIG],
            CONF_DEFAULT_OWNER: ANNA,
            CONF_SHARED_ADDRESSES: ["familie@example.org"],
        },
    )
    before = dict(entry.options)
    result, _ = await _save(hass, entry, _frontend_initial)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == before


async def test_person_is_stored_with_clean_addresses_and_targets(hass):
    entry = _entry(hass)
    result = await _save_person(
        hass,
        entry,
        ANNA,
        {
            "addresses": " Anna@Example.org \n\n  \nPakete+Anna@example.org\nanna@example.org\n",
            CONF_NOTIFY_TARGETS: ["notify.tablet"],
            "remove": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {**OPTIONS, CONF_PERSONS: [ANNA_CONFIG]}


async def test_stored_person_is_prefilled_and_untouched_changes_nothing(hass):
    entry = _entry(hass, **{CONF_PERSONS: [ANNA_CONFIG]})
    before = dict(entry.options)
    result = await _open_person(hass, entry, ANNA)
    initial = _frontend_initial(_fields(result))
    assert initial["addresses"] == "anna@example.org\npakete+anna@example.org"
    assert initial[CONF_NOTIFY_TARGETS] == ["notify.tablet"]
    assert initial["remove"] is False
    result = await _step(hass, result["flow_id"], initial)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == before


async def test_person_is_changed(hass):
    entry = _entry(hass, **{CONF_PERSONS: [ANNA_CONFIG]})
    result = await _save_person(
        hass,
        entry,
        ANNA,
        {"addresses": "anna@example.org", CONF_NOTIFY_TARGETS: [], "remove": False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PERSONS] == [
        {"person": ANNA, "addresses": ["anna@example.org"], "notify_targets": []}
    ]


async def test_second_person_is_added_behind_the_first(hass):
    entry = _entry(hass, **{CONF_PERSONS: [ANNA_CONFIG]})
    result = await _save_person(
        hass,
        entry,
        BEN,
        {"addresses": "ben@example.org", CONF_NOTIFY_TARGETS: [], "remove": False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PERSONS] == [
        ANNA_CONFIG,
        {"person": BEN, "addresses": ["ben@example.org"], "notify_targets": []},
    ]


async def test_person_is_removed_and_default_owner_falls_back_to_all(hass):
    entry = _entry(hass, **{CONF_PERSONS: [ANNA_CONFIG], CONF_DEFAULT_OWNER: ANNA})
    result = await _save_person(
        hass, entry, ANNA, lambda fields: {**_frontend_initial(fields), "remove": True}, ANNA
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == OPTIONS


async def test_person_without_addresses_and_targets_is_not_stored(hass):
    entry = _entry(hass)
    result = await _save_person(
        hass, entry, BEN, {"addresses": "", CONF_NOTIFY_TARGETS: [], "remove": False}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == OPTIONS


async def test_address_of_another_person_is_an_error(hass):
    entry = _entry(hass, **{CONF_PERSONS: [ANNA_CONFIG]})
    before = dict(entry.options)
    result = await _save_person(
        hass,
        entry,
        BEN,
        {"addresses": "ben@example.org\nANNA@example.org", CONF_NOTIFY_TARGETS: [],
         "remove": False},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"addresses": "address_twice"}
    assert entry.options == before


@pytest.mark.parametrize("address", ["anna", "anna@", "@example.org", "anna example.org"])
async def test_address_that_is_no_mail_address_is_an_error(hass, address):
    entry = _entry(hass)
    result = await _save_person(
        hass, entry, ANNA, {"addresses": address, CONF_NOTIFY_TARGETS: [], "remove": False}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"addresses": "address_invalid"}
    assert entry.options == OPTIONS


def _phone(hass, name="Annas Handy") -> str:
    """A phone of the Home Assistant app whose tracker belongs to Anna."""
    app = MockConfigEntry(domain="mobile_app")
    app.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=app.entry_id, identifiers={("mobile_app", "phone-1")}, name=name
    )
    tracker = er.async_get(hass).async_get_or_create(
        "device_tracker", "mobile_app", "phone-1", device_id=device.id, config_entry=app
    )
    hass.states.async_set(
        ANNA, "home", {"friendly_name": "Anna", "device_trackers": [tracker.entity_id]}
    )
    return device.id


async def test_new_person_gets_the_app_service_of_her_phone_suggested(hass):
    _phone(hass)
    async_mock_service(hass, "notify", "mobile_app_annas_handy")
    async_mock_service(hass, "notify", "mobile_app_other_phone")
    entry = _entry(hass)
    result = await _open_person(hass, entry, ANNA)
    initial = _frontend_initial(_fields(result))
    assert initial[CONF_NOTIFY_TARGETS] == ["service:mobile_app_annas_handy"]


async def test_new_person_gets_the_notify_entity_of_her_phone_suggested(hass):
    device_id = _phone(hass)
    app = hass.config_entries.async_entries("mobile_app")[0]
    notify = er.async_get(hass).async_get_or_create(
        "notify", "mobile_app", "phone-1-notify", device_id=device_id, config_entry=app
    )
    hass.states.async_set(notify.entity_id, "unknown", {"friendly_name": "Annas Handy"})
    entry = _entry(hass)
    result = await _open_person(hass, entry, ANNA)
    initial = _frontend_initial(_fields(result))
    assert initial[CONF_NOTIFY_TARGETS] == [notify.entity_id]


async def test_without_a_phone_nothing_is_suggested(hass):
    async_mock_service(hass, "notify", "mobile_app_annas_handy")
    entry = _entry(hass)
    result = await _open_person(hass, entry, ANNA)
    assert _frontend_initial(_fields(result))[CONF_NOTIFY_TARGETS] == []


async def test_stored_person_keeps_her_targets_instead_of_the_suggestion(hass):
    _phone(hass)
    async_mock_service(hass, "notify", "mobile_app_annas_handy")
    entry = _entry(hass, **{CONF_PERSONS: [{**ANNA_CONFIG, "notify_targets": []}]})
    result = await _open_person(hass, entry, ANNA)
    assert _frontend_initial(_fields(result))[CONF_NOTIFY_TARGETS] == []


async def test_default_owner_offers_all_and_the_configured_persons(hass):
    entry = _entry(hass, **{CONF_PERSONS: [ANNA_CONFIG]})
    result = await _open_persons(hass, entry)
    assert _owner_options(result) == ["all", ANNA]
    assert _frontend_initial(_fields(result))[CONF_DEFAULT_OWNER] == "all"


async def test_default_owner_is_stored_only_when_not_all(hass):
    entry = _entry(hass, **{CONF_PERSONS: [ANNA_CONFIG]})
    result = await _open_persons(hass, entry)
    result = await _step(hass, result["flow_id"], {CONF_DEFAULT_OWNER: ANNA})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DEFAULT_OWNER] == ANNA
    result = await _open_persons(hass, entry)
    assert _frontend_initial(_fields(result))[CONF_DEFAULT_OWNER] == ANNA
    result = await _step(hass, result["flow_id"], {CONF_DEFAULT_OWNER: "all"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_DEFAULT_OWNER not in entry.options


async def _coordinator(hass, options) -> ParcelCoordinator:
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"}, options=options)
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    return ParcelCoordinator(hass, entry, store, {})


async def test_coordinator_reads_the_persons(hass):
    coord = await _coordinator(
        hass,
        {
            CONF_NOTIFY_TARGETS: ["notify.tablet"],
            CONF_PERSONS: [
                ANNA_CONFIG,
                {"person": BEN, "addresses": ["ben@example.org"], "notify_targets": []},
                {"person": "nonsense"},
                "junk",
            ],
            CONF_DEFAULT_OWNER: BEN,
        },
    )
    assert coord.persons() == [
        PersonConfig(ANNA, ("anna@example.org", "pakete+anna@example.org"), ("notify.tablet",)),
        PersonConfig(BEN, ("ben@example.org",), ()),
    ]
    assert coord.default_owner == BEN


async def test_coordinator_without_persons_behaves_as_before(hass):
    coord = await _coordinator(hass, {CONF_NOTIFY_TARGETS: ["notify.tablet"]})
    assert coord.persons() == []
    assert coord.default_owner is None
    assert coord.owner_targets(None) == ["notify.tablet"]
    assert coord.owner_targets(ANNA) == ["notify.tablet"]


async def test_owner_targets_are_the_persons_own_else_the_general_ones(hass):
    coord = await _coordinator(
        hass,
        {
            CONF_NOTIFY_TARGETS: ["notify.tablet"],
            CONF_PERSONS: [
                {**ANNA_CONFIG, "notify_targets": ["service:mobile_app_annas_handy"]},
                {"person": BEN, "addresses": ["ben@example.org"], "notify_targets": []},
            ],
        },
    )
    assert coord.owner_targets(ANNA) == ["service:mobile_app_annas_handy"]
    assert coord.owner_targets(BEN) == ["notify.tablet"]
    assert coord.owner_targets("person.carla") == ["notify.tablet"]
    assert coord.owner_targets(None) == ["notify.tablet"]


async def test_default_owner_that_is_no_configured_person_is_all(hass):
    coord = await _coordinator(hass, {CONF_DEFAULT_OWNER: "all"})
    assert coord.default_owner is None
    coord = await _coordinator(hass, {CONF_PERSONS: [ANNA_CONFIG], CONF_DEFAULT_OWNER: BEN})
    assert coord.default_owner is None


GONE = "person.gone"
GONE_CONFIG = {"person": GONE, "addresses": ["gone@example.org"], "notify_targets": []}


def _configured_options(result) -> list[dict]:
    field = next(f for f in _fields(result) if f["name"] == "configured_person")
    return field["selector"]["select"]["options"]


async def test_configured_persons_are_listed_also_without_a_state(hass):
    entry = _entry(hass, **{CONF_PERSONS: [ANNA_CONFIG, GONE_CONFIG]})
    result = await _open_persons(hass, entry)
    # The hint is translated (Home Assistant's language; English here).
    assert _configured_options(result) == [
        {"value": ANNA, "label": "Anna"},
        {"value": GONE, "label": "person.gone (no longer in Home Assistant)"},
    ]


async def test_person_without_a_state_is_marked_in_german(hass):
    hass.config.language = "de"
    entry = _entry(hass, **{CONF_PERSONS: [ANNA_CONFIG, GONE_CONFIG]})
    result = await _open_persons(hass, entry)
    assert _configured_options(result)[1] == {
        "value": GONE, "label": "person.gone (nicht mehr in Home Assistant)",
    }


async def test_person_without_a_state_is_picked_from_the_list_and_removed(hass):
    entry = _entry(hass, **{CONF_PERSONS: [ANNA_CONFIG, GONE_CONFIG]})
    result = await _open_persons(hass, entry)
    result = await _step(
        hass, result["flow_id"], {"configured_person": GONE, CONF_DEFAULT_OWNER: "all"}
    )
    assert result["step_id"] == "person"
    assert _frontend_initial(_fields(result))["addresses"] == "gone@example.org"
    result = await _step(
        hass, result["flow_id"], {**_frontend_initial(_fields(result)), "remove": True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {**OPTIONS, CONF_PERSONS: [ANNA_CONFIG]}


async def test_address_of_a_removed_person_is_free_again(hass):
    entry = _entry(hass, **{CONF_PERSONS: [GONE_CONFIG]})
    result = await _open_persons(hass, entry)
    result = await _step(hass, result["flow_id"], {"configured_person": GONE})
    await _step(hass, result["flow_id"], {"remove": True})
    result = await _save_person(
        hass, entry, BEN, {"addresses": "gone@example.org", CONF_NOTIFY_TARGETS: [],
                           "remove": False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PERSONS][0]["addresses"] == ["gone@example.org"]


async def test_default_owner_without_a_state_is_shown_as_all(hass):
    entry = _entry(hass, **{CONF_PERSONS: [ANNA_CONFIG, GONE_CONFIG], CONF_DEFAULT_OWNER: GONE})
    result = await _open_persons(hass, entry)
    assert _owner_options(result) == ["all", ANNA]
    initial = _frontend_initial(_fields(result))
    assert initial[CONF_DEFAULT_OWNER] == "all"
    result = await _step(hass, result["flow_id"], initial)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_DEFAULT_OWNER not in entry.options
    assert entry.options[CONF_PERSONS] == [ANNA_CONFIG, GONE_CONFIG]


async def test_untouched_new_person_stores_the_suggested_phone(hass):
    """Accepted: the prefilled suggestion is stored like a chosen target."""
    _phone(hass)
    async_mock_service(hass, "notify", "mobile_app_annas_handy")
    entry = _entry(hass)
    result = await _save_person(hass, entry, ANNA, _frontend_initial)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_PERSONS] == [
        {"person": ANNA, "addresses": [], "notify_targets": ["service:mobile_app_annas_handy"]}
    ]


async def test_default_owner_is_set_while_saving_another_person(hass):
    entry = _entry(hass, **{CONF_PERSONS: [ANNA_CONFIG]})
    result = await _save_person(
        hass,
        entry,
        BEN,
        {"addresses": "ben@example.org", CONF_NOTIFY_TARGETS: [], "remove": False},
        default_owner=ANNA,
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DEFAULT_OWNER] == ANNA
    assert [p["person"] for p in entry.options[CONF_PERSONS]] == [ANNA, BEN]


async def test_effective_default_owner_needs_the_person_in_home_assistant(hass):
    coord = await _coordinator(
        hass, {CONF_PERSONS: [ANNA_CONFIG, GONE_CONFIG], CONF_DEFAULT_OWNER: GONE}
    )
    assert coord.default_owner == GONE
    assert coord.effective_default_owner() is None
    hass.states.async_set(GONE, "home")
    assert coord.effective_default_owner() == GONE
    coord = await _coordinator(hass, {CONF_PERSONS: [ANNA_CONFIG]})
    assert coord.effective_default_owner() is None


def test_person_configs_reads_each_person_once():
    from custom_components.parcel_tracker.models import person_configs

    assert person_configs(
        {CONF_PERSONS: [ANNA_CONFIG, {**ANNA_CONFIG, "addresses": []}, "junk"]}
    ) == [PersonConfig(ANNA, ("anna@example.org", "pakete+anna@example.org"), ("notify.tablet",))]
    assert person_configs({}) == []


async def _save_persons(hass, entry, change):
    result = await _open_persons(hass, entry)
    assert result["step_id"] == "persons"
    return await _step(
        hass, result["flow_id"], {**_frontend_initial(_fields(result)), **change}
    )


async def test_shared_addresses_are_stored_clean_and_only_when_there_is_one(hass):
    entry = _entry(hass)
    text = " Familie@Example.org \n\nhaus@example.org\nfamilie@example.org\n"
    result = await _save_persons(hass, entry, {CONF_SHARED_ADDRESSES: text})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    shared = ["familie@example.org", "haus@example.org"]
    assert entry.options == {**OPTIONS, CONF_SHARED_ADDRESSES: shared}
    # Prefilled; untouched it changes nothing.
    result = await _open_persons(hass, entry)
    assert _frontend_initial(_fields(result))[CONF_SHARED_ADDRESSES] == "\n".join(shared)
    result = await _step(hass, result["flow_id"], _frontend_initial(_fields(result)))
    assert entry.options == {**OPTIONS, CONF_SHARED_ADDRESSES: shared}
    # Emptied: the option is gone again.
    result = await _save_persons(hass, entry, {CONF_SHARED_ADDRESSES: ""})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == OPTIONS


@pytest.mark.parametrize(
    ("text", "error"),
    [("Pakete+Anna@example.org", "address_twice"), ("familie", "address_invalid")],
)
async def test_shared_address_of_a_person_or_no_address_is_an_error(hass, text, error):
    entry = _entry(hass, **{CONF_PERSONS: [ANNA_CONFIG]})
    before = dict(entry.options)
    result = await _save_persons(hass, entry, {CONF_SHARED_ADDRESSES: text})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "persons"
    assert result["errors"] == {CONF_SHARED_ADDRESSES: error}
    assert _frontend_initial(_fields(result))[CONF_SHARED_ADDRESSES] == text
    assert entry.options == before


async def test_person_address_that_is_shared_is_an_error(hass):
    entry = _entry(hass, **{CONF_SHARED_ADDRESSES: ["familie@example.org"]})
    before = dict(entry.options)
    result = await _save_person(
        hass, entry, ANNA,
        {"addresses": "Familie@example.org", CONF_NOTIFY_TARGETS: [], "remove": False},
    )  # fmt: skip
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"addresses": "address_twice"}
    assert entry.options == before


async def test_shared_addresses_submitted_with_a_person_are_stored_with_her(hass):
    entry = _entry(hass)
    result = await _open_persons(hass, entry)
    result = await _step(
        hass,
        result["flow_id"],
        {"person": ANNA, CONF_DEFAULT_OWNER: "all", CONF_SHARED_ADDRESSES: "haus@example.org"},
    )
    assert result["step_id"] == "person"
    # The address just made shared is no longer free for the person.
    result = await _step(
        hass, result["flow_id"],
        {"addresses": "haus@example.org", CONF_NOTIFY_TARGETS: [], "remove": False},
    )  # fmt: skip
    assert result["errors"] == {"addresses": "address_twice"}
    result = await _step(
        hass, result["flow_id"],
        {"addresses": "anna@example.org", CONF_NOTIFY_TARGETS: [], "remove": False},
    )  # fmt: skip
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {
        **OPTIONS,
        CONF_PERSONS: [
            {"person": ANNA, "addresses": ["anna@example.org"], "notify_targets": []}
        ],
        CONF_SHARED_ADDRESSES: ["haus@example.org"],
    }


def test_shared_addresses_reads_texts_only():
    options = {CONF_SHARED_ADDRESSES: [" A@Example.org", 5, "", "a@example.org", "b@x.org"]}
    assert shared_addresses(options) == ("a@example.org", "b@x.org")
    assert shared_addresses({CONF_SHARED_ADDRESSES: "a@example.org"}) == ()
    assert shared_addresses({}) == ()
