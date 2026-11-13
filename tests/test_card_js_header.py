"""Card: option ``header`` (v0.3.46) and no "0 heute" badge (run in Node).

``header: false`` leaves out the whole head (title, badges, gift switch, plus). Adding
stays reachable through a line "Paket hinzufügen" (unless ``add_form: never``), and the
gift question can no longer be opened from the card (the switch entity still works).
"""

import json
import re
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")
SOURCE = BUNDLED_CARD.read_text(encoding="utf-8")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const defined = {};
const fakeEl = () => {
  let html = "";
  const el = {
    hidden: false, value: "", textContent: "", className: "", title: "",
    listeners: {}, attrs: {}, kids: {}, children: [], dataset: {}, focused: 0,
    get innerHTML() { return html; },
    set innerHTML(value) { html = value; el.children = []; },
    addEventListener(name, fn) { el.listeners[name] = fn; },
    setAttribute(name, value) { el.attrs[name] = String(value); },
    toggleAttribute() {},
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
  location: { reload() {} },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8")
  + "\n;globalThis.__header = headerShown; globalThis.__empty = emptyText;"
  + "globalThis.__badges = todayBadges;", sandbox);
const Card = defined["parcel-tracker-card"];
const SWITCH = "switch.paket_tracker_geschenkmodus";
const tick = () => new Promise((r) => setTimeout(r, 0));

function makeHass(opts) {
  const states = {
    "sensor.pakete_heute": { entity_id: "sensor.pakete_heute", state: opts.today || "0",
      last_updated: "t" + (opts.today || "0"), attributes: { parcels: [] } },
  };
  const entities = {};
  if (opts.mode != null) {
    states[SWITCH] = { entity_id: SWITCH, state: opts.mode, last_updated: "t" + opts.mode,
      attributes: {} };
    entities[SWITCH] = { platform: "parcel_tracker" };
  }
  const log = opts.log;
  return {
    states, entities, user: { id: "u1" },
    callWS: async (msg) => {
      log.ws.push(msg.type);
      if (msg.type === "parcel_tracker/gift_viewer") return { viewer: true };
      throw new Error("unknown");
    },
    callService: async (domain, service, data) => { log.svc.push([domain, service, data]); },
  };
}

function mount(config, opts = {}) {
  const log = { ws: [], svc: [] };
  const card = new Card();
  const els = {};
  const root = {
    innerHTML: "", activeElement: null,
    getElementById(id) {
      if (!els[id]) {
        const el = fakeEl();
        el.focus = () => { el.focused += 1; root.activeElement = el; };
        els[id] = el;
      }
      return els[id];
    },
  };
  card.attachShadow = () => root;
  card.dispatchEvent = () => {};
  card.setConfig(config);
  card.hass = makeHass({ ...opts, log });
  const look = () => ({
    head: !els.head.hidden,
    plus: !els.toggle.hidden,
    line: !els.addline.hidden,
    lineText: els["toggle-line-text"].textContent,
    lineExpanded: els["toggle-line"].attrs["aria-expanded"],
    form: !els.form.hidden,
  });
  return { card, els, root, log, look, opts };
}

(async () => {
  const out = {};
  out.header = {
    none: sandbox.__header(undefined), empty: sandbox.__header({}),
    yes: sandbox.__header({ header: true }), no: sandbox.__header({ header: false }),
    noText: sandbox.__header({ header: " False " }), other: sandbox.__header({ header: "nope" }),
    zero: sandbox.__header({ header: 0 }),
  };
  out.empty = {
    buttonHead: sandbox.__empty("button", true),
    buttonNoHead: sandbox.__empty("button", false),
    alwaysNoHead: sandbox.__empty("always", false),
    neverNoHead: sandbox.__empty("never", false),
    unknownNoHead: sandbox.__empty("bogus", false),
  };

  // Default: the head as before, no line.
  const d = mount({});
  out.withHead = d.look();

  // header: false with the default add_form (button): the line stands for the plus.
  const a = mount({ header: false });
  out.noHead = { start: a.look(), list: a.els.list.innerHTML };
  a.els["toggle-line"].listeners.click();
  out.noHead.open = { ...a.look(), numFocused: a.els.num.focused };
  a.els.form.listeners.keydown({ key: "Escape", preventDefault() {} });
  out.noHead.escaped = { ...a.look(), lineFocused: a.els["toggle-line"].focused,
    plusFocused: a.els.toggle.focused };
  a.els["toggle-line"].listeners.click();
  a.els.num.value = "00340999999999999901";
  await a.card._add();
  out.noHead.added = { ...a.look(), calls: a.log.svc.map((c) => [c[1], c[2].number]),
    lineFocused: a.els["toggle-line"].focused, plusFocused: a.els.toggle.focused };
  a.els["added-close"].listeners.click();
  out.noHead.closedNote = { lineFocused: a.els["toggle-line"].focused,
    plusFocused: a.els.toggle.focused };

  // add_form always / never without a head.
  const b = mount({ header: false, add_form: "always" });
  out.alwaysNoHead = b.look();
  const c = mount({ header: false, add_form: "never" });
  out.neverNoHead = { ...c.look(), list: c.els.list.innerHTML };

  // Back to a head on the same card (dashboard editor).
  a.card.setConfig({});
  out.reconfig = a.look();

  // Gift mode without a head: the question cannot open, switching on elsewhere is fine.
  const g = mount({ header: false }, { mode: "off" });
  await tick();
  g.card._toggleGiftMode();
  out.gift = { asking: g.card._giftAsk, box: !g.els.giftask.hidden,
    cancelFocused: g.els["giftask-cancel"].focused, gmFocused: g.els.gm.focused,
    head: !g.els.head.hidden };
  g.card.hass = makeHass({ mode: "on", log: g.log });
  out.gift.on = { box: !g.els.giftask.hidden, err: g.els.err.innerHTML };
  await g.card._giftModeOn(true);
  out.gift.calls = g.log.svc.map((c) => [c[0], c[1]]);
  out.gift.after = { asking: g.card._giftAsk, box: !g.els.giftask.hidden,
    err: g.els.err.innerHTML };
  // With a head the question still opens as before.
  const h = mount({}, { mode: "off" });
  await tick();
  h.card._toggleGiftMode();
  out.giftHead = { asking: h.card._giftAsk, box: !h.els.giftask.hidden,
    cancelFocused: h.els["giftask-cancel"].focused };

  // Badges: none with nothing today, the box itself hidden; "1 heute" with one.
  const z = mount({});
  out.badges = { zero: { html: z.els.today.innerHTML, hidden: z.els.today.hidden } };
  z.card.hass = makeHass({ today: "1", log: z.log });
  out.badges.one = { html: z.els.today.innerHTML, hidden: z.els.today.hidden };
  out.badges.direct = {
    zero: sandbox.__badges({ state: "0", attributes: {} }).map((b) => b.text),
    zeroWithOthers: sandbox.__badges({ state: "0",
      attributes: { possible_count: 2, delivered_today_count: 1 } }).map((b) => b.text),
  };
  console.log(JSON.stringify(out));
})();
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node not installed")
    run = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, text=True, check=True
    )
    return json.loads(run.stdout)


HEAD = {
    "head": True, "plus": True, "line": False, "lineText": "Paket hinzufügen",
    "lineExpanded": "false", "form": False,
}
NO_HEAD = {**HEAD, "head": False, "plus": False, "line": True}


def test_header_option_is_on_unless_false(card):
    assert card["header"] == {
        "none": True, "empty": True, "yes": True, "no": False, "noText": False,
        "other": True, "zero": True,
    }


def test_default_card_keeps_its_head(card):
    assert card["withHead"] == HEAD
    assert card["reconfig"] == HEAD


def test_without_head_a_line_opens_the_form(card):
    no_head = card["noHead"]
    assert no_head["start"] == NO_HEAD
    assert no_head["open"] == {
        **NO_HEAD, "lineText": "Eingabe schließen", "lineExpanded": "true", "form": True,
        "numFocused": 1,
    }
    # Escape and a successful add give the focus back to the line, never the hidden plus.
    assert no_head["escaped"] == {**NO_HEAD, "lineFocused": 1, "plusFocused": 0}
    assert no_head["added"] == {
        **NO_HEAD, "calls": [["add_parcel", "00340999999999999901"]],
        "lineFocused": 2, "plusFocused": 0,
    }
    assert no_head["closedNote"] == {"lineFocused": 3, "plusFocused": 0}


def test_without_head_the_empty_list_points_to_the_line(card):
    assert "Über „Paket hinzufügen“ oben" in card["noHead"]["list"]
    line = "Noch keine Pakete. Über „Paket hinzufügen“ oben fügst du eine Sendung hinzu."
    assert card["empty"] == {
        "buttonHead": "Noch keine Pakete. Über das Plus oben fügst du eine Sendung hinzu.",
        "buttonNoHead": line,
        "alwaysNoHead": "Noch keine Pakete. Trag oben eine Sendungsnummer ein.",
        "neverNoHead": "Noch keine Pakete.",
        "unknownNoHead": line,
    }


def test_without_head_always_and_never_need_no_line(card):
    assert card["alwaysNoHead"] == {**NO_HEAD, "line": False, "form": True}
    never = card["neverNoHead"]
    assert {k: never[k] for k in NO_HEAD} == {**NO_HEAD, "line": False}
    assert never["list"] == '<div class="sub">Noch keine Pakete.</div>'


def test_without_head_the_gift_question_never_opens_and_switching_on_still_works(card):
    gift = card["gift"]
    assert gift["asking"] is False and gift["box"] is False and gift["head"] is False
    assert gift["cancelFocused"] == 0 and gift["gmFocused"] == 0
    assert gift["on"] == {"box": False, "err": ""}
    assert gift["calls"] == [["switch", "turn_on"], ["parcel_tracker", "set_gift"]]
    assert gift["after"] == {"asking": False, "box": False, "err": ""}
    # With the head nothing changed.
    assert card["giftHead"] == {"asking": True, "box": True, "cancelFocused": 1}


def test_no_zero_today_badge(card):
    badges = card["badges"]
    assert badges["zero"] == {"html": "", "hidden": True}
    assert ">1 heute<" in badges["one"]["html"] and badges["one"]["hidden"] is False
    assert badges["direct"] == {"zero": [], "zeroWithOthers": ["2 möglich", "1 zugestellt"]}


def test_source_has_the_line_and_the_head_id():
    assert '<div class="head" id="head">' in SOURCE
    line = re.search(r'<button type="button" id="toggle-line"[^>]*>', SOURCE).group(0)
    assert 'aria-controls="form"' in line and 'aria-expanded="false"' in line
    assert 'const ADD_LINE_LABEL = "Paket hinzufügen";' in SOURCE
    rule = re.search(r"\.addline button \{([^}]*)\}", SOURCE).group(1)
    assert "min-height:36px" in rule
    assert re.search(r"\.addline button:focus-visible \{[^}]*outline:2px solid", SOURCE)
