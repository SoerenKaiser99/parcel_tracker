from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from email import policy
from email.message import EmailMessage

import pytest

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.mail import parse_mail
from custom_components.parcel_tracker.mail.ebay import EBAY_SENDER, order_number, parse_ebay
from custom_components.parcel_tracker.models import ParcelStatus

from .conftest import load_mail

SHIPPED = "104_ebay_ihre_sendung_ist_jetzt_beim_versand.eml"
DELIVERED = "106_ebay_bestellung_zugestellt.eml"


def _msg(subject: str, body: str) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = f"eBay <{EBAY_SENDER}>"
    msg["Subject"] = subject
    msg["Date"] = "Wed, 30 Sep 2026 08:00:00 -0700"
    msg.set_content(body)
    return msg


def test_order_number():
    assert order_number("99-00000-00001") == "EBAY990000000001"


def test_shipped_html_only_two_items_one_order():
    [u] = parse_ebay(load_mail(SHIPPED))
    assert (u.number, u.carrier) == ("EBAY992179315376", "ebay")
    assert u.status is ParcelStatus.IN_TRANSIT
    assert u.title == "Bambu Lab PLA Basic Filament Blue Bl… und 1 weiterer Artikel"
    assert len(u.title) <= 60
    assert (u.eta_date, u.eta_latest) == (date(2026, 1, 28), date(2026, 1, 29))
    assert u.shipping_carrier_hint == "hermes"
    assert u.delivered_at is None


def test_delivered_with_emoji_subject_and_drop_time():
    [u] = parse_ebay(load_mail(DELIVERED))
    assert (u.number, u.status) == ("EBAY990157856617", ParcelStatus.DELIVERED)
    assert u.title == "Crucial RAM XY00Z0ABC0000 16GB DDR4 2666MHz PC Desktop RAM…"
    assert u.delivered_at == datetime(2026, 5, 5, 15, 15, tzinfo=BERLIN)
    # The return notice mentions Hermes and DHL; only "Versanddienstleister:" counts.
    assert u.shipping_carrier_hint is None


def test_title_falls_back_to_subject_and_unknown_carrier_hint_is_kept():
    msg = _msg(
        "BESTELLUNG ZUGESTELLT: Kabel USB-C",
        "Bestellnummer:\n12-34567-89012\nVersanddienstleister:\nFedEx Express\n",
    )
    [u] = parse_ebay(msg)
    assert (u.number, u.title, u.shipping_carrier_hint) == (
        "EBAY123456789012",
        "Kabel USB-C",
        "FedEx Express",
    )
    assert u.delivered_at == datetime(2026, 9, 30, 17, 0, tzinfo=BERLIN)


def test_gls_as_shipping_carrier_becomes_the_carrier_key():
    msg = _msg(
        "BESTELLUNG ZUGESTELLT: Kabel USB-C",
        "Bestellnummer:\n12-34567-89012\nVersanddienstleister:\nGLS Paket\n",
    )
    [u] = parse_ebay(msg)
    assert u.shipping_carrier_hint == "gls"


@pytest.mark.parametrize(
    "subject", ["Sie haben einen Artikel gekauft", "Bewerten Sie Ihren Kauf", "Angebot"]
)
def test_other_subjects_are_unrecognised_and_never_generic(subject):
    msg = _msg(subject, "Artikelnr.: 999999999901\nBestellnummer: 99-00000-00001\n"
                        "Sendungsnummer JJD000012978217606560")
    assert parse_ebay(msg) == []
    result = parse_mail(msg)
    assert result.updates == [] and not result.amazon and not result.ignored


# ----- "Update zur Bestellung": shipped, with the carrier's number -----
UPDATE = "167_ebay_update_zur_bestellung.eml"


def _update(tracking: str, item: str = "Beispiel-Artikel\n") -> EmailMessage:
    return _msg(
        "🚚 Update zur Bestellung: Beispiel-Artikel",
        f"Sendungsnummer:{tracking}\nEinzelheiten zu Ihrem Kauf\n{item}"
        "Artikelnr.:\n999999999901\nBestellnummer:\n99-00000-00001\n",
    )


def test_update_mail_is_shipped_and_brings_the_dhl_number():
    [u] = parse_mail(load_mail(UPDATE)).updates
    assert (u.number, u.carrier, u.status) == ("EBAY990000000167", "ebay", ParcelStatus.IN_TRANSIT)
    # The price lines between title and item number are no title.
    assert u.title == "Beispiel Akku-LED-Baustrahler blau IP55"
    assert (u.eta_date, u.eta_latest) == (date(2025, 7, 1), date(2025, 7, 9))
    assert (u.tracking_ref, u.tracking_carrier) == ("00340999999999990167", "dhl")
    assert u.delivered_at is None


@pytest.mark.parametrize(
    ("tracking", "ref", "carrier"),
    [
        (" 00340999999999990901", "00340999999999990901", "dhl"),
        ("\n00340999999999990901", "00340999999999990901", "dhl"),  # on the line below
        (" H1000999999999990901", "H1000999999999990901", "hermes"),
        # 12 or 14 digits may be DHL, GLS, DPD or Hermes: the number is left alone
        (" 999999999902", None, None),
        (" 09999999999903", None, None),
    ],
)
def test_update_mail_takes_only_a_number_that_tells_its_carrier(tracking, ref, carrier):
    [u] = parse_mail(_update(tracking)).updates
    assert (u.number, u.status) == ("EBAY990000000001", ParcelStatus.IN_TRANSIT)
    assert (u.tracking_ref, u.tracking_carrier) == (ref, carrier)
    assert u.title == "Beispiel-Artikel"


def test_update_mail_title_falls_back_to_the_subject():
    msg = _msg("🚚 Update zur Bestellung: Beispiel-Artikel mit langem Na...",
               "Bestellnummer:\n99-00000-00001\n")
    [u] = parse_mail(msg).updates
    assert (u.title, u.tracking_ref) == ("Beispiel-Artikel mit langem Na", None)


def test_the_number_of_another_ebay_mail_is_never_taken():
    msg = _msg("Ihre Sendung ist jetzt beim Versanddienstleister!",
               "Sendungsnummer: 00340999999999990901\nBestellnummer:\n99-00000-00001\n")
    [u] = parse_mail(msg).updates
    assert (u.status, u.tracking_ref) == (ParcelStatus.IN_TRANSIT, None)


def test_item_numbers_never_become_tracking_numbers():
    for name in (SHIPPED, DELIVERED):
        assert all(u.number.startswith("EBAY") for u in parse_mail(load_mail(name)).updates)


def test_update_mail_about_two_orders_gives_neither_the_number():
    msg = _msg(
        "🚚 Update zur Bestellung: Beispiel-Artikel",
        "Sendungsnummer: 00340999999999990901\n"
        "Artikel A\nArtikelnr.:\n999999999901\nBestellnummer:\n99-00000-00001\n"
        "Artikel B\nArtikelnr.:\n999999999902\nBestellnummer:\n99-00000-00002\n",
    )
    first, second = parse_mail(msg).updates
    assert (first.number, second.number) == ("EBAY990000000001", "EBAY990000000002")
    assert (first.tracking_ref, second.tracking_ref) == (None, None)


# ----- "Zustellversuch": nobody was met -----
def test_delivery_attempt_takes_the_order_back_on_its_way_in_its_own_words():
    msg = _msg(
        "Zustellversuch: Beispiel-Artikel...",
        "Update zu Ihrer Bestellung.\nDHL Germany hat Sie leider nicht angetroffen.\n"
        "Sendungsnummer: 00340999999999990901\nBestellung nachverfolgen\n"
        "Beispiel-Artikel mit vollem Namen\nArtikelnr.:\n999999999901\n"
        "Bestellnummer:\n99-00000-00001\nZustellversuch:\nMo, 28. Sep 15:56 Ortszeit\n"
        "Versanddienstleister:\nDHL Germany\n",
    )
    [u] = parse_mail(msg).updates
    assert (u.number, u.status) == ("EBAY990000000001", ParcelStatus.IN_TRANSIT)
    assert (u.status_text, u.postponed) == ("Zustellung versucht", True)
    assert (u.title, u.shipping_carrier_hint) == ("Beispiel-Artikel mit vollem Namen", "dhl")
    assert (u.tracking_ref, u.tracking_carrier) == ("00340999999999990901", "dhl")
    assert (u.eta_date, u.delivered_at) == (None, None)


def test_other_ebay_mails_are_never_postponed():
    for name in (SHIPPED, DELIVERED, UPDATE):
        updates = parse_mail(load_mail(name)).updates
        assert all(not u.postponed and u.status_text is None for u in updates)


# ----- review: the carrier's mail came first -----
def test_update_takes_over_the_parcel_a_dhl_mail_made_before():
    from custom_components.parcel_tracker.mail.apply import apply_update
    from custom_components.parcel_tracker.mail.base import sent_at

    update = load_mail(UPDATE)
    [order] = parse_mail(update).updates
    assert order.tracking_carrier == "dhl"
    dhl = EmailMessage(policy=policy.default)
    dhl["From"] = "DHL Paket <noreply@dhl.de>"
    dhl["Subject"] = "Ihre Sendung ist unterwegs"
    dhl["Date"] = update["Date"]
    dhl.set_content(f"{order.tracking_ref}\n")
    [parcel] = parse_mail(dhl).updates
    parcels = {}
    now = sent_at(update)
    apply_update(parcels, parcel, now)
    assert list(parcels) == [order.tracking_ref]
    apply_update(parcels, order, now)
    # One entry is left: the order, asked about at DHL.
    assert list(parcels) == [order.number]
    assert parcels[order.number].tracking_ref == order.tracking_ref


def test_attempt_keeps_a_later_day_the_carrier_named_before():
    from custom_components.parcel_tracker.mail.apply import apply_update
    from custom_components.parcel_tracker.mail.base import sent_at

    update = load_mail(UPDATE)
    [order] = parse_mail(update).updates
    now = sent_at(update)
    parcels = {}
    apply_update(parcels, order, now)
    parcel = parcels[order.number]
    later = now.date() + timedelta(days=30)
    # The carrier's mail named a new day; eBay's "Zustellversuch" comes after it.
    apply_update(parcels, replace(order, eta_date=later, eta_latest=None), now)
    attempt = replace(order, eta_date=None, eta_latest=None, postponed=True,
                      status_text="Zustellung versucht")
    apply_update(parcels, attempt, now)
    assert (parcel.result.status_text, parcel.result.eta_date) == ("Zustellung versucht", later)
    # ... but a day that is today (or past) is the one the attempt takes back.
    apply_update(parcels, replace(order, eta_date=now.date(), eta_latest=None), now)
    apply_update(parcels, attempt, now)
    assert parcel.result.eta_date is None


# ----- "PAKET ZUGESTELLT": the HTML-only delivery mail (issue 32) -----
PARCEL_DELIVERED = "175_ebay_paket_zugestellt.eml"


def test_parcel_delivered_mail_delivers_the_order_with_the_subject_title():
    msg = load_mail(PARCEL_DELIVERED)
    [u] = parse_mail(msg).updates
    assert (u.number, u.carrier, u.status) == ("EBAY990909000909", "ebay", ParcelStatus.DELIVERED)
    # The body names no title ("Einzelheiten zum Kauf ansehen" is a link): the subject's,
    # without eBay's "...".
    assert u.title == "Beispiel Thermostatkopf M30x1,5 wei"
    assert u.delivered_at == datetime(2026, 10, 13, 15, 41, 17, tzinfo=BERLIN)
    assert u.tracking_ref is None and u.shipping_carrier_hint is None


def test_parcel_delivered_mail_never_takes_the_seller_or_the_item_number():
    dump = repr([asdict(u) for u in parse_mail(load_mail(PARCEL_DELIVERED)).updates])
    for secret in ("beispielverkaeufer", "999990000909", "Max"):
        assert secret not in dump, secret


@pytest.mark.parametrize(
    "subject",
    [
        "📦PAKET ZUGESTELLT: Kabel USB-C",
        "✅ 📦 PAKET ZUGESTELLT: Kabel USB-C",
        "WG: 📦BESTELLUNG ZUGESTELLT: Kabel USB-C",
        "📦 WG: BESTELLUNG ZUGESTELLT: Kabel USB-C",
        "[EXTERN] BESTELLUNG ZUGESTELLT: Kabel USB-C",
        "[EXTERN] 📦PAKET ZUGESTELLT: Kabel USB-C",
        "*** SPAM *** 📦BESTELLUNG ZUGESTELLT: Kabel USB-C",
        "Weitergeleitet: 📦PAKET ZUGESTELLT: Kabel USB-C",
        "TR: BESTELLUNG ZUGESTELLT: Kabel USB-C",
        "Info von eBay – PAKET ZUGESTELLT: Kabel USB-C",
    ],
)
def test_delivered_keyword_anywhere_in_the_subject_as_ebay_writes_it(subject):
    [u] = parse_ebay(_msg(subject, "Bestellnummer:\n12-34567-89012\n"))
    assert (u.number, u.status, u.title) == (
        "EBAY123456789012", ParcelStatus.DELIVERED, "Kabel USB-C",
    )


@pytest.mark.parametrize(
    "subject",
    [
        "Ihr Paket zugestellt: Kabel USB-C",
        "Paket zugestellt: Kabel USB-C",
        "Bestellung zugestellt: Kabel USB-C",
        "PAKET ZUGESTELLT Kabel USB-C",  # no colon
        "EXTRAPAKET ZUGESTELLT: Kabel USB-C",
    ],
)
def test_delivered_keyword_only_in_upper_case_with_its_colon(subject):
    assert parse_ebay(_msg(subject, "Bestellnummer:\n12-34567-89012\n")) == []


def test_title_line_in_the_body_still_wins_over_the_cut_subject():
    msg = _msg(
        "📦PAKET ZUGESTELLT: Beispiel Thermostatkopf M30x...",
        "Ihre Sendung ist angekommen. Viel Spaß beim Auspacken!\n"
        "Einzelheiten zum Kauf ansehen\nBeispiel Thermostatkopf M30x1,5 weiß\n"
        "Artikelnr.:\n999990000909\nBestellnummer:\n99-09090-00909\nVerkäufer:\nbeispielverkaeufer\n",
    )
    [u] = parse_ebay(msg)
    assert (u.number, u.title) == ("EBAY990909000909", "Beispiel Thermostatkopf M30x1,5 weiß")


# ----- the purchase confirmation: "Bestellt" -----
# (the layout since 2026: every value twice; two items of one order)
CONFIRMED = "180_ebay_ihre_bestellung_wurde_bestaetigt.eml"


def test_purchase_confirmation_is_ordered_with_its_items_and_days():
    [u] = parse_mail(load_mail(CONFIRMED)).updates
    assert (u.number, u.carrier, u.status) == ("EBAY143825253407", "ebay", ParcelStatus.PRE_TRANSIT)
    assert u.title == "Beispiel-Zulaufschlauch Aquastop 1,6m und 1 weiterer Artikel"
    # The head names the days with a sentence behind them; the line below "Lieferung ca.:"
    # further down names them alone.
    assert (u.eta_date, u.eta_latest) == (date(2026, 3, 27), date(2026, 4, 2))
    assert (u.tracking_ref, u.shipping_carrier_hint, u.delivered_at) == (None, None, None)


def test_the_layout_before_2026_with_the_price_once_names_its_item():
    body = ("Wir benachrichtigen Sie, wenn Ihre Bestellung verschickt wird.\n"
            "Beispiel-Artikel\neBay-Käuferschutz\nPreis:\nEUR 21,80\nArtikelnr.:\n999999999901\n"
            "Bestellnummer:\n99-00000-00001\n")
    [u] = parse_ebay(_msg("Bestellung bestätigt: Beispiel-Art...", body))
    assert u.title == "Beispiel-Artikel"


@pytest.mark.parametrize(
    "subject",
    [
        "Bestellung bestätigt: Beispiel-Artikel",
        "Max, Ihre Bestellung wurde bestätigt.",
        "Ihre Bestellung wurde bestätigt",
        "Ihre Bestellung ist eingegangen!",  # (2022 and 2023)
        "✅ KAUF BESTÄTIGT: Beispiel-Artikel",  # (until 2021)
    ],
)
def test_every_wording_of_the_purchase_confirmation_is_ordered(subject):
    [u] = parse_ebay(_msg(subject, "Bestellnummer: 99-00000-00001\n"))
    assert (u.number, u.status) == ("EBAY990000000001", ParcelStatus.PRE_TRANSIT)


@pytest.mark.parametrize(
    "label",
    ["Artikelpreis: EUR 2,32 (2 x EUR 1,16)", "Bestellnummer: 99-00000-00001",
     "SKU: Farbe: blau", "Gesamt: EUR 5,79", "Insgesamt: EUR 32,85", "Preis:"],
)
def test_older_confirmation_takes_no_label_with_its_value_as_its_name(label):
    # (these layouts list an item in lines of their own; only the subject's item is taken)
    body = (f"Beispiel-Artikel, lang\n{label}\nArtikelnr.: 999999999901\n"
            "Bestellnummer: 99-00000-00001\n")
    [u] = parse_ebay(_msg("Ihre Bestellung ist eingegangen!", body))
    assert u.title is None
    [u] = parse_ebay(_msg("✅ Kauf bestätigt: Beispiel-Artikel, la...", body))
    assert u.title == "Beispiel-Artikel, la"


def test_the_order_goes_on_from_its_confirmation_to_the_shipping_mail():
    from custom_components.parcel_tracker.mail.apply import apply_update
    from custom_components.parcel_tracker.mail.base import sent_at

    confirmed = load_mail(CONFIRMED)
    [order] = parse_mail(confirmed).updates
    shipped = _msg(
        "🚚 Update zur Bestellung: Beispiel-Zulaufschlauch",
        "Sendungsnummer:\n00340434161094042557\nEinzelheiten zu Ihrem Kauf\n"
        "Beispiel-Zulaufschlauch Aquastop 1,6m\nArtikelnr.:\n097209577403\n"
        "Bestellnummer:\n14-38252-53407\nBeispiel-Magnetventil für Waschmaschine\n"
        "Artikelnr.:\n675788922619\nBestellnummer:\n14-38252-53407\n",
    )
    [update] = parse_mail(shipped).updates
    parcels = {}
    apply_update(parcels, order, sent_at(confirmed))
    parcel = parcels[order.number]
    assert (parcel.status, parcel.name) == (ParcelStatus.PRE_TRANSIT, order.title)
    change = apply_update(parcels, update, sent_at(confirmed) + timedelta(days=2))
    # One order: "Bestellt", then "Versendet", asked about at DHL from now on.
    assert list(parcels) == [order.number] and change.old_status is ParcelStatus.PRE_TRANSIT
    assert (parcel.status, parcel.tracking_ref) == (ParcelStatus.IN_TRANSIT, "00340434161094042557")
    assert [e.text for e in parcel.result.events] == ["Versendet", "Bestellt"]


def test_a_confirmation_read_after_the_shipping_mail_takes_nothing_back():
    from custom_components.parcel_tracker.mail.apply import apply_update
    from custom_components.parcel_tracker.mail.base import sent_at

    confirmed = load_mail(CONFIRMED)
    [order] = parse_mail(confirmed).updates
    shipped = replace(order, status=ParcelStatus.IN_TRANSIT,
                      sent_at=sent_at(confirmed) + timedelta(days=1))
    parcels = {}
    apply_update(parcels, shipped, shipped.sent_at)
    before = asdict(parcels[order.number].result)
    assert apply_update(parcels, order, shipped.sent_at + timedelta(hours=1)) is None
    assert asdict(parcels[order.number].result) == before


@pytest.mark.parametrize("closing", ["unconfirmed", "received"])
def test_a_confirmation_read_after_the_order_was_closed_opens_nothing(closing):
    # Closed without a delivery mail, or marked as received by hand; then the old
    # confirmation is read (forwarded by hand, handed in later).
    from custom_components.parcel_tracker.mail.apply import (
        apply_update,
        close_unconfirmed,
        mark_received,
    )
    from custom_components.parcel_tracker.mail.base import sent_at

    confirmed = load_mail(CONFIRMED)
    [order] = parse_mail(confirmed).updates
    shipped = replace(order, status=ParcelStatus.IN_TRANSIT,
                      sent_at=sent_at(confirmed) + timedelta(days=1))
    parcels = {}
    apply_update(parcels, shipped, shipped.sent_at)
    parcel = parcels[order.number]
    closed_at = shipped.sent_at + timedelta(days=20)
    close = close_unconfirmed if closing == "unconfirmed" else mark_received
    close(parcel, closed_at)
    before = parcel.to_dict()
    assert apply_update(parcels, order, closed_at + timedelta(days=1)) is None
    assert parcel.to_dict() == before


# ----- strict review: what never is a title, and what never is a confirmation -----
ITEM_2026 = "{title}\nPreis:\n{price}\n{second}\nArtikelnr.:\n999999999901\n999999999901\n"


@pytest.mark.parametrize(
    ("subject", "body"),
    [
        ("Ihre Sendung ist jetzt beim Versanddienstleister!",
         "NEU: Beispiel Kabel\nArtikelnr.:\n999999999901\n"),
        ("Ihre Bestellung wurde bestätigt",
         ITEM_2026.format(title="NEU: Beispiel Kabel", price="EUR 7,95", second="EUR 7,95")),
        # (the total, then its parts)
        ("Ihre Bestellung wurde bestätigt",
         ITEM_2026.format(title="NEU: Beispiel Kabel", price="EUR 15,90", second="2 x EUR 7,95")),
    ],
)
def test_a_title_with_a_word_and_a_colon_is_still_the_title(subject, body):
    [u] = parse_ebay(_msg(subject, body + "Bestellnummer:\n99-00000-00001\n"))
    assert u.title == "NEU: Beispiel Kabel"


@pytest.mark.parametrize(
    "body",
    [
        "Einzelheiten zum Kauf ansehen\nPreis:\nEUR 15,90\n2 x EUR 7,95\n"
        "Artikelnr.:\n999999999901\n",
        "Einzelheiten zum Kauf ansehen\neBay-Käuferschutz\nPreis:\nEUR 5,00\n"
        "Artikelnr.:\n999999999901\n",
    ],
)
def test_neither_a_price_nor_the_buyer_protection_becomes_the_title(body):
    [u] = parse_ebay(_msg("📦PAKET ZUGESTELLT: Beispiel Kabel",
                          body + "Bestellnummer:\n99-00000-00001\n"))
    assert u.title == "Beispiel Kabel"  # (the subject's)


@pytest.mark.parametrize(
    "subject",
    ["Verkauf bestätigt: Beispiel-Artikel", "Vorbestellung bestätigt: Beispiel-Artikel",
     "Einkauf bestätigt: Beispiel-Artikel", "Abbestellung bestätigt: Beispiel-Artikel"],
)
def test_only_the_whole_words_are_a_confirmation(subject):
    assert parse_ebay(_msg(subject, "Bestellnummer: 99-00000-00001\n")) == []


@pytest.mark.parametrize(
    ("subject", "status"),
    [
        ("🚚 Update zur Bestellung: Kauf bestätigt: Beispiel-Set", ParcelStatus.IN_TRANSIT),
        ("📦PAKET ZUGESTELLT: Ihre Bestellung ist eingegangen Set", ParcelStatus.DELIVERED),
    ],
)
def test_words_of_the_confirmation_in_an_item_title_take_nothing_back(subject, status):
    [u] = parse_ebay(_msg(subject, "Bestellnummer: 99-00000-00001\n"))
    assert u.status is status


def test_a_subject_with_only_dots_gives_no_name_and_the_shipping_mail_names_the_order():
    from custom_components.parcel_tracker.mail.apply import apply_update

    [order] = parse_ebay(_msg("Bestellung bestätigt: ...", "Bestellnummer: 99-00000-00001\n"))
    assert order.title is None
    [shipped] = parse_ebay(_msg("Ihre Sendung ist jetzt beim Versanddienstleister!",
                                "Beispiel Kabel\nArtikelnr.:\n999999999901\n"
                                "Bestellnummer:\n99-00000-00001\n"))
    parcels = {}
    apply_update(parcels, order, order.sent_at)
    apply_update(parcels, shipped, order.sent_at + timedelta(days=1))
    assert parcels[order.number].name == "Beispiel Kabel"
