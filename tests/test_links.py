"""The carrier's public tracking page of a parcel (``links.tracking_url``)."""

from datetime import UTC, datetime

import pytest

from custom_components.parcel_tracker.links import tracking_url
from custom_components.parcel_tracker.models import Parcel

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
DHL = "00340999999999999901"
DHL_URL = f"https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode={DHL}"


def _parcel(number, carrier, **kwargs):
    return Parcel(number, carrier, "manual", None, NOW, NOW, **kwargs)


@pytest.mark.parametrize(
    ("carrier", "number", "url"),
    [
        ("dhl", DHL, DHL_URL),
        ("dpd", "09999999999901", "https://tracking.dpd.de/status/de_DE/parcel/09999999999901"),
        ("gls", "99999999901", "https://www.gls-pakete.de/sendungsverfolgung?match=99999999901"),
        (
            "hermes",
            "H1234567890123456789",
            "https://www.myhermes.de/empfangen/sendungsverfolgung/sendungsinformation"
            "#H1234567890123456789",
        ),
        (
            "ups",
            "1Z999AA10123456784",
            "https://www.ups.com/track?loc=de_DE&tracknum=1Z999AA10123456784",
        ),
    ],
)
def test_each_carrier_links_to_its_tracking_page(carrier, number, url):
    assert tracking_url(_parcel(number, carrier)) == url


def test_gls_links_with_eleven_digits():
    # Stored with the check digit (12 digits): GLS knows the parcel by the first 11.
    assert tracking_url(_parcel("999999999017", "gls")) == (
        "https://www.gls-pakete.de/sendungsverfolgung?match=99999999901"
    )


@pytest.mark.parametrize(
    ("carrier", "number", "url"),
    [
        ("dhl", "CQ 99/9&x=1#DE", "…verfolgen.html?piececode=CQ%2099%2F9%26x%3D1%23DE"),
        ("dpd", "0999 9/..?a", "https://tracking.dpd.de/status/de_DE/parcel/0999%209%2F..%3Fa"),
        ("hermes", "H99#<b>", "…sendungsinformation#H99%23%3Cb%3E"),
        ("ups", '1Z9"&loc=x', "https://www.ups.com/track?loc=de_DE&tracknum=1Z9%22%26loc%3Dx"),
        ("gls", "99 &ä", "https://www.gls-pakete.de/sendungsverfolgung?match=99%20%26%C3%A4"),
    ],
)
def test_the_number_is_url_encoded(carrier, number, url):
    built = tracking_url(_parcel(number, carrier))
    assert built.endswith(url.removeprefix("…"))
    if not url.startswith("…"):
        assert built == url


@pytest.mark.parametrize("shop", ["amazon", "ebay", "aliexpress"])
def test_a_shop_order_links_with_its_carrier_number(shop):
    order = _parcel(
        "AMZ99991565342587125", shop, tracking_ref=DHL, tracking_carrier="dhl"
    )
    assert tracking_url(order) == DHL_URL


def test_a_shop_order_with_a_gls_number_links_with_eleven_digits():
    order = _parcel(
        "EBAY990000000001", "ebay", tracking_ref="999999999017", tracking_carrier="gls"
    )
    assert tracking_url(order) == "https://www.gls-pakete.de/sendungsverfolgung?match=99999999901"


@pytest.mark.parametrize(
    "parcel",
    [
        # Shop orders without a carrier number.
        _parcel("AMZ99991565342587125", "amazon"),
        _parcel("EBAY990000000001", "ebay"),
        _parcel("ALI9999999999990001", "aliexpress"),
        # A carrier number whose carrier nobody knows, or one without a page of ours.
        _parcel("AMZ99991565342587125", "amazon", tracking_ref=DHL),
        _parcel("AMZ99991565342587125", "amazon", tracking_ref=DHL, tracking_carrier="other"),
        _parcel("AMZ99991565342587125", "amazon", tracking_ref=DHL, tracking_carrier="amazon"),
        # 17track only, also when 17track recognised one of our carriers.
        _parcel("999999999901", "other"),
        _parcel("999999999901", "other", track17=True, track17_carrier=101070),
        # "Automatisch" that found no carrier yet.
        _parcel("999999999901", None),
        # Unknown carriers and no number.
        _parcel("999999999901", "fedex"),
        _parcel("", "dhl"),
    ],
)
def test_no_link(parcel):
    assert tracking_url(parcel) is None
