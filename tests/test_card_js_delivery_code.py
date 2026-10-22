"""Card: the delivery code is no attribute any more; the card asks for it over the WebSocket
(parcel_tracker/delivery_code) only when it is revealed, and forgets it with another user
(run in Node)."""

import json
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")
AMZ = "AMZ99905626221455530"
NONE = "AMZ99990000000000052"

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
const AMZ = process.argv[2];
const NONE = process.argv[3];
const tick = () => new Promise((r) => setTimeout(r, 0));

const blank = { days_until: null, events: [], status_text: null, progress: 0, last_error: null };
function makeHass(opts) {
  const parcels = [
    ["out_for_delivery", { number: AMZ, name: "Kopfhörer", carrier: "amazon",
                           has_delivery_code: opts.has !== false }],
    ["out_for_delivery", { number: NONE, name: "Buch", carrier: "amazon",
                           has_delivery_code: false }],
  ];
  const states = {};
  const entities = {};
  parcels.forEach(([state, attributes], i) => {
    const id = `sensor.paket_${i}`;
    states[id] = { entity_id: id, state, last_updated: "t" + (opts.has !== false),
      attributes: { ...blank, ...attributes } };
    entities[id] = { platform: "parcel_tracker" };
  });
  return {
    states, entities, user: { id: opts.user },
    callWS: async (msg) => {
      opts.log.push(msg);
      if (msg.type !== "parcel_tracker/delivery_code") throw new Error("unknown");
      if (opts.fail) { const e = new Error("lost"); e.code = "unknown_error"; throw e; }
      if (opts.hold) {
        return new Promise((r) => { opts.hold.release = () => r({ code: opts.code }); });
      }
      return { code: opts.code };
    },
    callService: async () => {},
  };
}

function mount(opts) {
  const log = [];
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
  const o = { ...opts, log };
  card.hass = makeHass(o);
  const rows = () => Object.fromEntries(els.list.children.map((item) => [
    /data-number="([^"]+)"/.exec(item.innerHTML)[1], item]));
  const html = (n) => rows()[n].innerHTML;
  const click = (n, a) => rows()[n].kids[`[data-a="${a}"]`].listeners.click();
  const toggle = (n) => rows()[n].kids[".row-toggle"].listeners.click();
  const again = (more = {}) => { Object.assign(o, more); card.hass = makeHass(o); };
  const err = () => root.getElementById("err").innerHTML;
  return { card, log, html, click, toggle, again, err, o };
}

(async () => {
  const out = {};

  // ---- the code is fetched only when revealed, shown escaped, kept for this user ----
  const m = mount({ user: "u1", code: "12<3>" });
  await tick();
  out.closed = { html: m.html(AMZ), ws: m.log.length };
  m.toggle(AMZ);
  m.toggle(NONE);
  out.open = { html: m.html(AMZ), none: m.html(NONE), ws: m.log.length };
  m.click(AMZ, "code");
  out.ask = { html: m.html(AMZ), ws: m.log.length };
  await m.click(AMZ, "code-confirm");
  await tick();
  out.show = { html: m.html(AMZ), ws: m.log.slice() };
  m.click(AMZ, "code-hide");
  out.hidden = m.html(AMZ);
  m.click(AMZ, "code");
  await m.click(AMZ, "code-confirm");
  await tick();
  out.again = { html: m.html(AMZ), ws: m.log.length };
  out.state = { sig: m.card._signature() };
  // Another user on the same card: nothing of the code stays, it is asked for anew.
  m.again({ user: "u2", code: "999999" });
  out.otherUser = { html: m.html(AMZ), cached: m.card._codes.size };
  m.toggle(AMZ);
  m.click(AMZ, "code");
  await m.click(AMZ, "code-confirm");
  await tick();
  out.otherUser.after = { html: m.html(AMZ), ws: m.log.length };
  // The parcel has no code any more: the button goes, the code is forgotten.
  m.again({ has: false });
  out.gone = { html: m.html(AMZ), cached: m.card._codes.size };

  // ---- no valid code (expired meanwhile, option switched off) ----------------------
  const n = mount({ user: "u1", code: null });
  await tick();
  n.toggle(AMZ);
  n.click(AMZ, "code");
  await n.click(AMZ, "code-confirm");
  await tick();
  out.nullCode = { html: n.html(AMZ), err: n.err(), cached: n.card._codes.size };

  // ---- the question fails --------------------------------------------------------
  const f = mount({ user: "u1", code: "4711", fail: true });
  await tick();
  f.toggle(AMZ);
  f.click(AMZ, "code");
  await f.click(AMZ, "code-confirm");
  await tick();
  out.failed = { html: f.html(AMZ), err: f.err(), cached: f.card._codes.size };

  // ---- the answer comes after another user took over: not kept, not shown ---------
  const hold = {};
  const h = mount({ user: "u1", code: "4711", hold });
  await tick();
  h.toggle(AMZ);
  h.click(AMZ, "code");
  const pending = h.click(AMZ, "code-confirm");
  await tick();
  h.again({ user: "u2", hold: null });
  h.toggle(AMZ);
  hold.release();
  await pending;
  await tick();
  out.late = { cached: h.card._codes.size, html: h.html(AMZ), mode: h.card._code.size };
  console.log(JSON.stringify(out));
  process.exit(0);
})();
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD), AMZ, NONE],
        capture_output=True, encoding="utf-8", check=True,
    )
    return json.loads(done.stdout)


def test_nothing_is_asked_before_the_reveal(card):
    assert card["closed"]["ws"] == 0
    assert card["open"]["ws"] == 0
    assert card["ask"]["ws"] == 0
    assert "Code anzeigen" in card["open"]["html"]
    assert "Zustell-Code anzeigen?" in card["ask"]["html"]


def test_a_parcel_without_a_code_has_no_button(card):
    assert "Code anzeigen" not in card["open"]["none"]


def test_the_reveal_asks_the_integration_and_shows_the_code_escaped(card):
    assert card["show"]["ws"] == [{"type": "parcel_tracker/delivery_code", "number": AMZ}]
    html = card["show"]["html"]
    assert "12&lt;3&gt;" in html and "<3>" not in html
    assert "Verbergen" in html
    assert "12&lt;3&gt;" not in card["hidden"]
    assert "Code anzeigen" in card["hidden"]


def test_the_code_is_kept_for_the_same_user(card):
    assert card["again"]["ws"] == 1
    assert "12&lt;3&gt;" in card["again"]["html"]
    # The code is not part of the render signature (only whether it is shown).
    assert "12" not in card["state"]["sig"].split("|code:")[1].split("|")[0].replace(AMZ, "")


def test_another_user_does_not_see_the_code_and_asks_anew(card):
    other = card["otherUser"]
    assert other["cached"] == 0
    assert "12&lt;3&gt;" not in other["html"]
    assert other["after"]["ws"] == 2
    assert "999999" in other["after"]["html"]
    assert "12&lt;3&gt;" not in other["after"]["html"]


def test_a_parcel_without_a_code_any_more_forgets_it(card):
    assert card["gone"]["cached"] == 0
    assert "Code anzeigen" not in card["gone"]["html"]
    assert "999999" not in card["gone"]["html"]


def test_no_valid_code_says_so(card):
    res = card["nullCode"]
    assert res["cached"] == 0
    assert "Kein gültiger Zustell-Code" in res["err"]
    assert "Code anzeigen" in res["html"]
    assert "Verbergen" not in res["html"]


def test_a_failed_question_says_so_and_shows_nothing(card):
    res = card["failed"]
    assert res["cached"] == 0
    assert "Das hat nicht geklappt" in res["err"]
    assert "4711" not in res["html"]


def test_a_late_answer_for_the_user_before_is_dropped(card):
    assert card["late"]["cached"] == 0
    assert card["late"]["mode"] == 0
    assert "4711" not in card["late"]["html"]
    assert "Code anzeigen" in card["late"]["html"]
