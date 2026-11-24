"""A shop order gets the carrier's number typed in ("Sendungsnummer eintragen")."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.parcel_tracker.const import CONF_POSTCODE, DOMAIN, EVENT_STATUS_CHANGED
from custom_components.parcel_tracker.mail.apply import link_tracking
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
NOW = datetime(2026, 11, 24, 8, 0, tzinfo=UTC)
ORDER = "AMZ99999999999999901"
OTHER_ORDER = "AMZ99999999999999902"
DHL = "00340999999999999901"


def _result(status, text, day=None):
    return TrackingResult(status, text, day, None, None, None, None, None, None, [])


def _order(number=ORDER, status=ParcelStatus.IN_TRANSIT) -> Parcel:
    result = _result(status, "Versendet", NOW.date())
    return Parcel(number, "amazon", "mail", "Beispielmarke Regal", NOW, NOW, result=result,
                  mail_title="Beispielmarke Regal")


def _carrier_parcel(mode="mail", **fields) -> Parcel:
    result = _result(ParcelStatus.OUT_FOR_DELIVERY, "In Zustellung", NOW.date())
    return Parcel(DHL, "dhl", mode, "Beispielmarke GmbH", NOW, NOW, result=result, **fields)


# ----- the rule itself (mail.apply.link_tracking) -----
def test_a_new_number_is_kept_and_asked_about():
    order = _order()
    parcels = {ORDER: order}
    assert link_tracking(parcels, order, DHL, "dhl") is None
    assert (order.tracking_ref, order.tracking_carrier) == (DHL, "dhl")
    assert order.poll_target == ("dhl", DHL)
    assert order.next_poll_at is None
    assert list(parcels) == [ORDER]


@pytest.mark.parametrize("mode", ["mail", "auto", "manual"])
def test_a_parcel_tracked_under_the_number_is_folded_into_the_order(mode):
    """Also one added by hand: the user joins them on purpose."""
    order, parcel = _order(), _carrier_parcel(mode)
    parcels = {ORDER: order, DHL: parcel}
    assert link_tracking(parcels, order, DHL, None) is parcel
    assert list(parcels) == [ORDER]
    assert (order.tracking_ref, order.tracking_carrier) == (DHL, "dhl")
    assert order.status is ParcelStatus.OUT_FOR_DELIVERY
    assert order.name == "Beispielmarke Regal"  # the order's name stays


def test_a_name_typed_in_on_the_parcel_goes_along():
    order, parcel = _order(), _carrier_parcel(name_manual=True)
    parcel.name = "Regal für den Keller"
    link_tracking({ORDER: order, DHL: parcel}, order, DHL, None)
    assert order.name == "Regal für den Keller"


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (lambda p: setattr(p[DHL], "carrier", "dhl"), "not_an_order"),
        (lambda p: setattr(p[ORDER], "tracking_ref", "00340999999999999902"), "has_tracking"),
        (lambda p: setattr(p[ORDER], "result", _result(ParcelStatus.CANCELLED, "Storniert")),
         "cancelled"),
    ],
)
def test_what_cannot_take_a_number(make, reason):
    parcels = {ORDER: _order(), DHL: _carrier_parcel()}
    make(parcels)
    target = parcels[DHL] if reason == "not_an_order" else parcels[ORDER]
    with pytest.raises(ValueError, match=reason):
        link_tracking(parcels, target, "00340999999999999903", None)
    assert len(parcels) == 2


@pytest.mark.parametrize(
    ("change", "refused"),
    [
        ({"result": _result(ParcelStatus.DELIVERED, "Zugestellt")}, True),
        ({"result": _result(ParcelStatus.DELIVERED, "Erhalten"), "manual_delivered": True}, True),
        # closed without a delivery mail: nobody knows it came, the carrier may tell
        ({"result": _result(ParcelStatus.DELIVERED, "Abgeschlossen"), "assumed_delivered": True},
         False),
    ],
)
def test_a_delivered_order_keeps_its_status(change, refused):
    order, parcel = _order(), _carrier_parcel()
    for key, value in change.items():
        setattr(order, key, value)
    parcels = {ORDER: order, DHL: parcel}
    if refused:
        with pytest.raises(ValueError, match="already_delivered"):
            link_tracking(parcels, order, DHL, None)
        assert DHL in parcels and order.status is ParcelStatus.DELIVERED
    else:
        assert link_tracking(parcels, order, DHL, None) is parcel
        assert order.status is ParcelStatus.OUT_FOR_DELIVERY and not order.assumed_delivered


@pytest.mark.parametrize(
    ("kind", "reason"),
    [("order", "not_a_carrier_parcel"), ("outgoing", "not_a_carrier_parcel"),
     ("own", "own_number")],
)
def test_a_number_that_is_no_carriers_parcel_is_refused(kind, reason):
    order = _order()
    parcels = {ORDER: order}
    number = {"order": OTHER_ORDER, "outgoing": DHL, "own": ORDER}[kind]
    if kind == "order":
        parcels[OTHER_ORDER] = _order(OTHER_ORDER)
    if kind == "outgoing":
        parcels[DHL] = _carrier_parcel(outgoing=True)
    with pytest.raises(ValueError, match=reason):
        link_tracking(parcels, order, number, None)
    assert order.tracking_ref is None and ORDER in parcels


@pytest.mark.parametrize(
    ("number", "typed"),
    [
        (ORDER, "99999999999999901"),  # Amazon's order number as the card shows it
        (f"{ORDER}P2", "99999999999999901"),  # a further shipment of the same order
        ("EBAY999999999999", "999999999999"),
        ("ALI9999999999999999", "9999999999999999"),
    ],
)
def test_the_order_number_as_shown_is_refused_as_well(number, typed):
    order = Parcel(number, "amazon" if number.startswith("AMZ") else "ebay", "mail", None,
                   NOW, NOW, result=_result(ParcelStatus.IN_TRANSIT, "Versendet"))
    if number.startswith("ALI"):
        order.carrier = "aliexpress"
    with pytest.raises(ValueError, match="own_number"):
        link_tracking({number: order}, order, typed, None)
    assert order.tracking_ref is None


def test_a_parcel_marked_as_received_stays_so_in_the_order():
    order, parcel = _order(), _carrier_parcel()
    parcel.result = _result(ParcelStatus.DELIVERED, "Erhalten (von Hand markiert)")
    parcel.manual_delivered = True
    link_tracking({ORDER: order, DHL: parcel}, order, DHL, None)
    assert order.status is ParcelStatus.DELIVERED and order.manual_delivered is True


@pytest.mark.parametrize(("chosen", "kept"), [("dhl", "dhl"), (None, None)])
def test_a_parcel_followed_through_17track_only_gets_a_carrier_to_ask(chosen, kept):
    """"Andere (über 17track)" is no carrier: the order would ask nobody every hour."""
    order, parcel = _order(), _carrier_parcel()
    parcel.carrier, parcel.track17 = "other", True
    link_tracking({ORDER: order, DHL: parcel}, order, DHL, chosen)
    assert order.tracking_carrier == kept and order.track17 is True


# ----- the service -----
@pytest.fixture
async def entry(hass):
    e = MockConfigEntry(domain=DOMAIN, data={CONF_POSTCODE: "10115", "dhl_api_key": "k"})
    e.add_to_hass(hass)
    with patch(FETCH, return_value=_result(ParcelStatus.IN_TRANSIT, "x")):
        assert await hass.config_entries.async_setup(e.entry_id)
        await hass.async_block_till_done()
    return e


async def _call(hass, **data):
    await hass.services.async_call(DOMAIN, "set_tracking_number", data, blocking=True)


async def test_service_gives_the_order_a_new_number_and_asks_dhl(hass, entry):
    coord = entry.runtime_data
    coord.store.add(_order())
    answer = _result(ParcelStatus.OUT_FOR_DELIVERY, "In Zustellung", NOW.date())
    with patch(FETCH, return_value=answer) as fetch:
        await _call(hass, number=ORDER, tracking_number="0034 0999 9999 9999 9901")
    order = coord.store.get(ORDER)
    assert (order.tracking_ref, order.tracking_carrier) == (DHL, "dhl")
    assert fetch.call_count == 1
    assert order.status is ParcelStatus.OUT_FOR_DELIVERY
    assert coord.store.get(DHL) is None


async def test_service_folds_the_parcel_of_its_own(hass, entry):
    coord = entry.runtime_data
    coord.store.add(_order())
    coord.store.add(_carrier_parcel())
    with patch(FETCH) as fetch:
        await _call(hass, number=ORDER, tracking_number=DHL)
    assert fetch.call_count == 0  # the parcel's result goes along, nothing to ask now
    order = coord.store.get(ORDER)
    assert order.tracking_ref == DHL and coord.store.get(DHL) is None
    assert order.status is ParcelStatus.OUT_FOR_DELIVERY


@pytest.mark.parametrize(
    ("data", "key"),
    [
        ({"number": "AMZ99999999999999909", "tracking_number": DHL}, "not_tracked"),
        ({"number": ORDER, "tracking_number": "TBA999999999999"}, "amazon"),
        ({"number": DHL, "tracking_number": "00340999999999999903"}, "not_an_order"),
        ({"number": OTHER_ORDER, "tracking_number": DHL}, "has_tracking"),
        ({"number": ORDER, "tracking_number": OTHER_ORDER}, "not_a_carrier_parcel"),
    ],
)
async def test_service_refusals(hass, entry, data, key):
    coord = entry.runtime_data
    coord.store.add(_order())
    tracked = _order(OTHER_ORDER)
    tracked.tracking_ref, tracked.tracking_carrier = "00340999999999999902", "dhl"
    coord.store.add(tracked)
    coord.store.add(_carrier_parcel())
    with patch(FETCH) as fetch, pytest.raises(ServiceValidationError) as err:
        await _call(hass, **data)
    assert err.value.translation_key == key
    assert fetch.call_count == 0
    assert coord.store.get(ORDER).tracking_ref is None


# ----- second review: told once, UPS and GLS as when adding, gifts -----
async def test_a_new_number_tells_the_carriers_answer_once(hass, entry):
    coord = entry.runtime_data
    coord._start_announcing()
    coord.store.add(_order())
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    answer = _result(ParcelStatus.OUT_FOR_DELIVERY, "In Zustellung", NOW.date())
    with patch(FETCH, return_value=answer):
        await _call(hass, number=ORDER, tracking_number=DHL)
    await hass.async_block_till_done()
    assert [(e.data["old_status"], e.data["new_status"]) for e in events] == [
        ("in_transit", "out_for_delivery")
    ]


async def test_folding_tells_nothing_the_parcel_told_already(hass, entry):
    coord = entry.runtime_data
    coord._start_announcing()
    coord.store.add(_order())
    delivered = _carrier_parcel()
    delivered.result = _result(ParcelStatus.DELIVERED, "Zugestellt")
    delivered.delivery_announced = True
    coord.store.add(delivered)
    events = async_capture_events(hass, EVENT_STATUS_CHANGED)
    await _call(hass, number=ORDER, tracking_number=DHL)
    await hass.async_block_till_done()
    order = coord.store.get(ORDER)
    assert order.status is ParcelStatus.DELIVERED and order.delivery_announced is True
    assert events == []


async def test_folding_hands_over_a_change_still_waiting_to_be_told(hass, entry):
    coord = entry.runtime_data
    coord.store.add(_order())
    waiting = _carrier_parcel()
    waiting.unannounced_from = ParcelStatus.IN_TRANSIT
    coord.store.add(waiting)
    await _call(hass, number=ORDER, tracking_number=DHL)
    assert coord.store.get(ORDER).unannounced_from is ParcelStatus.IN_TRANSIT


async def test_a_ups_number_without_the_api_is_known_as_ups(hass, entry):
    coord = entry.runtime_data
    coord.store.add(_order())
    with patch(FETCH) as fetch:
        await _call(hass, number=ORDER, tracking_number="1Z999AA10123456784")
    order = coord.store.get(ORDER)
    assert (order.tracking_carrier, order.last_error) == ("ups", "missing_key")
    assert fetch.call_count == 0


async def test_a_gls_parcel_is_found_under_the_other_form_of_its_number(hass, entry):
    coord = entry.runtime_data
    coord.store.add(_order())
    result = _result(ParcelStatus.IN_TRANSIT, "Unterwegs", NOW.date())
    coord.store.add(Parcel("99999999901", "gls", "mail", None, NOW, NOW, result=result))
    with patch(FETCH) as fetch:
        await _call(hass, number=ORDER, tracking_number="999999999017")
    order = coord.store.get(ORDER)
    assert (order.tracking_ref, order.tracking_carrier) == ("99999999901", "gls")
    assert coord.store.get("99999999901") is None and fetch.call_count == 0


async def test_a_gift_is_changed_only_by_someone_who_may_see_it(hass, entry):
    coord = entry.runtime_data
    gift = _order()
    gift.gift = True
    coord.store.add(gift)
    with patch.object(coord, "_may_change_gift", return_value=False), pytest.raises(
        HomeAssistantError
    ) as err:
        await _call(hass, number=ORDER, tracking_number=DHL)
    assert err.value.translation_key == "gift_tracking_not_allowed"
    assert coord.store.get(ORDER).tracking_ref is None


# ----- third look: GLS only for GLS, a change waiting on the order -----
async def test_another_carriers_twelve_digits_never_take_a_gls_parcel(hass, entry):
    coord = entry.runtime_data
    coord.store.add(_order())
    result = _result(ParcelStatus.IN_TRANSIT, "Unterwegs", NOW.date())
    coord.store.add(Parcel("99999999901", "gls", "mail", None, NOW, NOW, result=result))
    with patch(FETCH, return_value=result):
        await _call(hass, number=ORDER, tracking_number="999999999017", carrier="dhl")
    order = coord.store.get(ORDER)
    assert (order.tracking_ref, order.tracking_carrier) == ("999999999017", "dhl")
    assert coord.store.get("99999999901") is not None


async def test_what_the_parcel_told_already_is_not_told_again_for_the_order(hass, entry):
    """Before Home Assistant has started (no announcing yet): the order's own change
    waiting to be told is over, the parcel told the newer status already."""
    coord = entry.runtime_data
    order = _order()
    order.unannounced_from = ParcelStatus.PRE_TRANSIT
    coord.store.add(order)
    coord.store.add(_carrier_parcel())
    await _call(hass, number=ORDER, tracking_number=DHL)
    assert coord.store.get(ORDER).unannounced_from is None
