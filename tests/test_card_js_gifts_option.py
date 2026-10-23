"""Card option ``gifts``: ``show`` (default), ``hide_for_others`` and ``hide`` (run in Node).

Hidden gifts leave no trace: no row, not counted in the badges, the empty-list text and the
option ``show``. Until the integration has answered whether the user may see gifts, the user
counts as one who may not.
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
  document: { createElement: () => fakeEl() },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const Card = defined["parcel-tracker-card"];
const SWITCH = "switch.paket_tracker_geschenkmodus";
const tick = () => new Promise((r) => setTimeout(r, 0));
const G1 = "00340999999999999931";  // a gift that comes today
const G2 = "00340999999999999932";  // a gift delivered today
const P1 = "00340999999999999951";  // a plain parcel that comes today

const blank = { days_until: 0, events: [], status_text: null, progress: 0, last_error: null };
const ALL = [
  ["out_for_delivery", { number: G1, name: "Geschenk · DHL-Paket …9931", carrier: "dhl",
                         gift: true, tracking_url: null }],
  ["delivered", { number: G2, name: "Geschenk · DHL-Paket …9932", carrier: "dhl",
                  gift: true, tracking_url: null }],
  ["out_for_delivery", { number: P1, name: "Socken", carrier: "dhl", gift: false,
                         tracking_url: null }],
];
const item = (number, gift) => ({ number, name: "x", carrier: "dhl", eta_from: null,
                                  eta_to: null, gift });

function makeHass(opts) {
  const parcels = opts.onlyGifts ? ALL.filter(([, a]) => a.gift) : ALL;
  const states = {};
  const entities = {};
  parcels.forEach(([state, attributes], i) => {
    const id = `sensor.paket_${i}`;
    states[id] = { entity_id: id, state, last_updated: "t",
      attributes: { ...blank, ...attributes } };
    entities[id] = { platform: "parcel_tracker" };
  });
  const sure = opts.onlyGifts ? [item(G1, true)] : [item(G1, true), item(P1, false)];
  states["sensor.pakete_heute"] = { entity_id: "sensor.pakete_heute",
    state: String(sure.length), last_updated: "t",
    attributes: { parcels: sure, possible: [], possible_count: 0,
                  delivered_today: [item(G2, true)], delivered_today_count: 1 } };
  const active = sure;
  states["sensor.pakete_unterwegs"] = { entity_id: "sensor.pakete_unterwegs",
    state: String(active.length), last_updated: "t", attributes: { parcels: active } };
  if (opts.mode !== null) {
    states[SWITCH] = { entity_id: SWITCH, state: opts.mode || "off", last_updated: "t",
                       attributes: {} };
    entities[SWITCH] = { platform: "parcel_tracker" };
  }
  const log = opts.log;
  return {
    states, entities, user: { id: opts.user },
    callWS: async (msg) => {
      log.push(msg);
      if (msg.type === "parcel_tracker/gift_viewer") {
        const viewer = (opts.viewers || []).includes(opts.user);
        if (opts.hold) return new Promise((r) => { opts.hold.release = () => r({ viewer }); });
        return { viewer };
      }
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
  const view = () => ({
    rows: els.list.children.map((el) => /data-number="([^"]+)"/.exec(el.innerHTML)[1]),
    list: els.list.innerHTML,
    badges: els.today.innerHTML,
    hidden: card.hidden === true,
  });
  const as = (more) => { Object.assign(state, more); card.hass = makeHass(state); };
  return { card, view, as, state, log };
}

(async () => {
  const out = {};
  const viewers = ["u1"];

  for (const [key, config] of [["none", {}], ["show", { gifts: "show" }],
                               ["odd", { gifts: "verstecken" }]]) {
    const other = mount(config, { user: "u9", viewers });
    await tick();
    out[key] = other.view();
  }

  // ---- hide_for_others ----------------------------------------------------------------
  const cfg = { gifts: "hide_for_others" };
  const vw = mount(cfg, { user: "u1", viewers, hold: {} });
  out.pending = vw.view();                 // asked, no answer yet
  vw.state.hold.release();
  await tick();
  out.viewer = vw.view();
  // Another user on the wall tablet: hidden at once, before any answer.
  vw.as({ user: "u9", hold: {} });
  out.switched = vw.view();
  vw.state.hold.release();
  await tick();
  out.switchedAnswered = vw.view();
  // Back to the viewer: hidden until the answer, then shown.
  vw.as({ user: "u1", hold: {} });
  out.back = vw.view();
  vw.state.hold.release();
  await tick();
  out.backAnswered = vw.view();

  const nv = mount(cfg, { user: "u9", viewers });
  await tick();
  out.other = nv.view();

  // Only gifts: a non-viewer sees the plain empty list, and show: today hides the card.
  const only = mount(cfg, { user: "u9", viewers, onlyGifts: true });
  await tick();
  out.onlyGifts = only.view();
  const onlyToday = mount({ ...cfg, show: "today" }, { user: "u9", viewers, onlyGifts: true });
  await tick();
  out.onlyGiftsToday = onlyToday.view();
  const onlyActive = mount({ ...cfg, show: "active" }, { user: "u9", viewers, onlyGifts: true });
  await tick();
  out.onlyGiftsActive = onlyActive.view();
  const onlyViewer = mount({ ...cfg, show: "today" }, { user: "u1", viewers, onlyGifts: true });
  await tick();
  out.onlyGiftsViewer = onlyViewer.view();
  const onlyShow = mount({ show: "today" }, { user: "u9", viewers, onlyGifts: true });
  await tick();
  out.onlyGiftsShowOption = onlyShow.view();
  // With the person filter as well: the person's text, still without gifts.
  const person = mount({ ...cfg, person: "person.anna", include_unassigned: false },
                       { user: "u9", viewers });
  await tick();
  out.person = person.view();

  // An integration without the switch never answers: nobody is a viewer.
  const old = mount(cfg, { user: "u1", viewers, mode: null });
  await tick();
  out.noSwitch = { ...old.view(), asked: old.log.length };

  // ---- hide: never, not even for a viewer ------------------------------------------------
  const hv = mount({ gifts: " Hide " }, { user: "u1", viewers });
  await tick();
  out.hide = hv.view();

  console.log(JSON.stringify(out));
})();
"""

G1 = "00340999999999999931"
G2 = "00340999999999999932"
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


SHOWN = [G1, P1, G2]
WITHOUT = [P1]


def _counts(view):
    return view["badges"]


def test_without_the_option_everything_is_shown_as_before(card):
    for key in ("none", "show", "odd"):
        view = card[key]
        assert sorted(view["rows"]) == sorted(SHOWN), key
        assert ">2 heute<" in view["badges"], key
        assert ">1 zugestellt<" in view["badges"], key


def test_a_gift_viewer_sees_gifts_once_the_answer_is_there(card):
    assert sorted(card["viewer"]["rows"]) == sorted(SHOWN)
    assert ">2 heute<" in card["viewer"]["badges"]
    assert ">1 zugestellt<" in card["viewer"]["badges"]


def test_before_the_answer_gifts_are_hidden(card):
    view = card["pending"]
    assert view["rows"] == WITHOUT
    assert ">1 heute<" in view["badges"]
    assert "zugestellt" not in view["badges"]
    assert "Geschenk" not in view["list"]


def test_for_others_a_gift_has_no_row_and_no_count(card):
    view = card["other"]
    assert view["rows"] == WITHOUT
    assert "Geschenk" not in view["list"]
    assert ">1 heute<" in view["badges"]
    assert "zugestellt" not in view["badges"]


def test_another_user_on_the_card_counts_at_once(card):
    assert card["switched"]["rows"] == WITHOUT
    assert ">1 heute<" in card["switched"]["badges"]
    assert card["switchedAnswered"]["rows"] == WITHOUT
    assert card["back"]["rows"] == WITHOUT
    assert sorted(card["backAnswered"]["rows"]) == sorted(SHOWN)


def test_only_gifts_look_like_no_parcels(card):
    view = card["onlyGifts"]
    assert view["rows"] == []
    assert "Noch keine Pakete." in view["list"]
    assert ">0 heute<" in view["badges"]
    assert "zugestellt" not in view["badges"]
    # show: today / active count without the gifts as well.
    assert card["onlyGiftsToday"]["hidden"] is True
    assert card["onlyGiftsActive"]["hidden"] is True
    # The viewer, and a card without the option, still count them.
    assert card["onlyGiftsViewer"]["hidden"] is False
    assert card["onlyGiftsShowOption"]["hidden"] is False


def test_with_the_person_filter_gifts_stay_hidden(card):
    view = card["person"]
    assert view["rows"] == []
    assert "Keine Pakete für" in view["list"]
    assert ">0 heute<" in view["badges"]


def test_without_the_switch_nobody_is_a_viewer(card):
    assert card["noSwitch"]["asked"] == 0
    assert card["noSwitch"]["rows"] == WITHOUT


def test_hide_hides_gifts_even_from_a_viewer(card):
    view = card["hide"]
    assert view["rows"] == WITHOUT
    assert ">1 heute<" in view["badges"]
    assert "zugestellt" not in view["badges"]
