"""v0.3.30: Eventim ticket orders that come by post, from mails."""

from datetime import UTC, date, datetime, timedelta
from email import policy
from email.message import EmailMessage

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.const import (
    CARRIER_NAMES,
    CONF_HIDE_NAMES,
    DOMAIN,
    MAIL_CARRIERS,
    ORDER_NO_ETA_DAYS,
    ORDER_OVERDUE_DAYS,
    SHIP_LATER_SHOPS,
    SHOP_CARRIERS,
    SINGLE_PARCEL_SHOPS,
    STALE_REMOVE_DAYS,
)
from custom_components.parcel_tracker.coordinator import _parse_one, _ParsedMail
from custom_components.parcel_tracker.diagnostics import async_get_config_entry_diagnostics
from custom_components.parcel_tracker.links import tracking_url
from custom_components.parcel_tracker.mail import (
    KNOWN_MAIL_DOMAINS,
    forwarded_original,
    is_ignored,
    known_sender_domain,
    parse_mail,
)
from custom_components.parcel_tracker.mail.apply import ASSUMED_TEXT, MANUAL_TEXT, apply_update
from custom_components.parcel_tracker.mail.base import add_workdays, sender
from custom_components.parcel_tracker.mail.eventim import (
    EVENTIM_SENDER,
    is_postal,
    order_number,
    parse_eventim,
)
from custom_components.parcel_tracker.models import (
    Parcel,
    ParcelStatus,
    carrier_name,
    neutral_name,
)
from custom_components.parcel_tracker.notification import build_notification
from custom_components.parcel_tracker.schedule import order_overdue, should_remove, summarize

from .conftest import load_mail
from .test_coordinator_notify import _start
from .test_order_closing import _coordinator, _prepared, _refresh

ORDER_MAIL = "146_eventim_deine_bestellung.eml"
ORDER_MORE = "147_eventim_deine_bestellung.eml"
ORDER_DIGITAL = "148_eventim_deine_bestellung.eml"
SHIPPED = "149_eventim_versandbenachrichtigung_deine_be.eml"
TICKET_ALARM = "150_eventim_ticketalarm.eml"
CLUB_SHOP = "151_eventim_kundenservice_musterverein.eml"

ORDER = "EVT999999901"
ORDER_OF_TWO = "EVT9999999902"
EVENT = "Beispielband – Tour 2026"
ORDERED = datetime(2026, 1, 5, 10, 0, tzinfo=BERLIN)  # a Monday
SENT = datetime(2026, 1, 8, 10, 0, tzinfo=BERLIN)  # the Thursday after
FIRST, LAST = date(2026, 1, 10), date(2026, 1, 13)  # 2 and 4 working days later


def _update(name: str):
    result = parse_mail(load_mail(name))
    assert not result.ignored and not result.amazon
    (update,) = result.updates
    return update


def _mail(subject: str, text: str, address: str = EVENTIM_SENDER, html: bool = False,
          when: str = "Thu, 08 Jan 2026 10:00:00 +0100") -> EmailMessage:
    """An invented mail (the fixtures show the layout; variations of it are built here)."""
    msg = EmailMessage(policy=policy.default)
    msg["From"] = f"EVENTIM <{address}>"
    msg["To"] = "max@example.org"
    msg["Subject"] = subject
    msg["Date"] = when
    if html:
        rows = "".join(f"<tr><td>{line}</td></tr>" for line in text.splitlines())
        msg.set_content(f"<html><body><table>{rows}</table></body></html>", subtype="html")
    else:
        msg.set_content(text)
    return msg


def _order_subject(event: str = EVENT, number: str = "999999901") -> str:
    return f"Deine EVENTIM-Bestellung: {event} - Bestellnummer {number}"


def _order_text(method: str = "Liefermethode: Standardversand (Deutschland)") -> str:
    return (
        "BESTELLBESTÄTIGUNG\nHallo Max,\nDEINE BESTELLUNG\nBestellnummer: 999999901\n"
        f"Bestelldatum: 05.01.2026\n{method}\nZahlungsart: Rechnung\n"
        f"EINZELHEITEN DEINER BESTELLUNG\n{EVENT}\nDatum: Sa., 05.12.2026, 20:00\n"
    )


SHIPPED_SUBJECT = "eventim.de - Versandbenachrichtigung - Deine Bestellung Nr. 999999901"


def _shipped_text(arrival: str = "innerhalb von 2 bis 4 Werktagen", events: int = 1,
                  method: str | None = "Liefermethode: Standardversand (Deutschland)") -> str:
    names = [EVENT, "Musterfestival 2026 – Wochenendticket", "Beispielorchester"][:events]
    details = "".join(
        f"{name}\nDatum: Sa., 05.12.2026, 20:00\nOrt: Musterhalle, Musterstadt\n"
        "Veranstalter: Beispiel Konzert GmbH, Musterstadt\n"
        for name in names
    )
    return (
        "VERSANDBENACHRICHTIGUNG\nHallo Max,\n"
        "wir haben heute deine Bestellung Nr. 999999901 versandt.\n"
        "Lieferadresse:\nMax Mustermann\nMusterstraße 1\n12345 Musterstadt\nDeutschland\n"
        + (f"{method}\n" if method else "")
        + f"Voraussichtliche Ankunft: Die Zustellung der Tickets erfolgt {arrival}. In "
        "Ausnahmefällen kann es zu Verzögerungen kommen.\n"
        f"EINZELHEITEN DEINER BESTELLUNG\n{details}HINWEISE\n"
    )


# ----- the two mails -----
def test_order_mail_with_postal_delivery_is_an_order_without_a_day():
    update = _update(ORDER_MAIL)
    assert (update.number, update.carrier) == (ORDER, "eventim")
    assert update.status is ParcelStatus.PRE_TRANSIT
    assert update.title == EVENT
    assert update.sent_at == ORDERED
    # "spätestens innerhalb von 2 bis 4 Werktagen" counts from the order, and tickets often
    # leave weeks later: no estimate from the order mail.
    assert "innerhalb von 2 bis 4 Werktagen" in load_mail(ORDER_MAIL).get_content()
    assert (update.eta_date, update.eta_latest, update.eta_from, update.eta_to) == (None,) * 4
    assert (update.tracking_ref, update.tracking_carrier, update.shop) == (None, None, None)
    assert update.status_text is None and update.delivery_code is None


def test_order_of_several_events_is_one_order_named_like_the_subject():
    update = _update(ORDER_MORE)
    assert (update.number, update.status) == (ORDER_OF_TWO, ParcelStatus.PRE_TRANSIT)
    assert update.title == "Beispielorchester – Neujahrskonzert und 1 mehr"
    assert update.eta_date is None


def test_a_long_event_name_is_cut_and_keeps_the_count():
    long = "Beispielband mit einem sehr langen Namen – Die große Jubiläumstour 2026 und 3 mehr"
    (update,) = parse_eventim(_mail(_order_subject(long), _order_text())).updates
    assert update.title.endswith("… und 3 mehr") and len(update.title) == 60
    plain = "Beispielband mit einem sehr langen Namen – Die große Jubiläumstour 2026 Open Air"
    (update,) = parse_eventim(_mail(_order_subject(plain), _order_text())).updates
    assert update.title.endswith("…") and len(update.title) == 60
    # A dash in the event's name is part of it.
    (update,) = parse_eventim(_mail(_order_subject("Band - Live - 2026"), _order_text())).updates
    assert update.title == "Band - Live - 2026"


def test_shipping_notice_is_on_its_way_with_the_estimate_from_its_day():
    update = _update(SHIPPED)
    assert (update.number, update.carrier) == (ORDER, "eventim")
    assert update.status is ParcelStatus.IN_TRANSIT
    assert update.sent_at == SENT
    assert (update.eta_date, update.eta_latest) == (FIRST, LAST)
    assert (FIRST, LAST) == (add_workdays(SENT.date(), 2), add_workdays(SENT.date(), 4))
    assert update.title == EVENT  # from "EINZELHEITEN DEINER BESTELLUNG"
    assert (update.tracking_ref, update.tracking_carrier) == (None, None)
    assert update.status_text is None


@pytest.mark.parametrize(
    ("arrival", "when", "first", "last"),
    [
        # Thursday: Friday, Saturday, (no Sunday) Monday, Tuesday
        ("innerhalb von 2 bis 4 Werktagen", "Thu, 08 Jan 2026 10:00:00 +0100",
         date(2026, 1, 10), date(2026, 1, 13)),
        # Saturday: Monday is the first working day
        ("innerhalb von 1 bis 2 Werktagen", "Sat, 10 Jan 2026 18:00:00 +0100",
         date(2026, 1, 12), date(2026, 1, 13)),
        ("innerhalb von 3 - 5 Werktagen", "Mon, 05 Jan 2026 08:00:00 +0100",
         date(2026, 1, 8), date(2026, 1, 10)),
        # one number: one day
        ("innerhalb von 3 Werktagen", "Mon, 05 Jan 2026 08:00:00 +0100",
         date(2026, 1, 8), None),
        ("innerhalb von 2 bis 2 Werktagen", "Mon, 05 Jan 2026 08:00:00 +0100",
         date(2026, 1, 7), None),
        # late in the evening UTC is the next day in Berlin
        ("innerhalb von 1 bis 2 Werktagen", "Mon, 05 Jan 2026 23:30:00 +0000",
         date(2026, 1, 7), date(2026, 1, 8)),
        # nothing anybody can plan with
        ("in den nächsten Tagen", "Mon, 05 Jan 2026 08:00:00 +0100", None, None),
        ("innerhalb von 0 bis 4 Werktagen", "Mon, 05 Jan 2026 08:00:00 +0100", None, None),
        ("innerhalb von 4 bis 2 Werktagen", "Mon, 05 Jan 2026 08:00:00 +0100", None, None),
        ("innerhalb von 20 bis 60 Werktagen", "Mon, 05 Jan 2026 08:00:00 +0100", None, None),
    ],
)
def test_estimate_of_the_shipping_notice(arrival, when, first, last):
    msg = _mail(SHIPPED_SUBJECT, _shipped_text(arrival), when=when)
    (update,) = parse_eventim(msg).updates
    assert update.status is ParcelStatus.IN_TRANSIT
    assert (update.eta_date, update.eta_latest) == (first, last)


def test_the_estimate_is_only_read_behind_its_label():
    text = _shipped_text("bald").replace(
        "HINWEISE", "HINWEISE\nRückfragen beantworten wir innerhalb von 2 bis 4 Werktagen."
    )
    (update,) = parse_eventim(_mail(SHIPPED_SUBJECT, text)).updates
    assert update.eta_date is None


def test_shipping_notice_names_several_events_and_works_as_html_and_without_details():
    (two,) = parse_eventim(_mail(SHIPPED_SUBJECT, _shipped_text(events=3))).updates
    assert two.title == f"{EVENT} und 2 mehr"
    (as_html,) = parse_eventim(_mail(SHIPPED_SUBJECT, _shipped_text(), html=True)).updates
    assert (as_html.title, as_html.eta_date, as_html.eta_latest) == (EVENT, FIRST, LAST)
    bare = _shipped_text().split("EINZELHEITEN")[0]
    (update,) = parse_eventim(_mail(SHIPPED_SUBJECT, bare)).updates
    assert update.title is None and update.eta_date == FIRST
    # Without the line about the delivery method it is still a letter that was sent.
    (update,) = parse_eventim(_mail(SHIPPED_SUBJECT, _shipped_text(method=None))).updates
    assert update.status is ParcelStatus.IN_TRANSIT


# ----- only postal delivery -----
@pytest.mark.parametrize(
    "method",
    [
        "Standardversand (Deutschland)",
        "Standardversand (International)",
        "Einschreiben",
        "Einschreiben (Deutschland)",
        "Expressversand",
        "UPS Express",
        "Kurier",
        "Premiumversand",
        "Postversand",
        "Wertbrief",
        "Versand als Wertbrief (Deutschland)",
    ],
)
def test_postal_delivery_methods(method):
    assert is_postal(method)
    result = parse_eventim(_mail(_order_subject(), _order_text(f"Liefermethode: {method}")))
    assert [u.status for u in result.updates] == [ParcelStatus.PRE_TRANSIT]
    # Older mails: label and value on two lines.
    result = parse_eventim(_mail(_order_subject(), _order_text(f"Liefermethode:\n{method}")))
    assert [u.number for u in result.updates] == [ORDER]
    assert parse_eventim(_mail(_order_subject(), _order_text(f"Liefermethode: {method}"),
                               html=True)).updates


@pytest.mark.parametrize(
    "method",
    [
        "ticketdirect",
        "Mobile Ticket (für Apple & Google Wallet)",
        "print@home",
        "Print @ Home",
        "EVENTIM.Pass",
        "Hinterlegung an der Abendkasse",
        "Abholung",
        "E-Ticket per Mail",
        "",
        # v0.3.31: "Versand" and "Express" alone say nothing about a letter box.
        "Versand per E-Mail",
        "E-Mail-Versand",
        "Express-Download",
        "PDF-Ticket (Sofortversand)",
        "Abholung an der Abendkasse (kein Versand)",
        "Digitales Ticket (kein Postversand)",
        "Hinterlegung (Expressversand nicht möglich)",
    ],
)
def test_other_delivery_methods_make_no_order(method):
    assert not is_postal(method)
    for line in (f"Liefermethode: {method}", f"Liefermethode:\n{method}"):
        result = parse_eventim(_mail(_order_subject(), _order_text(line)))
        assert result.ignored and result.updates == []
    assert not is_postal(None)


def test_order_mail_for_tickets_to_print_is_ignored():
    result = parse_mail(load_mail(ORDER_DIGITAL))
    assert result.ignored and result.updates == []
    assert "Liefermethode: ticketdirect" in load_mail(ORDER_DIGITAL).get_content()


def test_order_mail_without_a_readable_delivery_method_is_ignored():
    text = _order_text("Der Versand erfolgt per Standardversand.")
    result = parse_eventim(_mail(_order_subject(), text))
    assert result.ignored and result.updates == []
    assert parse_eventim(_mail(_order_subject(), "")).ignored


def test_a_shipping_notice_that_names_a_digital_method_is_ignored():
    text = _shipped_text(method="Liefermethode: ticketdirect")
    result = parse_eventim(_mail(SHIPPED_SUBJECT, text))
    assert result.ignored and result.updates == []


def test_later_shipping_makes_no_estimate_either():
    """Tickets for an event far ahead: the order mail names the weeks they are sent in."""
    line = (
        "Liefermethode: Standardversand (Deutschland)\n"
        "Der Versand der Tickets erfolgt zwischen dem 1. Juni und 5. Juni 2026. Die "
        "Lieferzeit beträgt 2 - 8 Werktage (Montag bis Samstag, Feiertage ausgenommen)."
    )
    (update,) = parse_eventim(_mail(_order_subject(), _order_text(line))).updates
    assert (update.status, update.eta_date) == (ParcelStatus.PRE_TRANSIT, None)


# ----- every other mail of Eventim -----
@pytest.mark.parametrize("name", [TICKET_ALARM, CLUB_SHOP])
def test_other_eventim_senders_are_ignored(name):
    result = parse_mail(load_mail(name))
    assert result.ignored and result.updates == []


@pytest.mark.parametrize(
    ("address", "subject"),
    [
        ("ticketalarm@service.eventim.de", "Beispielband - Tickets jetzt bei EVENTIM!"),
        ("ticketnews@service.eventim.de", "Beispielband - Tickets ab Freitag bei EVENTIM!"),
        ("email@service.eventim.de", "Na, wie war's bei Beispielband? Jetzt Bewertung abgeben!"),
        ("newsletter@eventim.de", "Newsletter-Anmeldung bestätigen"),
        ("fanbonus@eventim.de", "Dein Bonus für Musterfans"),
        ("servicenews@eventim.de", "Wichtiger Hinweis zu Beispielband in MUSTERSTADT"),
        ("kundenservice@eventim.de", "Willkommen im Kundenkonto"),
        ("noreply_kundenservice-musterverein@eventim.de", "Antwort auf deine Frage"),
        ("info@eventimpresents.com", "Neues vom Musterfestival"),
        ("kundenservice-musterverein@eventim.de", "Musterverein - Tickets - 999999999901"),
        ("kundenservice-musterverein@eventim.de",
         "Deine Buchung 999999999901 vom 05.01.2026 im Online-Ticketshop des Mustervereins"),
        # Even with the words and a number of an order: only the order sender is read.
        ("kundenservice-musterverein@eventim.de", _order_subject()),
        ("servicenews@eventim.de", SHIPPED_SUBJECT),
    ],
)
def test_newsletters_service_mails_and_club_shops_are_ignored(address, subject):
    text = _order_text() + "Sendungsnummer: 00340999999999999901\n"
    result = parse_mail(_mail(subject, text, address))
    assert result.ignored and result.updates == []


def test_an_unknown_subject_of_the_order_sender_is_unrecognised():
    result = parse_mail(_mail("Deine Bestellung wurde storniert", _order_text()))
    assert not result.ignored and result.updates == []
    # No number in its text makes a parcel either (never the generic parser).
    text = "Sendungsnummer: 00340999999999999901\n1Z999AA10123456784\n"
    assert parse_mail(_mail("Neuigkeiten", text)).updates == []


def test_sender_class_for_the_diagnostics_and_the_relay():
    assert "eventim.de" in KNOWN_MAIL_DOMAINS
    assert known_sender_domain(EVENTIM_SENDER) == "eventim.de"
    assert known_sender_domain("ticketalarm@service.eventim.de") == "eventim.de"
    assert known_sender_domain("kundenservice-musterverein@eventim.de") == "eventim.de"
    assert known_sender_domain("info@eventimpresents.com") == "other"
    assert known_sender_domain("bestellstatus@eventim.de.example.org") == "other"
    assert is_ignored("info@eventimpresents.com") and not is_ignored(EVENTIM_SENDER)
    # Apple "E-Mail-Adresse verbergen" passes the order sender on.
    relay = "bestellstatus_at_eventim_de_k7m2x9q4pz_4f8e1a7c@privaterelay.appleid.com"
    msg = load_mail(SHIPPED)
    msg.replace_header("From", f"EVENTIM <{relay}>")
    assert sender(msg)[0] == EVENTIM_SENDER
    (update,) = parse_mail(msg).updates
    assert (update.number, update.eta_date) == (ORDER, FIRST)
    item = _parse_one(bytes(msg), False, SENT.astimezone(UTC))
    assert (item.domain, item.forwarded) == ("eventim.de", False)


def test_a_shipping_notice_forwarded_by_hand_is_read_as_the_original():
    quoted = (
        "Schau mal\n\n-------- Weitergeleitete Nachricht --------\n"
        f"Von: EVENTIM <{EVENTIM_SENDER}>\nGesendet: Donnerstag, 8. Januar 2026 10:00\n"
        f"An: max@example.org\nBetreff: {SHIPPED_SUBJECT}\n\n" + _shipped_text()
    )
    msg = _mail(f"WG: {SHIPPED_SUBJECT}", quoted, "max@example.org")
    assert forwarded_original(msg) is not None
    (update,) = parse_mail(msg).updates
    assert (update.number, update.status) == (ORDER, ParcelStatus.IN_TRANSIT)


# ----- wired like the other shops -----
def test_eventim_is_a_shop_carrier():
    assert "eventim" in SHOP_CARRIERS and "eventim" in MAIL_CARRIERS
    assert "eventim" in SINGLE_PARCEL_SHOPS and frozenset({"eventim"}) == SHIP_LATER_SHOPS
    assert CARRIER_NAMES["eventim"] == "Eventim"
    assert order_number("999999901") == ORDER
    parcel = Parcel(ORDER, "eventim", "mail", EVENT, SENT, SENT, mail_title=EVENT)
    assert carrier_name(parcel) == "Eventim"
    assert neutral_name(parcel) == "Eventim-Bestellung …9901"
    # Nobody can be asked about it: no poll, no 17track, no tracking page.
    assert parcel.poll_target is None and parcel.track17_target is None
    assert tracking_url(parcel) is None


def _apply(parcels, name_or_update, now):
    update = _update(name_or_update) if isinstance(name_or_update, str) else name_or_update
    return apply_update(parcels, update, now)


def test_order_then_shipping_notice_moves_the_order_forward():
    parcels: dict[str, Parcel] = {}
    change = _apply(parcels, ORDER_MAIL, ORDERED)
    assert change.created and list(parcels) == [ORDER]
    order = parcels[ORDER]
    assert (order.carrier, order.carrier_mode, order.name) == ("eventim", "mail", EVENT)
    assert (order.status, order.result.status_text) == (ParcelStatus.PRE_TRANSIT, "Bestellt")
    assert order.result.eta_date is None and order.name_manual is False

    change = _apply(parcels, SHIPPED, SENT)
    assert not change.created and change.old_status is ParcelStatus.PRE_TRANSIT
    assert list(parcels) == [ORDER]
    assert (order.status, order.result.status_text) == (ParcelStatus.IN_TRANSIT, "Versendet")
    assert (order.result.eta_date, order.result.eta_latest) == (FIRST, LAST)
    assert [(e.timestamp, e.text) for e in order.result.events] == [
        (SENT, "Versendet"), (ORDERED, "Bestellt"),
    ]
    assert order.tracking_ref is None and order.last_change_at == SENT


def test_the_order_never_goes_backwards():
    parcels: dict[str, Parcel] = {}
    _apply(parcels, SHIPPED, SENT)
    before = parcels[ORDER].to_dict()
    # The order mail read afterwards (a mailbox filled in one go) and the notice again.
    assert _apply(parcels, ORDER_MAIL, SENT + timedelta(hours=1)) is None
    assert _apply(parcels, SHIPPED, SENT + timedelta(hours=2)) is None
    assert parcels[ORDER].to_dict() == before and list(parcels) == [ORDER]


def test_a_shipping_notice_alone_makes_the_order():
    parcels: dict[str, Parcel] = {}
    change = _apply(parcels, SHIPPED, SENT)
    assert change.created
    order = parcels[ORDER]
    assert (order.name, order.mail_title) == (EVENT, EVENT)
    assert (order.status, order.result.eta_date, order.result.eta_latest) == (
        ParcelStatus.IN_TRANSIT, FIRST, LAST,
    )


def test_tickets_of_another_event_of_the_order_are_no_second_parcel():
    """An order of two events may come in two letters: it stays one entry."""
    parcels: dict[str, Parcel] = {}
    _apply(parcels, ORDER_MORE, ORDERED)
    notice = lambda event, when: parse_eventim(_mail(  # noqa: E731
        SHIPPED_SUBJECT.replace("999999901", "9999999902"),
        _shipped_text().replace(EVENT, event), when=when,
    )).updates[0]
    _apply(parcels, notice("Musterfestival 2026 – Wochenendticket",
                           "Thu, 08 Jan 2026 10:00:00 +0100"), SENT)
    later = SENT + timedelta(days=4)
    _apply(parcels, notice("Beispielorchester – Neujahrskonzert",
                           "Mon, 12 Jan 2026 10:00:00 +0100"), later)
    assert list(parcels) == [ORDER_OF_TWO]
    order = parcels[ORDER_OF_TWO]
    assert order.name == "Beispielorchester – Neujahrskonzert und 1 mehr"
    # The second notice counts anew.
    assert (order.result.eta_date, order.result.eta_latest) == (
        date(2026, 1, 14), date(2026, 1, 16),
    )


def test_digital_orders_and_other_mails_touch_nothing():
    parcels: dict[str, Parcel] = {}
    for name in (ORDER_DIGITAL, TICKET_ALARM, CLUB_SHOP):
        result = parse_mail(load_mail(name))
        for update in result.updates:
            apply_update(parcels, update, SENT)
    assert parcels == {}


# ----- how the order ends -----
def _shipped_order() -> Parcel:
    parcels: dict[str, Parcel] = {}
    _apply(parcels, ORDER_MAIL, ORDERED)
    _apply(parcels, SHIPPED, SENT)
    return parcels[ORDER]


def test_a_shipped_order_is_overdue_three_days_after_its_last_day():
    order = _shipped_order()
    assert not order_overdue(order, LAST + timedelta(days=ORDER_OVERDUE_DAYS), BERLIN)
    assert order_overdue(order, LAST + timedelta(days=ORDER_OVERDUE_DAYS + 1), BERLIN)
    # Without an estimate: two weeks after the notice.
    order.result.eta_date = order.result.eta_latest = None
    day = SENT.date()
    assert not order_overdue(order, day + timedelta(days=ORDER_NO_ETA_DAYS - 1), BERLIN)
    assert order_overdue(order, day + timedelta(days=ORDER_NO_ETA_DAYS), BERLIN)


def test_an_order_that_is_only_ordered_is_never_closed_on_its_own():
    """Tickets may be sent months after the order; until then nothing has been delivered."""
    parcels: dict[str, Parcel] = {}
    _apply(parcels, ORDER_MAIL, ORDERED)
    order = parcels[ORDER]
    for days in (ORDER_NO_ETA_DAYS, 60, 400):
        assert not order_overdue(order, ORDERED.date() + timedelta(days=days), BERLIN)
    # Like every parcel nothing changes for 30 days it leaves the list ...
    gone = ORDERED + timedelta(days=STALE_REMOVE_DAYS, minutes=1)
    assert not should_remove(order, ORDERED + timedelta(days=STALE_REMOVE_DAYS), 3)
    assert should_remove(order, gone, 3)
    # ... and an Amazon order that is only ordered is still closed after two weeks.
    amazon = Parcel("AMZ99999999999999901", "amazon", "mail", "x", ORDERED, ORDERED,
                    result=order.result)
    assert order_overdue(amazon, ORDERED.date() + timedelta(days=ORDER_NO_ETA_DAYS), BERLIN)


async def _mail_in(hass, coord, mail):
    msg = load_mail(mail) if isinstance(mail, str) else mail
    item = _parse_one(msg.as_bytes(), False, dt_util.utcnow())
    assert isinstance(item, _ParsedMail) and item.error is None and not item.stale
    async with coord._lock:
        folder = coord._handle_mail(item, dt_util.utcnow())
        coord._settle_orders(dt_util.utcnow())
        await coord.store.async_save()
    coord.async_set_updated_data(dict(coord.store.parcels))
    await hass.async_block_till_done()
    return folder


async def test_from_the_order_to_the_closing_without_a_delivery_mail(
    hass, hass_storage, freezer
):
    calls, events = await _prepared(hass, freezer)
    freezer.move_to(ORDERED + timedelta(minutes=5))
    coord = await _coordinator(hass, hass_storage, [])
    await _refresh(hass, coord)
    await _start(hass)

    assert await _mail_in(hass, coord, ORDER_MAIL) == "Paket-Tracker-Verarbeitet"
    assert await _mail_in(hass, coord, ORDER_DIGITAL) is None  # ignored: only marked read
    assert await _mail_in(hass, coord, TICKET_ALARM) is None
    assert await _mail_in(hass, coord, CLUB_SHOP) is None
    assert list(coord.store.parcels) == [ORDER]
    assert coord.unrecognized_mails == type(coord.unrecognized_mails)(maxlen=10)
    order = coord.store.parcels[ORDER]
    assert order.status is ParcelStatus.PRE_TRANSIT and events == []

    freezer.move_to(SENT + timedelta(minutes=5))
    assert await _mail_in(hass, coord, SHIPPED) == "Paket-Tracker-Verarbeitet"
    assert (order.status, order.result.eta_date, order.result.eta_latest) == (
        ParcelStatus.IN_TRANSIT, FIRST, LAST,
    )
    (event,) = events
    assert (event.data["number"], event.data["carrier"], event.data["carrier_name"]) == (
        ORDER, "eventim", "Eventim",
    )
    assert (event.data["old_status"], event.data["new_status"]) == ("pre_transit", "in_transit")
    assert event.data["eta_date"] == FIRST.isoformat() and event.data["name"] == EVENT
    assert calls == []  # "Versendet" is never pushed

    # In its delivery window it is possible today; three days after the last day it is
    # closed without a confirmation, told by the event only.
    freezer.move_to(datetime(2026, 1, 12, 12, 0, tzinfo=BERLIN))
    await _refresh(hass, coord)
    summary = summarize(coord.store.parcels.values(), date(2026, 1, 12), BERLIN)
    assert summary.possible == [order] and summary.active == [order]
    freezer.move_to(datetime(2026, 1, 16, 23, 0, tzinfo=BERLIN))
    await _refresh(hass, coord)
    assert order.status is ParcelStatus.IN_TRANSIT
    freezer.move_to(datetime(2026, 1, 17, 0, 30, tzinfo=BERLIN))
    await _refresh(hass, coord)
    assert (order.status, order.assumed_delivered) == (ParcelStatus.DELIVERED, True)
    assert order.result.status_text == ASSUMED_TEXT
    assert [(e.data["new_status"], e.data["assumed"], e.data["manual"]) for e in events[1:]] == [
        ("delivered", True, False)
    ]
    assert calls == []
    assert build_notification(order, ParcelStatus.IN_TRANSIT, dt_util.now()) is None
    await coord.async_shutdown()


async def test_erhalten_closes_the_order(hass, hass_storage, freezer):
    calls, events = await _prepared(hass, freezer)
    freezer.move_to(SENT + timedelta(minutes=5))
    coord = await _coordinator(hass, hass_storage, [])
    await _refresh(hass, coord)
    await _start(hass)
    await _mail_in(hass, coord, ORDER_MAIL)
    await _mail_in(hass, coord, SHIPPED)

    freezer.move_to(datetime(2026, 1, 10, 11, 0, tzinfo=BERLIN))
    await coord.async_mark_delivered(ORDER)
    await hass.async_block_till_done()
    order = coord.store.parcels[ORDER]
    assert (order.status, order.manual_delivered) == (ParcelStatus.DELIVERED, True)
    assert order.result.status_text == MANUAL_TEXT
    assert [e.text for e in order.result.events] == [MANUAL_TEXT, "Versendet", "Bestellt"]
    summary = summarize(coord.store.parcels.values(), date(2026, 1, 10), BERLIN)
    assert summary.delivered_today == [order] and summary.active == []
    assert [(e.data["new_status"], e.data["manual"]) for e in events] == [
        ("in_transit", False), ("delivered", True),
    ]
    assert calls == []

    # Nothing closes it "without confirmation" afterwards; it goes after the kept days.
    freezer.move_to(datetime(2026, 1, 13, 10, 0, tzinfo=BERLIN))
    await _refresh(hass, coord)
    assert order.assumed_delivered is False and ORDER in coord.store.parcels
    freezer.move_to(datetime(2026, 1, 13, 11, 1, tzinfo=BERLIN))
    await _refresh(hass, coord)
    assert coord.store.parcels == {}
    assert len(events) == 2
    await coord.async_shutdown()


async def test_an_order_that_is_only_ordered_can_be_marked_as_received(
    hass, hass_storage, freezer
):
    _calls, events = await _prepared(hass, freezer)
    freezer.move_to(ORDERED + timedelta(minutes=5))
    coord = await _coordinator(hass, hass_storage, [])
    await _refresh(hass, coord)
    await _start(hass)
    await _mail_in(hass, coord, ORDER_MAIL)
    # Weeks without a shipping notice: still open.
    freezer.move_to(ORDERED + timedelta(days=20))
    await _refresh(hass, coord)
    assert coord.store.parcels[ORDER].status is ParcelStatus.PRE_TRANSIT and events == []
    await coord.async_mark_delivered(ORDER)
    assert coord.store.parcels[ORDER].result.status_text == MANUAL_TEXT
    # The shipping notice that comes after all is filed and changes nothing.
    notice = _mail(SHIPPED_SUBJECT, _shipped_text(), when="Tue, 27 Jan 2026 10:00:00 +0100")
    notice["Message-ID"] = "<late-notice@synthetic.example>"
    freezer.move_to(datetime(2026, 1, 27, 10, 5, tzinfo=BERLIN))
    assert await _mail_in(hass, coord, notice) == "Paket-Tracker-Verarbeitet"
    assert len(events) == 1 and events[0].data["manual"] is True
    assert coord.store.parcels[ORDER].result.status_text == MANUAL_TEXT
    assert coord.store.parcels[ORDER].result.eta_date is None
    await coord.async_shutdown()


async def test_sensor_diagnostics_and_hidden_names(hass, hass_storage, freezer):
    freezer.move_to(SENT + timedelta(minutes=5))
    await hass.config.async_set_time_zone("Europe/Berlin")
    order = _shipped_order()
    hass_storage[DOMAIN] = {
        "version": 1, "key": DOMAIN,
        "data": {"parcels": [order.to_dict()], "message_ids": []},
    }
    entry = MockConfigEntry(domain=DOMAIN, data={"postcode": "10115"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.paket_evt999999901")
    assert state.state == "in_transit"
    attributes = state.attributes
    assert (attributes["carrier"], attributes["carrier_name"]) == ("eventim", "Eventim")
    assert (attributes["name"], attributes["status_text"]) == (EVENT, "Versendet")
    assert (attributes["eta_date"], attributes["eta_latest"]) == (
        FIRST.isoformat(), LAST.isoformat(),
    )
    assert attributes["tracking_url"] is None and attributes["tracking_ref"] is None
    assert attributes["manual_delivered"] is False
    assert hass.states.get("sensor.pakete_unterwegs").state == "1"

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    (parcel,) = diagnostics["parcels"]
    assert parcel["carrier"] == "eventim" and parcel["number"] != ORDER

    hass.config_entries.async_update_entry(entry, options={CONF_HIDE_NAMES: True})
    await hass.async_block_till_done()
    assert hass.states.get("sensor.paket_evt999999901").attributes["name"] == (
        "Eventim-Bestellung …9901"
    )


# ----- v0.3.31: the title of a shipping notice is the first line of the event block -----
def _notice(block: str) -> str:
    return (
        "VERSANDBENACHRICHTIGUNG\nHallo Max,\nLieferadresse:\nMax Mustermann\n"
        "Musterstraße 1\n12345 Musterstadt\nDeutschland\n"
        "Liefermethode: Standardversand (Deutschland)\n"
        f"EINZELHEITEN DEINER BESTELLUNG\n{block}HINWEISE\n"
    )


def _notice_title(block: str) -> str | None:
    (update,) = parse_eventim(_mail(SHIPPED_SUBJECT, _notice(block))).updates
    return update.title


REST = "Ort: Musterhalle, Musterstadt\nVeranstalter: Beispiel Konzert GmbH, Musterstadt\n"


def test_event_name_on_two_lines_gives_its_first_line():
    block = f"Beispielband\nDie große Abschiedstour\nDatum: Sa., 05.12.2026, 20:00\n{REST}"
    assert _notice_title(block) == "Beispielband"
    two = block + f"Musterfestival 2026\nWochenendticket\nDatum: So., 06.12.2026, 18:00\n{REST}"
    assert _notice_title(two) == "Beispielband und 1 mehr"


@pytest.mark.parametrize(
    "above",
    [
        "Hallo Max,",
        "Hi Max",
        "Liebe Erika,",
        "Max Mustermann\nMusterstraße 1\n12345 Musterstadt\nDeutschland",
        "Musterstraße 1",
        "12345 Musterstadt",
        "Erika Beispiel\nBeispielweg 12a",
        "Lieferadresse:",
        "https://www.eventim.de/…",
        "Zeile 1\nZeile 2\nZeile 3\nZeile 4",
    ],
)
def test_no_title_from_lines_that_may_be_a_greeting_a_name_or_an_address(above):
    """Fail closed: a person's name or address must never become the name of an order."""
    assert _notice_title(f"{above}\nDatum: Sa., 05.12.2026, 20:00\n{REST}") is None
    # Also not for the second event of a notice: no title at all then.
    good = f"{EVENT}\nDatum: Sa., 05.12.2026, 20:00\n{REST}"
    assert _notice_title(good + f"{above}\nDatum: So., 06.12.2026, 18:00\n{REST}") is None


@pytest.mark.parametrize(
    "name",
    [
        "Musterfest am Ring 2026",
        "1975 – Die Jubiläumstour",
        "Liebe ist alles – Das Musical",
        "Hi-Fi Tage Musterstadt",
    ],
)
def test_a_name_that_only_looks_a_bit_like_an_address_or_a_greeting_stays(name):
    assert _notice_title(f"{name}\nDatum: Sa., 05.12.2026, 20:00\n{REST}") == name


def test_no_title_without_an_event_line_above_the_day():
    assert _notice_title(f"Datum: Sa., 05.12.2026, 20:00\n{REST}") is None
