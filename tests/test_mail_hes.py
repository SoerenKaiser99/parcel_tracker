from datetime import date, datetime, timedelta
from email import policy
from email.message import EmailMessage

from custom_components.parcel_tracker.carriers.base import BERLIN
from custom_components.parcel_tracker.links import tracking_url
from custom_components.parcel_tracker.mail import known_sender_domain, parse_mail
from custom_components.parcel_tracker.mail.apply import apply_update
from custom_components.parcel_tracker.models import Parcel, ParcelStatus, TrackingResult

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


def test_shipper_line_without_a_name_names_nothing():
    for shipper in ("</td>", "12345", "Hermes Einrichtungs Service"):
        html = f"<p>Deine Sendung von:<br>{shipper}</p><p>Sendungsnummer: {SHOWN}</p>"
        [u] = parse_mail(_msg(f"Auftragseingang deiner Sendung {SHOWN}", html)).updates
        assert u.title is None, shipper


# Subjects (and texts) of HES mails we have never seen: none of them may set a status, a
# day or a window - the lookup at myhes.de tells those. Review of #70, all rounds.
UNKNOWN_MAILS = (
    # "delivered" somewhere on the way: would end the lookup for good
    ("Deine Sendung wurde an das Depot geliefert", ""),
    ("Deine Sendung wurde ins Lager geliefert", ""),
    ("Deine Sendung wurde vom Händler an uns ausgeliefert", ""),
    ("Deine Sendung wurde umgeplant und soll am 22.10.2026 geliefert werden", ""),
    ("Dein Liefertermin wurde vereinbart: Sendung kann am 22.10.2026 zugestellt werden", ""),
    ("Deine Sendung wurde an das Depot übergeben und kann bald ausgeliefert werden", ""),
    ("Deine Sendung wird am 22.10.2026 zugestellt", ""),
    # "today" that is no delivery today
    ("Deine Sendung geht morgen auf Tour", ""),
    ("Wir haben heute deine Lieferung für den 24.10. geplant", ""),
    ("Heute: Infos zu deiner Lieferung", ""),
    ("Deine Sendung ist heute im Depot eingetroffen", ""),
    # a day and the depot's service hours below it
    (
        "Information zu deinem Liefertermin",
        "<p>Liefertermin: 22.10.2026</p><p>Servicezeiten: Mo–Fr 08:00 - 18:00 Uhr</p>",
    ),
    ("Information zu deinem Liefertermin", "<p>Wir melden uns am 15.10.2026.</p>"),
    ("Information zu deinem Liefertermin", "<p>Bestellt am 01.10.2026</p>"),
    # even what reads like the delivery: the lookup says so within minutes
    ("Deine Sendung wurde zugestellt", ""),
    ("Deine Sendung kommt heute", "<p>Wir kommen zwischen 13:00 und 15:00 Uhr.</p>"),
)


def test_no_other_mail_sets_a_status_a_day_or_a_window():
    for subj, text in UNKNOWN_MAILS:
        html = f"<p>Sendungsnummer: {SHOWN}</p>{text}"
        [u] = parse_mail(_msg(subj, html)).updates
        assert u.number == NUMBER, subj
        assert u.status is None, subj
        assert (u.eta_date, u.eta_from, u.eta_to, u.delivered_at) == (None,) * 4, subj


def test_a_mail_about_a_known_parcel_asks_myhes_and_changes_nothing():
    """The status stays what the lookup said; the mail only makes it be asked again."""
    known = TrackingResult(
        ParcelStatus.AT_DELIVERY_DEPOT, "Im Depot", date(2026, 10, 22), None, None, None,
        None, None, None, [],
    )
    parcel = Parcel(NUMBER, "hes", "mail", "Sofa", NOW, NOW, result=known)
    parcel.next_poll_at = NOW + timedelta(minutes=30)
    parcels = {NUMBER: parcel}
    for subj, text in (*UNKNOWN_MAILS, (f"Auftragseingang deiner Sendung {SHOWN}", "")):
        parcel.next_poll_at = NOW + timedelta(minutes=30)
        html = f"<p>Sendungsnummer: {SHOWN}</p>{text}"
        [u] = parse_mail(_msg(subj, html)).updates
        apply_update(parcels, u, NOW)
        assert parcel.status is ParcelStatus.AT_DELIVERY_DEPOT, subj
        assert parcel.result.eta_date == date(2026, 10, 22), subj
        assert parcel.next_poll_at is None, subj
