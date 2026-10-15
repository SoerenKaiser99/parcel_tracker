"""Tester mode of the anonymiser: address blocks with Austrian and Swiss postcodes, street
spellings and the label "an folgende Adresse zugestellt:" (invented names and places only).

Nothing is given via options: the generic scrubbing has to find the address on its own.
"""

from email.message import EmailMessage

from .test_anonymize_rules import _absent, _mail, _run, _text

DPD_AT = "DPD Versandinfo <no_reply@dpd.at>"
SHOP = "Paketflitzer <tracking@paketflitzer.example>"
BLOCK = "Max Mustermann\nMusterstraße 1\n12345 Musterstadt\n"


def _scrub(tmp_path, sender: str, subject: str, text: str) -> EmailMessage:
    _, [(_, msg)] = _run(tmp_path, [_mail(sender, subject, text)])
    return msg


def _dpd_at(recipient: str) -> str:
    return (
        "Liebe/r Paketempfänger/in,\n"
        "Ihr Paket 09999999999931 von Beispielshop wird voraussichtlich\n"
        "heute zwischen 13:00 und 14:00 Uhr\n"
        "an folgende Adresse zugestellt:\n"
        f"{recipient}\n"
        "Sie können das Paket nicht entgegennehmen? Dann wählen Sie eine andere Zustelloption.\n"
    )


def test_dpd_austria_example_block_is_replaced_as_a_whole(tmp_path):
    text = _dpd_at("Max Mustermann\nMusterstrasse 1\n9999 Musterstadt")
    msg = _scrub(tmp_path, DPD_AT, "Ihr DPD Paket kommt zwischen 13:00 und 14:00 Uhr", text)
    out = _text(msg)
    assert "an folgende Adresse zugestellt:\n" + BLOCK + "Sie können" in out
    # the example's own name and street are gone: only the placeholder block is left
    assert out.count("Max Mustermann") == 1 and out.count("Muster") == 3
    _absent(msg, "musterstrasse", "9999 ")


def test_dpd_austria_block_with_a_real_looking_recipient(tmp_path):
    text = _dpd_at("Erika Sonnenschein\nLindengasse 12/3/7\n6789 Anderswo") + (
        "Erika Sonnenschein, wir freuen uns auf Sie.\n"
    )
    msg = _scrub(tmp_path, DPD_AT, "Ihr DPD Paket kommt zwischen 13:00 und 14:00 Uhr", text)
    assert "an folgende Adresse zugestellt:\n" + BLOCK in _text(msg)
    # what the block taught is replaced wherever it stands
    _absent(msg, "erika", "sonnenschein", "lindengasse", "6789", "anderswo")


def test_label_at_the_end_of_a_sentence_line_starts_the_block(tmp_path):
    text = (
        "Ihr Paket wird heute an folgende Adresse zugestellt:\n"
        "Erika Sonnenschein\nBirkenstrasse 4\n6789 Anderswo\nIhr DPD Team\n"
    )
    msg = _scrub(tmp_path, DPD_AT, "Ihr Paket kommt heute", text)
    assert "an folgende Adresse zugestellt:\n" + BLOCK + "Ihr DPD Team" in _text(msg)
    _absent(msg, "erika", "sonnenschein", "birkenstrasse", "6789", "anderswo")


def test_austrian_and_swiss_blocks_without_a_label(tmp_path):
    text = (
        "Ihre Bestellung ist unterwegs.\n\n"
        "Erika Sonnenschein\nBirkenstrasse 4\n6789 Anderswo\n\n"
        "Jonas Kieselbach\nSeeuferweg 9\nCH-8999 Anderswil\n\n"
        "Lena Wiesengrund\nHauptplatz 3/Top 5\nA-5999 Irgendwo\n\nEnde\n"
    )
    msg = _scrub(tmp_path, SHOP, "Ihre Bestellung", text)
    out = _text(msg)
    assert out.count(BLOCK) == 3 and out.endswith("\nEnde\n")
    _absent(msg, "erika", "sonnenschein", "birkenstrasse", "6789", "anderswo", "jonas",
            "kieselbach", "seeuferweg", "8999", "anderswil", "lena", "wiesengrund",
            "hauptplatz", "5999", "irgendwo")


def test_german_blocks_with_every_street_spelling(tmp_path):
    text = (
        "Lieferadresse:\nRalf Tannenzapf\nKastanienallee 3\n67890 Anderswo\n\n"
        "Zustelladresse:\nRalf Tannenzapf\nBirkenstr. 4\n67890 Anderswo\n\n"
        "Wir liefern an\nTannenzapf\nAm Mühlendamm 5\n67890 Anderswo\n\n"
        "Rheinufer 7, 67891 Anderswo-Süd\n"
        "Sägeweg 3, 9876 Spanstadt\n"
    )
    msg = _scrub(tmp_path, SHOP, "Ihre Bestellung", text)
    out = _text(msg)
    assert "Lieferadresse:\n" + BLOCK in out and "Zustelladresse:\n" + BLOCK in out
    # a name line above a street line goes even if it is a single word
    assert "Wir liefern an\nMax Mustermann\nMusterstraße 1\n12345 Musterstadt\n" in out
    _absent(msg, "ralf", "tannenzapf", "kastanienallee", "birkenstr", "mühlendamm", "67890",
            "anderswo", "rheinufer", "sägeweg", "9876", "spanstadt")


def test_companies_and_numbers_that_are_no_address_stay(tmp_path):
    text = (
        "Holzwurm Möbel GmbH\nSpanplatz 12\n9876 Spanstadt\n\n"
        "Artikel 3\n1299 Stück\n\n"
        "Bestellt am 12.10.2026\n2026 Highlights\n"
    )
    out = _text(_scrub(tmp_path, SHOP, "Ihre Bestellung", text))
    assert "Holzwurm Möbel GmbH\nMusterstraße 1\n12345 Musterstadt\n" in out
    # four digits below a line without a street word are no postcode
    assert "Artikel 3\n1299 Stück\n" in out
    assert "2026 Highlights\n" in out


def test_ebay_seller_written_twice_goes_in_both_lines(tmp_path):
    text = (
        "Ihre Sendung ist angekommen. Viel Spaß beim Auspacken!\n"
        "Artikelnr.:\n999990000909\nBestellnummer:\n99-09090-00909\n"
        "Verkäufer:\nbeispielverkaeufer\nbeispielverkaeufer\neBay-Käuferschutz\n"
    )
    msg = _scrub(tmp_path, "eBay <ebay@ebay.com>", "📦PAKET ZUGESTELLT: Beispiel", text)
    assert "Verkäufer:\nbeispielshop\nbeispielshop\neBay-Käuferschutz\n" in _text(msg)
    _absent(msg, "beispielverkaeufer")


def test_status_word_above_a_street_is_no_name(tmp_path):
    words = ["Abholbereit", "Zugestellt", "Hinterlegt", "Abholort", "Bereit", "Abgestellt",
             "Trafik", "Abgegeben", "Zustellung", "Lieferung", "Sendung", "Paket", "Status"]
    text = "".join(f"{word}\nHauptstraße 1\n50667 Köln\n\n" for word in words)
    text += "Abholort:\nHauptstraße 1\n50667 Köln\n"
    out = _text(_scrub(tmp_path, SHOP, "Ihr Paket", text))
    for word in words:
        assert f"{word}\nMusterstraße 1\n12345 Musterstadt\n" in out, word
    assert "Abholort:\nMusterstraße 1\n12345 Musterstadt\n" in out
    assert "Max Mustermann" not in out


def test_learnt_seller_handle_is_replaced_only_as_a_whole_word(tmp_path):
    # ("versand" itself counts as a company word and is kept; "sendung" is learnt)
    text = (
        "Versanddienstleister:\nDHL\nSendungsnummer:\nJJD000390007812345678\n"
        "Verkäufer:\nsendung\nsendung\nFragen an sendung? sendung.\n"
    )
    out = _text(_scrub(tmp_path, "eBay <ebay@ebay.com>", "Update zur Bestellung: Beispiel", text))
    assert "Versanddienstleister:\nDHL\nSendungsnummer:\n" in out
    assert "Verkäufer:\nbeispielshop\nbeispielshop\nFragen an beispielshop? beispielshop.\n" in out


def test_learnt_seller_handle_with_dots_and_digits_as_a_whole_word(tmp_path):
    text = (
        "Verkäufer:\nkiesel.24-de_x\nkiesel.24-de_x\n"
        "Gruß von kiesel.24-de_x, nicht von kiesel.24-de_xy oder mykiesel.24-de_x.\n"
    )
    out = _text(_scrub(tmp_path, "eBay <ebay@ebay.com>", "Update zur Bestellung: Beispiel", text))
    assert "Verkäufer:\nbeispielshop\nbeispielshop\nGruß von beispielshop, nicht" in out
