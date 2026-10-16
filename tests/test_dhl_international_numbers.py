"""v0.3.37 (issue #34): DHL mails about imports name a UPU S10 number of the sending
country ("LE…BE", "LW…NL"). Synthetic mails, invented numbers (9 and 0 only)."""

import re
from datetime import timedelta
from email import policy
from email.message import EmailMessage

import aiohttp
import pytest
from aioresponses import aioresponses
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.carriers.base import Match
from custom_components.parcel_tracker.carriers.dhl import DHL_URL, DhlCarrier
from custom_components.parcel_tracker.carriers.dpd import DpdCarrier
from custom_components.parcel_tracker.carriers.gls import GlsCarrier
from custom_components.parcel_tracker.carriers.hermes import HermesCarrier
from custom_components.parcel_tracker.carriers.ups import UpsCarrier
from custom_components.parcel_tracker.const import DOMAIN
from custom_components.parcel_tracker.coordinator import ParcelCoordinator
from custom_components.parcel_tracker.detect import candidates, normalize
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.mail.shipping import parse_dhl_mail
from custom_components.parcel_tracker.models import ParcelStatus
from custom_components.parcel_tracker.store import ParcelStore

from .conftest import DAYTIME

BELGIUM = "LE999999990BE"
NETHERLANDS = "LW999999990NL"
GERMANY = "CQ999999901DE"
DHL = re.compile(rf"^{re.escape(DHL_URL)}\?")
SENDERS = [
    "zustellung@dhl.de",
    "noreply@dhl.de",
    "paketankuendigung@dhl.de",
    "sendungsupdate@dhl.de",
]


def _msg(subject: str, body: str, from_: str) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = from_
    msg["Subject"] = subject
    msg["Date"] = "Wed, 30 Sep 2026 08:00:00 +0000"
    msg.set_content(body)
    return msg


def _today(number: str, sender: str = "zustellung@dhl.de") -> EmailMessage:
    body = (
        "Guten Tag,\n\nIhre Sendung kommt heute zwischen 13:10 - 14:40 Uhr.\n\n"
        f"Sendungsnummer: {number}\n"
    )
    return _msg("Ihre DHL Sendung kommt heute", body, f"DHL <{sender}>")


@pytest.mark.parametrize("number", [BELGIUM, NETHERLANDS])
@pytest.mark.parametrize("sender", SENDERS)
def test_dhl_mail_reads_the_s10_number_of_any_country(number, sender):
    [u] = parse_mail(_today(number, sender)).updates
    assert (u.number, u.carrier, u.status) == (number, "dhl", ParcelStatus.OUT_FOR_DELIVERY)
    assert (u.eta_from.hour, u.eta_from.minute) == (13, 10)


def test_german_s10_number_is_read_as_before():
    [u] = parse_mail(_today(GERMANY)).updates
    assert (u.number, u.carrier, u.status) == (GERMANY, "dhl", ParcelStatus.OUT_FOR_DELIVERY)


@pytest.mark.parametrize("number", [BELGIUM, NETHERLANDS])
def test_number_in_the_newer_layout_with_table_markup(number):
    body = (
        "<table><tr><td>Ihre Sendung kommt heute.</td></tr>"
        f"<tr><td>Sendungsnummer</td><td>{number}</td></tr></table>"
    )
    [u] = parse_dhl_mail(_msg("Ihre DHL Sendung kommt heute", body, "DHL <zustellung@dhl.de>"))
    assert (u.number, u.status) == (number, ParcelStatus.OUT_FOR_DELIVERY)


@pytest.mark.parametrize("number", [BELGIUM, NETHERLANDS])
def test_number_only_in_the_html_part(number):
    msg = _msg("Ihre DHL Sendung kommt heute", "", "DHL <zustellung@dhl.de>")
    msg.add_alternative(
        f"<html><body><p>Ihre Sendung kommt heute.</p><p>Sendungsnummer: {number}</p>"
        "</body></html>",
        subtype="html",
    )
    [u] = parse_dhl_mail(msg)
    assert (u.number, u.carrier) == (number, "dhl")


@pytest.mark.parametrize(
    "text",
    [
        "XLE999999990BE",  # glued to more letters or digits: no number of its own
        "LE999999990BEX",
        "9LE999999990BE",
        "le999999990be",  # lower case
        "LE99999999BE",  # eight digits
        "LE9999999990BE",  # ten digits
        "L999999990BE",  # one letter
        "LE999999990B",  # one letter at the end
        "LE999999990B3",
    ],
)
def test_nothing_else_is_taken_for_an_s10_number(text):
    assert parse_dhl_mail(_today(text)) == []


@pytest.mark.parametrize("number", [BELGIUM, NETHERLANDS])
@pytest.mark.parametrize(
    "sender", ["Shop <shop@example.org>", "DHL <noreply@notdhl.de>", "Post <info@example.be>"]
)
def test_s10_number_of_another_country_counts_only_in_mails_from_dhl(number, sender):
    body = f"Ihre Sendung {number} kommt heute."
    assert parse_mail(_msg("Ihre DHL Sendung kommt heute", body, sender)).updates == []


def test_national_number_still_wins_over_an_international_one():
    both = f"{BELGIUM}\n00340999999999999917"
    [u] = parse_dhl_mail(_msg("Ihre Sendung ist unterwegs", both, "DHL <noreply@dhl.de>"))
    assert u.number == "00340999999999999917"


# ----- "Automatisch" is unchanged: these numbers belong to other posts too -----
REAL = {
    "dhl": DhlCarrier, "dpd": DpdCarrier, "hermes": HermesCarrier, "gls": GlsCarrier,
    "ups": UpsCarrier,
}


@pytest.mark.parametrize(
    "number",
    [BELGIUM, NETHERLANDS, "RR999999990AT", "CP999999990CH", "LX999999990FR", "RR999999990US"],
)
def test_automatic_detection_takes_no_s10_number_of_another_country(number):
    """bpost, PostNL, Österreichische Post, Swiss Post …: no carrier's rule takes them, so
    "Automatisch" leaves them to the existing fallback (DHL asked once with a key)."""
    assert candidates(normalize(number), REAL) == []
    for carrier in REAL.values():
        assert carrier.matches(number) is Match.NO
    # "…DE" stays a sure DHL number
    assert candidates(GERMANY, REAL) == ["dhl"]


# ----- the parcel a DHL mail created is asked at DHL -----
@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as client:
        yield client


async def _coordinator(hass, carriers):
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    store = ParcelStore(hass)
    await store.async_load()
    return ParcelCoordinator(hass, entry, store, carriers)


def _answer(number: str) -> dict:
    status = {
        "timestamp": "2026-09-29T08:00:00+02:00",
        "statusCode": "transit",
        "status": "Die Sendung wurde im Start-Paketzentrum bearbeitet.",
    }
    return {"shipments": [{"id": number, "service": "parcel-de", "status": status}]}


@pytest.mark.parametrize("number", [BELGIUM, NETHERLANDS])
async def test_parcel_from_the_mail_is_tracked_with_the_dhl_key(hass, session, freezer, number):
    freezer.move_to(DAYTIME)
    coord = await _coordinator(hass, {"dhl": DhlCarrier(session, "key")})
    mail = _msg("Ihre DHL Sendung ist unterwegs", number, "DHL <noreply@dhl.de>")
    [update] = parse_mail(mail).updates
    assert apply_update(coord.store.parcels, update, dt_util.utcnow()).created
    parcel = coord.store.get(number)
    assert (parcel.carrier, parcel.carrier_mode, parcel.poll_target) == (
        "dhl", "mail", ("dhl", number)
    )
    with aioresponses() as m:
        m.get(DHL, payload=_answer(number), repeat=True)
        parcel.next_poll_at = dt_util.utcnow() - timedelta(seconds=1)
        await coord.async_refresh()
        queries = [dict(url.query) for (_, url), calls in m.requests.items() for _ in calls]
    assert {"trackingNumber": number, "language": "de"} in queries
    assert (parcel.status, parcel.last_error) == (ParcelStatus.IN_TRANSIT, None)
