"""Card: marking parcels as gifts one by one – the button "Geschenk" in an opened parcel and
"Einzeln auswählen" in the question of the Geschenkmodus (run in Node)."""

import json
import re
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
    focus() { el.focused = true; },
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
  HTMLElement: class {},
  customElements: { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } },
  window: {}, Event: class { constructor(n) { this.type = n; } },
  document: { createElement: () => fakeEl() },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const Card = defined["parcel-tracker-card"];
const SWITCH = "switch.paket_tracker_geschenkmodus";
const tick = () => new Promise((r) => setTimeout(r, 0));
// Ticks (or unticks) a parcel in the list of "Einzeln auswählen".
const tickIn = (c, number, checked = true) => c.els["giftpick-list"].listeners.change({
  target: { dataset: { number, pick: "" }, checked } });

const blank = { days_until: null, events: [], status_text: null, progress: 0, last_error: null };
const P1 = "00340999999999999951";
const P2 = "00340999999999999952";
const G1 = "00340999999999999931";
const S1 = "00340999999999999971";
const D1 = "00340999999999999981";
const C1 = "AMZ99990000000000091";
const BASE = [
  ["in_transit", { number: G1, name: "Geschenk · DHL-Paket …9931", carrier: "dhl", gift: true }],
  ["in_transit", { number: P1, name: "Socken <i>", carrier: "dhl", gift: false }],
  ["pre_transit", { number: P2, name: null, carrier: "dhl", gift: false }],
  ["in_transit", { number: S1, name: "Rücksendung", carrier: "dhl", gift: false, outgoing: true }],
  ["delivered", { number: D1, name: "Kabel", carrier: "dhl", gift: false }],
  ["cancelled", { number: C1, name: "Storniert", carrier: "amazon", gift: false }],
];

function makeHass(opts) {
  const states = {};
  const entities = {};
  (opts.parcels || BASE).forEach(([state, attributes], i) => {
    const id = `sensor.paket_${i}`;
    const gift = (opts.gifts || []).includes(attributes.number) || attributes.gift;
    // The integration hides a gift's name in the sensor.
    const name = gift ? `Geschenk · DHL-Paket …${attributes.number.slice(-4)}` : attributes.name;
    states[id] = { entity_id: id, state, last_updated: "t" + (gift ? "g" : ""),
      attributes: { ...blank, ...attributes, gift, name } };
    entities[id] = { platform: "parcel_tracker" };
  });
  if (opts.mode != null) {
    states[SWITCH] = { entity_id: SWITCH, state: opts.mode, last_updated: "t" + opts.mode,
      attributes: {} };
    entities[SWITCH] = { platform: "parcel_tracker" };
  }
  const log = opts.log;
  return {
    states, entities, user: { id: opts.user },
    callWS: async (msg) => {
      log.ws.push(msg);
      if (msg.type === "parcel_tracker/gift_viewer") return { viewer: opts.viewer };
      throw new Error("unknown");
    },
    callService: async (domain, service, data) => {
      log.svc.push([domain, service, data]);
      if (opts.refuse && service === "set_gift" && data.number === opts.refuse) {
        const e = new Error("x"); e.translation_key = "gift_outgoing"; throw e;
      }
    },
  };
}

function mount(opts) {
  const log = { ws: [], svc: [] };
  const card = new Card();
  const els = {};
  const root = {
    innerHTML: "", activeElement: null,
    getElementById(id) {
      if (!els[id]) {
        const el = fakeEl();
        el.focus = () => { root.activeElement = el; };
        els[id] = el;
      }
      return els[id];
    },
  };
  card.attachShadow = () => root;
  card.setConfig(opts.config || {});
  card.dispatchEvent = () => {};
  card.hass = makeHass({ ...opts, log });
  // The list hands out a row button per row, as a browser would.
  const toggles = {};
  els.list.querySelectorAll = () => els.list.children.map((item) => {
    const number = /data-number="([^"]+)"/.exec(item.innerHTML)[1];
    const t = (toggles[number] ||= { dataset: { number, a: "toggle" }, id: number });
    t.focus = () => { root.activeElement = t; };
    return t;
  });
  const rows = () => Object.fromEntries(els.list.children.map((item) => [
    /data-number="([^"]+)"/.exec(item.innerHTML)[1], item]));
  const html = () => Object.fromEntries(
    Object.entries(rows()).map(([n, item]) => [n, item.innerHTML]));
  const click = (n, a) => rows()[n].kids[`[data-a="${a}"]`].listeners.click();
  const openAll = () => {
    for (const n of Object.keys(rows())) rows()[n].kids[".row-toggle"].listeners.click();
  };
  const $ = (id) => root.getElementById(id);
  const head = () => ({
    ask: !$("giftask").hidden, label: $("giftask").attrs["aria-label"],
    text: $("giftask-text").innerHTML,
    all: !$("giftask-all").hidden, new: !$("giftask-new").hidden,
    pick: !$("giftask-pick").hidden, only: !$("giftask-on").hidden,
    cancel: !$("giftask-cancel").hidden,
    list: $("giftpick").hidden ? null : $("giftpick-list").innerHTML,
    mark: !$("giftpick-mark").hidden,
    err: $("err").innerHTML,
  });
  const again = (more = {}) => {
    Object.assign(opts, more);
    card.hass = makeHass({ ...opts, log });
  };
  const focused = () => (root.activeElement && root.activeElement.id) || null;
  const idOf = (el) => Object.keys(els).find((k) => els[k] === el) || null;
  return { card, els, root, log, rows, html, click, openAll, head, again, focused, idOf, $ };
}

(async () => {
  const out = {};

  // ---- the button in an opened parcel -------------------------------------------------
  const v = mount({ user: "u1", viewer: true, mode: "off" });
  await tick();
  out.closed = v.html();
  v.openAll();
  out.open = v.html();
  v.log.svc.length = 0;
  await v.click(P1, "gift-mark");
  out.viewerMark = { calls: v.log.svc.slice(), html: v.html()[P1], open: v.card._open.has(P1),
    focus: v.focused() };
  // The sensor says it is a gift now: the row is a gift row, closed, the focus on it.
  v.again({ gifts: [P1] });
  await tick();
  out.viewerMark.after = v.html()[P1];
  out.viewerMark.focusAfter = v.focused();
  out.viewerMark.focusDone = v.card._giftFocus;

  // Not a gift viewer: asked first, "Abbrechen" first and focused.
  const n = mount({ user: "u9", viewer: false, mode: "on" });
  await tick();
  n.openAll();
  n.click(P1, "gift-mark");
  out.ask = { html: n.html()[P1], calls: n.log.svc.length };
  n.click(P1, "gift-mark-cancel");
  out.ask.cancelled = n.html()[P1];
  n.click(P1, "gift-mark");
  await n.click(P1, "gift-mark-confirm");
  out.ask.confirmed = { calls: n.log.svc.slice(), html: n.html()[P1] };
  // Marked, the sensor says gift: no name and no rename field for the non-viewer.
  n.card._renaming.set(P1, "Socken");
  n.again({ gifts: [P1] });
  await tick();
  out.ask.gift = n.html()[P1];

  // A rename field open: "Geschenk" is not offered then; marking drops it.
  const rn = mount({ user: "u9", viewer: false, mode: "off" });
  await tick();
  rn.openAll();
  rn.click(P1, "rename");
  out.renaming = rn.html()[P1];

  // An integration without the Geschenkmodus: no button.
  const old = mount({ user: "u1", viewer: true, mode: null });
  await tick();
  old.openAll();
  out.old = old.html()[P1];

  // Refused (a sent parcel): the error in German, the row stays open.
  const rf = mount({ user: "u1", viewer: true, mode: "off", refuse: P1 });
  await tick();
  rf.openAll();
  await rf.click(P1, "gift-mark");
  out.refused = { err: rf.head().err, open: rf.card._open.has(P1) };

  // In a parcel row: per order, the focus candidates are the row first.
  const order = (number) => ["in_transit", { number, name: "Kabel", carrier: "aliexpress",
    gift: false, tracking_carrier: "dhl", tracking_ref: "X" }];
  const bx = mount({ user: "u1", viewer: true, mode: "off",
    parcels: [order("AL1"), order("AL2")] });
  await tick();
  out.boxRows = Object.keys(bx.rows());
  const item = sandbox.document.createElement();
  const m = bx.card._hass.states["sensor.paket_0"].attributes;
  bx.card._open.add("box:dhl:X");
  bx.card._wireActions(item, m, ["box:dhl:X", "AL2", "AL1"]);
  await item.kids['[data-a="gift-mark"]'].listeners.click();
  out.box = { calls: bx.log.svc.slice(-1), focus: bx.card._giftFocus,
    open: bx.card._open.has("box:dhl:X"),
    member: bx.card._actionsHtml(m, "in_transit", { received: false }), rowFocus: bx.focused() };

  // ---- "Einzeln auswählen" -----------------------------------------------------------
  const p = mount({ user: "u1", viewer: true, mode: "off" });
  await tick();
  p.els.gm.listeners.click();
  out.question = p.head();
  p.log.svc.length = 0;
  await p.els["giftask-pick"].listeners.click();
  out.pick = { head: p.head(), calls: p.log.svc.slice(), focus: p.idOf(p.root.activeElement) };
  p.again({ mode: "on" });
  out.pick.on = p.head();
  tickIn(p, P1);
  tickIn(p, P2);
  tickIn(p, P2, false);
  tickIn(p, P2);
  p.log.svc.length = 0;
  await p.els["giftpick-mark"].listeners.click();
  out.pick.marked = { calls: p.log.svc.slice(), head: p.head(),
    focus: p.idOf(p.root.activeElement) };

  // Nothing ticked: only switched on.
  const e = mount({ user: "u1", viewer: true, mode: "off" });
  await tick();
  e.els.gm.listeners.click();
  e.log.svc.length = 0;
  await e.els["giftask-pick"].listeners.click();
  await e.els["giftpick-mark"].listeners.click();
  out.empty = { calls: e.log.svc.slice(), head: e.head() };

  // Escape: closed, nothing marked; "Fertig" the same.
  const x = mount({ user: "u1", viewer: true, mode: "off" });
  await tick();
  x.els.gm.listeners.click();
  x.log.svc.length = 0;
  await x.els["giftask-pick"].listeners.click();
  tickIn(x, P1);
  let prevented = false;
  x.els.giftask.listeners.keydown({ key: "Escape", preventDefault() { prevented = true; } });
  out.escape = { calls: x.log.svc.slice(), head: x.head(), prevented,
    focus: x.idOf(x.root.activeElement) };
  x.els.gm.listeners.click();
  out.escape.reopened = x.head();
  x.again({ mode: "on" });
  out.escape.onAgain = x.head();

  const f = mount({ user: "u1", viewer: true, mode: "off" });
  await tick();
  f.els.gm.listeners.click();
  await f.els["giftask-pick"].listeners.click();
  tickIn(f, P1);
  f.log.svc.length = 0;
  f.els["giftpick-done"].listeners.click();
  out.done = { calls: f.log.svc.slice(), head: f.head() };

  // A ticked parcel that became a gift meanwhile leaves the list and is not marked again.
  const g = mount({ user: "u1", viewer: true, mode: "off" });
  await tick();
  g.els.gm.listeners.click();
  await g.els["giftask-pick"].listeners.click();
  tickIn(g, P1);
  tickIn(g, P2);
  g.again({ mode: "on", gifts: [P1] });
  out.gone = { list: g.head().list };
  g.log.svc.length = 0;
  await g.els["giftpick-mark"].listeners.click();
  out.gone.calls = g.log.svc.slice();

  // No open parcel: no "Einzeln auswählen".
  const none = mount({ user: "u1", viewer: true, mode: "off",
    parcels: [BASE[0], BASE[3], BASE[4], BASE[5]] });
  await tick();
  none.els.gm.listeners.click();
  out.none = none.head();

  console.log(JSON.stringify(out));
})();
"""

P1 = "00340999999999999951"
P2 = "00340999999999999952"
G1 = "00340999999999999931"
S1 = "00340999999999999971"
D1 = "00340999999999999981"
C1 = "AMZ99990000000000091"
SWITCH = "switch.paket_tracker_geschenkmodus"
ON = ["switch", "turn_on", {"entity_id": SWITCH}]


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)],
        capture_output=True, encoding="utf-8", check=True,
    )
    return json.loads(done.stdout)


def _actions(html: str) -> list[str]:
    blocks = re.findall(r'<div class="actions"[^>]*>(.*?)</div>', html, re.S)
    return [label for b in blocks for label in re.findall(r">([^<>\n]+)</button>", b)]


def _mark(number: str) -> list:
    return ["parcel_tracker", "set_gift", {"number": number, "gift": True}]


# ----- the button "Geschenk" -------------------------------------------------------------
def test_the_button_stands_in_an_opened_parcel_that_is_no_gift(card):
    html = card["open"][P1]
    assert _actions(html) == ["Erhalten", "Umbenennen", "Geschenk", "Löschen"]
    assert re.search(r'<button type="button" data-a="gift-mark" data-number="' + P1
                     + r'" title="Als Geschenk kennzeichnen">Geschenk</button>', html)
    # The service marks delivered and cancelled parcels as well.
    assert "Geschenk</button>" in card["open"][D1]
    assert "Geschenk</button>" in card["open"][C1]
    # Not in a closed row.
    assert "gift-mark" not in card["closed"][P1]


def test_no_button_for_a_gift_a_sent_parcel_or_without_the_gift_mode(card):
    assert "gift-mark" not in card["open"][G1]
    assert "gift-mark" not in card["open"][S1]
    assert "gift-mark" not in card["old"]


def test_a_viewer_marks_at_once_and_the_row_closes(card):
    mark = card["viewerMark"]
    assert mark["calls"] == [_mark(P1)]
    assert mark["open"] is False
    assert 'aria-expanded="false"' in mark["html"]
    assert mark["focus"] == P1
    # Once a gift: a gift row, still closed, the focus on it, nothing more to follow.
    assert 'class="giftbox"' in mark["after"]
    assert 'aria-expanded="false"' in mark["after"]
    assert mark["focusAfter"] == P1
    assert mark["focusDone"] is None


def test_others_are_asked_first_because_they_cannot_take_it_back(card):
    ask = card["ask"]
    assert ask["calls"] == 0
    assert 'role="group" aria-label="Geschenk bestätigen"' in ask["html"]
    assert _actions(ask["html"]) == ["Abbrechen", "Wirklich als Geschenk verbergen?"]
    assert _actions(ask["cancelled"]) == ["Erhalten", "Umbenennen", "Geschenk", "Löschen"]
    assert ask["confirmed"]["calls"] == [_mark(P1)]
    assert 'aria-expanded="false"' in ask["confirmed"]["html"]


def test_a_marked_parcel_shows_nothing_of_its_name_to_others(card):
    html = card["ask"]["gift"]
    assert "Socken" not in html
    assert "rename-input" not in html
    assert '<span class="giftbox" role="img"' in html


def test_no_button_while_renaming(card):
    assert "gift-mark" not in card["renaming"]
    assert 'data-a="rename-input"' in card["renaming"]


def test_a_refused_mark_is_said_in_german(card):
    assert card["refused"]["err"] == "Ein versendetes Paket kann kein Geschenk sein."
    assert card["refused"]["open"] is True


def test_in_a_parcel_row_each_order_has_its_own_button(card):
    box = card["box"]
    assert "Geschenk</button>" in box["member"]
    assert "Erhalten" not in box["member"]
    assert box["calls"] == [_mark("AL1")]
    assert box["focus"] == {"number": "AL1", "toggles": ["box:dhl:X", "AL2", "AL1"]}
    assert card["boxRows"] == ["box:dhl:X"]
    assert box["rowFocus"] == "box:dhl:X"
    # The parcel row stays open for the other orders.
    assert box["open"] is True


# ----- "Einzeln auswählen" ---------------------------------------------------------------
def test_the_question_offers_einzeln_auswaehlen_with_open_parcels(card):
    q = card["question"]
    assert q["ask"] and q["all"] and q["new"] and q["pick"] and q["cancel"]
    assert not q["only"]
    assert q["list"] is None
    assert "Auch die 2 offenen Pakete verbergen?" in q["text"]
    none = card["none"]
    assert none["ask"] and none["only"]
    assert not none["pick"] and not none["all"] and not none["new"]


def test_einzeln_auswaehlen_switches_on_and_lists_the_open_parcels(card):
    pick = card["pick"]
    assert pick["calls"] == [ON]
    head = pick["on"]
    assert head["ask"] and head["label"] == "Geschenke auswählen"
    assert not (head["all"] or head["new"] or head["pick"] or head["only"] or head["cancel"])
    assert head["mark"]
    assert "Welche Pakete sollen Geschenke sein?" in head["text"]
    listed = re.findall(r'data-number="([^"]+)"', head["list"])
    assert listed == [P1, P2]
    for other in (G1, S1, D1, C1):
        assert other not in head["list"]
    # Labelled boxes; names escaped; without a name the number.
    assert '<label for="giftpick-0"><input type="checkbox" id="giftpick-0"' in head["list"]
    assert "Socken &lt;i&gt;" in head["list"] and "<i>" not in head["list"]
    assert f"<span>{P2}</span>" in head["list"]
    assert pick["focus"] == "giftpick-0"


def test_the_list_is_a_labelled_group(card):
    template = card["pick"]["head"]["list"]
    assert template is not None
    script = BUNDLED_CARD.read_text(encoding="utf-8")
    assert 'id="giftpick-list" role="group" aria-label="Pakete als Geschenk auswählen"' in script
    assert ">Als Geschenk markieren</button>" in script
    assert ">Fertig</button>" in script


def test_ticked_parcels_are_marked_one_by_one(card):
    marked = card["pick"]["marked"]
    assert marked["calls"] == [_mark(P1), _mark(P2)]
    assert marked["head"]["ask"] is False
    assert marked["focus"] == "gm"


def test_nothing_ticked_only_switches_on(card):
    assert card["empty"]["calls"] == [ON]
    assert card["empty"]["head"]["ask"] is False


def test_escape_and_fertig_close_without_marking(card):
    esc = card["escape"]
    # Switched on with the choice, nothing marked.
    assert esc["calls"] == [ON]
    assert esc["head"]["ask"] is False and esc["prevented"] is True
    assert esc["focus"] == "gm"
    # Asked again later: the question as before, no list left over.
    assert esc["reopened"]["ask"] and esc["reopened"]["list"] is None
    assert esc["reopened"]["pick"]
    assert card["done"]["calls"] == []  # (switched on before the log was emptied)
    assert card["done"]["head"]["ask"] is False


def test_a_parcel_that_became_a_gift_leaves_the_list(card):
    gone = card["gone"]
    assert re.findall(r'data-number="([^"]+)"', gone["list"]) == [P2]
    assert gone["calls"] == [_mark(P2)]
