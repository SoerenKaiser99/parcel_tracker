"""v0.3.24: the option "Namen ausblenden" (``hide_names``).

Switched on, nothing the integration shows tells what a parcel is or who sent it:
sensors, the lists of the summary sensors, the calendar, the status event and the push
notification name a parcel by its carrier only. The store keeps every name, and a name
the user typed in stays visible.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)

from custom_components.parcel_tracker.card_install import BUNDLED_CARD
from custom_components.parcel_tracker.const import (
    CONF_HIDE_NAMES,
    CONF_NOTIFY_TARGETS,
    CONF_POSTCODE,
    DOMAIN,
    EVENT_STATUS_CHANGED,
)
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import MailUpdate
from custom_components.parcel_tracker.models import (
    Parcel,
    ParcelStatus,
    TrackingResult,
    display_name,
    neutral_name,
)
from custom_components.parcel_tracker.notification import build_notification

from .conftest import DAYTIME

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
PHONE = "notify.mobile_app_handy"
BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=BERLIN)

DHL = "00340999999999990012"
AMAZON = "AMZ99999999999994321"
GLS = "99999999977"
# Names a mail gave (never to be shown) and one the user typed in (shown).
SHOP_NAME = "Spielwaren Muster"
TITLE = "Holzeisenbahn Starterset"
MANUAL = "Überraschung"
HIDDEN = ("Spielwaren", "Holzeisenbahn", "Starterset")


def _result(status=ParcelStatus.IN_TRANSIT, eta=None):
    return TrackingResult(status, "Unterwegs", eta, None, None, None, None, None, None, [])


def _parcel(number=DHL, carrier="dhl", name=SHOP_NAME, **fields) -> Parcel:
    return Parcel(number, carrier, "mail", name, NOW, NOW, **fields)


# ----- the neutral name -----


@pytest.mark.parametrize(
    ("number", "carrier", "fields", "expected"),
    [
        (DHL, "dhl", {}, "DHL-Paket …0012"),
        (GLS, "gls", {}, "GLS-Paket …9977"),
        ("H9999999999999990034", "hermes", {}, "Hermes-Paket …0034"),
        (AMAZON, "amazon", {}, "Amazon-Bestellung …4321"),
        ("EBAY999999999955P2", "ebay", {}, "eBay-Bestellung …55P2"),
        # A shop order stays one, also once a carrier's number is known.
        (AMAZON, "amazon", {"tracking_ref": DHL, "tracking_carrier": "dhl"},
         "Amazon-Bestellung …4321"),
        # "Automatisch" before the first answer, and 17track without a known carrier.
        (DHL, None, {}, "Paket …0012"),
        ("999999999988", "other", {}, "Paket …9988"),
        ("999999999988", "other", {"track17_carrier": 190271}, "Paket …9988"),
        ("999999999988", "other", {"track17_carrier": 101070}, "GLS-Paket …9988"),
    ],
)
def test_neutral_name_is_built_from_the_carrier_and_the_last_four(
    number, carrier, fields, expected
):
    parcel = _parcel(number, carrier, **fields)
    assert neutral_name(parcel) == expected
    assert display_name(parcel, True) == expected


def test_display_name_is_the_stored_name_while_the_option_is_off():
    assert display_name(_parcel(), False) == SHOP_NAME
    assert display_name(_parcel(name=None), False) is None


def test_a_name_typed_in_by_the_user_stays_visible():
    assert display_name(_parcel(name=MANUAL, name_manual=True), True) == MANUAL
    # Nothing typed in (any more): the mark alone shows nothing.
    assert display_name(_parcel(name=None, name_manual=True), True) == "DHL-Paket …0012"


def test_the_mail_title_is_never_a_fallback():
    order = _parcel(AMAZON, "amazon", None, mail_title=TITLE)
    assert display_name(order, True) == "Amazon-Bestellung …4321"


def test_name_manual_is_stored_and_missing_means_not_typed_in():
    parcel = _parcel(name=MANUAL, name_manual=True)
    data = parcel.to_dict()
    assert data["name_manual"] is True
    assert Parcel.from_dict(data).name_manual is True
    del data["name_manual"]  # stored by an older version: nobody knows who set the name
    assert Parcel.from_dict(data).name_manual is False
    for odd in (None, 1, "true"):
        assert Parcel.from_dict({**data, "name_manual": odd}).name_manual is False


# ----- notification text -----


def _delivered(**fields) -> Parcel:
    return _parcel(result=_result(ParcelStatus.DELIVERED), **fields)


def test_notification_names_the_parcel_by_its_carrier_only():
    _, message = build_notification(_delivered(), ParcelStatus.IN_TRANSIT, NOW, hide_names=True)
    assert message == "✅ DHL-Paket …0012 wurde zugestellt"
    order = _delivered(number=AMAZON, carrier="amazon", name=None, mail_title=TITLE)
    _, message = build_notification(order, ParcelStatus.IN_TRANSIT, NOW, hide_names=True)
    assert message == "✅ Amazon-Bestellung …4321 wurde zugestellt"


def test_notification_keeps_a_name_typed_in_by_the_user():
    parcel = _delivered(name=MANUAL, name_manual=True)
    _, message = build_notification(parcel, ParcelStatus.IN_TRANSIT, NOW, hide_names=True)
    assert message == f"✅ {MANUAL} (DHL) wurde zugestellt"


def test_notification_is_unchanged_while_the_option_is_off():
    _, message = build_notification(_delivered(), ParcelStatus.IN_TRANSIT, NOW)
    assert message == f"✅ {SHOP_NAME} (DHL) wurde zugestellt"
    _, message = build_notification(_delivered(name=None), ParcelStatus.IN_TRANSIT, NOW)
    assert message == "✅ Paket …0012 (DHL) wurde zugestellt"


# ----- a mail never marks a name as typed in -----


def test_a_name_from_a_mail_replaces_a_typed_in_carrier_name_and_its_mark():
    """A carrier's own display name counts as no name (see ``_apply_tracking``): the
    shop a mail names takes its place, and that name is the mail's, not the user's."""
    parcel = Parcel(DHL, "dhl", "manual", "DHL Zustell-Update", NOW, NOW, name_manual=True)
    parcels = {DHL: parcel}
    update = MailUpdate(DHL, "dhl", ParcelStatus.IN_TRANSIT, NOW, title=SHOP_NAME)
    apply_update(parcels, update, NOW)
    assert parcel.name == SHOP_NAME
    assert parcel.name_manual is False


def test_parcels_from_mails_are_not_marked():
    parcels: dict[str, Parcel] = {}
    apply_update(parcels, MailUpdate(DHL, "dhl", ParcelStatus.IN_TRANSIT, NOW, title=SHOP_NAME),
                 NOW)
    apply_update(
        parcels, MailUpdate(AMAZON, "amazon", ParcelStatus.PRE_TRANSIT, NOW, title=TITLE), NOW
    )
    assert [p.name for p in parcels.values()] == [SHOP_NAME, TITLE]
    assert not any(p.name_manual for p in parcels.values())


# ----- in Home Assistant -----


def _stored(now: datetime) -> list[Parcel]:
    today = dt_util.as_local(now).date()
    later = now + timedelta(hours=2)
    return [
        Parcel(DHL, "dhl", "mail", SHOP_NAME, now, now, last_poll_at=now, next_poll_at=later,
               result=_result(ParcelStatus.OUT_FOR_DELIVERY, today)),
        Parcel(AMAZON, "amazon", "mail", TITLE, now, now, mail_title=TITLE,
               shipping_carrier_hint="hermes",
               result=_result(eta=today + timedelta(days=1))),
        Parcel(GLS, "gls", "manual", MANUAL, now, now, last_poll_at=now, next_poll_at=later,
               name_manual=True, result=_result(eta=today + timedelta(days=1))),
    ]


async def _setup(hass, hass_storage, freezer, hide=True):
    freezer.move_to(DAYTIME)
    now = dt_util.utcnow()
    hass_storage[DOMAIN] = {
        "version": 1,
        "key": DOMAIN,
        "data": {"parcels": [p.to_dict() for p in _stored(now)], "message_ids": []},
    }
    options = {CONF_NOTIFY_TARGETS: [PHONE]}
    if hide is not None:
        options[CONF_HIDE_NAMES] = hide
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"}, options=options
    )
    entry.add_to_hass(hass)
    hass.states.async_set(PHONE, "unknown")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _names(hass) -> dict[str, str | None]:
    return {
        number: hass.states.get(f"sensor.paket_{number.lower()}").attributes["name"]
        for number in (DHL, AMAZON, GLS)
    }


async def _calendar(hass) -> list[dict]:
    result = await hass.services.async_call(
        "calendar", "get_events",
        {"entity_id": "calendar.pakete", "duration": {"days": 3}},
        blocking=True, return_response=True,
    )
    return result["calendar.pakete"]["events"]


def _shown(hass) -> str:
    """Every state of Home Assistant with all its attributes, as one text."""
    return json.dumps([s.as_dict() for s in hass.states.async_all()], ensure_ascii=False,
                      default=str)


NEUTRAL = {DHL: "DHL-Paket …0012", AMAZON: "Amazon-Bestellung …4321", GLS: MANUAL}
REAL = {DHL: SHOP_NAME, AMAZON: TITLE, GLS: MANUAL}


async def test_sensors_and_lists_show_neutral_names(hass, hass_storage, freezer):
    await _setup(hass, hass_storage, freezer)
    assert _names(hass) == NEUTRAL
    for number, name in NEUTRAL.items():
        state = hass.states.get(f"sensor.paket_{number.lower()}")
        assert state.attributes["friendly_name"] == name
        assert state.attributes["number"] == number
    order = hass.states.get(f"sensor.paket_{AMAZON.lower()}")
    # The carrier stays, also the one a shop mail named.
    assert order.attributes["carrier_name"] == "Amazon"
    assert order.attributes["shipping_carrier_hint"] == "hermes"
    today = hass.states.get("sensor.pakete_heute")
    assert [p["name"] for p in today.attributes["parcels"]] == [NEUTRAL[DHL]]
    active = hass.states.get("sensor.pakete_unterwegs")
    assert [p["name"] for p in active.attributes["parcels"]] == list(NEUTRAL.values())
    text = _shown(hass)
    for word in HIDDEN:
        assert word not in text


async def test_calendar_shows_neutral_names(hass, hass_storage, freezer):
    await _setup(hass, hass_storage, freezer)
    events = await _calendar(hass)
    assert sorted(e["summary"] for e in events) == sorted(
        f"Paket: {name}" for name in NEUTRAL.values()
    )
    text = json.dumps(events, ensure_ascii=False)
    for word in HIDDEN:
        assert word not in text
    state = hass.states.get("calendar.pakete")
    assert state.attributes["message"] in {f"Paket: {name}" for name in NEUTRAL.values()}


async def test_event_and_notification_show_neutral_names(hass, hass_storage, freezer):
    entry = await _setup(hass, hass_storage, freezer)
    coordinator = entry.runtime_data
    calls = async_mock_service(hass, "notify", "send_message")
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    freezer.tick(timedelta(hours=3))
    with patch(FETCH, return_value=_result(ParcelStatus.DELIVERED)):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    (event,) = events
    assert event.data["number"] == DHL
    assert event.data["name"] == NEUTRAL[DHL]
    assert event.data["carrier_name"] == "DHL"
    (call,) = calls
    assert call.data["message"] == "✅ DHL-Paket …0012 wurde zugestellt"
    text = json.dumps([dict(event.data), dict(call.data)], ensure_ascii=False)
    for word in HIDDEN:
        assert word not in text


async def test_option_off_shows_the_names_as_before(hass, hass_storage, freezer):
    for hide in (False, None):  # switched off, and an entry from before v0.3.24
        entry = await _setup(hass, hass_storage, freezer, hide=hide)
        assert _names(hass) == REAL
        events = await _calendar(hass)
        assert sorted(e["summary"] for e in events) == sorted(
            f"Paket: {name}" for name in REAL.values()
        )
        assert await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()


async def test_toggling_keeps_entity_ids_and_stored_names(hass, hass_storage, freezer):
    entry = await _setup(hass, hass_storage, freezer)
    ids = sorted(hass.states.async_entity_ids("sensor"))
    assert f"sensor.paket_{DHL.lower()}" in ids
    stored = [p.to_dict() for p in entry.runtime_data.store.parcels.values()]
    assert [p["name"] for p in stored] == list(REAL.values())
    assert stored[1]["mail_title"] == TITLE

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_HIDE_NAMES: False}
    )
    await hass.async_block_till_done()
    assert _names(hass) == REAL  # at once, without a restart
    assert sorted(hass.states.async_entity_ids("sensor")) == ids
    assert [p.to_dict() for p in entry.runtime_data.store.parcels.values()] == stored

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_HIDE_NAMES: True}
    )
    await hass.async_block_till_done()
    assert _names(hass) == NEUTRAL
    assert sorted(hass.states.async_entity_ids("sensor")) == ids
    assert [p.to_dict() for p in entry.runtime_data.store.parcels.values()] == stored


# ----- "Umbenennen" and "Paket hinzufügen" -----


async def test_renaming_marks_the_name_as_typed_in(hass, hass_storage, freezer):
    entry = await _setup(hass, hass_storage, freezer)
    await hass.services.async_call(
        DOMAIN, "rename_parcel", {"number": DHL, "name": "Für Oma"}, blocking=True
    )
    await hass.async_block_till_done()
    parcel = entry.runtime_data.store.parcels[DHL]
    assert (parcel.name, parcel.name_manual) == ("Für Oma", True)
    assert _names(hass)[DHL] == "Für Oma"

    # Emptied again: no name, so nothing typed in is left to show.
    await hass.services.async_call(
        DOMAIN, "rename_parcel", {"number": DHL, "name": ""}, blocking=True
    )
    await hass.async_block_till_done()
    assert (parcel.name, parcel.name_manual) == (None, False)
    assert _names(hass)[DHL] == NEUTRAL[DHL]


async def test_saving_the_shown_name_untouched_changes_nothing(hass, hass_storage, freezer):
    """The card prefills "Umbenennen" with the name it shows. Saved as it is, the
    neutral name does not replace the stored one, and the stored name of a mail is
    not turned into a typed-in one."""
    entry = await _setup(hass, hass_storage, freezer)
    parcels = entry.runtime_data.store.parcels
    for number, name in ((DHL, NEUTRAL[DHL]), (AMAZON, NEUTRAL[AMAZON]), (AMAZON, TITLE)):
        await hass.services.async_call(
            DOMAIN, "rename_parcel", {"number": number, "name": name}, blocking=True
        )
    await hass.async_block_till_done()
    assert (parcels[DHL].name, parcels[DHL].name_manual) == (SHOP_NAME, False)
    assert (parcels[AMAZON].name, parcels[AMAZON].name_manual) == (TITLE, False)
    assert _names(hass) == NEUTRAL


async def test_a_name_given_when_adding_is_typed_in(hass, hass_storage, freezer):
    entry = await _setup(hass, hass_storage, freezer)
    named, plain = "00340999999999990029", "00340999999999990036"
    with patch(FETCH, return_value=_result()):
        await hass.services.async_call(
            DOMAIN, "add_parcel", {"number": named, "carrier": "dhl", "name": "Für Opa"},
            blocking=True,
        )
        await hass.services.async_call(
            DOMAIN, "add_parcel", {"number": plain, "carrier": "dhl"}, blocking=True
        )
        await hass.async_block_till_done()
    parcels = entry.runtime_data.store.parcels
    assert (parcels[named].name, parcels[named].name_manual) == ("Für Opa", True)
    assert (parcels[plain].name, parcels[plain].name_manual) == (None, False)
    assert hass.states.get(f"sensor.paket_{named}").attributes["name"] == "Für Opa"
    assert hass.states.get(f"sensor.paket_{plain}").attributes["name"] == "DHL-Paket …0036"


# ----- the card -----


def test_the_card_names_a_parcel_by_its_name_attribute_only():
    """The card needs no setting of its own: the one name it shows is the attribute
    ``name`` (else the number), and it reads neither a mail title nor a friendly name."""
    source = BUNDLED_CARD.read_text(encoding="utf-8")
    assert "esc(a.name || a.number)" in source
    assert "mail_title" not in source
    assert "friendly_name" not in source
