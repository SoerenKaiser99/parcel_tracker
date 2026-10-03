"""Card: 17track button and confirmation, carrier 'other', subline and logo (run in Node)."""

import json
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const defined = {};
const sandbox = {
  HTMLElement: class {},
  customElements: { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } },
  window: {},
};
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(process.argv[1], "utf8")
    + "\n;globalThis.__t17 = track17State; globalThis.__can = canTrack17;"
    + "globalThis.__ask = track17Question; globalThis.__sub = subText;"
    + "globalThis.__err = errorLine; globalThis.__svc = SERVICE_ERRORS;"
    + "globalThis.__stale = staleLine;",
  sandbox,
);
const Card = defined["parcel-tracker-card"];
const card = new Card();
card.setConfig({});
const quota = (state) => ({
  states: { "sensor.paket_tracker_17track_kontingent": { state, last_updated: "t" } },
});
const on = { on: true, rest: 150 };
const off = { on: false, rest: null };
const out = {};
out.state = {
  missing: sandbox.__t17({ states: {} }),
  unavailable: sandbox.__t17(quota("unavailable")),
  unknown: sandbox.__t17(quota("unknown")),
  rest: sandbox.__t17(quota("150")),
};
out.can = {
  dpd: sandbox.__can({ carrier: "dpd" }, "in_transit", on),
  noKey: sandbox.__can({ carrier: "dpd" }, "in_transit", off),
  delivered: sandbox.__can({ carrier: "dpd" }, "delivered", on),
  registered: sandbox.__can({ carrier: "dpd", track17: true }, "in_transit", on),
  amazon: sandbox.__can({ carrier: "amazon" }, "pre_transit", on),
  ebay: sandbox.__can({ carrier: "ebay" }, "in_transit", on),
  amazonRef: sandbox.__can({ carrier: "amazon", tracking_ref: "H9999999999999999901" },
    "in_transit", on),
  otherLost: sandbox.__can({ carrier: "other", track17: false }, "in_transit", on),
};
out.ask = { rest: sandbox.__ask(150), none: sandbox.__ask(null) };
out.sub = {
  via: sandbox.__sub("Unterwegs",
    { carrier: "dpd", location: "Köln", location_source: "17track" }, "in_transit"),
  own: sandbox.__sub("Unterwegs", { carrier: "dpd", location: "Bonn" }, "in_transit"),
  other: sandbox.__sub("Unterwegs", { carrier: "other", carrier_name: "GLS", location: "Köln",
    location_source: "17track" }, "in_transit"),
  otherUnknown: sandbox.__sub("Unterwegs", { carrier: "other" }, "in_transit"),
};
out.err = sandbox.__err({ last_error: "track17_not_registered", carrier: "other" });
// 17track covers a carrier that delivers nothing: its "nothing" errors are not shown.
const covered = (last_error, state, track17 = true, carrier = "dhl") =>
  sandbox.__err({ last_error, carrier, track17 }, state);
out.cover = {
  missingKey: covered("missing_key", "in_transit"),
  notFound: covered("not_found", "out_for_delivery", true, "ups"),
  carrierNotFound: covered("carrier_not_found", "delivered", true, null),
  noStatusYet: covered("not_found", "unknown"),
  missingKeyNoStatus: covered("missing_key", "unknown"),
  notRegistered: covered("not_found", "in_transit", false),
  unavailable: covered("unavailable", "in_transit"),
  auth: covered("auth", "in_transit"),
  rateLimited: covered("rate_limited", "in_transit"),
  budget: covered("ups_budget", "in_transit", true, "ups"),
};
// ... and the generic "Carrier nicht erreichbar" line does not take their place.
const staleOf = (last_error, track17) => sandbox.__stale(
  { last_error, carrier: "dhl", track17, stale: true, last_update: "2026-09-29T10:00:00+00:00" },
  "in_transit",
);
out.stale = {
  covered: staleOf("missing_key", true),
  uncovered: staleOf("not_found", false),
  missingKey: staleOf("missing_key", false),
  unavailable: staleOf("unavailable", true),
  unnamed: staleOf("something_new", true),
};
out.svc = sandbox.__svc;
out.icon = card._icon("other");
out.hermes = card._icon("hermes");
card._hass = { states: {}, entities: {} };
const parcel = { number: "X1", carrier: "dpd" };
out.button = card._track17Html(parcel, "in_transit", on);
out.hidden = card._track17Html(parcel, "in_transit", off);
card._t17ask.add("X1");
out.confirm = card._track17Html(parcel, "in_transit", on);
out.sig = card._signature();

// No number left (rest === 0): registering is not offered at all.
const none = { on: true, rest: 0 };
card._t17ask.clear();
out.zero = {
  state: sandbox.__t17(quota("0")),
  can: sandbox.__can({ carrier: "dpd" }, "in_transit", none),
  unknownRest: sandbox.__can({ carrier: "dpd" }, "in_transit", { on: true, rest: null }),
  button: card._track17Html(parcel, "in_transit", none),
};

// A tiny stand-in for the shadow DOM: elements remember listeners and innerHTML writes.
const fakeEl = () => {
  const el = {
    hidden: false, value: "", writes: 0, html: "", listeners: {}, option: false,
    kids: {}, focused: 0, attrs: {},
    addEventListener(name, fn) { el.listeners[name] = fn; },
    setAttribute(name, value) { el.attrs[name] = String(value); },
    focus() { el.focused += 1; },
    querySelector(sel) {
      if (sel === 'option[value="other"]') {
        return el.option ? { remove() { el.option = false; } } : null;
      }
      return (el.kids[sel] ||= fakeEl());
    },
    insertAdjacentHTML(_where, html) { if (html.includes('value="other"')) el.option = true; },
  };
  Object.defineProperty(el, "innerHTML", {
    get() { return el.html; },
    set(v) { el.html = v; el.writes += 1; },
  });
  return el;
};
const els = {};
const root = {
  innerHTML: "", activeElement: null,
  getElementById(id) { return (els[id] ||= fakeEl()); },
};
card.attachShadow = () => root;
card._build();
const box = root.getElementById("addask");
box.hidden = true;

const sel = els.car;
card._syncOther(on);
out.option = { offered: sel.option };
sel.value = "other";
card._syncOther(none);
out.option.atZero = sel.option;
out.option.valueAtZero = sel.value;
card._syncOther({ on: true, rest: null });
out.option.unknownRest = sel.option;
card._syncOther(off);
out.option.noKey = sel.option;

// The add confirmation: rebuilt only when its text changes, gone at rest === 0.
card._addAsk = true;
card._renderAddAsk(on);
out.addask = {
  shown: !box.hidden, text: box.html.includes("von 150 verbleibenden"), writes: [box.writes],
};
card._renderAddAsk(on);
out.addask.writes.push(box.writes);
card._renderAddAsk({ on: true, rest: 149 });
out.addask.writes.push(box.writes);
card._renderAddAsk(none);
out.addask.atZero = { hidden: box.hidden, asking: card._addAsk, html: box.html };
card._addAsk = true;
card._renderAddAsk({ on: true, rest: 149 });
out.addask.shownAgain = !box.hidden && box.html.includes("von 149 verbleibenden");

// Typing another number dismisses the confirmation.
card._hass = quota("149");
card._hass.entities = {};
els.num.listeners.input();
out.addask.afterTyping = { hidden: box.hidden, asking: card._addAsk };

// "Abbrechen" and "Fortfahren" remove their own buttons: the focus goes to the number field.
const added = [];
card._hass.callService = async (...args) => { added.push(args); };
card._addAsk = true;
card._renderAddAsk({ on: true, rest: 149 });
box.kids["#addask-no"].listeners.click();
out.addask.afterNo = { hidden: box.hidden, focused: els.num.focused, added: added.length };
els.num.value = "99999999999903";
sel.value = "other";
card._addAsk = true;
card._renderAddAsk({ on: true, rest: 149 });
box.kids["#addask-yes"].listeners.click();
out.addask.afterYes = {
  hidden: box.hidden, focused: els.num.focused,
  added: added.map((a) => [a[1], a[2].number, a[2].carrier]),
};

// After a 17track confirm the focus goes to the parcel's toggle.
const handlers = {};
const item = { querySelector(q) { return { addEventListener(name, fn) { handlers[q] = fn; } }; } };
card._wireActions(item, parcel);
card._call = async () => true;
card._renderList = () => { out.focusAfterConfirm = card._pendingFocus; };
card._t17ask.add("X1");
handlers['[data-a="t17-confirm"]']().then(() => {
  out.askingAfterConfirm = card._t17ask.has("X1");
  console.log(JSON.stringify(out));
});
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node not installed")
    run = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, text=True, check=True
    )
    return json.loads(run.stdout)


def test_key_presence_and_remaining_numbers_come_from_the_quota_sensor(card):
    assert card["state"] == {
        "missing": {"on": False, "rest": None},
        "unavailable": {"on": False, "rest": None},
        "unknown": {"on": True, "rest": None},
        "rest": {"on": True, "rest": 150},
    }


def test_button_only_where_registering_makes_sense(card):
    assert card["can"] == {
        "dpd": True, "noKey": False, "delivered": False, "registered": False,
        "amazon": False, "ebay": False, "amazonRef": True, "otherLost": True,
    }


def test_question_names_the_remaining_numbers(card):
    assert card["ask"]["rest"] == "Verbraucht 1 von 150 verbleibenden 17track-Nummern. Fortfahren?"
    assert card["ask"]["none"] == "Verbraucht 1 17track-Nummer. Fortfahren?"


def test_button_and_inline_confirmation(card):
    assert "Details über 17track holen" in card["button"]
    assert 'data-a="t17"' in card["button"]
    assert card["hidden"] == ""
    assert "Verbraucht 1 von 150 verbleibenden 17track-Nummern. Fortfahren?" in card["confirm"]
    assert 'data-a="t17-confirm"' in card["confirm"] and 'data-a="t17-cancel"' in card["confirm"]
    assert "|t17:X1" in card["sig"]


def test_subline_says_where_the_place_comes_from(card):
    assert card["sub"] == {
        "via": "DPD · Unterwegs · Köln · Ort via 17track",
        "own": "DPD · Unterwegs · Bonn",
        "other": "GLS · Unterwegs · Köln",
        "otherUnknown": "17track · Unterwegs",
    }


def test_other_logo_is_a_neutral_dot_with_17(card):
    assert 'aria-label="other"' in card["icon"]
    assert 'fill="#757575"' in card["icon"] and ">17</text>" in card["icon"]
    assert "<path" not in card["icon"]
    assert 'fill="#0091CD"' in card["hermes"] and ">H</text>" in card["hermes"]


def test_german_error_texts(card):
    assert card["err"] == "Bei 17track nicht mehr angemeldet"
    svc = card["svc"]
    assert svc["track17_carrier"] == "17track hat den Carrier dieser Nummer nicht erkannt."
    assert svc["track17_quota"] == "Das 17track-Kontingent ist erschöpft."
    assert svc["track17_auth"].startswith("17track hat den API-Key abgelehnt")
    assert svc["track17_unavailable"].startswith("17track ist gerade nicht erreichbar")
    assert {"track17_off", "track17_not_possible"} <= set(svc)


def test_source_has_the_other_option_and_services():
    text = BUNDLED_CARD.read_text(encoding="utf-8")
    assert '<option value="other">Andere (über 17track)</option>' in text
    assert '"track_17track"' in text
    assert 'id="addask"' in text


def test_nothing_is_offered_when_no_number_is_left(card):
    zero = card["zero"]
    assert zero["state"] == {"on": True, "rest": 0}
    assert zero["can"] is False and zero["button"] == ""
    assert zero["unknownRest"] is True  # count not read yet: still offered
    assert card["option"] == {
        "offered": True, "atZero": False, "valueAtZero": "auto", "unknownRest": True,
        "noKey": False,
    }


def test_add_confirmation_is_rebuilt_only_when_its_text_changes(card):
    ask = card["addask"]
    assert ask["shown"] and ask["text"]
    assert ask["writes"] == [1, 1, 2]  # same question: buttons (and focus) stay
    assert ask["atZero"] == {"hidden": True, "asking": False, "html": ""}
    assert ask["shownAgain"] is True


def test_typing_a_number_dismisses_the_add_confirmation(card):
    assert card["addask"]["afterTyping"] == {"hidden": True, "asking": False}


def test_focus_goes_to_the_parcel_toggle_after_a_17track_confirm(card):
    assert card["focusAfterConfirm"] == {"number": "X1", "a": "toggle"}
    assert card["askingAfterConfirm"] is False


def test_carrier_gap_errors_are_hidden_while_17track_shows_a_status(card):
    cover = card["cover"]
    assert (cover["missingKey"], cover["notFound"], cover["carrierNotFound"]) == (None,) * 3
    # Nothing to show yet, or not registered at 17track: the error stays.
    assert cover["noStatusYet"] == "Noch keine Daten vom Carrier"
    assert cover["notRegistered"] == cover["noStatusYet"]
    # Every other error is still said.
    assert cover["unavailable"] == "Carrier gerade nicht erreichbar"
    assert cover["auth"] == "DHL-API-Key abgelehnt – in den Integrations-Optionen prüfen"
    assert cover["rateLimited"] == "Zu viele Abfragen – nächster Versuch später"
    assert cover["budget"].startswith("UPS-Monatsbudget verbraucht")
    stale = card["stale"]
    assert stale["covered"] is None
    assert stale["uncovered"] == cover["noStatusYet"]
    # A missing key is never a line in the row (v0.3.12): the expanded details say it.
    assert cover["missingKeyNoStatus"] is None and stale["missingKey"] is None
    assert stale["unavailable"] == "Carrier gerade nicht erreichbar"
    assert stale["unnamed"].startswith("Stand ") and stale["unnamed"].endswith(
        ", Carrier nicht erreichbar"
    )


def test_focus_goes_to_the_number_field_after_the_add_confirmation(card):
    ask = card["addask"]
    assert ask["afterNo"] == {"hidden": True, "focused": 1, "added": 0}
    assert ask["afterYes"] == {
        "hidden": True, "focused": 2, "added": [["add_parcel", "99999999999903", "other"]],
    }
