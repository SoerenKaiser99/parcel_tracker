"""v0.3.25: AliExpress orders from mails, and senders behind Apple's mail relay."""

from datetime import UTC, date, datetime, timedelta
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.const import ORDER_NO_ETA_DAYS, ORDER_OVERDUE_DAYS
from custom_components.parcel_tracker.diagnostics import mask_number
from custom_components.parcel_tracker.mail import (
    forwarded_original,
    is_ignored,
    known_sender_domain,
    parse_mail,
)
from custom_components.parcel_tracker.mail.aliexpress import (
    ALIEXPRESS_SENDER,
    CONFIRMED_TEXT,
    CUSTOMS_TEXT,
    HANDED_OVER_TEXT,
    PARCEL_NAME,
    order_number,
    parse_aliexpress,
)
from custom_components.parcel_tracker.mail.apply import (
    ASSUMED_TEXT,
    apply_update,
    close_unconfirmed,
    fold_delivered,
)
from custom_components.parcel_tracker.mail.base import sender, shop_of, unrelay
from custom_components.parcel_tracker.models import (
    Parcel,
    ParcelStatus,
    TrackingEvent,
    TrackingResult,
    carrier_name,
    neutral_name,
)
from custom_components.parcel_tracker.notification import build_notification
from custom_components.parcel_tracker.schedule import order_overdue

from .conftest import load_mail

ORDERS = "126_aliexpress_2_bestellungen_wurden_best_ti.eml"
CONFIRMED = "127_aliexpress_bestellung_bestellauftrag_bes.eml"
READY = "128_aliexpress_bestellung_versandfertig.eml"
SHIPPED = "129_aliexpress_bestellung_wurde_versandt.eml"
HANDED_OVER = "130_aliexpress_bestellung_wird_zugestellt.eml"
IN_TRANSIT = "131_aliexpress_bestellung_paket_im_transit.eml"
ARRIVED = "132_aliexpress_bestellung_in_ihrem_land_ihre.eml"
COMBINED = "133_aliexpress_bestellung_neuer_lieferstatus.eml"
PARCEL_DHL = "134_aliexpress_packst_ck_hat_die_abflugregio.eml"
CUSTOMS = "135_aliexpress_zollabfertigung_f_r_wurde_bee.eml"
PARCEL_HERMES = "136_aliexpress_packst_ck_in_ihrem_land_ihrer.eml"
PARCEL_UNKNOWN = "137_aliexpress_packst_ck_vom_kurier_abgeholt.eml"
RATING = "138_aliexpress_bestellung_wie_war_ihr_einkau.eml"
DELIVERY_CONFIRMED = "139_aliexpress_bestellung_wie_ist_es_gelaufe.eml"
REMINDER = "140_aliexpress_bestellung_auf_best_tigung_wi.eml"
OFFERS = "141_aliexpress_ihre_bestellung_hat_einen_lok.eml"
CLOSED = "142_aliexpress_your_order_is_closed.eml"

NOW = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
ORDER = "ALI9999999999990901"
DHL = "00340999999999990902"
HERMES = "H9999999999999990903"
RELAY_IDS = "0a1b2c3d4e_0a1b2c3d"
RELAY = f"transaction_at_notice_aliexpress_com_{RELAY_IDS}@privaterelay.appleid.com"
LINK = "https://www.aliexpress.com/p/tracking/index.html?_login=yes&tradeOrderId="


def _msg(subject: str, body: str = "", sender_: str = ALIEXPRESS_SENDER, html: str | None = None):
    msg = EmailMessage(policy=policy.default)
    msg["From"] = f"AliExpress <{sender_}>"
    msg["Subject"] = subject
    msg["Date"] = "Wed, 07 Oct 2026 08:00:00 +0200"
    if html is None:
        msg.set_content(body or "Hallo Max Mustermann,\n")
    else:
        msg.set_content(html, subtype="html")
    return msg


def _one(name: str):
    [update] = parse_mail(load_mail(name)).updates
    return update


def _apply(parcels: dict, msg_or_name, now: datetime = NOW):
    msg = load_mail(msg_or_name) if isinstance(msg_or_name, str) else msg_or_name
    return [apply_update(parcels, update, now) for update in parse_mail(msg).updates]


# ----- the parser, on the anonymised mails -----


def test_order_number():
    assert order_number("9999999999990001") == "ALI9999999999990001"


def test_confirmation_is_an_order_named_after_its_item():
    u = _one(CONFIRMED)
    assert (u.number, u.carrier) == ("ALI9999999999990003", "aliexpress")
    assert (u.status, u.status_text) == (ParcelStatus.PRE_TRANSIT, None)
    assert u.title == "Beispiel-Schalter kabellos m…"
    assert (u.eta_date, u.tracking_ref, u.delivered_at) == (None, None, None)


def test_confirmation_of_several_orders_gives_one_update_per_order():
    first, second = parse_mail(load_mail(ORDERS)).updates
    # (the list counts the orders right in front of their numbers)
    assert (first.number, first.title) == ("ALI9999999999990001", "Beispiel-Kabel USB-C auf USB-…")
    assert (second.number, second.title) == (
        "ALI9999999999990002",
        "Beispiel-Sensor für Temperatu…",
    )
    assert {first.status, second.status} == {ParcelStatus.PRE_TRANSIT}


def test_ready_to_ship_is_still_ordered_and_tells_the_estimate():
    u = _one(READY)
    assert (u.status, u.status_text) == (ParcelStatus.PRE_TRANSIT, "Versandbereit")
    # "Voraussichtliche Zustellzeit" is day/month/year
    assert (u.eta_date, u.eta_latest) == (date(2024, 8, 30), None)
    assert u.title is None  # this layout shows no item


def test_shipped_through_the_relay_reads_the_item_but_never_the_shop():
    msg = load_mail(SHIPPED)
    assert "privaterelay.appleid.com" in str(msg["From"])
    [u] = parse_mail(msg).updates
    assert (u.number, u.status, u.status_text) == (
        "ALI9999999999990005",
        ParcelStatus.IN_TRANSIT,
        None,
    )
    assert u.title == "Beispiel-Lampe LED flach…"
    assert "Store" not in u.title


def test_wird_zugestellt_is_only_the_handover_to_the_carrier():
    u = _one(HANDED_OVER)
    assert (u.status, u.status_text) == (ParcelStatus.IN_TRANSIT, HANDED_OVER_TEXT)


def test_wird_zugestellt_without_that_sentence_is_out_for_delivery():
    [u] = parse_mail(_msg("Bestellung 9999999999990901: Wird zugestellt")).updates
    assert (u.status, u.status_text) == (ParcelStatus.OUT_FOR_DELIVERY, None)


def test_in_transit_and_arrived_keep_the_words_of_aliexpress():
    u = _one(IN_TRANSIT)
    assert (u.status, u.status_text) == (ParcelStatus.IN_TRANSIT, "Paket im Transit")
    assert u.eta_date == date(2024, 8, 30)
    u = _one(ARRIVED)
    assert (u.status, u.status_text) == (ParcelStatus.IN_TRANSIT, "Im Zielland angekommen")


def test_combined_delivery_updates_both_orders_and_names_the_carrier_number():
    first, second = parse_mail(load_mail(COMBINED)).updates
    assert [first.number, second.number] == ["ALI9999999999990007", "ALI9999999999990008"]
    assert [first.title, second.title] == [
        "Beispiel-Handtuch aus Bau…",
        "Beispiel-Spielzeug Kreise…",
    ]
    for u in (first, second):
        # "Neuer Lieferstatus" tells no step of its own
        assert (u.status, u.status_text) == (ParcelStatus.IN_TRANSIT, None)
        assert (u.tracking_ref, u.tracking_carrier) == ("H9999702885602351723", "hermes")


@pytest.mark.parametrize(
    ("name", "words"),
    [(PARCEL_DHL, "Abflugregion verlassen"), (CUSTOMS, CUSTOMS_TEXT)],
)
def test_parcel_mail_gives_its_order_the_dhl_number(name, words):
    u = _one(name)
    # The order stands only in the mail's link; the parcel's number is the carrier's.
    assert (u.number, u.carrier) == ("ALI9999999999990011", "aliexpress")
    assert (u.status, u.status_text) == (ParcelStatus.IN_TRANSIT, words)
    assert (u.tracking_ref, u.tracking_carrier) == ("00340999999999990010", "dhl")
    assert u.title == "Beispiel-Ersatzteil Getriebe Set für…"  # one item, listed twice


def test_parcel_with_several_orders_gives_each_the_hermes_number():
    updates = parse_mail(load_mail(PARCEL_HERMES)).updates
    assert [u.number for u in updates] == [
        "ALI9999999999990013",
        "ALI9999999999990014",
        "ALI9999999999990015",
    ]
    for u in updates:
        assert (u.tracking_ref, u.tracking_carrier) == ("H9999207472066355373", "hermes")
        assert (u.status, u.status_text) == (ParcelStatus.IN_TRANSIT, "Im Zielland angekommen")
        assert u.title is None  # which item is in which order is not told


def test_parcel_number_in_an_unknown_format_is_dropped():
    updates = parse_mail(load_mail(PARCEL_UNKNOWN)).updates
    assert len(updates) == 4
    for u in updates:
        assert u.carrier == "aliexpress" and u.number.startswith("ALI99999999999900")
        assert (u.status, u.status_text) == (ParcelStatus.IN_TRANSIT, "Vom Kurier abgeholt")
        assert (u.tracking_ref, u.tracking_carrier) == (None, None)


def test_confirmed_delivery_closes_the_order():
    u = _one(DELIVERY_CONFIRMED)
    assert (u.number, u.status) == ("ALI9999999999990021", ParcelStatus.DELIVERED)
    assert (u.status_text, u.confirmation) == (CONFIRMED_TEXT, True)
    assert u.delivered_at == datetime(2023, 12, 23, 17, 4, 11, tzinfo=BERLIN)
    assert u.title == "Beispiel-Schalter kabello…"


@pytest.mark.parametrize("name", [RATING, REMINDER, OFFERS, CLOSED])
def test_mails_without_news_are_ignored_not_unrecognised(name):
    result = parse_mail(load_mail(name))
    assert result.ignored and not result.updates and not result.amazon


def test_offers_are_ignored_by_their_sender():
    assert is_ignored("angebote@deals.aliexpress.com")
    assert is_ignored(f"angebote_at_deals_aliexpress_com_{RELAY_IDS}@privaterelay.appleid.com")
    assert not is_ignored(ALIEXPRESS_SENDER)


# ----- the parser, on invented mails -----


@pytest.mark.parametrize(
    ("step", "status", "words"),
    [
        ("Bestellbestätigung", ParcelStatus.PRE_TRANSIT, None),
        ("Versandbereit", ParcelStatus.PRE_TRANSIT, "Versandbereit"),
        ("Bestellung versandt", ParcelStatus.IN_TRANSIT, None),
        ("teilweise versandt", ParcelStatus.IN_TRANSIT, "Teilweise versandt"),
        ("Neuer Lieferstatus", ParcelStatus.IN_TRANSIT, None),
    ],
)
def test_steps_of_an_order(step, status, words):
    [u] = parse_mail(_msg(f"Bestellung 9999999999990901: {step}")).updates
    assert (u.number, u.status, u.status_text, u.title) == (ORDER, status, words, None)


def test_survey_without_the_confirmation_is_ignored():
    result = parse_mail(_msg("Bestellung 9999999999990901: wie ist es gelaufen?", "Hallo,\n"))
    assert result.ignored and not result.updates


def test_unknown_subjects_are_unrecognised():
    for subject in (
        "Bestellung 9999999999990901: etwas ganz Neues",
        "Packstück 00340999999999990902: etwas ganz Neues",
        "Ihr Konto",
    ):
        result = parse_mail(_msg(subject, f"Sendungsnummer {DHL}\n"))
        # (never the generic parser: the DHL number would become a second parcel)
        assert not result.ignored and result.updates == []


def test_item_names_per_layout():
    with_prices = (
        "Bestelldetails\nAufgegeben am Jan 01,2026, 12:00\nBeispiel Store\n"
        "Beispiel-Kabel USB-C auf...\nVariante A\n€ 1,99x1\n"
        "Beispiel-Lampe LED flach...\n€ 1,99 x2\nBestell-Nr.\n9999999999990901\n"
    )
    [u] = parse_mail(_msg("Bestellung 9999999999990901: Bestellung versandt", with_prices)).updates
    assert u.title == "Beispiel-Kabel USB-C auf… und 1 weiterer Artikel"
    # Without a variant the line above the item is the shop's: never the title.
    bare = "Aufgegeben am Jan 01,2026, 12:00\nBeispiel Store\nKabel 2 m\n€ 1,99x1\n"
    [u] = parse_mail(_msg("Bestellung 9999999999990901: Bestellung versandt", bare)).updates
    assert u.title == "Kabel 2 m"
    plain = "Bestellung verfolgen\nBeispiel-Sensor für Temp...\nVariante A, Bei... x1\n"
    [u] = parse_mail(_msg("Bestellung 9999999999990901: Bestellung versandt", plain)).updates
    assert u.title == "Beispiel-Sensor für Temp…"
    # A mail that shows only dots where the item stands, or a quantity below a label.
    for body in ("Sendungsverfolgung\n...\nBestellsumme 1,99€\n", "Bestellung verfolgen\nx1\n"):
        [u] = parse_mail(_msg("Bestellung 9999999999990901: teilweise versandt", body)).updates
        assert u.title is None


def test_estimate_must_be_a_day_that_is_not_long_gone():
    subject = "Bestellung 9999999999990901: Paket im Transit"
    for line, day in (
        ("20/10/2026", date(2026, 10, 20)),
        ("03/11/2026", date(2026, 11, 3)),  # day first, also when both could be a month
        ("31/02/2027", None),
        ("20/09/2026", None),
    ):
        [u] = parse_mail(_msg(subject, f"Voraussichtliche Zustellzeit\n{line}\n")).updates
        assert u.eta_date == day, line


def test_parcel_mail_reads_its_orders_from_html_links_only():
    html = (
        "<html><body><p>Ihr Paket ist angekommen.</p>"
        f'<a href="{LINK}9999999999990901&amp;x=1">Lieferung verfolgen</a>'
        f'<a href="https://www.aliexpress.com/x?a=1&amp;o_ids=9999999999990904">Artikel</a>'
        f'<a href="{LINK}9999999999990901">noch einmal</a>'
        '<a href="https://www.aliexpress.com/item/9999999999990999.html">Angebot</a>'
        '<a href="https://www.aliexpress.com/x?o_ids=9999999999990907%2C9999999999990904">x</a>'
        "</body></html>"
    )
    updates = parse_mail(_msg(f"Packstück {HERMES}: Vom Kurier abgeholt", html=html)).updates
    assert [u.number for u in updates] == [ORDER, "ALI9999999999990904", "ALI9999999999990907"]
    assert {(u.tracking_ref, u.tracking_carrier) for u in updates} == {(HERMES, "hermes")}


def test_parcel_mail_without_links_is_a_carrier_mail_about_an_aliexpress_shipment():
    [u] = parse_mail(_msg(f"Packstück {DHL} hat die Abflugregion verlassen")).updates
    assert (u.number, u.carrier, u.shop) == (DHL, "dhl", "aliexpress")
    assert (u.status, u.status_text) == (ParcelStatus.IN_TRANSIT, "Abflugregion verlassen")
    assert u.title == PARCEL_NAME and shop_of(PARCEL_NAME) == "aliexpress"
    [u] = parse_mail(_msg("Packstück AP99999999990905: Vom Kurier abgeholt")).updates
    # An unknown format without an order: nothing but the status, for the one order that fits.
    assert (u.number, u.carrier, u.shop, u.title) == ("", "aliexpress", "aliexpress", None)
    assert (u.tracking_ref, u.status_text) == (None, "Vom Kurier abgeholt")


def test_parse_aliexpress_returns_a_result():
    result = parse_aliexpress(_msg("Your order 9999999999990901 is closed"))
    assert result.ignored and not result.updates


def test_forwarded_by_hand_is_read_like_the_original():
    msg = EmailMessage(policy=policy.default)
    msg["From"] = "Max Mustermann <max@example.org>"
    msg["Subject"] = "WG: Bestellung 9999999999990901: Bestellung versandt"
    msg["Date"] = "Wed, 07 Oct 2026 09:00:00 +0200"
    msg.set_content(
        "Von: AliExpress <transaction@notice.aliexpress.com>\n"
        "Gesendet: Mittwoch, 7. Oktober 2026 08:00\nAn: max@example.org\n"
        "Betreff: Bestellung 9999999999990901: Bestellung versandt\n\n"
        "Hallo Max Mustermann,\nIhre Bestellung 9999999999990901 wurde versandt.\n"
    )
    assert forwarded_original(msg) is not None
    [u] = parse_mail(msg).updates
    assert (u.number, u.status) == (ORDER, ParcelStatus.IN_TRANSIT)


# ----- applying -----


def test_order_is_created_and_moves_forward_with_its_own_words():
    parcels: dict = {}
    order = "ALI9999999999990005"
    [created] = _apply(parcels, _msg("Bestellung 9999999999990005: Bestellbestätigung"))
    assert created.created and list(parcels) == [order]
    parcel = parcels[order]
    assert (parcel.carrier, parcel.carrier_mode, parcel.status) == (
        "aliexpress",
        "mail",
        ParcelStatus.PRE_TRANSIT,
    )
    assert parcel.result.status_text == "Bestellt"
    assert parcel.poll_target is None and parcel.track17_target is None
    assert carrier_name(parcel) == "AliExpress"
    [change] = _apply(parcels, SHIPPED)
    assert (change.old_status, parcel.status) == (
        ParcelStatus.PRE_TRANSIT,
        ParcelStatus.IN_TRANSIT,
    )
    # The first mail showed no item: the name comes with the first one that does.
    assert (parcel.name, parcel.mail_title) == ("Beispiel-Lampe LED flach…",) * 2
    _apply(parcels, HANDED_OVER)
    assert parcel.status is ParcelStatus.IN_TRANSIT
    assert [event.text for event in parcel.result.events] == [
        HANDED_OVER_TEXT,
        "Versendet",
        "Bestellt",
    ]
    assert list(parcels) == [order]


def test_order_never_moves_backwards():
    parcels: dict = {}
    _apply(parcels, IN_TRANSIT)
    [parcel] = parcels.values()
    before = parcel.result.to_dict()
    assert _apply(parcels, _msg("Bestellung 9999999999990006: versandfertig")) == [None]
    assert _apply(parcels, _msg("Bestellung 9999999999990006: Bestellauftrag bestätigt")) == [None]
    assert parcel.result.to_dict() == before
    assert parcel.result.eta_date == date(2024, 8, 30)


def test_mail_that_only_repeats_the_status_keeps_the_words_of_the_step():
    parcels: dict = {}
    _apply(parcels, ARRIVED)
    [parcel] = parcels.values()
    assert parcel.result.status_text == "Im Zielland angekommen"
    assert _apply(parcels, _msg("Bestellung 9999999999990007: Neuer Lieferstatus")) == [None]
    assert parcel.result.status_text == "Im Zielland angekommen"
    assert [event.text for event in parcel.result.events] == ["Im Zielland angekommen"]
    # A step with words of its own is news again.
    [change] = _apply(parcels, _msg("Bestellung 9999999999990007: Paket im Transit"))
    assert change is not None and parcel.result.status_text == "Paket im Transit"


def test_mail_with_another_item_is_never_a_further_shipment():
    parcels: dict = {}
    subject = "Bestellung 9999999999990901: Bestellung versandt"
    _apply(parcels, _msg(subject, "Bestellung verfolgen\nBeispiel-Kabel 2 m\nVariante A\nx1\n"))
    _apply(parcels, _msg(subject, "Bestellung verfolgen\nBeispiel-Lampe LED\nVariante A\nx1\n"))
    assert list(parcels) == [ORDER]
    assert parcels[ORDER].name == "Beispiel-Kabel 2 m"


def test_parcel_mail_attaches_the_number_to_the_order_instead_of_a_second_parcel():
    parcels: dict = {}
    order = "ALI9999999999990011"
    _apply(parcels, _msg("Bestellung 9999999999990011: Bestellung versandt"))
    parcels[order].next_poll_at = NOW + timedelta(hours=1)
    [change] = _apply(parcels, PARCEL_DHL)
    assert list(parcels) == [order] and not change.created
    parcel = parcels[order]
    assert (parcel.tracking_ref, parcel.tracking_carrier) == ("00340999999999990010", "dhl")
    assert parcel.poll_target == ("dhl", "00340999999999990010")  # asked at DHL from now on
    assert parcel.next_poll_at is None
    assert parcel.result.status_text == "Abflugregion verlassen"
    # The next mail about the parcel finds the same order.
    _apply(parcels, CUSTOMS)
    assert list(parcels) == [order]
    assert [event.text for event in parcel.result.events][:2] == [
        CUSTOMS_TEXT,
        "Abflugregion verlassen",
    ]
    assert not order_overdue(parcel, NOW.date() + timedelta(days=60))  # the carrier tells


def test_parcel_mail_creates_the_order_it_names_when_no_order_mail_came():
    parcels: dict = {}
    [change] = _apply(parcels, PARCEL_DHL)
    assert change.created and list(parcels) == ["ALI9999999999990011"]
    [parcel] = parcels.values()
    assert parcel.name == "Beispiel-Ersatzteil Getriebe Set für…"
    assert parcel.tracking_carrier == "dhl"


def test_parcel_mail_with_an_unknown_number_only_moves_the_orders():
    parcels: dict = {}
    _apply(parcels, _msg("Bestellung 9999999999990017: Bestellauftrag bestätigt"))
    _apply(parcels, PARCEL_UNKNOWN)
    assert len(parcels) == 4 and all(number.startswith("ALI") for number in parcels)
    for parcel in parcels.values():
        assert parcel.status is ParcelStatus.IN_TRANSIT
        assert parcel.result.status_text == "Vom Kurier abgeholt"
        assert parcel.tracking_ref is None and parcel.poll_target is None


def test_parcel_mail_without_order_merges_into_the_one_order_on_its_way():
    parcels: dict = {}
    _apply(parcels, _msg("Bestellung 9999999999990901: Bestellung versandt"))
    [change] = _apply(parcels, _msg(f"Packstück {DHL}: Vom Kurier abgeholt"))
    assert list(parcels) == [ORDER] and not change.created
    assert (parcels[ORDER].tracking_ref, parcels[ORDER].tracking_carrier) == (DHL, "dhl")
    assert parcels[ORDER].result.status_text == "Vom Kurier abgeholt"


def test_parcel_mail_without_order_is_a_parcel_of_its_own_when_two_orders_fit():
    parcels: dict = {}
    for number in ("9999999999990901", "9999999999990906"):
        _apply(parcels, _msg(f"Bestellung {number}: Bestellung versandt"))
    [change] = _apply(parcels, _msg(f"Packstück {HERMES}: In Ihrem Land / Ihrer Region"))
    assert change.created and set(parcels) == {ORDER, "ALI9999999999990906", HERMES}
    parcel = parcels[HERMES]
    assert (parcel.carrier, parcel.name) == ("hermes", PARCEL_NAME)
    assert parcel.poll_target == ("hermes", HERMES)
    # An unknown number says nothing then: no parcel, no change.
    assert _apply(parcels, _msg("Packstück AP99999999990905: Vom Kurier abgeholt")) == [None]
    assert len(parcels) == 3


def test_unknown_number_without_order_moves_the_one_order_that_fits():
    parcels: dict = {}
    assert _apply(parcels, _msg("Packstück AP99999999990905: Vom Kurier abgeholt")) == [None]
    assert parcels == {}
    _apply(parcels, _msg("Bestellung 9999999999990901: Bestellung versandt"))
    [change] = _apply(parcels, _msg("Zollabfertigung für AP99999999990905 wurde beendet"))
    assert change.parcel is parcels[ORDER] and list(parcels) == [ORDER]
    assert parcels[ORDER].result.status_text == CUSTOMS_TEXT
    assert parcels[ORDER].tracking_ref is None


def test_delivered_parcel_of_its_own_closes_the_order_later():
    """What v0.3.20 does for Amazon: the parcel's name tells the shop."""
    parcels: dict = {}
    for number in ("9999999999990901", "9999999999990906"):
        _apply(parcels, _msg(f"Bestellung {number}: Bestellung versandt"))
    _apply(parcels, _msg(f"Packstück {HERMES}: In Ihrem Land / Ihrer Region"))
    del parcels["ALI9999999999990906"]  # one order is left when the parcel arrives
    parcel = parcels[HERMES]
    delivered = NOW + timedelta(days=2)
    parcel.result = TrackingResult(
        ParcelStatus.DELIVERED, "Zugestellt", None, None, None, None, None, None, delivered,
        [TrackingEvent(delivered, "Zugestellt", None)],
    )
    order = fold_delivered(parcels, parcel, delivered)
    assert order is parcels[ORDER] and list(parcels) == [ORDER]
    assert (order.tracking_ref, order.status) == (HERMES, ParcelStatus.DELIVERED)


def test_confirmed_delivery_closes_an_open_order():
    parcels: dict = {}
    _apply(parcels, _msg("Bestellung 9999999999990021: Bestellung versandt"))
    [change] = _apply(parcels, DELIVERY_CONFIRMED)
    [parcel] = parcels.values()
    assert (change.old_status, parcel.status) == (ParcelStatus.IN_TRANSIT, ParcelStatus.DELIVERED)
    assert parcel.result.status_text == CONFIRMED_TEXT
    assert parcel.result.delivered_at == datetime(2023, 12, 23, 17, 4, 11, tzinfo=BERLIN)


def test_late_confirmation_leaves_a_real_delivery_as_it_is():
    parcels: dict = {}
    _apply(parcels, _msg("Bestellung 9999999999990021: Bestellung versandt"))
    [parcel] = parcels.values()
    arrived = datetime(2023, 12, 20, 11, 30, tzinfo=BERLIN)
    parcel.tracking_ref, parcel.tracking_carrier = DHL, "dhl"
    parcel.result = TrackingResult(
        ParcelStatus.DELIVERED, "Zugestellt", None, None, None, "Musterstadt", None, None,
        arrived, [TrackingEvent(arrived, "Zugestellt", "Musterstadt")],
    )
    before = parcel.result.to_dict()
    assert _apply(parcels, DELIVERY_CONFIRMED) == [None]
    assert parcel.result.to_dict() == before


def test_confirmation_makes_an_assumed_delivery_a_real_one():
    parcels: dict = {}
    _apply(parcels, _msg("Bestellung 9999999999990021: Bestellung versandt"))
    [parcel] = parcels.values()
    close_unconfirmed(parcel, NOW)
    assert parcel.assumed_delivered and parcel.result.status_text == ASSUMED_TEXT
    [change] = _apply(parcels, DELIVERY_CONFIRMED)
    assert change is not None and not parcel.assumed_delivered
    assert parcel.result.status_text == CONFIRMED_TEXT


def test_ignored_mails_change_nothing():
    parcels: dict = {}
    _apply(parcels, _msg("Bestellung 9999999999990015: Bestellung versandt"))
    before = {number: parcel.to_dict() for number, parcel in parcels.items()}
    for name in (RATING, REMINDER, OFFERS, CLOSED):
        assert _apply(parcels, name) == []
    assert {number: parcel.to_dict() for number, parcel in parcels.items()} == before


def test_overdue_order_is_closed_like_an_amazon_order():
    parcels: dict = {}
    sent = datetime(2024, 8, 23, 8, 0, tzinfo=UTC)
    _apply(parcels, IN_TRANSIT, sent)  # estimate: 30 August
    [parcel] = parcels.values()
    last = date(2024, 8, 30)
    assert not order_overdue(parcel, last + timedelta(days=ORDER_OVERDUE_DAYS))
    assert order_overdue(parcel, last + timedelta(days=ORDER_OVERDUE_DAYS + 1))
    close_unconfirmed(parcel, sent + timedelta(days=11))
    assert parcel.status is ParcelStatus.DELIVERED and parcel.assumed_delivered
    # Without any estimate the wait starts with the last change.
    parcels = {}
    _apply(parcels, _msg("Bestellung 9999999999990901: Bestellung versandt"))
    assert not order_overdue(parcels[ORDER], NOW.date() + timedelta(days=ORDER_NO_ETA_DAYS - 1))
    assert order_overdue(parcels[ORDER], NOW.date() + timedelta(days=ORDER_NO_ETA_DAYS))


# ----- everything a shop touches knows the new one -----


def test_names_notification_and_diagnostics_know_aliexpress():
    parcel = Parcel(ORDER, "aliexpress", "mail", "Beispiel-Kabel 2 m", NOW, NOW)
    assert neutral_name(parcel) == "AliExpress-Bestellung …0901"
    parcel.result = TrackingResult(
        ParcelStatus.DELIVERED, CONFIRMED_TEXT, None, None, None, None, None, None, NOW
    )
    assert build_notification(parcel, ParcelStatus.IN_TRANSIT, NOW) == (
        "Paket Tracker",
        "✅ Beispiel-Kabel 2 m (AliExpress) wurde zugestellt",
    )
    _, hidden = build_notification(parcel, ParcelStatus.IN_TRANSIT, NOW, hide_names=True)
    assert hidden == "✅ AliExpress-Bestellung …0901 wurde zugestellt"
    assert mask_number("ALI1234567890123456") == "ALI9999999999999999"
    assert known_sender_domain(ALIEXPRESS_SENDER) == "aliexpress.com"
    assert known_sender_domain("angebote@deals.aliexpress.com") == "aliexpress.com"
    assert known_sender_domain(RELAY) == "aliexpress.com"


def test_dhl_mail_that_names_aliexpress_merges_into_the_open_order():
    parcels: dict = {}
    _apply(parcels, _msg("Bestellung 9999999999990901: Bestellung versandt"))
    msg = EmailMessage(policy=policy.default)
    msg["From"] = "DHL Paket <noreply@dhl.de>"
    msg["Subject"] = "Ihre AliExpress Sendung ist unterwegs"
    msg["Date"] = "Wed, 07 Oct 2026 09:00:00 +0200"
    msg.set_content(f"Sendungsnummer {DHL}\n")
    [change] = _apply(parcels, msg)
    assert list(parcels) == [ORDER] and change.parcel.tracking_ref == DHL


# ----- Apple "E-Mail-Adresse verbergen" -----


@pytest.mark.parametrize(
    ("relayed", "original"),
    [
        (RELAY, "transaction@notice.aliexpress.com"),
        (f"versandbestaetigung_at_amazon_de_{RELAY_IDS}@privaterelay.appleid.com",
         "versandbestaetigung@amazon.de"),
        (f"shipment-tracking_at_amazon_de_{RELAY_IDS}@privaterelay.appleid.com",
         "shipment-tracking@amazon.de"),
        (f"noreply_at_dhl_de_{RELAY_IDS}@privaterelay.appleid.com", "noreply@dhl.de"),
        # any sender of a known domain, also of a sub-domain of it
        (f"zustellung_at_mail_dhl_de_{RELAY_IDS}@privaterelay.appleid.com",
         "zustellung@mail.dhl.de"),
        (f"noreply_at_service_dpd_de_{RELAY_IDS}@privaterelay.appleid.com",
         "noreply@service.dpd.de"),
        # an underscore of the local part is no dot: the known address tells
        (f"no_reply_at_dpd_at_{RELAY_IDS}@privaterelay.appleid.com", "no_reply@dpd.at"),
        (f"no-reply_at_gls-pakete_de_{RELAY_IDS}@privaterelay.appleid.com",
         "no-reply@gls-pakete.de"),
        (f"noreply_at_paketankuendigung_myhermes_de_{RELAY_IDS}@privaterelay.appleid.com",
         "noreply@paketankuendigung.myhermes.de"),
        (f"pkginfo_at_ups_com_{RELAY_IDS}@privaterelay.appleid.com", "pkginfo@ups.com"),
        (f"ebay_at_ebay_com_{RELAY_IDS}@privaterelay.appleid.com", "ebay@ebay.com"),
        (f"No-Reply_at_primevideo_com_{RELAY_IDS}@PrivateRelay.AppleID.com",
         "no-reply@primevideo.com"),
    ],
)
def test_unrelay_gives_the_original_sender(relayed, original):
    assert unrelay(relayed) == original


@pytest.mark.parametrize(
    "address",
    [
        "noreply@dhl.de",
        "max@example.org",
        # another relay domain, another shape, an unknown sender
        f"noreply_at_dhl_de_{RELAY_IDS}@relay.example.org",
        f"noreply_at_dhl_de_{RELAY_IDS}@evil.privaterelay.appleid.com.example.org",
        "noreply.dhl.de@privaterelay.appleid.com",
        "noreply_at_dhl_de@privaterelay.appleid.com",
        "noreply_at_dhl_de_0a1b2c3d4e@privaterelay.appleid.com",
        f"_at_dhl_de_{RELAY_IDS}@privaterelay.appleid.com",
        f"noreply_at_dhl_de_0a1b-2c_{RELAY_IDS}@privaterelay.appleid.com",
        f"max_at_example_org_{RELAY_IDS}@privaterelay.appleid.com",
        f"noreply_at_dhl_de_evil_example_{RELAY_IDS}@privaterelay.appleid.com",
        f"noreply_at_notdhl_de_{RELAY_IDS}@privaterelay.appleid.com",
        "",
    ],
)
def test_unrelay_leaves_everything_else_as_it_is(address):
    assert unrelay(address) == address
    assert known_sender_domain(address) == ("dhl.de" if address == "noreply@dhl.de" else "other")


def test_relayed_senders_are_routed_like_the_original():
    amazon = load_mail("124_bestellbestaetigung_bestellt.eml")
    expected = parse_mail(amazon)
    assert expected.amazon and expected.updates
    local = sender(amazon)[0].replace("@", "_at_").replace(".", "_")
    amazon.replace_header("From", f"Amazon.de <{local}_{RELAY_IDS}@privaterelay.appleid.com>")
    assert sender(amazon)[0] == "bestellbestaetigung@amazon.de"
    relayed = parse_mail(amazon)
    assert relayed.amazon and relayed.updates == expected.updates

    dhl = EmailMessage(policy=policy.default)
    dhl["From"] = f"DHL Paket <noreply_at_dhl_de_{RELAY_IDS}@privaterelay.appleid.com>"
    dhl["Subject"] = "Ihre Beispiel GmbH Sendung kommt heute"
    dhl["Date"] = "Wed, 07 Oct 2026 08:00:00 +0200"
    dhl.set_content(f"Sendungsnummer {DHL}\n")
    [u] = parse_mail(dhl).updates
    assert (u.number, u.carrier, u.status) == (DHL, "dhl", ParcelStatus.OUT_FOR_DELIVERY)
    assert u.title == "Beispiel GmbH"

    ignored = EmailMessage(policy=policy.default)
    ignored["From"] = f"Amazon <rueckgabe_at_amazon_de_{RELAY_IDS}@privaterelay.appleid.com>"
    ignored["Subject"] = "Rücksendung"
    ignored["Date"] = "Wed, 07 Oct 2026 08:00:00 +0200"
    ignored.set_content(f"Sendungsnummer {DHL}\n")
    assert parse_mail(ignored).ignored

    [u] = parse_mail(_msg("Bestellung 9999999999990901: Paket im Transit", sender_=RELAY)).updates
    assert (u.number, u.carrier) == (ORDER, "aliexpress")


def test_unknown_relayed_sender_is_an_ordinary_unknown_mail():
    msg = _msg(
        "Bestellung 9999999999990901: Paket im Transit",
        f"Sendungsnummer {DHL}\n",
        sender_=f"shop_at_example_org_{RELAY_IDS}@privaterelay.appleid.com",
    )
    assert sender(msg)[0].endswith("@privaterelay.appleid.com")
    [u] = parse_mail(msg).updates  # the generic parser: only the safe number
    assert (u.number, u.carrier, u.status) == (DHL, "dhl", None)
