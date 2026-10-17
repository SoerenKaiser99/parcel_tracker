"""Card: "Erhalten" marks a parcel as received by hand, asked twice (run in Node)."""

import json
import re
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")
DHL = "https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode=X1"

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
    + "\n;globalThis.__label = stateLabel; globalThis.__eta = etaText;"
    + "globalThis.__sub = subText; globalThis.__svc = SERVICE_ERRORS;"
    + "globalThis.__can = canMarkReceived;",
  sandbox,
);
const Card = defined["parcel-tracker-card"];
const card = new Card();
card.setConfig({});
card._hass = { states: {}, entities: {} };
const parcel = { number: "X1", carrier: "dhl", name: "Oma", tracking_url: process.argv[2] };
const order = { number: "AMZ99991565342587125", carrier: "amazon", tracking_url: process.argv[2] };
const out = {};
out.html = {
  transit: card._actionsHtml(parcel, "in_transit"),
  pickup: card._actionsHtml(parcel, "awaiting_pickup"),
  unknown: card._actionsHtml(parcel, "unknown"),
  problem: card._actionsHtml(parcel, "exception"),
  ordered: card._actionsHtml({ number: "EVT999999901", carrier: "eventim" }, "pre_transit"),
  both: card._actionsHtml(order, "in_transit"),
  delivered: card._actionsHtml(parcel, "delivered"),
  manual: card._actionsHtml({ ...parcel, manual_delivered: true }, "delivered"),
  assumed: card._actionsHtml({ ...order, assumed_delivered: true }, "delivered"),
};
out.can = {
  transit: sandbox.__can({}, "in_transit"),
  delivered: sandbox.__can({}, "delivered"),
  assumed: sandbox.__can({ assumed_delivered: true }, "delivered"),
  assumedOpenAgain: sandbox.__can({ assumed_delivered: true }, "in_transit"),
};
const manual = { carrier: "dhl", carrier_name: "DHL", manual_delivered: true,
  delivered_at: new Date().toISOString(), days_until: null };
out.shown = {
  label: sandbox.__label({ state: "delivered", attributes: manual }),
  plain: sandbox.__label(
    { state: "delivered", attributes: { ...manual, manual_delivered: false } }),
  open: sandbox.__label({ state: "in_transit", attributes: manual }),
  right: sandbox.__eta("delivered", manual),
  sub: sandbox.__sub("Erhalten", manual, "delivered"),
};
out.error = sandbox.__svc.already_delivered;

// Clicks: the handlers the card wires to the buttons of a row.
const handlers = {};
const item = { querySelector(q) { return { addEventListener(name, fn) { handlers[q] = fn; } }; } };
const click = (a) => handlers[`[data-a="${a}"]`]();
const calls = [];
let renders = 0;
card._renderList = () => { renders += 1; };
card._call = async (service, data) => { calls.push([service, data]); return out.answer; };
card._wireActions(item, parcel);
const state = () => ({
  asking: card._receiving.has("X1"), focus: card._pendingFocus, calls: calls.length,
  html: card._actionsHtml(parcel, "in_transit"),
});
out.signature = { before: card._signature() };
card._renaming.set("X1", "Neu");
card._confirming.add("X1");
click("received");
out.signature.asking = card._signature();
out.asked = { ...state(), renaming: card._renaming.has("X1"),
  deleting: card._confirming.has("X1") };
// A row without any link (Eventim): what stands where "Erhalten" was?
const ticket = { number: "EVT999999901", carrier: "eventim" };
out.place = { before: card._actionsHtml(ticket, "in_transit") };
card._receiving.add(ticket.number);
out.place.asking = card._actionsHtml(ticket, "in_transit");
// Delivered between the two taps: nothing is left to confirm.
out.place.delivered = card._actionsHtml(ticket, "delivered");
out.place.stillAsking = card._receiving.has(ticket.number);
card._receiving.add(ticket.number);
out.place.assumed = card._actionsHtml({ ...ticket, assumed_delivered: true }, "delivered");
card._receiving.delete(ticket.number);
click("received-cancel");
out.cancelled = state();
click("received");
click("rename");
out.renameInstead = { asking: card._receiving.has("X1"), renaming: card._renaming.has("X1") };
card._renaming.clear();
click("received");
click("remove");
out.removeInstead = { asking: card._receiving.has("X1"), deleting: card._confirming.has("X1") };
card._confirming.clear();
click("received");
out.answer = false;
click("received-confirm").then(() => {
  out.refused = state();
  out.answer = true;
  return click("received-confirm");
}).then(() => {
  out.confirmed = { ...state(), call: calls[calls.length - 1] };
  out.renders = renders;
  console.log(JSON.stringify(out));
});
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD), DHL], capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout)


BUTTON = '<button type="button" data-a="received" data-number="X1">Erhalten</button>'


def _actions(html: str) -> list[str]:
    """The labels of the action row, in order."""
    return re.findall(r">([^<>\n]+)</(?:a|button)>", html)


@pytest.mark.parametrize("state", ["transit", "pickup", "unknown", "problem"])
def test_every_parcel_that_is_not_delivered_has_the_button(card, state):
    assert BUTTON in card["html"][state]
    assert _actions(card["html"][state]) == ["Erhalten", "Umbenennen", "Löschen"]


def test_order_of_the_actions_the_button_first(card):
    # The links stand behind the numbers: the row holds only buttons, also for an order.
    assert _actions(card["html"]["both"]) == ["Erhalten", "Umbenennen", "Löschen"]
    assert _actions(card["html"]["ordered"]) == ["Erhalten", "Umbenennen", "Löschen"]
    assert "<a " not in card["html"]["both"]


def test_a_delivered_parcel_has_no_button(card):
    for state in ("delivered", "manual"):
        assert 'data-a="received"' not in card["html"][state]
        assert _actions(card["html"][state]) == ["Umbenennen", "Löschen"]
    assert card["can"] == {
        "transit": True, "delivered": False, "assumed": True, "assumedOpenAgain": True,
    }


def test_an_order_closed_without_a_delivery_mail_can_be_confirmed(card):
    assert 'data-a="received"' in card["html"]["assumed"]


def test_a_parcel_marked_by_hand_is_shown_like_a_delivered_one(card):
    assert card["shown"] == {
        "label": "Erhalten",
        "plain": "Zugestellt",
        "open": "Unterwegs",
        "right": "Zugestellt heute",
        "sub": "DHL · Erhalten",
    }
    assert card["error"] == "Dieses Paket ist schon zugestellt."


def test_the_first_tap_only_asks(card):
    asked = card["asked"]
    assert asked["asking"] is True and asked["calls"] == 0
    # The focus goes to "Abbrechen": a second tap or Enter never confirms by itself.
    assert asked["focus"] == {"number": "X1", "a": "received-cancel"}
    assert _actions(asked["html"]) == ["Abbrechen", "Wirklich erhalten?"]
    assert 'role="group" aria-label="Erhalten bestätigen"' in asked["html"]
    assert 'class="danger"' not in asked["html"]
    # Renaming or deleting that was under way is over.
    assert asked["renaming"] is False and asked["deleting"] is False
    # The open question is part of what the card compares before it draws anew.
    assert card["signature"]["before"] != card["signature"]["asking"]
    assert "|rcv:X1|" in card["signature"]["asking"]


def test_a_double_tap_hits_abbrechen_not_the_confirmation(card):
    """The mark cannot be taken back: where "Erhalten" was tapped stands "Abbrechen"."""
    place = card["place"]
    assert _actions(place["before"]) == ["Erhalten", "Umbenennen", "Löschen"]
    assert _actions(place["asking"]) == ["Abbrechen", "Wirklich erhalten?"]
    assert _actions(card["html"]["transit"])[:1] == ["Erhalten"]
    assert _actions(card["asked"]["html"])[:1] == ["Abbrechen"]


def test_delivered_between_the_two_taps_ends_the_question(card):
    place = card["place"]
    assert _actions(place["delivered"]) == ["Umbenennen", "Löschen"]
    assert place["stillAsking"] is False
    # An order closed on its own can still be confirmed: the question stays.
    assert _actions(place["assumed"]) == ["Abbrechen", "Wirklich erhalten?"]


def test_cancel_and_the_other_actions_take_the_question_back(card):
    cancelled = card["cancelled"]
    assert cancelled["asking"] is False and cancelled["calls"] == 0
    assert cancelled["focus"] == {"number": "X1", "a": "received"}
    assert BUTTON in cancelled["html"]
    assert card["renameInstead"] == {"asking": False, "renaming": True}
    assert card["removeInstead"] == {"asking": False, "deleting": True}


def test_the_second_tap_calls_the_service(card):
    # Refused by the service (e.g. delivered in the meantime): the question stays.
    assert card["refused"]["asking"] is True and card["refused"]["calls"] == 1
    confirmed = card["confirmed"]
    assert confirmed["call"] == ["mark_delivered", {"number": "X1"}]
    assert confirmed["asking"] is False and confirmed["calls"] == 2
    assert confirmed["focus"] == {"number": "X1", "a": "toggle"}


def test_the_action_row_wraps():
    source = BUNDLED_CARD.read_text(encoding="utf-8")
    rule = re.search(r"\.actions \{([^}]*)\}", source).group(1)
    assert "display:flex" in rule and "flex-wrap:wrap" in rule
