"""Constants for Paket Tracker."""

from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Protocol

DOMAIN = "parcel_tracker"
VERSION = "0.3.21"

CONF_DHL_API_KEY = "dhl_api_key"
CONF_COUNTRY = "country"
CONF_POSTCODE = "postcode"
CONF_KEEP_DELIVERED_DAYS = "keep_delivered_days"
CONF_MAIL_SECTION = "mail"
CONF_MAIL_ENABLED = "mail_enabled"
CONF_IMAP_HOST = "imap_host"
CONF_IMAP_USER = "imap_user"
CONF_IMAP_PASSWORD = "imap_password"
CONF_MOVE_PROCESSED = "move_processed"
CONF_READ_OTP = "read_otp"
CONF_MAIL_INTERVAL = "mail_interval"
CONF_UPS_SECTION = "ups"
CONF_UPS_ENABLED = "ups_enabled"
CONF_UPS_CLIENT_ID = "ups_client_id"
CONF_UPS_CLIENT_SECRET = "ups_client_secret"
CONF_UPS_BUDGET = "ups_monthly_budget"
CONF_TRACK17_API_KEY = "track17_api_key"
CONF_NOTIFY_SECTION = "notify"
CONF_NOTIFY_ENABLED = "notify_enabled"
CONF_NOTIFY_TARGETS = "notify_targets"
CONF_NOTIFY_EVENTS = "notify_events"

# Countries on offer (ISO 3166-1 alpha-2, lower case: selector option values double as
# translation keys, which hassfest only accepts as [a-z0-9-_]+). An entry without one
# behaves as Germany.
COUNTRIES = ("de", "at", "ch")
DEFAULT_COUNTRY = "de"
# Digits of a postcode per country.
POSTCODE_DIGITS = {"de": 5, "at": 4, "ch": 4}
DEFAULT_POSTCODE = ""
DEFAULT_KEEP_DELIVERED_DAYS = 3
MIN_KEEP_DELIVERED_DAYS = 1
MAX_KEEP_DELIVERED_DAYS = 30
STALE_REMOVE_DAYS = 30
DEFAULT_IMAP_HOST = "imap.mailbox.org"
DEFAULT_MOVE_PROCESSED = True
DEFAULT_READ_OTP = False
DEFAULT_MAIL_INTERVAL = 5
MIN_MAIL_INTERVAL = 1
MAX_MAIL_INTERVAL = 60
DEFAULT_UPS_BUDGET = 100
MIN_UPS_BUDGET = 0
MAX_UPS_BUDGET = 10000

TICK = timedelta(minutes=1)
DHL_DAILY_SOFT_LIMIT = 200
CARRIER_BROKEN_AFTER = timedelta(hours=24)

EVENT_STATUS_CHANGED = "parcel_tracker_status_changed"
# Status changes found while Home Assistant starts are announced once it has started,
# but never later than this after the first refresh (a start can hang for minutes).
ANNOUNCE_MAX_WAIT = timedelta(seconds=120)
# Statuses a push notification can announce (in the order the options show them)
# and the ones ticked by default.
NOTIFY_EVENTS = ("out_for_delivery", "delivered", "awaiting_pickup", "exception")
DEFAULT_NOTIFY_EVENTS = ("out_for_delivery", "delivered")
# A stored notify target is either the ID of a notify entity ("notify.tablet") or,
# with this prefix, the name of a classic notify service ("service:pushover" is the
# service notify.pushover). No entity ID contains a colon, so the two never collide.
NOTIFY_SERVICE_PREFIX = "service:"
# Registered under "notify" but no targets of their own: the service for notify
# entities and the notifications inside Home Assistant.
NOTIFY_SERVICES_HIDDEN = frozenset({"send_message", "persistent_notification"})
# The catch-all notify.notify: on offer, but last.
NOTIFY_SERVICE_ALL = "notify"
# Classic services of the Home Assistant app; they understand ``data.tag``.
NOTIFY_APP_SERVICE_PREFIX = "mobile_app_"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

CARD_URL = "/parcel_tracker/parcel-tracker-card.js"
LOCAL_CARD_URL = "/local/parcel_tracker/parcel-tracker-card.js"

CARRIER_AUTO = "auto"
MAX_EVENTS = 5
GLS_MAX_EVENTS = 20  # GLS history entries kept per parcel

# Shops whose orders become parcels ("AMZ…", "EBAY…"); only mails or a merged
# carrier number (tracking_ref) tell their status, the order itself is never polled.
SHOP_CARRIERS = frozenset({"amazon", "ebay"})
MAIL_CARRIERS = SHOP_CARRIERS
# A shop order without a carrier number is known only from mails, and a marketplace
# seller's parcel often gets no "delivered" mail. Such an order is closed on its own
# ("Abgeschlossen ohne Zustellbestätigung") once its last delivery day lies more than
# ORDER_OVERDUE_DAYS full days back; without any delivery day ORDER_NO_ETA_DAYS days
# after its last change. A mail that changes the order starts the wait anew.
ORDER_OVERDUE_DAYS = 3
ORDER_NO_ETA_DAYS = 14
# Polled only while their optional API is configured; otherwise mail-only.
OPTIONAL_API_CARRIERS = frozenset({"ups"})
# Carriers a user can pick for a manually added parcel.
SELECTABLE_CARRIERS = ("dhl", "dpd", "gls", "hermes", "ups")
# Their lookup often tells no delivery day: the day a mail named is kept then. (DPD names
# a day only once the parcel is out for delivery; its announcement mail gives an estimate.)
MAIL_ETA_CARRIERS = frozenset({"hermes", "gls", "dpd"})
# DHL may take an estimate back and compute it anew: a day and window it named are kept
# while the parcel is on its way, until that day is over.
KEEP_ETA_UNTIL_DAY_CARRIERS = frozenset({"dhl"})
# "Automatisch" with a number no rule takes: with a DHL key DHL is asked (it knows all
# its own formats, e.g. Express). At most this often while DHL cannot be reached; an
# answer "not found" ends it at once.
DHL_FALLBACK_TRIES = 3
# "Automatisch" with 12 digits that no carrier knows (or without a DHL key): GLS is asked
# once with all 12 digits, as GLS only finds a parcel for the right check digit. At most
# this often while GLS cannot be reached; an answer (hit or "not found") ends it at once.
GLS_PROBE_TRIES = 3
# A carrier without own connection: status only via 17track (needs a 17track key).
CARRIER_OTHER = "other"
CARRIER_NAMES = {
    "dhl": "DHL",
    "dpd": "DPD",
    "gls": "GLS",
    "hermes": "Hermes",
    "ups": "UPS",
    "amazon": "Amazon",
    "ebay": "eBay",
    "other": "17track",
}

# Base of the error backoff (5, 10, 20, 40, 60 min); the regular schedule is an option.
MAIL_INTERVAL = timedelta(minutes=5)
MAIL_MAX_BACKOFF = timedelta(minutes=60)
# Older mails (e.g. a forwarded archive) are only marked read, never applied.
MAIL_MAX_AGE = timedelta(days=14)
MAIL_DEDUP_KEEP = 500
AMAZON_UNRECOGNIZED_LIMIT = 5
FOLDER_PROCESSED = "Paket-Tracker-Verarbeitet"
FOLDER_UNRECOGNIZED = "Paket-Tracker-Nicht-erkannt"

# 17track (optional, registration only on explicit request; tracking API v2.2)
TRACK17_SOURCE = "17track"
TRACK17_BATCH = 40  # numbers per API call
TRACK17_MAX_EVENTS = 20
TRACK17_FIRST_POLL = timedelta(minutes=2)
TRACK17_INTERVAL = timedelta(hours=6)  # 17track itself updates every 6-12 h
TRACK17_QUOTA_INTERVAL = timedelta(days=1)
TRACK17_QUOTA_RETRY = timedelta(hours=1)
TRACK17_QUOTA_LOW = 10
# 17track carrier codes of our carriers (sent when registering) and names of known codes.
TRACK17_CARRIER_CODES = {
    "dpd": 100007,
    "dhl": 7041,
    "hermes": 100031,
    "ups": 100002,
    "gls": 101070,
}
TRACK17_CARRIER_NAMES = {
    100007: "DPD",
    7041: "DHL",
    100031: "Hermes",
    100002: "UPS",
    101070: "GLS",
}


class _Entry(Protocol):
    data: Mapping[str, Any]
    options: Mapping[str, Any]


def known_country(value: object) -> str:
    """``value`` (any case) as one of ``COUNTRIES``, else Germany."""
    if isinstance(value, str) and (country := value.strip().lower()) in COUNTRIES:
        return country
    return DEFAULT_COUNTRY


def entry_country(entry: _Entry) -> str:
    """The country of a config entry: options before data, Germany if none is stored."""
    return known_country(entry.options.get(CONF_COUNTRY, entry.data.get(CONF_COUNTRY)))
