"""A carrier's number typed in stays changeable until a mail names it; review of #95."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.const import CONF_POSTCODE, DOMAIN
from custom_components.parcel_tracker.coordinator import _ParsedMail
from custom_components.parcel_tracker.mail.apply import (
    _fold,
    apply_update,
    link_tracking,
    unlink_tracking,
)
from custom_components.parcel_tracker.mail.base import MailResult, MailUpdate
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult

FETCH = "custom_components.parcel_tracker.carriers.dhl.DhlCarrier.fetch"
PARSE = "custom_components.parcel_tracker.coordinator._parse_mails"
NOW = datetime(2026, 11, 24, 8, 0, tzinfo=UTC)
ORDER = "AMZ99999999999999901"
OTHER_ORDER = "AMZ99999999999999902"
EBAY = "EBAY999999999901"
DHL = "00340999999999999901"
WRONG = "00340999999999999909"


def _result(status, text, day=None):
    return TrackingResult(status, text, day, None, None, None, None, None, None, [])


def _order(number=ORDER, carrier="amazon") -> Parcel:
    result = _result(ParcelStatus.IN_TRANSIT, "Versendet", NOW.date())
    return Parcel(number, carrier, "mail", "Beispielmarke Regal", NOW, NOW, result=result,
                  mail_title="Beispielmarke Regal")


def _typed_wrong(order: Parcel) -> None:
    """The order took a wrong number, and the carrier told about a stranger's parcel."""
    link_tracking({order.number: order}, order, WRONG, "dhl", NOW)
    order.result = _result(ParcelStatus.OUT_FOR_DELIVERY, "In Zustellung", NOW.date())
    order.carrier_status = ParcelStatus.OUT_FOR_DELIVERY
    order.last_poll_at = NOW
    order.last_error = "not_found"
    order.delivery_code, order.delivery_code_day = "1234", NOW.date()  # (by the shop's mail)
    order.track17, order.track17_carrier = True, 100001


# ----- the rule (mail.apply) -----
def test_a_number_typed_in_is_marked_and_the_result_before_is_kept():
    order = _order()
    before = order.result
    link_tracking({ORDER: order}, order, DHL, "dhl", NOW)
    assert order.tracking_manual is True and order.result_before_tracking is before
    # it is stored like the rest
    again = Parcel.from_dict(order.to_dict())
    assert again.tracking_manual is True
    assert again.result_before_tracking.to_dict() == before.to_dict()


def test_a_parcel_folded_in_is_no_number_typed_in():
    order = _order()
    parcel = Parcel(DHL, "dhl", "mail", None, NOW, NOW,
                    result=_result(ParcelStatus.IN_TRANSIT, "Unterwegs"))
    link_tracking({ORDER: order, DHL: parcel}, order, DHL, None, NOW)
    assert order.tracking_manual is False and order.result_before_tracking is None
    with pytest.raises(ValueError, match="has_tracking"):
        unlink_tracking(order)


def test_taking_the_number_away_brings_the_order_back_and_drops_the_carriers_answer():
    order = _order()
    before = order.result
    _typed_wrong(order)
    unlink_tracking(order)
    assert order.result is before and order.status is ParcelStatus.IN_TRANSIT
    assert (order.tracking_ref, order.tracking_carrier) == (None, None)
    assert order.tracking_manual is False
    assert order.carrier_status is None and order.last_poll_at is None
    assert order.last_error is None and order.active_code(NOW.date()) == "1234"
    assert order.track17 is False and order.track17_carrier is None
    assert order.poll_target is None  # a shop order without a number asks nobody


def test_an_order_closed_on_its_own_is_closed_again():
    order = _order()
    order.result = _result(ParcelStatus.DELIVERED, "Abgeschlossen")
    order.assumed_delivered = True
    link_tracking({ORDER: order}, order, WRONG, "dhl", NOW)
    order.result, order.assumed_delivered = _result(ParcelStatus.IN_TRANSIT, "Unterwegs"), False
    unlink_tracking(order)
    assert order.status is ParcelStatus.DELIVERED and order.assumed_delivered is True


def test_another_number_replaces_the_one_typed_in():
    order = _order()
    before = order.result
    _typed_wrong(order)
    link_tracking({ORDER: order}, order, DHL, "dhl", NOW)
    assert (order.tracking_ref, order.tracking_manual) == (DHL, True)
    assert order.result_before_tracking is before and order.result is before
    assert order.carrier_status is None and order.track17 is False


def test_a_number_typed_in_that_the_carrier_called_delivered_may_still_be_changed():
    order = _order()
    _typed_wrong(order)
    order.result = _result(ParcelStatus.DELIVERED, "Zugestellt")
    link_tracking({ORDER: order}, order, DHL, "dhl", NOW)
    assert order.tracking_ref == DHL and order.status is ParcelStatus.IN_TRANSIT


def test_an_order_marked_as_received_is_never_changed_again():
    order = _order()
    _typed_wrong(order)
    order.manual_delivered = True
    with pytest.raises(ValueError, match="already_delivered"):
        unlink_tracking(order)
    with pytest.raises(ValueError, match="already_delivered"):
        link_tracking({ORDER: order}, order, DHL, "dhl", NOW)
    assert order.tracking_ref == WRONG


def test_the_same_number_again_changes_nothing():
    order = _order()
    _typed_wrong(order)
    link_tracking({ORDER: order}, order, WRONG, "dhl", NOW)
    assert order.status is ParcelStatus.OUT_FOR_DELIVERY and order.carrier_status is not None


@pytest.mark.parametrize("typed_before", [False, True])
def test_another_orders_carrier_number_is_refused(typed_before):
    """Two orders never share a box without anybody asking (the error text says so)."""
    order, other = _order(), _order(OTHER_ORDER)
    other.tracking_ref, other.tracking_carrier = DHL, "dhl"
    parcels = {ORDER: order, OTHER_ORDER: other}
    if typed_before:
        _typed_wrong(order)
    with pytest.raises(ValueError, match="not_a_carrier_parcel"):
        link_tracking(parcels, order, DHL, "dhl", NOW)
    assert order.tracking_ref == (WRONG if typed_before else None)


def test_a_delivery_code_still_valid_goes_along_when_the_order_keeps_its_own():
    order = _order()
    parcel = Parcel(DHL, "dhl", "mail", None, NOW, NOW,
                    result=_result(ParcelStatus.OUT_FOR_DELIVERY, "In Zustellung"))
    parcel.delivery_code, parcel.delivery_code_day = "4711", NOW.date()
    link_tracking({ORDER: order, DHL: parcel}, order, DHL, None, NOW)
    assert order.active_code(NOW.date()) == "4711"
    # Without ``keep`` (a delivered parcel closes the order) nobody needs one.
    order, parcel = _order(), Parcel(DHL, "dhl", "mail", None, NOW, NOW)
    parcel.delivery_code, parcel.delivery_code_day = "4711", NOW.date()
    _fold({DHL: parcel}, parcel, order)
    assert order.delivery_code is None


# ----- mails -----
def _shop_mail(number, tracking_ref, carrier="ebay", at=None, status=ParcelStatus.IN_TRANSIT):
    return MailUpdate(number, carrier, status, at or NOW + timedelta(hours=1),
                      title="Beispielmarke Regal", tracking_ref=tracking_ref,
                      tracking_carrier="dhl" if tracking_ref else None)


def test_what_the_shop_told_after_the_typing_stays_when_the_number_goes():
    """Bestellt → a number typed in → "Versendet" and "Zugestellt" without a number →
    the number goes: the order is delivered, with both lines in its history."""
    order = _order()
    order.result = _result(ParcelStatus.PRE_TRANSIT, "Bestellt")
    parcels = {ORDER: order}
    _typed_wrong(order)
    for hours, status in ((1, ParcelStatus.IN_TRANSIT), (2, ParcelStatus.DELIVERED)):
        at = NOW + timedelta(hours=hours)
        apply_update(parcels, _shop_mail(ORDER, None, "amazon", at, status), at)
    assert order.tracking_ref == WRONG  # (the number is still there)
    # The shop's word made it delivered: the number is not changed any more ...
    with pytest.raises(ValueError, match="already_delivered"):
        link_tracking(parcels, order, DHL, "dhl", NOW)
    # ... but taken away it may be, and nothing the shop told is lost.
    unlink_tracking(order)
    assert order.status is ParcelStatus.DELIVERED and order.assumed_delivered is False
    assert order.result.delivered_at == NOW + timedelta(hours=2)
    assert [e.timestamp for e in order.result.events] == [
        NOW + timedelta(hours=2), NOW + timedelta(hours=1)
    ]
    assert order.active_code(NOW.date()) is None  # (delivered: no code any more)


def test_an_order_closed_by_the_shops_late_word_is_closed_on_its_own_again():
    """The shop's "delivered" days later (a confirmation) closes the order as one without
    a delivery mail: without the number it is that again."""
    order = _order()
    parcels = {ORDER: order}
    _typed_wrong(order)
    at = NOW + timedelta(days=30)
    mail = _shop_mail(ORDER, None, "amazon", at, ParcelStatus.DELIVERED)
    apply_update(parcels, replace(mail, confirmation=True), at)
    unlink_tracking(order)
    assert order.status is ParcelStatus.DELIVERED and order.assumed_delivered is True


def test_a_shop_mail_naming_the_number_confirms_it():
    order = _order(EBAY, "ebay")
    parcels = {EBAY: order}
    link_tracking(parcels, order, DHL, "dhl", NOW)
    apply_update(parcels, _shop_mail(EBAY, DHL), NOW)
    assert order.tracking_ref == DHL and order.tracking_manual is False
    with pytest.raises(ValueError, match="has_tracking"):
        unlink_tracking(order)


def test_a_shop_mail_naming_another_number_replaces_the_one_typed_in():
    order = _order(EBAY, "ebay")
    parcels = {EBAY: order}
    _typed_wrong(order)
    apply_update(parcels, _shop_mail(EBAY, DHL), NOW)
    assert (order.tracking_ref, order.tracking_manual) == (DHL, False)
    assert order.carrier_status is None and order.track17 is False


def test_a_shop_mail_older_than_the_typing_does_not_replace_the_number():
    """An earlier mail read late: the user typed in what they knew after it."""
    order = _order(EBAY, "ebay")
    parcels = {EBAY: order}
    link_tracking(parcels, order, DHL, "dhl", NOW)
    apply_update(parcels, _shop_mail(EBAY, WRONG, at=NOW - timedelta(hours=1)), NOW)
    assert (order.tracking_ref, order.tracking_manual) == (DHL, True)


def test_a_carriers_mail_about_the_number_confirms_it():
    order = _order()
    parcels = {ORDER: order}
    link_tracking(parcels, order, DHL, "dhl", NOW)
    mail = MailUpdate(DHL, "dhl", ParcelStatus.IN_TRANSIT, NOW + timedelta(hours=1))
    apply_update(parcels, mail, NOW)
    assert list(parcels) == [ORDER] and order.tracking_manual is False


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


@pytest.mark.parametrize("typed", ["hallo 123", "ABC"])
async def test_a_number_no_carrier_knows_is_refused(hass, entry, typed):
    coord = entry.runtime_data
    coord.store.add(_order())
    with patch(FETCH) as fetch, pytest.raises(ServiceValidationError) as err:
        await _call(hass, number=ORDER, tracking_number=typed)
    assert err.value.translation_key == "no_carrier"
    assert fetch.call_count == 0 and coord.store.get(ORDER).tracking_ref is None


async def test_with_a_carrier_chosen_the_number_is_taken(hass, entry):
    coord = entry.runtime_data
    coord.store.add(_order())
    with patch(FETCH, return_value=_result(ParcelStatus.IN_TRANSIT, "Unterwegs")):
        await _call(hass, number=ORDER, tracking_number="ABC", carrier="dhl")
    assert coord.store.get(ORDER).tracking_ref == "ABC"


async def test_a_wrong_number_is_changed_and_taken_away_again(hass, entry):
    coord = entry.runtime_data
    coord.store.add(_order())
    stranger = _result(ParcelStatus.OUT_FOR_DELIVERY, "In Zustellung", date(2026, 11, 24))
    with patch(FETCH, return_value=stranger):
        await _call(hass, number=ORDER, tracking_number=WRONG)
    order = coord.store.get(ORDER)
    assert order.status is ParcelStatus.OUT_FOR_DELIVERY
    with patch(FETCH, return_value=_result(ParcelStatus.IN_TRANSIT, "Unterwegs")) as fetch:
        await _call(hass, number=ORDER, tracking_number=DHL)
    assert fetch.call_args.args[0] == DHL  # the right number is asked about at once
    assert (order.tracking_ref, order.tracking_manual) == (DHL, True)
    assert order.result.status_text == "Unterwegs"
    with patch(FETCH) as fetch:
        await _call(hass, number=ORDER, tracking_number="")
    assert fetch.call_count == 0
    assert order.tracking_ref is None and order.result.status_text == "Versendet"
    # (and with nothing typed in, nothing happens)
    await _call(hass, number=ORDER)
    assert order.tracking_ref is None


async def test_a_number_a_mail_named_is_not_taken_away(hass, entry):
    coord = entry.runtime_data
    order = _order()
    order.tracking_ref, order.tracking_carrier = DHL, "dhl"
    coord.store.add(order)
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, number=ORDER, tracking_number="")
    assert err.value.translation_key == "has_tracking" and order.tracking_ref == DHL


async def test_the_orders_own_number_is_told_as_such_also_with_automatisch(hass, entry):
    coord = entry.runtime_data
    coord.store.add(_order())
    with pytest.raises(ServiceValidationError) as err:
        await _call(hass, number=ORDER, tracking_number="999-9999999-9999901")
    assert err.value.translation_key == "own_number"


def _carrier_parcel(gift=False) -> Parcel:
    parcel = Parcel(DHL, "dhl", "mail", None, NOW, NOW,
                    result=_result(ParcelStatus.IN_TRANSIT, "Unterwegs"))
    parcel.gift = gift
    return parcel


async def test_another_persons_parcel_is_never_folded_in(hass, entry):
    coord = entry.runtime_data
    coord.store.add(_order())
    coord.store.add(_carrier_parcel())
    owners = {ORDER: "person.anna", DHL: "person.ben"}
    with patch.object(coord, "effective_owner", side_effect=lambda p: owners[p.number]):
        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, number=ORDER, tracking_number=DHL)
        assert err.value.translation_key == "other_owner"
        assert coord.store.get(DHL) is not None
        # A parcel for everybody may be.
        owners[DHL] = None
        await _call(hass, number=ORDER, tracking_number=DHL)
    assert coord.store.get(DHL) is None and coord.store.get(ORDER).tracking_ref == DHL


async def test_a_hidden_gift_is_refused_without_telling_it_is_one(hass, entry):
    coord = entry.runtime_data
    coord.store.add(_order())
    coord.store.add(_carrier_parcel(gift=True))
    with patch.object(coord, "_may_change_gift", side_effect=lambda p, _user: not p.gift):
        with pytest.raises(ServiceValidationError) as err:
            await _call(hass, number=ORDER, tracking_number=DHL)
    assert err.value.translation_key == "other_owner"
    assert coord.store.get(DHL).gift is True and coord.store.get(ORDER).tracking_ref is None


async def test_a_shop_mail_replacing_the_number_forgets_what_the_number_told(hass, entry):
    coord = entry.runtime_data
    coord.store.add(_order(EBAY, "ebay"))
    stranger = _result(ParcelStatus.OUT_FOR_DELIVERY, "In Zustellung", date(2026, 11, 24))
    with patch(FETCH, return_value=stranger):
        await _call(hass, number=EBAY, tracking_number=WRONG)
    order = coord.store.get(EBAY)
    # What the wrong number told: a change waiting, a status remembered as announced.
    order.unannounced_from = ParcelStatus.IN_TRANSIT
    coord._announced[EBAY] = ParcelStatus.OUT_FOR_DELIVERY
    mail = _shop_mail(EBAY, DHL, at=dt_util.utcnow() + timedelta(minutes=1))
    parsed = [_ParsedMail(message_id="<r@synthetic.example>", result=MailResult([mail]))]
    with patch(PARSE, return_value=parsed), patch(FETCH, return_value=stranger):
        await coord.async_import_raw_mail(b"synthetic")
    assert (order.tracking_ref, order.tracking_manual) == (DHL, False)
    assert order.unannounced_from is None and EBAY not in coord._announced
