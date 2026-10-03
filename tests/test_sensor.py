from datetime import timedelta
from unittest.mock import patch

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_POSTCODE, DOMAIN, VERSION
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult
from custom_components.parcel_tracker.sensor import ParcelSensor, TodaySensor
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import DAYTIME

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
NUMBER = "00340999999999999901"


def _res(status, eta_today=False):
    today = dt_util.now().date() if eta_today else None
    return TrackingResult(
        status, "Zustellfahrzeug", today, None, None, "Bonn", None, None, None, []
    )


async def test_parcel_and_today_sensor(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=_res(ParcelStatus.OUT_FOR_DELIVERY, eta_today=True)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.services.async_call(
            DOMAIN, "add_parcel", {"number": NUMBER, "name": "Oma"}, blocking=True
        )
        await hass.async_block_till_done()

    state = hass.states.get(f"sensor.paket_{NUMBER}")
    assert state.state == "out_for_delivery"
    assert state.attributes["name"] == "Oma"
    assert state.attributes["days_until"] == 0
    assert state.attributes["eta_latest"] is None
    assert state.attributes["progress"] == 4
    assert state.attributes["friendly_name"] == "Oma"

    today = hass.states.get("sensor.pakete_heute")
    assert today.state == "1"
    assert today.attributes["parcels"][0]["name"] == "Oma"

    await hass.services.async_call(DOMAIN, "remove_parcel", {"number": NUMBER}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(f"sensor.paket_{NUMBER}") is None
    assert er.async_get(hass).async_get(f"sensor.paket_{NUMBER}") is None
    assert hass.states.get("sensor.pakete_heute").state == "0"


async def test_sensors_stay_available_when_refresh_fails(hass, freezer):
    """A failed coordinator update (e.g. a store save error) must not make
    the collective sensor, parcel sensors, or the calendar unavailable."""
    freezer.move_to(DAYTIME)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=_res(ParcelStatus.OUT_FOR_DELIVERY, eta_today=True)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.services.async_call(
            DOMAIN, "add_parcel", {"number": NUMBER, "name": "Oma"}, blocking=True
        )
        await hass.async_block_till_done()

        coordinator = entry.runtime_data
        freezer.tick(timedelta(minutes=11))  # OUT_FOR_DELIVERY polls every 10 minutes
        with patch.object(ParcelStore, "async_save", side_effect=OSError("disk full")):
            await coordinator.async_refresh()

    assert coordinator.last_update_success is False

    today = hass.states.get("sensor.pakete_heute")
    assert today.state != "unavailable"

    parcel_state = hass.states.get(f"sensor.paket_{NUMBER}")
    assert parcel_state.state != "unavailable"

    calendar_state = hass.states.get("calendar.pakete")
    assert calendar_state.state != "unavailable"


async def test_add_parcel_builds_valid_entity_id_via_slugify(hass):
    """Entity ids are built with slugify so unexpected characters (dots,
    slashes) in a tracking number don't produce an invalid entity id."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=_res(ParcelStatus.IN_TRANSIT)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.services.async_call(
            DOMAIN,
            "add_parcel",
            {"number": "JJD0003.9/7", "carrier": "dhl", "name": "Test"},
            blocking=True,
        )
        await hass.async_block_till_done()

    state = hass.states.get("sensor.paket_jjd0003_9_7")
    assert state is not None
    assert state.state == "in_transit"


async def test_ghost_sensor_removed_on_setup(hass):
    """A stale registry entry for a parcel that's no longer in the store
    (e.g. removed during the first refresh, before platforms loaded) must
    not linger as a restored, attribute-less `unavailable` sensor."""
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    stale = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_GHOST0000000",
        config_entry=entry,
        suggested_object_id="paket_ghost0000000",
    )

    with patch(FETCH, return_value=_res(ParcelStatus.IN_TRANSIT)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert registry.async_get(stale.entity_id) is None


async def test_mail_parcel_sensor_shows_code_and_carrier_name(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=_res(ParcelStatus.IN_TRANSIT)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data
    now = dt_util.utcnow()
    today = dt_util.now().date()
    coordinator.store.add(
        Parcel(
            "AMZ99905626221455530", "amazon", "mail", None, now, now,
            result=_res(ParcelStatus.OUT_FOR_DELIVERY, eta_today=True),
            tracking_ref="JJD000012978217606560", tracking_carrier="dhl",
            delivery_code="123456", delivery_code_day=today,
        )
    )
    coordinator.store.add(
        Parcel(
            "AMZ99991565342587125", "amazon", "mail", None, now, now,
            delivery_code="999999", delivery_code_day=today - timedelta(days=1),
        )
    )
    coordinator.async_set_updated_data(dict(coordinator.store.parcels))
    await hass.async_block_till_done()

    state = hass.states.get("sensor.paket_amz99905626221455530")
    assert state.attributes["friendly_name"] == "Amazon AMZ99905626221455530"
    assert state.attributes["carrier"] == "amazon"
    assert state.attributes["tracking_ref"] == "JJD000012978217606560"
    assert state.attributes["tracking_carrier"] == "dhl"
    assert state.attributes["delivery_code"] == "123456"
    expired = hass.states.get("sensor.paket_amz99991565342587125")
    assert expired.attributes["delivery_code"] is None
    assert "delivery_code" in ParcelSensor._unrecorded_attributes


async def test_sensor_exposes_eta_latest(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=_res(ParcelStatus.IN_TRANSIT)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data
    now = dt_util.utcnow()
    today = dt_util.now().date()
    result = _res(ParcelStatus.PRE_TRANSIT)
    result.eta_date = today + timedelta(days=2)
    result.eta_latest = today + timedelta(days=5)
    coordinator.store.add(
        Parcel("AMZ99960312290000000", "amazon", "mail", None, now, now, result=result)
    )
    coordinator.async_set_updated_data(dict(coordinator.store.parcels))
    await hass.async_block_till_done()

    attrs = hass.states.get("sensor.paket_amz99960312290000000").attributes
    assert attrs["eta_latest"] == (today + timedelta(days=5)).isoformat()
    assert attrs["days_until"] == 2
    assert hass.states.get("sensor.pakete_heute").state == "0"


async def _setup_with(hass, parcels):
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    with patch(FETCH, return_value=_res(ParcelStatus.IN_TRANSIT)):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data
    for parcel in parcels:
        coordinator.store.add(parcel)
    coordinator.async_set_updated_data(dict(coordinator.store.parcels))
    await hass.async_block_till_done()
    return coordinator


def _mail_parcel(number, name, status, first=None, last=None, window=None):
    """A parcel whose estimate runs from today+first to today+last (days)."""
    now = dt_util.utcnow()
    today = dt_util.now().date()
    result = _res(status)
    result.eta_date = today + timedelta(days=first) if first is not None else None
    result.eta_latest = today + timedelta(days=last) if last is not None else None
    if window:
        result.eta_from, result.eta_to = window
    return Parcel(number, "amazon", "mail", name, now, now, result=result)


async def test_today_counts_only_sure_parcels_and_lists_possible_ones(hass, freezer):
    """A range that starts today ("2.–5. Okt.") is possible, not counted."""
    freezer.move_to(DAYTIME)
    start = dt_util.now().replace(hour=14, minute=0, second=0, microsecond=0)
    window = (start, start + timedelta(hours=2))
    await _setup_with(hass, [
        _mail_parcel("AMZ99900000000000001", "Fest", ParcelStatus.IN_TRANSIT, 0, window=window),
        _mail_parcel("AMZ99900000000000002", "Fahrer", ParcelStatus.OUT_FOR_DELIVERY),
        _mail_parcel("AMZ99900000000000003", "Spanne", ParcelStatus.IN_TRANSIT, 0, 3),
        _mail_parcel("AMZ99900000000000004", "Mitte", ParcelStatus.PRE_TRANSIT, -1, 1),
        _mail_parcel("AMZ99900000000000005", "Später", ParcelStatus.IN_TRANSIT, 1, 3),
        _mail_parcel("AMZ99900000000000006", "Vorbei", ParcelStatus.IN_TRANSIT, -3, -1),
        _mail_parcel("AMZ99900000000000007", "Da", ParcelStatus.DELIVERED, 0, 3),
    ])

    today = hass.states.get("sensor.pakete_heute")
    assert today.state == "2"
    assert [p["name"] for p in today.attributes["parcels"]] == ["Fest", "Fahrer"]
    assert today.attributes["possible_count"] == 2
    assert [p["name"] for p in today.attributes["possible"]] == ["Spanne", "Mitte"]
    # Both lists have the same item shape.
    assert today.attributes["parcels"][0] == {
        "number": "AMZ99900000000000001",
        "name": "Fest",
        "carrier": "amazon",
        "eta_from": window[0].isoformat(),
        "eta_to": window[1].isoformat(),
    }
    assert today.attributes["possible"][0] == {
        "number": "AMZ99900000000000003",
        "name": "Spanne",
        "carrier": "amazon",
        "eta_from": None,
        "eta_to": None,
    }
    # The parcel's own attributes keep the range as it is.
    attrs = hass.states.get("sensor.paket_amz99900000000000003").attributes
    assert attrs["days_until"] == 0
    assert attrs["eta_latest"] == (dt_util.now().date() + timedelta(days=3)).isoformat()


async def test_today_without_possible_parcels_has_empty_list(hass, freezer):
    freezer.move_to(DAYTIME)
    await _setup_with(hass, [
        _mail_parcel("AMZ99900000000000001", "Fest", ParcelStatus.IN_TRANSIT, 0),
    ])
    today = hass.states.get("sensor.pakete_heute")
    assert today.state == "1"
    assert today.attributes["possible"] == []
    assert today.attributes["possible_count"] == 0


async def test_today_sensor_names_the_integration_version_for_the_card(hass, freezer):
    """The card compares it with its own version and asks for a page reload if they differ."""
    freezer.move_to(DAYTIME)
    await _setup_with(hass, [])
    today = hass.states.get("sensor.pakete_heute")
    assert today.attributes["integration_version"] == VERSION
    # Constant between updates: nothing for the history.
    assert "integration_version" in TodaySensor._unrecorded_attributes


async def test_possible_parcel_becomes_sure_when_its_data_says_so(hass, freezer):
    """"In Zustellung" or a fixed day today moves a parcel out of "possible"."""
    freezer.move_to(DAYTIME)
    today_date = dt_util.now().date()
    coordinator = await _setup_with(hass, [
        _mail_parcel("AMZ99900000000000001", "Eins", ParcelStatus.IN_TRANSIT, 0, 3),
        _mail_parcel("AMZ99900000000000002", "Zwei", ParcelStatus.IN_TRANSIT, 0, 3),
    ])
    today = hass.states.get("sensor.pakete_heute")
    assert (today.state, today.attributes["possible_count"]) == ("0", 2)

    # "In Zustellung" without a new day: the old range stays, the status decides.
    coordinator.store.get("AMZ99900000000000001").result.status = ParcelStatus.OUT_FOR_DELIVERY
    coordinator.async_set_updated_data(dict(coordinator.store.parcels))
    await hass.async_block_till_done()
    today = hass.states.get("sensor.pakete_heute")
    assert (today.state, today.attributes["possible_count"]) == ("1", 1)
    assert [p["name"] for p in today.attributes["parcels"]] == ["Eins"]

    # "Ankunft heute": a fixed day replaces the range.
    result = coordinator.store.get("AMZ99900000000000002").result
    result.eta_date, result.eta_latest = today_date, None
    coordinator.async_set_updated_data(dict(coordinator.store.parcels))
    await hass.async_block_till_done()
    today = hass.states.get("sensor.pakete_heute")
    assert (today.state, today.attributes["possible_count"]) == ("2", 0)
    assert today.attributes["possible"] == []


async def test_in_delivery_does_not_count_forever(hass, freezer):
    """A parcel whose "zugestellt" never arrives leaves "heute" once its day is over."""
    freezer.move_to(DAYTIME)
    stuck = _mail_parcel("AMZ99900000000000001", "Gestern", ParcelStatus.OUT_FOR_DELIVERY, -1)
    ended = _mail_parcel("AMZ99900000000000002", "Spanne", ParcelStatus.OUT_FOR_DELIVERY, -3, -1)
    old = _mail_parcel("AMZ99900000000000003", "Alt", ParcelStatus.OUT_FOR_DELIVERY)
    old.last_change_at -= timedelta(days=2)
    fresh = _mail_parcel("AMZ99900000000000004", "Frisch", ParcelStatus.OUT_FOR_DELIVERY)
    await _setup_with(hass, [stuck, ended, old, fresh])

    today = hass.states.get("sensor.pakete_heute")
    assert today.state == "1"
    assert [p["name"] for p in today.attributes["parcels"]] == ["Frisch"]
    assert today.attributes["possible"] == []


async def test_in_delivery_changed_today_follows_the_home_assistant_time_zone(hass, freezer):
    """"Today" is the day at home: 23:30 UTC is already tomorrow in Berlin."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-10-01 23:30:00+00:00")  # 01:30 on 2 Oct. in Berlin
    early = _mail_parcel("AMZ99900000000000001", "Nachts", ParcelStatus.OUT_FOR_DELIVERY)
    early.last_change_at = dt_util.utcnow() - timedelta(hours=1)  # 00:30 in Berlin
    late = _mail_parcel("AMZ99900000000000002", "Vortag", ParcelStatus.OUT_FOR_DELIVERY)
    late.last_change_at = dt_util.utcnow() - timedelta(hours=2)  # 23:30 the day before
    await _setup_with(hass, [early, late])

    today = hass.states.get("sensor.pakete_heute")
    assert [p["name"] for p in today.attributes["parcels"]] == ["Nachts"]


def _delivered(number, name, delivered_at, changed=None):
    parcel = _mail_parcel(number, name, ParcelStatus.DELIVERED)
    parcel.result.delivered_at = delivered_at
    if changed is not None:
        parcel.last_change_at = changed
    return parcel


async def test_today_lists_the_parcels_delivered_today(hass, freezer):
    """A delivered parcel leaves "heute" and shows up as delivered today, for that day."""
    freezer.move_to(DAYTIME)
    now = dt_util.utcnow()
    day = timedelta(days=1)
    await _setup_with(hass, [
        _mail_parcel("AMZ99900000000000001", "Fahrer", ParcelStatus.OUT_FOR_DELIVERY),
        _mail_parcel("AMZ99900000000000002", "Spanne", ParcelStatus.IN_TRANSIT, 0, 3),
        _delivered("AMZ99900000000000003", "Da", now - timedelta(hours=1)),
        _delivered("AMZ99900000000000004", "Gestern", now - day),
        _delivered("AMZ99900000000000005", "Ohne Zeit", None),
        _delivered("AMZ99900000000000006", "Ohne Zeit, alt", None, now - day),
        # The time of delivery decides, not the time the mail came in.
        _delivered("AMZ99900000000000007", "Spät gemeldet", now - day, now),
    ])

    today = hass.states.get("sensor.pakete_heute")
    assert today.state == "1"  # unchanged: only what still comes for sure
    assert [p["name"] for p in today.attributes["parcels"]] == ["Fahrer"]
    assert (today.attributes["possible_count"], len(today.attributes["possible"])) == (1, 1)
    assert [p["name"] for p in today.attributes["delivered_today"]] == ["Da", "Ohne Zeit"]
    assert today.attributes["delivered_today_count"] == 2
    # Same item shape as ``parcels``.
    assert today.attributes["delivered_today"][0] == {
        "number": "AMZ99900000000000003",
        "name": "Da",
        "carrier": "amazon",
        "eta_from": None,
        "eta_to": None,
    }
    assert set(today.attributes["delivered_today"][0]) == set(today.attributes["parcels"][0])
    # Recorded like ``parcels`` and ``possible``: only the version is kept out of the history.
    assert TodaySensor._unrecorded_attributes == frozenset({"integration_version"})


async def test_today_without_delivered_parcels_has_an_empty_list(hass, freezer):
    freezer.move_to(DAYTIME)
    await _setup_with(hass, [])
    today = hass.states.get("sensor.pakete_heute")
    assert today.attributes["delivered_today"] == []
    assert today.attributes["delivered_today_count"] == 0


async def test_parcel_moves_from_today_to_delivered_today(hass, freezer):
    """The tester's case: right after the delivery the card must not just say "0 heute"."""
    freezer.move_to(DAYTIME)
    coordinator = await _setup_with(hass, [
        _mail_parcel("AMZ99900000000000001", "Eins", ParcelStatus.OUT_FOR_DELIVERY),
    ])
    today = hass.states.get("sensor.pakete_heute")
    assert (today.state, today.attributes["delivered_today_count"]) == ("1", 0)

    result = coordinator.store.get("AMZ99900000000000001").result
    result.status, result.delivered_at = ParcelStatus.DELIVERED, dt_util.utcnow()
    coordinator.async_set_updated_data(dict(coordinator.store.parcels))
    await hass.async_block_till_done()
    today = hass.states.get("sensor.pakete_heute")
    assert (today.state, today.attributes["delivered_today_count"]) == ("0", 1)
    assert [p["name"] for p in today.attributes["delivered_today"]] == ["Eins"]


async def test_delivered_today_follows_the_home_assistant_time_zone(hass, freezer):
    """"Today" is the day at home: 23:30 UTC is already tomorrow in Berlin."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to("2026-10-01 23:30:00+00:00")  # 01:30 on 2 Oct. in Berlin
    now = dt_util.utcnow()
    await _setup_with(hass, [
        _delivered("AMZ99900000000000001", "Nachts", now - timedelta(hours=1)),  # 00:30 Berlin
        _delivered("AMZ99900000000000002", "Vortag", now - timedelta(hours=2)),  # 23:30 before
        _delivered("AMZ99900000000000003", "Nachts gemeldet", None, now - timedelta(hours=1)),
        _delivered("AMZ99900000000000004", "Vortag gemeldet", None, now - timedelta(hours=2)),
    ])

    today = hass.states.get("sensor.pakete_heute")
    assert [p["name"] for p in today.attributes["delivered_today"]] == [
        "Nachts", "Nachts gemeldet",
    ]


SUMMARY_IDS = (
    "sensor.pakete_unterwegs", "sensor.pakete_moeglich", "sensor.pakete_zugestellt_heute",
)


async def test_three_summary_sensors_count_what_the_today_sensor_lists(hass, freezer):
    """v0.3.11: on the way, possible today, delivered today as sensors of their own."""
    freezer.move_to(DAYTIME)
    now = dt_util.utcnow()
    no_result = Parcel("00340999999999999950", "dhl", "manual", "Neu", now, now)
    await _setup_with(hass, [
        _mail_parcel("AMZ99900000000000001", "Fahrer", ParcelStatus.OUT_FOR_DELIVERY),
        _mail_parcel("AMZ99900000000000002", "Spanne", ParcelStatus.IN_TRANSIT, 0, 3),
        _mail_parcel("AMZ99900000000000003", "Abholen", ParcelStatus.AWAITING_PICKUP),
        _mail_parcel("AMZ99900000000000004", "Problem", ParcelStatus.EXCEPTION),
        _mail_parcel("AMZ99900000000000005", "Unklar", ParcelStatus.UNKNOWN),
        no_result,
        _delivered("AMZ99900000000000006", "Da", now - timedelta(hours=1)),
        _delivered("AMZ99900000000000007", "Gestern", now - timedelta(days=1)),
    ])

    today = hass.states.get("sensor.pakete_heute")
    active = hass.states.get("sensor.pakete_unterwegs")
    possible = hass.states.get("sensor.pakete_moeglich")
    delivered = hass.states.get("sensor.pakete_zugestellt_heute")

    assert active.state == "6"
    assert [p["name"] for p in active.attributes["parcels"]] == [
        "Fahrer", "Spanne", "Abholen", "Problem", "Unklar", "Neu",
    ]
    # Same item shape as in sensor.pakete_heute, also for a parcel without any answer yet.
    assert active.attributes["parcels"][0] == today.attributes["parcels"][0]
    assert active.attributes["parcels"][-1] == {
        "number": "00340999999999999950", "name": "Neu", "carrier": "dhl",
        "eta_from": None, "eta_to": None,
    }
    assert possible.state == "1" == str(today.attributes["possible_count"])
    assert possible.attributes["parcels"] == today.attributes["possible"]
    assert delivered.state == "1" == str(today.attributes["delivered_today_count"])
    assert delivered.attributes["parcels"] == today.attributes["delivered_today"]
    # The today sensor keeps its state and attributes.
    assert today.state == "1"
    assert set(today.attributes) == {
        "parcels", "possible", "possible_count", "delivered_today", "delivered_today_count",
        "integration_version", "friendly_name", "icon",
    }
    for state, name, icon in (
        (active, "Pakete unterwegs", "mdi:truck-fast"),
        (possible, "Pakete möglich", "mdi:calendar-question"),
        (delivered, "Pakete zugestellt heute", "mdi:package-variant-closed-check"),
    ):
        assert state.attributes["friendly_name"] == name
        assert state.attributes["icon"] == icon
        # No state class, like sensor.pakete_heute.
        assert set(state.attributes) == {"parcels", "friendly_name", "icon"}


async def test_summary_sensors_are_zero_without_parcels(hass, freezer):
    freezer.move_to(DAYTIME)
    await _setup_with(hass, [])
    for entity_id in SUMMARY_IDS:
        state = hass.states.get(entity_id)
        assert state.state == "0", entity_id
        assert state.attributes["parcels"] == []


async def test_summary_sensor_ids_do_not_depend_on_the_language(hass, freezer):
    """The ids are set in the code, not built from a translated name."""
    freezer.move_to(DAYTIME)
    hass.config.language = "en"
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    for entity_id, suffix in zip(
        SUMMARY_IDS, ("active", "possible", "delivered_today"), strict=True
    ):
        assert hass.states.get(entity_id) is not None, entity_id
        assert registry.async_get(entity_id).unique_id == f"{entry.entry_id}_{suffix}"
    assert hass.states.get("sensor.pakete_heute") is not None


async def test_summary_sensors_survive_the_ghost_cleanup(hass, freezer):
    """The cleanup of parcel sensors without a parcel leaves the fixed sensors alone."""
    freezer.move_to(DAYTIME)
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    for entity_id in (*SUMMARY_IDS, "sensor.pakete_heute"):
        assert registry.async_get(entity_id) is not None, entity_id
        assert hass.states.get(entity_id).state == "0"


async def test_summary_sensors_follow_a_delivery(hass, freezer):
    freezer.move_to(DAYTIME)
    coordinator = await _setup_with(hass, [
        _mail_parcel("AMZ99900000000000001", "Fahrer", ParcelStatus.OUT_FOR_DELIVERY),
    ])
    assert hass.states.get("sensor.pakete_unterwegs").state == "1"
    assert hass.states.get("sensor.pakete_zugestellt_heute").state == "0"

    parcel = coordinator.store.get("AMZ99900000000000001")
    parcel.result.status = ParcelStatus.DELIVERED
    parcel.result.delivered_at = dt_util.utcnow()
    coordinator.async_set_updated_data(dict(coordinator.store.parcels))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.pakete_unterwegs").state == "0"
    assert hass.states.get("sensor.pakete_zugestellt_heute").state == "1"
