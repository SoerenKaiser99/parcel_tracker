"""Card: gifts for the user's own person (``gift_for``, WebSocket answer ``hidden``; run in Node).

A gift viewer gets the numbers of the gifts that are for her person; for those the card acts
as for somebody who may not see gifts: no gift button, no real name, no rename, delete or
owner, and with ``gifts: hide_for_others`` no row and no count - also not for a moment
before the answer, nor for a gift that is new since the last answer.
"""

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
const fakeEl = () => {
  let html = "";
  const el = {
    hidden: false, value: "", textContent: "", className: "", title: "",
    listeners: {}, attrs: {}, kids: {}, children: [], dataset: {},
    get innerHTML() { return html; },
    set innerHTML(value) { html = value; el.children = []; },
    addEventListener(name, fn) { el.listeners[name] = fn; },
    setAttribute(name, value) { el.attrs[name] = String(value); },
    toggleAttribute() {},
    focus() {},
    contains() { return false; },
    appendChild(child) { el.children.push(child); },
    querySelector(sel) {
      if (sel === 'option[value="other"]') return null;
      return (el.kids[sel] ||= fakeEl());
    },
    querySelectorAll() { return []; },
    insertAdjacentHTML() {},
  };
  return el;
};
const sandbox = {
  HTMLElement: class {
    constructor() { this.hidden = false; }
    toggleAttribute(name, force) { if (name === "hidden") this.hidden = !!force; }
    dispatchEvent() { return true; }
  },
  customElements: { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } },
  window: {}, Event: class { constructor(n) { this.type = n; } },
  document: {
    createElement: () => fakeEl(), visibilityState: "visible", listeners: [],
    addEventListener(name, fn) { this.listeners.push([name, fn]); },
    removeEventListener(name, fn) {
      this.listeners = this.listeners.filter(([n, f]) => !(n === name && f === fn));
    },
  },
  // A fake timer: the test runs it by hand.
  timers: new Map(), nextTimer: 1,
};
sandbox.setInterval = (fn, ms) => {
  const id = sandbox.nextTimer++;
  sandbox.timers.set(id, [fn, ms]);
  return id;
};
sandbox.clearInterval = (id) => { sandbox.timers.delete(id); };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const Card = defined["parcel-tracker-card"];
const SWITCH = "switch.paket_tracker_geschenkmodus";
const tick = () => new Promise((r) => setTimeout(r, 0));
const G1 = "00340999999999999931";  // a gift for Ben, comes today
const G2 = "00340999999999999932";  // a gift for somebody else, delivered today
const G3 = "00340999999999999933";  // a gift that turns up later
const P1 = "00340999999999999951";  // a plain parcel that comes today

const blank = { days_until: 0, events: [], status_text: null, progress: 0, last_error: null };
const gift = (number, state) => [state, { number, name: `Geschenk · DHL-Paket …${number.slice(-4)}`,
                                          carrier: "dhl", gift: true, tracking_url: null }];
const item = (number, g) => ({ number, name: "x", carrier: "dhl", eta_from: null, eta_to: null,
                               gift: g });

function makeHass(opts) {
  const parcels = [gift(G1, "out_for_delivery"), gift(G2, "delivered"),
    ["out_for_delivery", { number: P1, name: "Socken", carrier: "dhl", gift: false,
                           tracking_url: null }]];
  if (opts.third) parcels.push(gift(G3, "out_for_delivery"));
  const states = {};
  const entities = {};
  parcels.forEach(([given, attributes]) => {
    const state = (opts.statuses || {})[attributes.number] || given;
    const id = `sensor.paket_${attributes.number}`;
    const stamp = (opts.stamps || {})[attributes.number] || "t";
    states[id] = { entity_id: id, state, last_updated: stamp,
      attributes: { ...blank, ...attributes } };
    entities[id] = { platform: "parcel_tracker" };
  });
  const sure = [item(G1, true), item(P1, false), ...(opts.third ? [item(G3, true)] : [])];
  states["sensor.pakete_heute"] = { entity_id: "sensor.pakete_heute",
    state: String(sure.length), last_updated: "t",
    attributes: { parcels: sure, possible: [], possible_count: 0,
                  delivered_today: [item(G2, true)], delivered_today_count: 1,
                  persons: ["person.ben"], default_owner: null } };
  states["person.ben"] = { entity_id: "person.ben", state: "home", last_updated: "t",
                           attributes: { friendly_name: "Ben", user_id: "ben" } };
  states["sensor.pakete_unterwegs"] = { entity_id: "sensor.pakete_unterwegs",
    state: String(sure.length), last_updated: "t", attributes: { parcels: sure } };
  states[SWITCH] = { entity_id: SWITCH, state: "on", last_updated: "t", attributes: {} };
  entities[SWITCH] = { platform: "parcel_tracker" };
  const log = opts.log;
  return {
    states, entities, user: { id: opts.user },
    callWS: async (msg) => {
      log.push(msg);
      if (msg.type === "parcel_tracker/gift_viewer") {
        // (an integration before v0.3.45 answers without `hidden`)
        const answer = { viewer: true };
        if (opts.hidden[opts.user]) answer.hidden = opts.hidden[opts.user].slice();
        if (opts.hold) return new Promise((r) => { opts.hold.release = () => r(answer); });
        return answer;
      }
      if (msg.type === "parcel_tracker/gift_name") return { name: "Lego", mail_title: null };
      throw new Error("unknown");
    },
    callService: async () => {},
  };
}

function mount(config, opts) {
  const log = [];
  const card = new Card();
  const els = {};
  const root = { innerHTML: "", activeElement: null,
    getElementById(id) { return (els[id] ||= fakeEl()); } };
  card.attachShadow = () => root;
  card.setConfig(config);
  const state = { ...opts, log };
  card.hass = makeHass(state);
  const rows = () => Object.fromEntries(els.list.children.map((el) => [
    /data-number="([^"]+)"/.exec(el.innerHTML)[1], el.innerHTML]));
  const attrs = (n) => card._parcels().find((st) => st.attributes.number === n);
  const view = () => {
    const r = rows();
    const out = { rows: Object.keys(r).sort(), badges: els.today.innerHTML,
                  giftButton: {}, actions: {}, owner: {} };
    for (const n of Object.keys(r)) {
      out.giftButton[n] = r[n].includes('data-a="gift"');
      const st = attrs(n);
      out.actions[n] = card._actionsHtml(st.attributes, st.state);
      out.owner[n] = card._ownerHtml(st.attributes);
    }
    return out;
  };
  const as = (more) => { Object.assign(state, more); card.hass = makeHass(state); };
  const asks = () => log.filter((m) => m.type === "parcel_tracker/gift_viewer").length;
  return { card, view, as, state, log, asks };
}

(async () => {
  const out = {};
  const hidden = { ben: [G1], anna: [] };
  const persons = {};

  // ---- hide_for_others: Ben is a gift viewer, G1 is for him -----------------------------
  const cfg = { gifts: "hide_for_others" };
  const b = mount(cfg, { user: "ben", hidden, hold: {} });
  out.pending = b.view();
  b.state.hold.release();
  await tick();
  out.ben = b.view();
  // A new gift turns up: not shown before the answer, and asked again.
  const before = b.asks();
  b.as({ third: true, hidden: { ben: [G1, G3], anna: [] }, hold: {} });
  out.newGift = { ...b.view(), askedAgain: b.asks() - before };
  b.state.hold.release();
  await tick();
  out.newGiftAnswered = b.view();
  // Nothing changed: not asked again.
  const still = b.asks();
  b.as({ hold: null });
  await tick();
  out.unchangedAsks = b.asks() - still;
  // Only last_updated of a gift changes (a poll): not asked again.
  const polled = b.asks();
  b.as({ stamps: { [G2]: "t9" } });
  await tick();
  out.pollAsks = b.asks() - polled;
  // G2 changes its status: asked again, and now it is for Ben as well.
  b.as({ statuses: { [G2]: "awaiting_pickup" }, hidden: { ben: [G1, G2, G3], anna: [] } });
  await tick();
  out.changedGift = b.view();
  // Another user on the card: hidden at once, then that user's answer.
  b.as({ user: "anna", hold: {} });
  out.switched = b.view();
  b.state.hold.release();
  await tick();
  out.anna = b.view();
  // And back to Ben: nothing of Anna's answer is kept.
  b.as({ user: "ben", hold: {} });
  out.back = b.view();
  b.state.hold.release();
  await tick();
  out.backAnswered = b.view();

  // ---- show (default): the row stays, but as for somebody who may not see gifts ----------
  const s = mount({}, { user: "ben", hidden: { ben: [G1] } });
  await tick();
  out.show = s.view();
  // Revealed before (another answer): dropped once the gift is hidden.
  const r = mount({}, { user: "ben", hidden: { ben: [] } });
  await tick();
  r.card._revealed.set(G1, { name: "Lego" });
  r.card._renaming.set(G1, "Lego");
  r.as({ statuses: { [G1]: "delivered" }, hidden: { ben: [G1] } });
  await tick();
  out.dropped = { revealed: r.card._revealed.has(G1), renaming: r.card._renaming.has(G1),
                  rows: r.view().rows, button: r.view().giftButton[G1] };

  // ---- an older integration answers without `hidden`: as before ------------------------
  const o = mount(cfg, { user: "ben", hidden: {} });
  await tick();
  out.old = o.view();

  // ---- only gift_for changed (no sensor changes): the timer and a shown tab ask again ----
  const live = () => Array.from(sandbox.timers.values()).filter(([, ms]) => ms === 60000).length;
  sandbox.timers.clear();
  const t = mount({}, { user: "ben", hidden: { ben: [] } });
  await tick();
  const timer = { running: live() };
  t.state.hidden = { ben: [G1] };  // set_gift with gift_for: Ben, nothing on the sensors
  let asked = t.asks();
  t.as({});
  await tick();
  timer.sameHass = t.asks() - asked;
  for (const [fn] of sandbox.timers.values()) fn();
  await tick();
  timer.timerAsks = t.asks() - asked;
  timer.button = t.view().giftButton[G1];
  t.card.connectedCallback();
  timer.listening = sandbox.document.listeners.filter(([n]) => n === "visibilitychange").length;
  asked = t.asks();
  for (const [, fn] of sandbox.document.listeners) fn();
  await tick();
  timer.visibleAsks = t.asks() - asked;
  sandbox.document.visibilityState = "hidden";
  asked = t.asks();
  for (const [, fn] of sandbox.document.listeners) fn();
  await tick();
  timer.hiddenAsks = t.asks() - asked;
  sandbox.document.visibilityState = "visible";
  t.card.disconnectedCallback();
  timer.afterDisconnect = { running: live(),
    listening: sandbox.document.listeners.filter(([n]) => n === "visibilitychange").length };
  t.card.connectedCallback();
  timer.reconnected = live();
  // Another user: no timer until that user's answer says viewer.
  t.as({ user: "anna", hold: {}, hidden: { anna: [] } });
  timer.userChange = live();
  t.state.hold.release();
  await tick();
  timer.userAnswered = live();
  out.timer = timer;
  // A viewer without any gift on the card: no timer.
  sandbox.timers.clear();
  const ng = mount({ gifts: "hide" }, { user: "ben", hidden: { ben: [] } });
  await tick();
  out.noGiftTimer = live();

  console.log(JSON.stringify(out));
})();
"""

G1 = "00340999999999999931"
G2 = "00340999999999999932"
G3 = "00340999999999999933"
P1 = "00340999999999999951"


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)],
        capture_output=True, encoding="utf-8", check=True,
    )
    return json.loads(done.stdout)


def test_before_the_answer_ben_sees_no_gift(card):
    assert card["pending"]["rows"] == [P1]
    assert ">1 heute<" in card["pending"]["badges"]
    assert "zugestellt" not in card["pending"]["badges"]


def test_ben_sees_no_row_and_no_count_of_his_gift(card):
    view = card["ben"]
    assert view["rows"] == sorted([G2, P1])
    assert ">1 heute<" in view["badges"]
    assert ">1 zugestellt<" in view["badges"]
    assert view["giftButton"][G2] is True


def test_a_new_gift_stays_hidden_until_the_answer(card):
    assert card["newGift"]["rows"] == sorted([G2, P1])
    assert card["newGift"]["askedAgain"] == 1
    assert card["newGiftAnswered"]["rows"] == sorted([G2, P1])
    assert card["unchangedAsks"] == 0


def test_a_poll_alone_asks_nothing(card):
    assert card["pollAsks"] == 0


def test_only_gift_for_changed_the_timer_and_the_shown_tab_ask_again(card):
    timer = card["timer"]
    assert timer["running"] == 1
    assert timer["sameHass"] == 0
    assert timer["timerAsks"] == 1
    assert timer["button"] is False
    assert timer["listening"] == 1
    assert timer["visibleAsks"] == 1
    assert timer["hiddenAsks"] == 0
    assert timer["afterDisconnect"] == {"running": 0, "listening": 0}
    assert timer["reconnected"] == 1
    assert timer["userChange"] == 0
    assert timer["userAnswered"] == 1
    assert card["noGiftTimer"] == 0


def test_a_changed_gift_is_asked_again_and_hidden(card):
    assert card["changedGift"]["rows"] == [P1]
    assert "zugestellt" not in card["changedGift"]["badges"]


def test_another_user_and_back(card):
    assert card["switched"]["rows"] == [P1]
    assert card["anna"]["rows"] == sorted([G1, G2, G3, P1])
    assert card["anna"]["giftButton"][G1] is True
    assert card["back"]["rows"] == [P1]
    assert card["backAnswered"]["rows"] == [P1]


def test_with_show_the_row_stays_as_for_a_non_viewer(card):
    view = card["show"]
    assert view["rows"] == sorted([G1, G2, P1])
    assert view["giftButton"][G1] is False
    assert view["giftButton"][G2] is True
    assert "Umbenennen" not in view["actions"][G1]
    assert "Löschen" not in view["actions"][G1]
    assert "Umbenennen" in view["actions"][G2]
    assert view["owner"][G1] == ""
    assert 'data-a="owner"' in view["owner"][G2]


def test_a_revealed_name_is_dropped_once_the_gift_is_hidden(card):
    dropped = card["dropped"]
    assert dropped["revealed"] is False
    assert dropped["renaming"] is False
    assert dropped["button"] is False


def test_an_answer_without_hidden_works_as_before(card):
    assert card["old"]["rows"] == sorted([G1, G2, P1])
