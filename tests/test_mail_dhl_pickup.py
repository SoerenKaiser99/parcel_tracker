"""DHL's pickup mails name the branch the parcel waits at ("Adresse der Filiale:").

Its name and street become the pickup point, like the place of Amazon's pickup mail.
"""

from datetime import timedelta
from email import policy
from email.parser import BytesParser

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.carriers.base import Carrier, Match
from custom_components.parcel_tracker.const import DOMAIN
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.base import sent_at
from custom_components.parcel_tracker.models import ParcelStatus, TrackingResult
from custom_components.parcel_tracker.notification import build_notification
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import FIXTURES, load_mail

CURRENT = "178_dhl_sendung_ist_in_der_filiale_abholbereit.eml"
OLDER = "179_dhl_paket_ist_ab_sofort_abholbereit.eml"
NUMBER = "00340999999999990178"
PLACE = "Postfiliale 999, Beispielweg 12"


def _variant(name: str, *swaps: tuple[str, str]):
    """The fixture with parts of its text replaced."""
    text = (FIXTURES / "mail" / name).read_text(encoding="utf-8")
    for old, new in swaps:
        assert old in text, old
        text = text.replace(old, new)
    return BytesParser(policy=policy.default).parsebytes(text.encode("utf-8"))


# ----- what the mail tells -----
def test_pickup_mail_names_the_branch_and_its_street():
    [u] = parse_mail(load_mail(CURRENT)).updates
    assert (u.number, u.carrier) == (NUMBER, "dhl")
    assert (u.status, u.pickup_point, u.pickup_until) == (
        ParcelStatus.AWAITING_PICKUP, PLACE, None,
    )


def test_older_layout_names_the_branch_in_its_html_part():
    # The text part is a calendar entry; the place is read from the HTML part.
    [u] = parse_mail(load_mail(OLDER)).updates
    assert (u.number, u.status) == ("00340999999999990179", ParcelStatus.AWAITING_PICKUP)
    assert u.pickup_point == "Filiale 999 (Postbank Filiale), Beispielweg 12"


def test_reminder_and_packstation_name_the_place_too():
    msg = _variant(
        CURRENT,
        ("ist in der Filiale abholbereit", "liegt seit 2 Tagen in der Filiale"),
        ("Postfiliale 999", "Packstation 123"),
    )
    [u] = parse_mail(msg).updates
    assert (u.status, u.pickup_point) == (
        ParcelStatus.AWAITING_PICKUP, "Packstation 123, Beispielweg 12",
    )


def test_no_postcode_town_or_person_becomes_the_place():
    [u] = parse_mail(load_mail(CURRENT)).updates
    assert "12345" not in u.pickup_point and "Musterstadt" not in u.pickup_point
    # An address block that does not start with a place of DHL's is never read.
    [u] = parse_mail(_variant(CURRENT, ("Postfiliale 999", "Max Mustermann"))).updates
    assert (u.status, u.pickup_point) == (ParcelStatus.AWAITING_PICKUP, None)
    # (nor one without a street that has a number)
    [u] = parse_mail(_variant(CURRENT, ("Beispielweg 12", "Beispielweg"))).updates
    assert u.pickup_point is None


def test_only_a_parcel_ready_for_pickup_has_a_pickup_point():
    # "auf dem Weg in eine Filiale" names the branch too, but the parcel is not there yet.
    msg = _variant(CURRENT, ("ist in der Filiale abholbereit", "ist auf dem Weg in eine Filiale"))
    [u] = parse_mail(msg).updates
    assert (u.status, u.pickup_point) == (ParcelStatus.IN_TRANSIT, None)


# ----- on the parcel and in the notification -----
def test_parcel_shows_the_branch_and_the_notification_names_it():
    parcels: dict = {}
    msg = load_mail(CURRENT)
    [update] = parse_mail(msg).updates
    apply_update(parcels, update, sent_at(msg))
    parcel = parcels[NUMBER]
    assert (parcel.status, parcel.result.pickup_point) == (ParcelStatus.AWAITING_PICKUP, PLACE)
    _, message = build_notification(parcel, ParcelStatus.IN_TRANSIT, sent_at(msg))
    assert message == f"📍 Paket …0178 (DHL) liegt zur Abholung bereit – {PLACE}"


# ----- DHL's lookup after the mail -----
class _Dhl(Carrier):
    key = "dhl"
    name = "DHL"

    def __init__(self, answer: TrackingResult):
        self.answer = answer

    @staticmethod
    def matches(number):
        return Match.SURE

    async def fetch(self, number, postcode):
        return self.answer


def _answer(status: ParcelStatus, place: str | None) -> TrackingResult:
    return TrackingResult(
        status, "Die Sendung liegt in der Filiale zur Abholung bereit.",
        None, None, None, place, place, None, None,
    )


async def _polled(hass, freezer, answer: TrackingResult):
    msg = load_mail(CURRENT)
    freezer.move_to(sent_at(msg) + timedelta(minutes=5))
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    [update] = parse_mail(msg).updates
    apply_update(store.parcels, update, sent_at(msg))
    store.parcels[NUMBER].next_poll_at = None
    coord = ParcelCoordinator(hass, entry, store, {"dhl": _Dhl(answer)})
    await coord.async_refresh()
    await hass.async_block_till_done()
    return store.parcels[NUMBER]


async def test_the_branch_of_the_mail_stays_over_dhls_town(hass, freezer):
    parcel = await _polled(hass, freezer, _answer(ParcelStatus.AWAITING_PICKUP, "Musterstadt"))
    assert parcel.status is ParcelStatus.AWAITING_PICKUP
    assert parcel.result.status_text.startswith("Die Sendung liegt in der Filiale")
    assert parcel.result.pickup_point == PLACE


async def test_dhls_delivery_drops_the_branch(hass, freezer):
    parcel = await _polled(hass, freezer, _answer(ParcelStatus.DELIVERED, None))
    assert (parcel.status, parcel.result.pickup_point) == (ParcelStatus.DELIVERED, None)
