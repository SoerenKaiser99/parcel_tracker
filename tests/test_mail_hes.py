from datetime import date, datetime
from email import policy
from email.message import EmailMessage

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.links import tracking_url
from custom_components.parcel_tracker.mail import known_sender_domain, parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.models import Parcel, ParcelStatus

from .conftest import load_mail

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=BERLIN)
NUMBER = "999999999999999999903"
SHOWN = "9999999999999 99999903"
FROM = "Hermes.Serviceteam@HES.de <hermes.serviceteam@hes.de>"
LINK = f"https://myhes.de/de/tracking/{NUMBER}?utm_source=cm&amp;utm_medium=email"

# The "Auftragseingang" mail as HES sends it (HTML only), the recipient's name left out.
RECEIVED_HTML = f"""<html><body><table><tr><td>Auftragseingang</td></tr>
<tr><td><p>Guten Tag Erika Musterfrau,</p>
<p>Dein Auftrag wurde vom Hermes Einrichtungs Service übernommen und wird
schnellstmöglich für dich eingeplant. Sobald wir alle Informationen haben und ein
konkreter Liefertermin feststeht, melden wir uns umgehend aktiv bei dir. Wir teilen dir
dann das genaue Lieferdatum und ein voraussichtliches Zeitfenster mit.</p>
<p>Vielen Dank für dein Verständnis</p>
<p><b>Deine Sendung von:</b><br>Beispiel Matratzen GmbH (Hammer)</p>
<p><b>Sendungsnummer:</b><br><a href="{LINK}">{SHOWN}</a></p>
<p>Viele Grüße</p></td></tr></table></body></html>"""


def _msg(subject: str, html: str, from_: str = FROM) -> EmailMessage:
    msg = EmailMessage(policy=policy.default)
    msg["From"] = from_
    msg["Subject"] = subject
    msg["Date"] = "Mon, 19 Oct 2026 07:39:00 +0200"
    msg.set_content(html, subtype="html")
    return msg


def _received() -> EmailMessage:
    return _msg(f"Auftragseingang deiner Sendung {SHOWN}", RECEIVED_HTML)


def test_received_mail():
    [u] = parse_mail(_received()).updates
    assert (u.number, u.carrier, u.status, u.title) == (
        NUMBER, "hes", ParcelStatus.PRE_TRANSIT, "Beispiel Matratzen GmbH",
    )
    assert u.eta_date is None


def test_hes_is_a_known_sender():
    assert known_sender_domain("hermes.serviceteam@hes.de") == "hes.de"


def test_number_from_the_text_without_a_link():
    html = RECEIVED_HTML.replace(f'<a href="{LINK}">{SHOWN}</a>', SHOWN)
    [u] = parse_mail(_msg(f"Auftragseingang deiner Sendung {SHOWN}", html)).updates
    assert u.number == NUMBER


def test_number_from_the_subject_alone():
    html = "<p>Dein Auftrag wurde übernommen.</p>"
    [u] = parse_mail(_msg(f"Auftragseingang deiner Sendung {SHOWN}", html)).updates
    assert (u.number, u.title) == (NUMBER, None)


def test_delivery_day_and_window():
    html = (
        "<p>Dein Liefertermin steht fest: Mittwoch, 21.10.2026 zwischen 10:00 und 14:00 Uhr."
        f"</p><p>Deine Sendung von:<br>Beispiel Matratzen GmbH</p><p>Sendungsnummer:<br>{SHOWN}</p>"
    )
    [u] = parse_mail(_msg(f"Dein Liefertermin für deine Sendung {SHOWN}", html)).updates
    assert u.status is ParcelStatus.IN_TRANSIT
    assert u.eta_date == date(2026, 10, 21)
    assert (u.eta_from.hour, u.eta_to.hour) == (10, 14)


def test_delivered_and_not_delivered():
    html = f"<p>Sendungsnummer: {SHOWN}</p>"
    [done] = parse_mail(_msg("Deine Sendung wurde zugestellt", html)).updates
    assert done.status is ParcelStatus.DELIVERED
    [failed] = parse_mail(_msg("Deine Sendung konnte nicht zugestellt werden", html)).updates
    assert failed.status is None


def test_parcel_is_polled_at_hes_and_links_to_myhes():
    parcels: dict[str, Parcel] = {}
    [u] = parse_mail(_received()).updates
    change = apply_update(parcels, u, NOW)
    parcel = parcels[NUMBER]
    assert change.created
    assert (parcel.carrier, parcel.name, parcel.status) == (
        "hes", "Beispiel Matratzen GmbH", ParcelStatus.PRE_TRANSIT,
    )
    # The tracking page of myhes.de is asked about it.
    assert parcel.poll_target == ("hes", NUMBER)
    assert tracking_url(parcel) == f"https://myhes.de/de/tracking/{NUMBER}"


def test_existing_unnamed_parcel_gets_the_shop():
    parcel = Parcel(NUMBER, "hes", "mail", None, NOW, NOW)
    parcels = {NUMBER: parcel}
    [u] = parse_mail(_received()).updates
    apply_update(parcels, u, NOW)
    assert parcel.name == "Beispiel Matratzen GmbH"


def test_real_received_mail():
    """HES's own mail: its text/plain part is the HTML source as well."""
    [u] = parse_mail(load_mail("209_hes_auftragseingang.eml")).updates
    assert (u.number, u.carrier, u.status, u.title) == (
        "999999999999999999902", "hes", ParcelStatus.PRE_TRANSIT, "Emma Matratzen GmbH",
    )


def test_announced_delivery_is_no_delivery():
    """"wird am … zugestellt" announces the day, it never closes the parcel."""
    html = f"<p>Sendungsnummer: {SHOWN}</p><p>Liefertermin: 21.10.2026</p>"
    subjects = (
        "Deine Sendung wird am 21.10.2026 zugestellt",
        "Deine Sendung wird geliefert, sobald der Termin feststeht",
    )
    for subj in subjects:
        [u] = parse_mail(_msg(subj, html)).updates
        assert u.status is ParcelStatus.IN_TRANSIT, subj
        assert u.delivered_at is None


def test_am_only_as_a_word_and_never_the_day_of_the_order():
    """"Hamburg", "Team" and "Bestellt am" name no delivery day."""
    html = (
        "<p>Dein Team aus Hamburg: Bestellt am 01.10.2026.</p>"
        f"<p>Sendungsnummer: {SHOWN}</p>"
    )
    [u] = parse_mail(_msg("Information zu deinem Liefertermin", html)).updates
    assert u.status is ParcelStatus.IN_TRANSIT
    assert u.eta_date is None
    for line in (
        "Auftrag erteilt am  01.10.2026",
        "Aufgegeben am\n01.10.2026",
        "Bestellung eingegangen am 01.10.2026",
        "Liefertermin: folgt. Bestellt am 01.10.2026",
        "Liefertermin: folgt. Bestelldatum 01.10.2026",
    ):
        text = f"<p>{line}</p><p>Sendungsnummer: {SHOWN}</p>"
        [u] = parse_mail(_msg("Information zu deinem Liefertermin", text)).updates
        assert u.eta_date is None, line
    html += "<p>Wir liefern am 22.10.2026 zwischen 8:00 und 12:00 Uhr.</p>"
    [u] = parse_mail(_msg("Dein Liefertermin steht fest", html)).updates
    assert u.eta_date == date(2026, 10, 22)


def test_today_takes_only_a_window_with_zwischen():
    """"heute": the depot's service hours are no window, "zwischen … und …" is."""
    html = (
        f"<p>Sendungsnummer: {SHOWN}</p>"
        "<p>Dein Depot: Servicezeiten Mo.-Fr. 08:00 - 17:00 Uhr</p>"
    )
    [u] = parse_mail(_msg("Deine Sendung kommt heute", html)).updates
    assert u.status is ParcelStatus.OUT_FOR_DELIVERY
    assert u.eta_date == date(2026, 10, 19)
    assert (u.eta_from, u.eta_to) == (None, None)
    html += "<p>Wir kommen zwischen 13:00 und 15:00 Uhr.</p>"
    [u] = parse_mail(_msg("Deine Sendung kommt heute", html)).updates
    assert (u.eta_from.hour, u.eta_to.hour) == (13, 15)


def test_shipper_line_without_a_name_names_nothing():
    for shipper in ("</td>", "12345", "Hermes Einrichtungs Service"):
        html = f"<p>Deine Sendung von:<br>{shipper}</p><p>Sendungsnummer: {SHOWN}</p>"
        [u] = parse_mail(_msg(f"Auftragseingang deiner Sendung {SHOWN}", html)).updates
        assert u.title is None, shipper


def test_what_may_be_delivered_is_not_delivered():
    """Review of #70: a participle that belongs to an announcement never closes the parcel."""
    html = f"<p>Sendungsnummer: {SHOWN}</p><p>Wir liefern am 22.10.2026.</p>"
    for subj in (
        "Deine Sendung wurde umgeplant und soll am 22.10.2026 geliefert werden",
        "Dein Liefertermin wurde vereinbart: Sendung kann am 22.10.2026 zugestellt werden",
        "Deine Sendung wurde an das Depot übergeben und kann bald ausgeliefert werden",
        "Deine Sendung wurde eingeplant, sie soll am 22.10.2026 geliefert werden",
        "Deine Sendung wurde voraussichtlich am 22.10.2026 zugestellt",
        "Deine Sendung wurde für die Zustellung geplant",
    ):
        [u] = parse_mail(_msg(subj, html)).updates
        assert u.status is ParcelStatus.IN_TRANSIT, subj
        assert u.delivered_at is None, subj
        assert u.eta_date == date(2026, 10, 22), subj


def test_what_was_delivered_is_delivered():
    html = f"<p>Sendungsnummer: {SHOWN}</p>"
    for subj in (
        "Deine Sendung wurde zugestellt",
        "Deine Sendung wurde heute erfolgreich zugestellt",
        "Deine Sendung wurde am 20.10.2026 geliefert",
        "Deine Bestellung wurde ausgeliefert",
    ):
        [u] = parse_mail(_msg(subj, html)).updates
        assert u.status is ParcelStatus.DELIVERED, subj


def test_today_only_with_a_word_for_the_delivery():
    html = f"<p>Sendungsnummer: {SHOWN}</p>"
    [u] = parse_mail(_msg("Deine Sendung ist heute im Depot eingetroffen", html)).updates
    assert u.status is ParcelStatus.IN_TRANSIT
    assert u.eta_date is None
    for subj in ("Deine Sendung kommt heute", "Heute in Zustellung: deine Sendung",
                 "Deine Sendung wird heute geliefert", "Deine Sendung ist heute auf Tour",
                 "Deine Sendung befindet sich auf Tour"):
        [u] = parse_mail(_msg(subj, html)).updates
        assert u.status is ParcelStatus.OUT_FOR_DELIVERY, subj


def test_am_is_a_delivery_day_only_on_a_line_about_the_delivery():
    """"Wir melden uns am …" names the day of the call, not of the delivery."""
    html = (
        f"<p>Sendungsnummer: {SHOWN}</p>"
        "<p>Wir melden uns am 15.10.2026 telefonisch, um den Termin abzustimmen.</p>"
    )
    [u] = parse_mail(_msg("Information zu deinem Liefertermin", html)).updates
    assert u.status is ParcelStatus.IN_TRANSIT
    assert u.eta_date is None
    for line in (
        "Rückfragen bis am 20.10.2026 an das Depot. Lieferung folgt.",
        "Du hast am 18.10.2026 deinen Termin bestätigt. Wir liefern bald.",
    ):
        text = f"<p>Sendungsnummer: {SHOWN}</p><p>{line}</p>"
        [u] = parse_mail(_msg("Information zu deinem Liefertermin", text)).updates
        assert u.eta_date is None, line
    text = (
        f"<p>Sendungsnummer: {SHOWN}</p>"
        "<p>Du hast am 18.10.2026 deinen Termin bestätigt. Wir liefern am 22.10.2026.</p>"
    )
    [u] = parse_mail(_msg("Information zu deinem Liefertermin", text)).updates
    assert u.eta_date == date(2026, 10, 22)
    html += "<p>Deine Sendung wird am 23.10.2026 zwischen 9:00 und 13:00 Uhr zugestellt.</p>"
    [u] = parse_mail(_msg("Information zu deinem Liefertermin", html)).updates
    assert u.eta_date == date(2026, 10, 23)
    assert (u.eta_from.hour, u.eta_to.hour) == (9, 13)


def test_appointment_and_tomorrow_are_on_the_way():
    html = f"<p>Sendungsnummer: {SHOWN}</p>"
    for subj in ("Terminbestätigung für deine Lieferung am 22.10.2026",
                 "Erinnerung: Deine Lieferung morgen zwischen 10 und 14 Uhr"):
        [u] = parse_mail(_msg(subj, html)).updates
        assert u.status is ParcelStatus.IN_TRANSIT, subj
