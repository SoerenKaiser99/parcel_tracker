from datetime import timedelta

from custom_components.parcel_tracker import const


def test_carrier_groups():
    assert const.SHOP_CARRIERS == frozenset({"amazon", "ebay"})
    assert const.MAIL_CARRIERS == const.SHOP_CARRIERS
    assert const.OPTIONAL_API_CARRIERS == frozenset({"ups"})
    assert const.SELECTABLE_CARRIERS == ("dhl", "dpd", "gls", "hermes", "ups")
    assert const.MAIL_ETA_CARRIERS == frozenset({"hermes", "gls"})
    assert const.GLS_MAX_EVENTS == 20
    assert const.CARRIER_NAMES == {
        "dhl": "DHL",
        "dpd": "DPD",
        "gls": "GLS",
        "hermes": "Hermes",
        "ups": "UPS",
        "amazon": "Amazon",
        "ebay": "eBay",
        "other": "17track",
    }


def test_ups_settings():
    assert (const.CONF_UPS_SECTION, const.CONF_UPS_CLIENT_ID, const.CONF_UPS_CLIENT_SECRET) == (
        "ups",
        "ups_client_id",
        "ups_client_secret",
    )
    assert const.CONF_UPS_BUDGET == "ups_monthly_budget"
    assert (const.DEFAULT_UPS_BUDGET, const.MIN_UPS_BUDGET, const.MAX_UPS_BUDGET) == (
        100,
        0,
        10000,
    )


def test_track17_settings():
    assert (const.CONF_TRACK17_API_KEY, const.CARRIER_OTHER, const.TRACK17_SOURCE) == (
        "track17_api_key",
        "other",
        "17track",
    )
    assert (const.TRACK17_BATCH, const.TRACK17_MAX_EVENTS, const.TRACK17_QUOTA_LOW) == (40, 20, 10)
    assert (const.TRACK17_FIRST_POLL, const.TRACK17_INTERVAL) == (
        timedelta(minutes=2),
        timedelta(hours=6),
    )
    assert (const.TRACK17_QUOTA_INTERVAL, const.TRACK17_QUOTA_RETRY) == (
        timedelta(days=1),
        timedelta(hours=1),
    )
    assert const.TRACK17_CARRIER_CODES == {
        "dpd": 100007,
        "dhl": 7041,
        "hermes": 100031,
        "ups": 100002,
        "gls": 101070,
    }
    assert const.TRACK17_CARRIER_NAMES == {
        100007: "DPD",
        7041: "DHL",
        100031: "Hermes",
        100002: "UPS",
        101070: "GLS",
    }
