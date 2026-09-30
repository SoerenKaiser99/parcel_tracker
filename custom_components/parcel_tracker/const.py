"""Constants for Paket Tracker."""

from datetime import timedelta

DOMAIN = "parcel_tracker"
VERSION = "0.1.5"

CONF_DHL_API_KEY = "dhl_api_key"
CONF_POSTCODE = "postcode"
CONF_KEEP_DELIVERED_DAYS = "keep_delivered_days"

DEFAULT_POSTCODE = ""
DEFAULT_KEEP_DELIVERED_DAYS = 3
MIN_KEEP_DELIVERED_DAYS = 1
MAX_KEEP_DELIVERED_DAYS = 30
STALE_REMOVE_DAYS = 30

TICK = timedelta(minutes=1)
DHL_DAILY_SOFT_LIMIT = 200
CARRIER_BROKEN_AFTER = timedelta(hours=24)

EVENT_STATUS_CHANGED = "parcel_tracker_status_changed"

STORAGE_KEY = DOMAIN
STORAGE_VERSION = 1

CARD_URL = "/parcel_tracker/parcel-tracker-card.js"
LOCAL_CARD_URL = "/local/parcel_tracker/parcel-tracker-card.js"

CARRIER_AUTO = "auto"
MAX_EVENTS = 5
