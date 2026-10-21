"""Issue #36: the import duty is forgotten as soon as the parcel is delivered, however that
became known (the coordinator looks at every parcel once a minute)."""

from dataclasses import replace
from datetime import UTC, datetime

from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_mail
from .test_coordinator_mail import FakeMailbox, _coordinator

NOW = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)
NUMBER = "LE999999901BE"


async def _parcel_with_duty(hass):
    coord = await _coordinator(hass, FakeMailbox())
    [update] = parse_mail(load_mail("178_dhl_zustellung_kommt_heute_einfuhrabgaben.eml")).updates
    apply_update(coord.store.parcels, update, NOW)
    parcel = coord.store.parcels[NUMBER]
    assert parcel.customs_due == (12.34, "EUR", True)
    return coord, parcel


async def test_a_delivery_the_carrier_tells_deletes_the_duty(hass):
    coord, parcel = await _parcel_with_duty(hass)
    parcel.result = replace(parcel.result, status=ParcelStatus.DELIVERED)
    assert coord._cleanup(NOW) is True  # something changed: it is saved
    assert (parcel.customs_amount, parcel.customs_currency, parcel.customs_cash) == (
        None,
        None,
        False,
    )
    assert coord._cleanup(NOW) is False  # and nothing left to do the next minute


async def test_a_parcel_that_is_not_delivered_keeps_its_duty(hass):
    coord, parcel = await _parcel_with_duty(hass)
    assert coord._cleanup(NOW) is False
    assert parcel.customs_due == (12.34, "EUR", True)
