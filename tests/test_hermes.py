"""Hermes carrier against the ha-hermes payloads (MIT) plus synthetic edge cases."""

import logging
from datetime import UTC, datetime

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.parcel_tracker.carriers import build_carriers
from custom_components.parcel_tracker.carriers import hermes as hermes_module
from custom_components.parcel_tracker.carriers.base import (
    CarrierUnavailable,
    Match,
    NotFound,
    ParseError,
    RateLimited,
)
from custom_components.parcel_tracker.carriers.hermes import HERMES_URL, HermesCarrier, parse_hermes
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_fixture

CODE = "12345678901234"


def _response(name: str) -> list:
    return load_fixture(name)["response"]


def _event(code, ts, text):
    return {"timestamp": ts, "status": "HAPPY", "parcelStatus": code, "historyText": text}


def test_matches():
    assert HermesCarrier.matches("H9999999999999999901") is Match.SURE
    assert HermesCarrier.matches("12345678901234") is Match.POSSIBLE
    assert HermesCarrier.matches("H99999999999999999") is Match.NO
    assert HermesCarrier.matches("00340999999999999901") is Match.NO


def test_fixtures_credit_their_source():
    for name in ("hermes_delivered.json", "hermes_out_for_delivery.json", "hermes_pickup.json",
                 "hermes_real_dropoff_delivered.json"):
        assert "ha-hermes (MIT License" in load_fixture(name)["_source"]


def test_delivered():
    r = parse_hermes(_response("hermes_delivered.json"))
    assert r.status is ParcelStatus.DELIVERED
    assert r.status_text == "Delivered to the recipient"
    assert r.delivered_at == datetime(2026, 4, 29, 13, 12, 42, tzinfo=UTC)
    assert [e.text for e in r.events][:2] == ["Delivered to the recipient", "Out for delivery"]
    assert r.events[0].location is None
    assert r.eta_date is None


def test_out_for_delivery_and_pickup():
    assert parse_hermes(_response("hermes_out_for_delivery.json")).status is (
        ParcelStatus.OUT_FOR_DELIVERY
    )
    pickup = parse_hermes(_response("hermes_pickup.json"))
    assert pickup.status is ParcelStatus.AWAITING_PICKUP
    assert pickup.delivered_at is None


def test_real_dropoff_delivery():
    r = parse_hermes(_response("hermes_real_dropoff_delivered.json"))
    assert r.status is ParcelStatus.DELIVERED
    assert r.status_text == "Am Wunschablageort zugestellt"
    assert r.delivered_at == datetime(2026, 8, 10, 8, 16, 21, 25000, tzinfo=UTC)
    assert len(r.events) == 5


def test_drop_off_events_get_fixed_texts_never_the_raw_place():
    data = [{"barcode": CODE, "parcelProgress": [
        _event("DELIVERED_DROPOFF", "2026-08-10T08:16:21Z", "Zugestellt: Hinter dem Schuppen."),
        _event("EDL_BOOKED_DROPOFF", "2026-08-07T16:00:12Z", "Ablageort: Hinter dem Schuppen."),
        _event("EDL_CHANGED", "2026-08-07T15:00:12Z", "Neu: Hinter dem Schuppen."),
        _event("PARCELSHOP_DROP_OFF", "2026-08-07T14:29:35Z", "Im PaketShop abgegeben."),
    ]}]
    r = parse_hermes(data)
    assert r.status_text == "Am Wunschablageort zugestellt"
    assert [e.text for e in r.events] == [
        "Am Wunschablageort zugestellt",
        "Wunschablageort gebucht",
        "Wunschablageort gebucht",
        "Im PaketShop abgegeben.",
    ]
    assert "Schuppen" not in str(r.to_dict())


def test_booked_drop_off_is_skipped_for_the_status():
    data = [{"barcode": CODE, "parcelProgress": [
        _event("EDL_BOOKED_DROPOFF", "2026-08-07T16:00:12Z", "WunschAblageort gebucht."),
        _event("PARCELSHOP_DROP_OFF", "2026-08-07T14:29:35Z", "Im PaketShop abgegeben."),
    ]}]
    r = parse_hermes(data)
    assert (r.status, r.status_text) == (ParcelStatus.PRE_TRANSIT, "Im PaketShop abgegeben.")


def test_depot_maps_to_delivery_depot():
    data = [{"barcode": CODE, "parcelProgress": [
        _event("ARRIVED_AT_DELIVERY_DEPOT", "2026-08-09T02:20:50Z", "Im Zustelldepot."),
    ]}]
    assert parse_hermes(data).status is ParcelStatus.AT_DELIVERY_DEPOT


def test_unknown_status_is_unknown_and_warned_once(caplog):
    hermes_module._WARNED.clear()
    data = [{"barcode": CODE, "parcelProgress": [
        _event("BRAND_NEW_CODE", "2026-08-09T02:20:50Z", "Etwas Neues."),
    ]}]
    with caplog.at_level(logging.WARNING):
        assert parse_hermes(data).status is ParcelStatus.UNKNOWN
        parse_hermes(data)
    assert caplog.text.count("BRAND_NEW_CODE") == 1


def test_delivered_flag_wins_over_an_unmapped_last_event():
    hermes_module._WARNED.clear()
    data = [{"barcode": CODE,
             "parcelAttributes": {"delivered": True, "deliveredTimestamp": "2026-08-10T08:16:21Z"},
             "parcelProgress": [_event("NEW_DELIVERY_KIND", "2026-08-10T08:16:21Z", "Da.")]}]
    r = parse_hermes(data)
    assert r.status is ParcelStatus.DELIVERED
    assert r.delivered_at == datetime(2026, 8, 10, 8, 16, 21, tzinfo=UTC)


@pytest.mark.parametrize("data", [[], [{"barcode": CODE}]])
def test_empty_answers(data):
    if not data:
        with pytest.raises(NotFound):
            parse_hermes(data)
    else:
        r = parse_hermes(data)
        assert (r.status, r.events) == (ParcelStatus.UNKNOWN, [])


@pytest.mark.parametrize("data", [{"barcode": CODE}, ["text"]])
def test_unexpected_shapes(data):
    with pytest.raises(ParseError):
        parse_hermes(data)


async def _fetch(status, body=None, headers=None, raw=None):
    with aioresponses() as m:
        if raw is not None:
            m.get(f"{HERMES_URL}/{CODE}", status=status, body=raw)
        else:
            m.get(f"{HERMES_URL}/{CODE}", status=status, payload=body, headers=headers)
        async with aiohttp.ClientSession() as session:
            return await HermesCarrier(session).fetch(CODE, "10115")


async def test_fetch_ok():
    r = await _fetch(200, _response("hermes_delivered.json"))
    assert r.status is ParcelStatus.DELIVERED


async def test_fetch_errors():
    for status in (400, 404):
        with pytest.raises(NotFound):
            await _fetch(status, {})
    with pytest.raises(RateLimited) as err:
        await _fetch(429, {}, headers={"Retry-After": "90"})
    assert err.value.retry_after == 90
    with pytest.raises(CarrierUnavailable):
        await _fetch(503, {})
    with pytest.raises(ParseError):
        await _fetch(200, raw="<html>Wartung</html>")


async def test_fetch_network_error():
    with aioresponses() as m:
        m.get(f"{HERMES_URL}/{CODE}", exception=aiohttp.ClientConnectionError("down"))
        async with aiohttp.ClientSession() as session:
            with pytest.raises(CarrierUnavailable):
                await HermesCarrier(session).fetch(CODE, None)


async def test_build_carriers_includes_hermes():
    async with aiohttp.ClientSession() as session:
        carriers = build_carriers(session, None)
    assert list(carriers) == ["dhl", "dpd", "hermes", "gls"]
    assert carriers["hermes"].name == "Hermes"


# ----- v0.3.29: a parcel waiting in a PaketShop is "Abholbereit" (issue #18) -----

SHOP = "Kiosk Beispiel, Musterweg 1, 12345 Musterstadt"
LOADED = (
    "Die Sendung wurde ins Zustellfahrzeug geladen und wird voraussichtlich heute an den "
    "PaketShop zugestellt."
)
WAITING = f"Die Sendung liegt im Hermes PaketShop {SHOP} max. 7 Werktage zur Abholung bereit."
COLLECTED = f"Die Sendung wurde im Hermes PaketShop {SHOP} erfolgreich abgeholt."


def _shop_history(loaded, waiting=None, collected=None, attributes=None):
    """The history of issue #18, newest first, cut off after the given steps."""
    steps = [
        (collected, "2026-10-08T15:02:00Z", COLLECTED),
        (waiting, "2026-10-08T13:50:00Z", WAITING),
        (loaded, "2026-10-08T07:12:00Z", LOADED),
    ]
    parcel = {
        "barcode": CODE,
        "parcelProgress": [_event(code, ts, text) for code, ts, text in steps if code],
    }
    if attributes is not None:
        parcel["parcelAttributes"] = attributes
    return [parcel]


@pytest.mark.parametrize(
    ("waiting", "collected"),
    [
        ("SHOP_CODE_NOBODY_KNOWS", "COLLECTION_CODE_NOBODY_KNOWS"),
        ("DELIVERED_PARCELSHOP", "PICKED_UP_BY_RECIPIENT"),
        ("DELIVERED_PARCELSHOP", "DELIVERED_PARCELSHOP"),
        ("DELIVERED_PARCELSHOP", "COLLECTED"),
        ("PARCELSHOP_ITEMS_FOR_COLLECTION", "PICKED_UP_BY_RECIPIENT"),
        ("READY_FOR_COLLECTION", "COLLECTED"),
    ],
    ids=["unknown", "delivered-shop", "delivered-shop-twice", "delivered-shop-collected",
         "known", "known-2"],
)
def test_parcel_shop_history_step_by_step(waiting, collected):
    hermes_module._WARNED.clear()
    loaded = parse_hermes(_shop_history("DELIVERY_TOUR_STARTED"))
    assert loaded.status is ParcelStatus.OUT_FOR_DELIVERY
    waits = parse_hermes(_shop_history("DELIVERY_TOUR_STARTED", waiting))
    assert waits.status is ParcelStatus.AWAITING_PICKUP
    assert (waits.status_text, waits.delivered_at) == (WAITING, None)
    assert waits.pickup_point is None  # the shop is only named in the text, as before
    done = parse_hermes(_shop_history("DELIVERY_TOUR_STARTED", waiting, collected))
    assert done.status is ParcelStatus.DELIVERED
    assert done.status_text == COLLECTED
    assert done.delivered_at == datetime(2026, 10, 8, 15, 2, tzinfo=UTC)
    assert [e.text for e in done.events] == [COLLECTED, WAITING, LOADED]


def test_unknown_code_is_still_warned_once_when_the_text_gave_the_status(caplog):
    hermes_module._WARNED.clear()
    data = _shop_history("DELIVERY_TOUR_STARTED", "SHOP_CODE_NOBODY_KNOWS")
    with caplog.at_level(logging.WARNING):
        assert parse_hermes(data).status is ParcelStatus.AWAITING_PICKUP
        parse_hermes(data)
    assert caplog.text.count("SHOP_CODE_NOBODY_KNOWS") == 1
    # The text names the shop and its address: never part of the log.
    assert "Kiosk" not in caplog.text and "Musterweg" not in caplog.text


def test_known_code_is_never_warned_about(caplog):
    hermes_module._WARNED.clear()
    with caplog.at_level(logging.WARNING):
        parse_hermes(_shop_history("DELIVERY_TOUR_STARTED", "DELIVERED_PARCELSHOP"))
    assert caplog.text == ""


@pytest.mark.parametrize("code", ["DELIVERY_TOUR_STARTED", "CODE_NOBODY_KNOWS"])
def test_on_its_way_to_the_shop_is_not_waiting_there(code):
    """The word PaketShop alone says nothing: a known code keeps its status, an
    unknown one stays unknown."""
    hermes_module._WARNED.clear()
    expected = (
        ParcelStatus.OUT_FOR_DELIVERY if code == "DELIVERY_TOUR_STARTED" else ParcelStatus.UNKNOWN
    )
    assert parse_hermes(_shop_history(code)).status is expected


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("Die Sendung ist abholbereit.", ParcelStatus.AWAITING_PICKUP),
        ("Die Sendung liegt im PaketShop zur Abholung.", ParcelStatus.AWAITING_PICKUP),
        ("Die Sendung kann im PaketShop abgeholt werden.", ParcelStatus.AWAITING_PICKUP),
        ("Die Sendung liegt im PaketShop und wird 7 Werktage zur Abholung bereitgehalten.",
         ParcelStatus.AWAITING_PICKUP),
        ("Ihre Sendung steht zur Abholung bereit.", ParcelStatus.AWAITING_PICKUP),
        # An announcement of the step is not the step.
        ("Sobald die Sendung zur Abholung bereit liegt, informieren wir Sie.",
         ParcelStatus.UNKNOWN),
        ("Die Sendung wird morgen im PaketShop zur Abholung bereit liegen.",
         ParcelStatus.UNKNOWN),
        ("Sobald die Sendung im PaketShop liegt, kann sie abgeholt werden.",
         ParcelStatus.UNKNOWN),
        ("Die Sendung wurde im PaketShop abgegeben.", ParcelStatus.UNKNOWN),
        ("Die Sendung wurde vom Fahrer im PaketShop abgeholt.", ParcelStatus.UNKNOWN),
        ("", ParcelStatus.UNKNOWN),
    ],
)
def test_texts_of_an_unknown_code(text, status):
    hermes_module._WARNED.clear()
    data = [{"barcode": CODE, "parcelProgress": [
        _event("CODE_NOBODY_KNOWS", "2026-10-08T13:50:00Z", text),
    ]}]
    assert parse_hermes(data).status is status


@pytest.mark.parametrize(
    ("text", "status"),
    [
        ("Die Sendung wurde an den PaketShop zugestellt.", ParcelStatus.AWAITING_PICKUP),
        ("Delivered to a ParcelShop", ParcelStatus.AWAITING_PICKUP),
        (None, ParcelStatus.AWAITING_PICKUP),
        ("Die Sendung kann im PaketShop abgeholt werden.", ParcelStatus.AWAITING_PICKUP),
        ("Die Sendung wurde nicht abgeholt.", ParcelStatus.AWAITING_PICKUP),
        ("Die Sendung wurde vom Empfänger abgeholt.", ParcelStatus.DELIVERED),
    ],
)
def test_delivered_to_a_shop_without_the_waiting_text(text, status):
    """Delivered to a PaketShop is not delivered to the recipient; only a text that
    tells the collection makes it "delivered"."""
    data = [{"barcode": CODE, "parcelProgress": [
        _event("DELIVERED_PARCELSHOP", "2026-10-08T13:50:00Z", text),
    ]}]
    assert parse_hermes(data).status is status


DELIVERED_FLAG = {"delivered": True, "deliveredTimestamp": "2026-10-08T13:50:00Z"}


@pytest.mark.parametrize(
    "waiting",
    ["SHOP_CODE_NOBODY_KNOWS", "DELIVERED_PARCELSHOP", "PARCELSHOP_ITEMS_FOR_COLLECTION"],
)
def test_delivered_flag_does_not_end_the_wait_in_the_shop(waiting):
    hermes_module._WARNED.clear()
    waits = parse_hermes(_shop_history("DELIVERY_TOUR_STARTED", waiting, attributes=DELIVERED_FLAG))
    assert (waits.status, waits.delivered_at) == (ParcelStatus.AWAITING_PICKUP, None)
    done = parse_hermes(
        _shop_history("DELIVERY_TOUR_STARTED", waiting, "PICKED_UP_BY_RECIPIENT", DELIVERED_FLAG)
    )
    assert done.status is ParcelStatus.DELIVERED
    assert done.delivered_at == datetime(2026, 10, 8, 15, 2, tzinfo=UTC)


def test_delivered_flag_still_wins_over_an_unknown_collection_code():
    """The collection under a code nobody knows, in a text nobody knows: the flag decides."""
    hermes_module._WARNED.clear()
    data = [{"barcode": CODE, "parcelAttributes": {
        "delivered": True, "deliveredTimestamp": "2026-10-08T15:02:00Z",
    }, "parcelProgress": [
        _event("CODE_NOBODY_KNOWS", "2026-10-08T15:02:00Z", "Vorgang abgeschlossen."),
        _event("DELIVERED_PARCELSHOP", "2026-10-08T13:50:00Z", WAITING),
    ]}]
    r = parse_hermes(data)
    assert r.status is ParcelStatus.DELIVERED
    assert r.delivered_at == datetime(2026, 10, 8, 15, 2, tzinfo=UTC)
