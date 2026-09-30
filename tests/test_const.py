from custom_components.parcel_tracker import const


def test_carrier_groups():
    assert const.SHOP_CARRIERS == frozenset({"amazon", "ebay"})
    assert const.MAIL_CARRIERS == const.SHOP_CARRIERS
    assert const.OPTIONAL_API_CARRIERS == frozenset({"ups"})
    assert const.SELECTABLE_CARRIERS == ("dhl", "dpd", "hermes", "ups")
    assert const.CARRIER_NAMES == {
        "dhl": "DHL",
        "dpd": "DPD",
        "hermes": "Hermes",
        "ups": "UPS",
        "amazon": "Amazon",
        "ebay": "eBay",
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
