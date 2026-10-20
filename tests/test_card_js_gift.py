"""Card: the Geschenkmodus – the gift box in a row, the real name for gift viewers only, the
switch in the head and its question (run in Node)."""

import json
import re
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")
DHL = "https://www.dhl.de/de/privatkunden/pakete-empfangen/verfolgen.html?piececode=X9"

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const defined = {};
// A tiny stand-in for the DOM: elements remember what the card writes into them.
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
vm.runInContext(fs.readFileSync(process.argv[1], "utf8")
  + "\n;globalThis.__svc = SERVICE_ERRORS;", sandbox);
const Card = defined["parcel-tracker-card"];
const DHL = process.argv[2];
const SWITCH = "switch.paket_tracker_geschenkmodus";
const tick = () => new Promise((r) => setTimeout(r, 0));
const G1 = "00340999999999999931";

const blank = { days_until: null, events: [], status_text: null, progress: 0, last_error: null };
const PARCELS = [
  ["in_transit", { number: "00340999999999999931", name: "Geschenk · DHL-Paket …9931",
                   carrier: "dhl", gift: true, tracking_url: null }],
  ["in_transit", { number: "AMZ99990000000000041", name: "Geschenk · Amazon-Bestellung …0041",
                   carrier: "amazon", gift: true, tracking_url: null, amazon_shipment: null }],
  ["delivered", { number: "00340999999999999961", name: "Geschenk · DHL-Paket …9961",
                  carrier: "dhl", gift: true, tracking_url: null }],
  ["in_transit", { number: "00340999999999999951", name: "Socken", carrier: "dhl",
                   gift: false, tracking_url: DHL }],
  ["pre_transit", { number: "00340999999999999952", name: "Mütze", carrier: "dhl",
                    gift: false, tracking_url: DHL }],
];

function makeHass(opts) {
  const states = {};
  const entities = {};
  PARCELS.forEach(([state, attributes], i) => {
    const id = `sensor.paket_${i}`;
    states[id] = { entity_id: id, state, last_updated: "t",
      attributes: { ...blank, ...attributes } };
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
      if (msg.type === "parcel_tracker/gift_viewer") {
        if (opts.fails && opts.fails.n > 0) { opts.fails.n -= 1; throw new Error("lost"); }
        if (opts.hold) {
          return new Promise((r) => { opts.hold.release = () => r({ viewer: opts.viewer }); });
        }
        return { viewer: opts.viewer };
      }
      if (msg.type === "parcel_tracker/gift_name") {
        if (!opts.viewer || opts.denied) {
          const e = new Error("Not allowed to see gifts");
          e.code = "not_allowed";
          throw e;
        }
        if (msg.number === "AMZ99990000000000041") {
          return { name: null, mail_title: "Bestellung Puppe",
                   tracking_url: "javascript:alert(1)" };
        }
        return { name: "<b>Lego</b>", mail_title: "Lego-Bausatz", tracking_url: DHL };
      }
      throw new Error("unknown");
    },
    callService: async (domain, service, data) => {
      log.svc.push([domain, service, data]);
      if (opts.refuse) { const e = new Error("x"); e.translation_key = opts.refuse; throw e; }
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
  card.setConfig({});
  card.dispatchEvent = () => {};
  card.hass = makeHass({ ...opts, log });
  const rows = () => Object.fromEntries(els.list.children.map((item) => [
    /data-number="([^"]+)"/.exec(item.innerHTML)[1], item]));
  const html = () => Object.fromEntries(
    Object.entries(rows()).map(([n, item]) => [n, item.innerHTML]));
  const click = (n, a) => rows()[n].kids[`[data-a="${a}"]`].listeners.click();
  const $ = (id) => root.getElementById(id);
  const head = () => ({
    gm: { hidden: $("gm").hidden, checked: $("gm").attrs["aria-checked"] },
    on: { hidden: $("gm-on").hidden },
    ask: { hidden: $("giftask").hidden, text: $("giftask-text").innerHTML,
           all: !$("giftask-all").hidden, new: !$("giftask-new").hidden,
           only: !$("giftask-on").hidden },
    err: $("err").innerHTML,
  });
  const again = (more = {}) => { card.hass = makeHass({ ...opts, ...more, log }); };
  return { card, els, root, log, rows, html, click, head, opts, again };
}

(async () => {
  const out = {};

  // ---- a gift viewer, mode off ---------------------------------------------------
  const v = mount({ user: "u1", viewer: true, mode: "off" });
  await tick();
  out.template = v.root.innerHTML;
  out.viewer = { closed: v.html(), ws: v.log.ws.slice(), head: v.head() };
  // Another hass of the same user: not asked again.
  v.card.hass = makeHass({ ...v.opts, log: v.log });
  await tick();
  out.viewer.wsAgain = v.log.ws.length;
  await v.click("00340999999999999931", "gift");
  await tick();
  out.viewer.revealed = v.html();
  out.viewer.wsName = v.log.ws[v.log.ws.length - 1];
  await v.click("AMZ99990000000000041", "gift");
  out.viewer.revealedOrder = v.html()["AMZ99990000000000041"];
  await v.click("00340999999999999931", "gift-unhide");
  out.viewer.unhide = v.log.svc[v.log.svc.length - 1];
  out.viewer.afterUnhide = v.html()["00340999999999999931"];
  // Tapping the box again hides the name.
  await v.click("AMZ99990000000000041", "gift");
  out.viewer.hiddenAgain = v.html()["AMZ99990000000000041"];
  v.rows()["00340999999999999931"].kids[".row-toggle"].listeners.click();
  out.viewer.open = v.html()["00340999999999999931"];
  // Switching the mode on: the question first, nothing called yet.
  v.log.svc.length = 0;
  v.els.gm.listeners.click();
  out.viewer.asking = { head: v.head(), calls: v.log.svc.length };
  await v.els["giftask-all"].listeners.click();
  out.viewer.all = { calls: v.log.svc.slice(), head: v.head() };
  v.log.svc.length = 0;
  v.els.gm.listeners.click();
  await v.els["giftask-new"].listeners.click();
  out.viewer.onlyNew = v.log.svc.slice();
  v.log.svc.length = 0;
  v.els.gm.listeners.click();
  v.els["giftask-cancel"].listeners.click();
  out.viewer.cancelled = { calls: v.log.svc.length, head: v.head() };
  // Mode on: a viewer switches it off at once.
  v.card.hass = makeHass({ ...v.opts, mode: "on", log: v.log });
  out.viewer.onHead = v.head();
  v.log.svc.length = 0;
  await v.els.gm.listeners.click();
  out.viewer.off = { calls: v.log.svc.slice(), head: v.head() };
  // Another user on the same card: the name shown before is gone, asked anew.
  await v.click("00340999999999999931", "gift");
  const before = v.log.ws.length;
  v.card.hass = makeHass({ ...v.opts, user: "u2", viewer: false, mode: "on", log: v.log });
  out.viewer.otherUser = { html: v.html()["00340999999999999931"], asked: v.log.ws.slice(before) };
  await tick();
  out.viewer.otherUserLater = v.html()["00340999999999999931"];

  // ---- not a gift viewer, mode on --------------------------------------------------
  const n = mount({ user: "u9", viewer: false, mode: "on" });
  await tick();
  out.other = { closed: n.html(), head: n.head() };
  for (const num of Object.keys(n.rows())) n.rows()[num].kids[".row-toggle"].listeners.click();
  out.other.open = n.html();
  // A tap that slipped through (an old card): the error is said in German.
  await n.click("00340999999999999931", "gift");
  out.other.wsError = n.head().err;

  // ---- not a gift viewer, mode off: switching on warns ------------------------------
  const w = mount({ user: "u9", viewer: false, mode: "off" });
  await tick();
  w.els.gm.listeners.click();
  out.warn = w.head();
  // Only one open parcel left that is not a gift yet: singular.
  const one = mount({ user: "u9", viewer: false, mode: "off" });
  await tick();
  one.card._hass.states["sensor.paket_4"].state = "delivered";
  one.els.gm.listeners.click();
  out.one = one.head();
  // A cancelled order is no open parcel either (the service leaves it alone).
  const can = mount({ user: "u9", viewer: false, mode: "off" });
  await tick();
  can.card._hass.states["sensor.paket_4"].state = "cancelled";
  can.els.gm.listeners.click();
  out.cancelled = can.head();

  // ---- a refused service call is said in German ------------------------------------
  const r = mount({ user: "u9", viewer: false, mode: "on", refuse: "gift_mode_not_allowed" });
  await tick();
  await r.card._call("set_gift", { number: "x", gift: false });
  out.refused = r.head().err;

  // ---- an integration without the switch: no switch, nothing asked ----------------
  const o = mount({ user: "u1", viewer: true, mode: null });
  await tick();
  out.old = { ws: o.log.ws.length, head: o.head() };

  // ---- the real name never stays in a rename field -----------------------------------
  const rn = mount({ user: "u1", viewer: true, mode: "on" });
  await tick();
  await rn.click(G1, "gift");
  rn.rows()[G1].kids[".row-toggle"].listeners.click();
  rn.click(G1, "rename");
  out.rename = { typing: rn.html()[G1] };
  // A second tap on the box: the name is gone from the field as well.
  await rn.click(G1, "gift");
  out.rename.hidden = rn.html()[G1];
  // Revealed and renaming again, then another user takes over the card.
  await rn.click(G1, "gift");
  rn.click(G1, "rename");
  rn.again({ user: "u2", viewer: false });
  out.rename.otherUserClosed = rn.html()[G1];
  rn.rows()[G1].kids[".row-toggle"].listeners.click();
  out.rename.otherUserOpen = rn.html()[G1];
  out.rename.direct = rn.card._actionsHtml(
    { number: G1, gift: true, name: "Geschenk · DHL-Paket …9931" }, "in_transit");
  // Even a rename left in the card for a non-viewer is not drawn.
  rn.card._renaming.set(G1, "Lego");
  out.rename.leftOver = rn.card._actionsHtml(
    { number: G1, gift: true, name: "Geschenk · DHL-Paket …9931" }, "in_transit");

  // ---- the question is not answered: not a viewer, asked again with the next update --
  const fl = mount({ user: "u1", viewer: true, mode: "on", fails: { n: 1 } });
  await tick();
  out.failed = { html: fl.html()[G1], head: fl.head(), asked: fl.log.ws.length };
  fl.again();
  await tick();
  out.failed.retry = { html: fl.html()[G1], head: fl.head(), asked: fl.log.ws.length };
  // Always refused: asked a few times, then no more.
  const fx = mount({ user: "u1", viewer: true, mode: "on", fails: { n: 99 } });
  for (let i = 0; i < 10; i += 1) { await tick(); fx.again(); }
  await tick();
  out.failed.limit = fx.log.ws.length;

  // ---- before the answer arrives: drawn as for a non-viewer ---------------------------
  const hd = mount({ user: "u1", viewer: true, mode: "on", hold: {} });
  await tick();
  out.pending = { html: hd.html()[G1], head: hd.head() };
  hd.opts.hold.release();
  await tick();
  out.pending.after = { html: hd.html()[G1], head: hd.head() };

  // ---- taken for a viewer, but gift_name says no: viewer status dropped, asked anew ---
  const dn = mount({ user: "u1", viewer: true, mode: "on", denied: true });
  await tick();
  out.denied = { before: dn.html()[G1] };
  await dn.click(G1, "gift");
  out.denied.after = dn.html()[G1];
  out.denied.err = dn.head().err;
  out.denied.headAfter = dn.head();
  const asked = dn.log.ws.length;
  dn.again();
  await tick();
  out.denied.askedAgain = dn.log.ws.length - asked;

  // ---- switched on by a non-viewer: the focus does not stay on the vanished switch ----
  const fc = mount({ user: "u9", viewer: false, mode: "off" });
  await tick();
  fc.els.gm.listeners.click();
  await fc.els["giftask-new"].listeners.click();
  out.focus = { before: fc.root.activeElement === fc.els.gm };
  fc.again({ mode: "on" });
  out.focus.after = fc.root.activeElement === fc.els["gm-on"];
  out.focus.gmHidden = fc.els.gm.hidden;

  out.svc = sandbox.__svc;
  console.log(JSON.stringify(out));
})();
"""

G1 = "00340999999999999931"
G2 = "AMZ99990000000000041"
G3 = "00340999999999999961"
P1 = "00340999999999999951"
SWITCH = "switch.paket_tracker_geschenkmodus"


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD), DHL],
        capture_output=True, encoding="utf-8", check=True,
    )
    return json.loads(done.stdout)


def _actions(html: str) -> list[str]:
    blocks = re.findall(r'<div class="actions"[^>]*>(.*?)</div>', html, re.S)
    return [label for b in blocks for label in re.findall(r">([^<>\n]+)</button>", b)]


def test_a_gift_row_shows_the_gift_box(card):
    for html in (card["viewer"]["closed"][G1], card["other"]["closed"][G1]):
        assert 'icon="mdi:gift"' in html
        assert "Geschenk · DHL-Paket …9931" in html
    assert 'icon="mdi:gift"' not in card["viewer"]["closed"][P1]


def test_for_a_gift_viewer_the_box_is_a_button(card):
    html = card["viewer"]["closed"][G1]
    assert re.search(r'<button type="button" class="giftbox" data-a="gift" data-number="'
                     + G1 + r'"[^>]*aria-label="Inhalt anzeigen"', html)
    assert 'aria-pressed="false"' in html


def test_for_others_the_box_is_only_a_symbol(card):
    html = card["other"]["closed"][G1]
    assert 'data-a="gift"' not in html
    assert "Inhalt anzeigen" not in html
    assert re.search(r'<span class="giftbox" role="img" aria-label="Geschenk"', html)


def test_the_card_asks_once_whether_the_user_is_a_gift_viewer(card):
    assert card["viewer"]["ws"] == [{"type": "parcel_tracker/gift_viewer"}]
    assert card["viewer"]["wsAgain"] == 1
    # Without the switch (older integration) nothing is asked and no switch is shown.
    assert card["old"]["ws"] == 0
    assert card["old"]["head"]["gm"]["hidden"] is True
    assert card["old"]["head"]["on"]["hidden"] is True


def test_a_tap_shows_the_real_name_only_in_this_row(card):
    assert card["viewer"]["wsName"] == {"type": "parcel_tracker/gift_name", "number": G1}
    revealed = card["viewer"]["revealed"]
    html = revealed[G1]
    assert "&lt;b&gt;Lego&lt;/b&gt;" in html and "<b>Lego" not in html
    assert "Lego-Bausatz" in html
    assert 'aria-pressed="true"' in html
    assert "Nicht mehr verbergen" in html
    # The link of the parcel comes with the name.
    assert f'href="{DHL}"' in html
    for number, other in revealed.items():
        if number != G1:
            assert "Lego" not in other


def test_only_https_links_from_the_real_name(card):
    html = card["viewer"]["revealedOrder"]
    assert "Bestellung Puppe" in html
    assert "javascript:" not in html


def test_nicht_mehr_verbergen_calls_set_gift(card):
    assert card["viewer"]["unhide"] == ["parcel_tracker", "set_gift", {"number": G1, "gift": False}]
    assert "Lego" not in card["viewer"]["afterUnhide"]


def test_a_second_tap_hides_the_name_again(card):
    html = card["viewer"]["hiddenAgain"]
    assert "Bestellung Puppe" not in html and 'aria-pressed="false"' in html


def test_a_gift_shows_no_links_to_others(card):
    for number in (G1, G2):
        html = card["other"]["open"][number]
        assert "<a " not in html and "href=" not in html
    # The numbers themselves stay.
    assert "Bestellnummer: <span" in card["other"]["open"][G2]
    assert f'href="{DHL}"' in card["other"]["open"][P1]


def test_renaming_and_deleting_a_gift_only_for_viewers(card):
    assert _actions(card["other"]["open"][G1]) == ["Erhalten"]
    assert _actions(card["other"]["open"][G3]) == []
    assert _actions(card["other"]["open"][P1]) == ["Erhalten", "Umbenennen", "Löschen"]
    assert _actions(card["viewer"]["open"]) == ["Erhalten", "Umbenennen", "Löschen"]


def test_the_head_shows_the_switch(card):
    assert "Geschenkmodus" in card["template"]
    head = card["viewer"]["head"]
    assert head["gm"] == {"hidden": False, "checked": "false"}
    assert head["on"]["hidden"] is True
    assert head["ask"]["hidden"] is True
    assert card["viewer"]["onHead"]["gm"] == {"hidden": False, "checked": "true"}
    assert re.search(r'id="gm"[^>]*role="switch"', card["template"])


def test_only_viewers_can_switch_it_off(card):
    head = card["other"]["head"]
    assert head["gm"]["hidden"] is True
    assert head["on"]["hidden"] is False
    off = card["viewer"]["off"]
    assert off["calls"] == [["switch", "turn_off", {"entity_id": SWITCH}]]
    assert off["head"]["ask"]["hidden"] is True


def test_switching_on_asks_first(card):
    asking = card["viewer"]["asking"]
    assert asking["calls"] == 0
    ask = asking["head"]["ask"]
    assert ask["hidden"] is False
    assert "Auch die 2 offenen Pakete verbergen?" in ask["text"]
    assert (
        "Wandtablets und Kinder-Handys brauchen einen eigenen Benutzer in Home Assistant."
    ) in ask["text"]
    assert "Wähle zuerst" not in ask["text"]
    assert ask["all"] and ask["new"] and not ask["only"]


def test_yes_hides_the_open_parcels_too(card):
    assert card["viewer"]["all"]["calls"] == [
        ["switch", "turn_on", {"entity_id": SWITCH}],
        ["parcel_tracker", "set_gift", {"open_parcels": True, "gift": True}],
    ]
    assert card["viewer"]["all"]["head"]["ask"]["hidden"] is True
    assert card["viewer"]["onlyNew"] == [["switch", "turn_on", {"entity_id": SWITCH}]]
    assert card["viewer"]["cancelled"]["calls"] == 0
    assert card["viewer"]["cancelled"]["head"]["ask"]["hidden"] is True


def test_cancelled_orders_are_not_counted_as_open_parcels(card):
    assert "Auch das offene Paket verbergen?" in card["cancelled"]["ask"]["text"]


def test_switching_on_without_being_a_viewer_warns(card):
    text = card["warn"]["ask"]["text"]
    assert (
        "Wähle zuerst unter Konfigurieren aus, wer Geschenke sehen darf. Sonst lässt sich "
        "der Geschenkmodus nur per Automation wieder ausschalten."
    ) in text
    assert "Wandtablets und Kinder-Handys" in text
    assert "Auch das offene Paket verbergen?" in card["one"]["ask"]["text"]


def test_another_user_does_not_see_the_name_shown_before(card):
    other = card["viewer"]["otherUser"]
    assert "Lego" not in other["html"]
    assert other["asked"] == [{"type": "parcel_tracker/gift_viewer"}]
    assert 'data-a="gift"' not in card["viewer"]["otherUserLater"]


def test_errors_are_said_in_german(card):
    svc = card["svc"]
    assert svc["gift_mode_not_allowed"] == (
        "Nur wer Geschenke sehen darf, kann den Geschenkmodus ausschalten."
    )
    assert svc["gift_not_allowed"] == (
        "Nur wer Geschenke sehen darf, kann ein Geschenk wieder sichtbar machen."
    )
    assert svc["gift_remove_not_allowed"] == (
        "Nur wer Geschenke sehen darf, kann ein Geschenk löschen."
    )
    assert svc["gift_rename_not_allowed"] == (
        "Nur wer Geschenke sehen darf, kann ein Geschenk umbenennen."
    )
    assert card["refused"] == svc["gift_mode_not_allowed"]
    assert card["other"]["wsError"] == "Nur wer Geschenke sehen darf, sieht, was drin ist."


def test_the_real_name_never_stays_in_the_rename_field(card):
    rename = card["rename"]
    # While the viewer types, the field holds the revealed name (escaped).
    assert 'data-a="rename-input"' in rename["typing"] and "&lt;b&gt;Lego" in rename["typing"]
    # A second tap on the box hides it from the field as well.
    assert "Lego" not in rename["hidden"]
    assert 'data-a="rename-input"' not in rename["hidden"]
    # Another user on the same card: nothing of it, not even after opening the row.
    for key in ("otherUserClosed", "otherUserOpen", "direct", "leftOver"):
        assert "Lego" not in rename[key], key
        assert "rename-input" not in rename[key], key
    assert 'aria-expanded="false"' in rename["otherUserClosed"]
    assert _actions(rename["otherUserOpen"]) == ["Erhalten"]


def _non_viewer(html: str, head: dict) -> None:
    assert 'data-a="gift"' not in html
    assert '<span class="giftbox" role="img"' in html
    assert head["gm"]["hidden"] is True and head["on"]["hidden"] is False


def test_an_unanswered_question_means_no_viewer_and_is_asked_again(card):
    failed = card["failed"]
    _non_viewer(failed["html"], failed["head"])
    assert failed["asked"] == 1
    retry = failed["retry"]
    assert retry["asked"] == 2
    assert 'data-a="gift"' in retry["html"]
    assert retry["head"]["gm"] == {"hidden": False, "checked": "true"}
    # A question that is always refused is not asked with every update.
    assert failed["limit"] == 5


def test_before_the_answer_the_card_is_drawn_for_a_non_viewer(card):
    pending = card["pending"]
    _non_viewer(pending["html"], pending["head"])
    assert 'data-a="gift"' in pending["after"]["html"]
    assert pending["after"]["head"]["gm"]["hidden"] is False


def test_not_allowed_takes_the_viewer_status_back(card):
    denied = card["denied"]
    assert 'data-a="gift"' in denied["before"]
    _non_viewer(denied["after"], denied["headAfter"])
    assert "Lego" not in denied["after"]
    assert denied["err"] == "Nur wer Geschenke sehen darf, sieht, was drin ist."
    assert denied["askedAgain"] == 1


def test_the_focus_moves_to_the_sign_when_the_switch_disappears(card):
    focus = card["focus"]
    assert focus["before"] is True
    assert focus["gmHidden"] is True
    assert focus["after"] is True
