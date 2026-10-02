"""Card: add form behind the plus button, option ``add_form``, reload hint (run in Node)."""

import json
import re
import shutil
import subprocess

import pytest

from custom_components.parcel_tracker import const
from custom_components.parcel_tracker.card_install import BUNDLED_CARD

NODE = shutil.which("node")
SOURCE = BUNDLED_CARD.read_text(encoding="utf-8")

SCRIPT = r"""
const fs = require("fs");
const vm = require("vm");
const defined = {};
let reloads = 0;
const sandbox = {
  HTMLElement: class {},
  customElements: { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } },
  window: {},
  location: { reload() { reloads += 1; } },
};
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(process.argv[1], "utf8")
    + "\n;globalThis.__mode = addFormMode; globalThis.__reload = needsReload;"
    + "globalThis.__version = CARD_VERSION; globalThis.__empty = emptyText;",
  sandbox,
);
const Card = defined["parcel-tracker-card"];

// A tiny stand-in for the shadow DOM: elements remember listeners, attributes and focus.
const fakeEl = () => {
  const el = {
    hidden: false, value: "", innerHTML: "", textContent: "", className: "", title: "",
    listeners: {}, attrs: {}, kids: {}, focused: 0,
    addEventListener(name, fn) { el.listeners[name] = fn; },
    setAttribute(name, value) { el.attrs[name] = String(value); },
    focus() { el.focused += 1; },
    contains() { return false; },
    querySelector(sel) {
      if (sel === 'option[value="other"]') return null;
      return (el.kids[sel] ||= fakeEl());
    },
    insertAdjacentHTML() {},
  };
  return el;
};
const today = (version) => ({
  state: "0", last_updated: "t" + version,
  attributes: version === undefined ? {} : { integration_version: version },
});
const hassWith = (version, extra = {}) => ({
  states: { "sensor.pakete_heute": today(version), ...extra }, entities: {},
});
const QUOTA = { "sensor.paket_tracker_17track_kontingent": { state: "150", last_updated: "t" } };

function mount(config, hass = hassWith(sandbox.__version)) {
  const card = new Card();
  const els = {};
  const root = {
    innerHTML: "", activeElement: null,
    getElementById(id) { return (els[id] ||= fakeEl()); },
  };
  card.attachShadow = () => root;
  card.setConfig(config);
  const calls = [];
  hass.callService = async (...args) => { calls.push(args); };
  card.hass = hass;
  return { card, els, root, calls, hass };
}
const look = ({ els }) => ({
  form: !els.form.hidden,
  toggle: !els.toggle.hidden,
  expanded: els.toggle.attrs["aria-expanded"],
  label: els.toggle.attrs["aria-label"],
  title: els.toggle.title,
});

const out = { version: sandbox.__version };
out.mode = {
  none: sandbox.__mode(undefined),
  empty: sandbox.__mode({}),
  button: sandbox.__mode({ add_form: "button" }),
  always: sandbox.__mode({ add_form: "always" }),
  never: sandbox.__mode({ add_form: "never" }),
  upper: sandbox.__mode({ add_form: " Never " }),
  unknown: sandbox.__mode({ add_form: "sometimes" }),
  bool: sandbox.__mode({ add_form: false }),
  nothing: sandbox.__mode({ add_form: null }),
};
out.reload = {
  noSensor: sandbox.__reload(undefined),
  noAttributes: sandbox.__reload({ state: "unavailable" }),
  missing: sandbox.__reload(today(undefined)),
  equal: sandbox.__reload(today(sandbox.__version)),
  newer: sandbox.__reload(today("99.0.0")),
  older: sandbox.__reload(today("0.0.1")),
  empty: sandbox.__reload(today("")),
  odd: sandbox.__reload(today(7)),
};
out.empty = {
  button: sandbox.__empty("button"), always: sandbox.__empty("always"),
  never: sandbox.__empty("never"),
};
out.stub = Card.getStubConfig();

(async () => {
  // Default: collapsed behind the plus; a click opens, the next one closes.
  const a = mount({});
  out.button = { start: look(a) };
  a.els.toggle.listeners.click();
  out.button.open = { ...look(a), numFocused: a.els.num.focused };
  // A hass update re-renders the list: the form stays open.
  a.hass.states["sensor.pakete_heute"].last_updated = "later";
  a.card.hass = a.hass;
  out.button.afterHass = look(a);
  a.els.toggle.listeners.click();
  out.button.closed = look(a);

  // A failed add keeps the form open and says why; a successful one closes it.
  a.els.toggle.listeners.click();
  a.els.num.value = "00340999999999999901";
  a.hass.callService = async () => { throw { code: "duplicate" }; };
  await a.card._add();
  out.button.afterError = { ...look(a), err: a.els.err.innerHTML, num: a.els.num.value };
  a.hass.callService = async (...args) => { a.calls.push(args); };
  await a.card._add();
  out.button.afterAdd = {
    ...look(a), err: a.els.err.innerHTML, num: a.els.num.value,
    added: a.calls.map((c) => [c[1], c[2].number]), toggleFocused: a.els.toggle.focused,
  };

  // Escape in the form closes it and hands the focus back to the plus.
  a.els.toggle.listeners.click();
  let prevented = 0;
  a.els.form.listeners.keydown({ key: "a", preventDefault() { prevented += 1; } });
  out.button.afterOtherKey = look(a).form;
  a.els.form.listeners.keydown({ key: "Escape", preventDefault() { prevented += 1; } });
  out.button.afterEscape = { ...look(a), prevented, toggleFocused: a.els.toggle.focused };

  // The 17track confirmation lives in the form: closing the form dismisses it, adds nothing.
  const b = mount({ add_form: "button" }, hassWith(sandbox.__version, QUOTA));
  b.els.toggle.listeners.click();
  b.els.num.value = "999999999907";
  b.els.car.value = "other";
  await b.card._add();
  out.ask = {
    shown: !b.els.addask.hidden && b.card._addAsk,
    question: b.els.addask.innerHTML.includes("von 150 verbleibenden"),
    form: look(b).form,
  };
  b.els.toggle.listeners.click();
  out.ask.afterClose = {
    form: look(b).form, hidden: b.els.addask.hidden, asking: b.card._addAsk,
    added: b.calls.length,
  };
  // Open again: no stale question; confirming adds and closes the form.
  b.els.toggle.listeners.click();
  out.ask.reopened = { hidden: b.els.addask.hidden, form: look(b).form };
  await b.card._add();
  b.els.addask.kids["#addask-yes"].listeners.click();
  await new Promise((r) => setTimeout(r, 0));
  out.ask.afterYes = {
    form: look(b).form, hidden: b.els.addask.hidden,
    added: b.calls.map((c) => [c[1], c[2].number, c[2].carrier]),
  };

  // always: the old look, no plus; never: neither form nor plus.
  const c = mount({ add_form: "always" });
  out.always = { start: look(c), err: c.els.err.className };
  c.els.num.value = "00340999999999999901";
  await c.card._add();
  out.always.afterAdd = { ...look(c), added: c.calls.length };
  c.els.form.listeners.keydown({ key: "Escape", preventDefault() {} });
  out.always.afterEscape = look(c).form;
  const d = mount({ add_form: "never" });
  out.never = { start: look(d), err: d.els.err.className };
  const e = mount({ add_form: "bogus" });
  out.unknown = look(e);
  out.collapsedErr = e.els.err.className;

  // Two cards: each has its own state.
  const f = mount({});
  const g = mount({});
  f.els.toggle.listeners.click();
  out.instances = [look(f).form, look(g).form];

  // A config change on a built card takes effect (dashboard editor).
  f.card.setConfig({ add_form: "always" });
  out.reconfig = { always: look(f) };
  f.card.setConfig({ add_form: "never" });
  out.reconfig.never = look(f);
  f.card.setConfig({});
  out.reconfig.button = look(f);

  // The reload hint: only when the integration says another version than the card's.
  const hint = (version) => {
    const m = mount({}, hassWith(version));
    return { m, shown: !m.els.reload.hidden };
  };
  out.hint = {
    equal: hint(sandbox.__version).shown,
    missing: hint(undefined).shown,
  };
  const h = hint("99.0.0");
  out.hint.differs = h.shown;
  h.m.els["reload-btn"].listeners.click();
  out.hint.reloads = reloads;
  // The integration and the card agree again (e.g. state restored): the hint goes away.
  h.m.card.hass = hassWith(sandbox.__version);
  out.hint.afterMatch = !h.m.els.reload.hidden;
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


CLOSED = {
    "form": False, "toggle": True, "expanded": "false",
    "label": "Sendung hinzufügen", "title": "Sendung hinzufügen",
}
OPEN = {
    "form": True, "toggle": True, "expanded": "true",
    "label": "Eingabe schließen", "title": "Eingabe schließen",
}


def test_card_version_is_the_integration_version(card):
    """Every release bumps CARD_VERSION: the reload hint compares against it."""
    assert card["version"] == const.VERSION
    assert re.findall(r'^const CARD_VERSION = "([^"]+)";$', SOURCE, re.M) == [const.VERSION]


def test_add_form_option_has_three_values_and_falls_back_to_button(card):
    assert card["mode"] == {
        "none": "button", "empty": "button", "button": "button", "always": "always",
        "never": "never", "upper": "never", "unknown": "button", "bool": "button",
        "nothing": "button",
    }
    assert card["stub"] == {}  # the stub config means the default: behind the plus


def test_form_is_collapsed_behind_the_plus_by_default(card):
    assert card["button"]["start"] == CLOSED
    assert card["unknown"] == CLOSED


def test_plus_toggles_the_form_and_focuses_the_number_field(card):
    button = card["button"]
    assert button["open"] == {**OPEN, "numFocused": 1}
    assert button["closed"] == CLOSED


def test_open_form_survives_a_hass_update(card):
    assert card["button"]["afterHass"] == OPEN


def test_form_stays_open_on_an_error_and_closes_after_an_add(card):
    button = card["button"]
    assert button["afterError"] == {
        **OPEN, "err": "Dieses Paket ist schon in der Liste.", "num": "00340999999999999901",
    }
    assert button["afterAdd"] == {
        **CLOSED, "err": "", "num": "",
        "added": [["add_parcel", "00340999999999999901"]], "toggleFocused": 1,
    }


def test_escape_closes_the_form(card):
    button = card["button"]
    assert button["afterOtherKey"] is True
    assert button["afterEscape"] == {**CLOSED, "prevented": 1, "toggleFocused": 2}


def test_17track_confirmation_works_inside_the_form(card):
    ask = card["ask"]
    assert ask["shown"] and ask["question"] and ask["form"]
    assert ask["afterClose"] == {"form": False, "hidden": True, "asking": False, "added": 0}
    assert ask["reopened"] == {"hidden": True, "form": True}
    assert ask["afterYes"] == {
        "form": False, "hidden": True, "added": [["add_parcel", "999999999907", "other"]],
    }


def test_always_shows_the_form_without_a_plus(card):
    always = card["always"]
    shown = {**CLOSED, "form": True, "toggle": False}
    assert always["start"] == shown
    assert always["afterAdd"] == {**shown, "added": 1}  # nothing to close
    assert always["afterEscape"] is True
    assert always["err"] == "err"  # the line under the form keeps its room


def test_never_shows_neither_form_nor_plus(card):
    assert card["never"]["start"] == {**CLOSED, "form": False, "toggle": False}
    # Without the form the empty error line takes no room.
    assert card["never"]["err"] == "err bare" and card["collapsedErr"] == "err bare"


def test_state_is_per_card(card):
    assert card["instances"] == [True, False]


def test_config_change_on_a_built_card_takes_effect(card):
    reconfig = card["reconfig"]
    assert reconfig["always"] == {**CLOSED, "form": True, "toggle": False}
    assert reconfig["never"] == {**CLOSED, "form": False, "toggle": False}
    assert reconfig["button"] == CLOSED


def test_empty_list_text_points_to_what_the_card_offers(card):
    empty = card["empty"]
    assert empty["always"] == "Noch keine Pakete. Trag oben eine Sendungsnummer ein."
    assert empty["button"] == "Noch keine Pakete. Über das Plus oben fügst du eine Sendung hinzu."
    assert empty["never"] == "Noch keine Pakete."


def test_reload_hint_only_when_the_integration_has_another_version(card):
    assert card["reload"] == {
        "noSensor": False, "noAttributes": False, "missing": False, "equal": False,
        "newer": True, "older": True, "empty": False, "odd": False,
    }
    hint = card["hint"]
    assert (hint["equal"], hint["missing"], hint["differs"]) == (False, False, True)
    assert hint["reloads"] == 1
    assert hint["afterMatch"] is False


def test_source_has_the_plus_button_and_the_hint():
    plus = re.search(r'<button type="button" class="plus" id="toggle"[^>]*>', SOURCE).group(0)
    assert 'const ADD_LABEL = "Sendung hinzufügen";' in SOURCE
    assert 'const CLOSE_LABEL = "Eingabe schließen";' in SOURCE
    for text in (
        'aria-label="${ADD_LABEL}"',
        'title="${ADD_LABEL}"',
        'aria-expanded="false"',
        'aria-controls="form"',
    ):
        assert text in plus, text
    assert '<div id="form" hidden>' in SOURCE
    # At least 36 x 36 px to hit, round, with a visible focus ring.
    rule = re.search(r"\.plus \{([^}]*)\}", SOURCE).group(1)
    assert "width:36px" in rule and "height:36px" in rule and "border-radius:50%" in rule
    assert re.search(r"\.plus:focus-visible \{[^}]*outline:2px solid", SOURCE)
    assert (
        "Neue Version installiert – Seite neu laden, um die Karte zu aktualisieren." in SOURCE
    )
    assert '<button type="button" id="reload-btn">Neu laden</button>' in SOURCE
    assert "location.reload()" in SOURCE
