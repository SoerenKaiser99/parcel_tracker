"""Constants for Paket Tracker."""

from datetime import timedelta

DOMAIN = "parcel_tracker"
VERSION = "0.3.6"

CONF_DHL_API_KEY = "dhl_api_key"
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
# Statuses a push notification can announce (in the order the options show them)
# and the ones ticked by default.
NOTIFY_EVENTS = ("out_for_delivery", "delivered", "awaiting_pickup", "exception")
DEFAULT_NOTIFY_EVENTS = ("out_for_delivery", "delivered")

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
# Polled only while their optional API is configured; otherwise mail-only.
OPTIONAL_API_CARRIERS = frozenset({"ups"})
# Carriers a user can pick for a manually added parcel.
SELECTABLE_CARRIERS = ("dhl", "dpd", "gls", "hermes", "ups")
# Their lookup often tells no delivery day: the day a mail named is kept then.
MAIL_ETA_CARRIERS = frozenset({"hermes", "gls"})
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
