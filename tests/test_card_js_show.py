"""Card: option ``show`` – the card hides itself while nothing is due (run in Node)."""

import json
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
// The host element as Home Assistant's hui-card sees it: the `hidden` property mirrors the
// attribute, events are collected.
class FakeHost {
  constructor() { this.hidden = false; this.events = []; }
  toggleAttribute(name, force) { if (name === "hidden") this.hidden = !!force; }
  dispatchEvent(ev) { this.events.push(ev); return true; }
}
class FakeEvent {
  constructor(type, init) { this.type = type; Object.assign(this, init); }
}
const sandbox = {
  HTMLElement: FakeHost,
  Event: FakeEvent,
  customElements: { get: (n) => defined[n], define: (n, c) => { defined[n] = c; } },
  window: {},
  location: { reload() {} },
};
vm.createContext(sandbox);
vm.runInContext(
  fs.readFileSync(process.argv[1], "utf8")
    + "\n;globalThis.__mode = showMode; globalThis.__show = shouldShow;"
    + "globalThis.__modes = SHOW_MODES; globalThis.__note = hiddenNote;",
  sandbox,
);
const Card = defined["parcel-tracker-card"];

const fakeEl = () => {
  const el = {
    hidden: false, value: "", innerHTML: "", textContent: "", className: "", title: "",
    listeners: {}, attrs: {}, kids: {},
    addEventListener(name, fn) { el.listeners[name] = fn; },
    setAttribute(name, value) { el.attrs[name] = String(value); },
    focus() {},
    contains() { return false; },
    querySelector(sel) {
      if (sel === 'option[value="other"]') return null;
      return (el.kids[sel] ||= fakeEl());
    },
    insertAdjacentHTML() {},
  };
  return el;
};

let tick = 0;
// today: [sure, possible, delivered] of sensor.pakete_heute, active: sensor.pakete_unterwegs.
function hassWith({ today = [0, 0, 0], active = 0 } = {}) {
  const states = {};
  tick += 1;
  if (today !== null) {
    const [sure, possible, delivered] = today;
    const attributes = {};
    if (possible !== undefined) attributes.possible_count = possible;
    if (delivered !== undefined) attributes.delivered_today_count = delivered;
    states["sensor.pakete_heute"] = { state: String(sure), attributes, last_updated: "t" + tick };
  }
  if (active !== null) {
    states["sensor.pakete_unterwegs"] = {
      state: String(active), attributes: {}, last_updated: "t" + tick };
  }
  return { states, entities: {}, callService: async () => {} };
}

function mount(config, hass, before) {
  const card = new Card();
  const els = {};
  const root = {
    innerHTML: "", activeElement: null,
    getElementById(id) { return (els[id] ||= fakeEl()); },
  };
  card.attachShadow = () => root;
  if (before) before(card);
  card.setConfig(config);
  card.hass = hass;
  return { card, els, root };
}
const look = (m) => ({
  hidden: m.card.hidden,
  note: m.els["hidden-note"].hidden ? null : m.els["hidden-note"].textContent,
  events: m.card.events.map((e) => [e.type, e.detail.value, e.bubbles, e.composed]),
});

const out = { modes: sandbox.__modes };
out.mode = {
  none: sandbox.__mode(undefined), empty: sandbox.__mode({}),
  always: sandbox.__mode({ show: "always" }), active: sandbox.__mode({ show: "active" }),
  today: sandbox.__mode({ show: "today" }),
  todayPossible: sandbox.__mode({ show: "today_possible" }),
  upper: sandbox.__mode({ show: " Today_Possible " }), unknown: sandbox.__mode({ show: "never" }),
  bool: sandbox.__mode({ show: true }), nothing: sandbox.__mode({ show: null }),
};

// The decision: every mode against every situation.
const CASES = {
  nothing: hassWith(),
  activeOnly: hassWith({ active: 2 }),
  sure: hassWith({ today: [1, 0, 0], active: 1 }),
  possible: hassWith({ today: [0, 1, 0], active: 1 }),
  delivered: hassWith({ today: [0, 0, 1], active: 0 }),
  noActiveSensor: hassWith({ active: null }),
  noTodaySensor: hassWith({ today: null }),
  noSensors: hassWith({ today: null, active: null }),
  oldTodaySensor: hassWith({ today: [0, undefined, undefined] }),
  oldTodaySensorPossible: hassWith({ today: [0, 0, undefined] }),
  unavailable: { states: {
    "sensor.pakete_heute": { state: "unavailable", attributes: {} },
    "sensor.pakete_unterwegs": { state: "unavailable", attributes: {} } } },
  unknown: { states: {
    "sensor.pakete_heute": { state: "unknown", attributes: {} },
    "sensor.pakete_unterwegs": { state: "unknown", attributes: {} } } },
  noHass: undefined,
  noStates: {},
};
out.decision = {};
for (const mode of sandbox.__modes) {
  out.decision[mode] = Object.fromEntries(
    Object.entries(CASES).map(([name, hass]) => [name, sandbox.__show(mode, hass)]));
}
out.note = sandbox.__note("active");

// On a dashboard.
const quiet = mount({ show: "active" }, hassWith());
out.hiddenAtStart = look(quiet);
quiet.card.hass = hassWith();  // still nothing: no second event
out.stillHidden = look(quiet);
quiet.card.hass = hassWith({ active: 1 });
out.shownAgain = look(quiet);
quiet.card.hass = hassWith({ active: 0 });
out.hiddenAgain = look(quiet);

out.always = look(mount({}, hassWith()));
out.visible = look(mount({ show: "active" }, hassWith({ active: 3 })));
out.oldIntegration = look(mount({ show: "active" }, hassWith({ active: null })));
const possibleOnly = () => hassWith({ today: [0, 1, 0], active: 1 });
out.today = look(mount({ show: "today" }, possibleOnly()));
out.todayPossible = look(mount({ show: "today_possible" }, possibleOnly()));

// In edit mode / the card preview Home Assistant sets `preview` (and `editMode`) before hass.
const edited = mount({ show: "active" }, hassWith(),
  (card) => { card.preview = true; card.editMode = true; });
out.preview = look(edited);
edited.card.preview = false; edited.card.editMode = false;
out.previewOff = look(edited);
edited.card.preview = true;
out.previewOn = look(edited);
const legacy = mount({ show: "today" }, hassWith(), (card) => { card.editMode = true; });
out.editModeOnly = look(legacy);
out.previewGetter = [edited.card.preview, legacy.card.preview, legacy.card.editMode];
const busy = mount({ show: "active" }, hassWith({ active: 2 }), (card) => { card.preview = true; });
out.previewWithParcels = look(busy);

// The add form keeps the card while it is open.
const form = mount({ show: "active" }, hassWith({ active: 1 }));
form.els.toggle.listeners.click();
form.card.hass = hassWith({ active: 0 });
out.formOpen = look(form);
form.els.toggle.listeners.click();
out.formClosed = look(form);

// A changed option takes effect on a built card.
const changed = mount({ show: "active" }, hassWith());
changed.card.setConfig({});
out.configChanged = look(changed);
changed.card.setConfig({ show: "today" });
out.configChangedBack = look(changed);
console.log(JSON.stringify(out));
"""

MODES = ["always", "active", "today", "today_possible"]
NOTE = "Ausgeblendet, solange nichts ansteht (show: {})"


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node not installed")
    run = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, text=True, check=True
    )
    return json.loads(run.stdout)


HIDE = ["card-visibility-changed", False, True, True]
SHOW = ["card-visibility-changed", True, True, True]


def test_show_option_has_four_values_and_falls_back_to_always(card):
    assert card["modes"] == MODES
    assert card["mode"] == {
        "none": "always", "empty": "always", "always": "always", "active": "active",
        "today": "today", "todayPossible": "today_possible", "upper": "today_possible",
        "unknown": "always", "bool": "always", "nothing": "always",
    }


def test_always_is_always_visible(card):
    assert set(card["decision"]["always"].values()) == {True}
    assert card["always"] == {"hidden": False, "note": None, "events": []}


def test_active_follows_the_sensor_of_parcels_on_the_way(card):
    decision = card["decision"]["active"]
    assert decision["nothing"] is False
    assert decision["delivered"] is False  # delivered today, nothing on the way any more
    for case in ("activeOnly", "sure", "possible"):
        assert decision[case] is True, case


def test_today_needs_a_sure_or_a_delivered_parcel(card):
    decision = card["decision"]["today"]
    assert decision["sure"] is True
    assert decision["delivered"] is True
    for case in ("nothing", "activeOnly", "possible"):
        assert decision[case] is False, case


def test_today_possible_also_counts_possible_parcels(card):
    decision = card["decision"]["today_possible"]
    for case in ("sure", "delivered", "possible"):
        assert decision[case] is True, case
    for case in ("nothing", "activeOnly"):
        assert decision[case] is False, case


def test_missing_sensor_keeps_the_card_visible(card):
    """An integration from before v0.3.11 has no sensor.pakete_unterwegs: do not hide."""
    decision = card["decision"]
    for case in ("noActiveSensor", "noSensors", "unavailable", "unknown", "noHass", "noStates"):
        assert decision["active"][case] is True, case
    assert decision["active"]["noTodaySensor"] is False  # not needed for `active`
    for mode in ("today", "today_possible"):
        for case in ("noTodaySensor", "noSensors", "unavailable", "unknown", "noHass",
                     "noStates", "oldTodaySensor"):
            assert decision[mode][case] is True, (mode, case)
        assert decision[mode]["noActiveSensor"] is False  # not needed for these
    # Only the value the mode needs has to be there.
    assert decision["today"]["oldTodaySensorPossible"] is True
    assert decision["today_possible"]["oldTodaySensorPossible"] is True
    assert card["oldIntegration"] == {"hidden": False, "note": None, "events": []}


def test_card_hides_the_way_home_assistant_expects(card):
    """`hidden` on the card plus the event hui-card listens to (bubbling, composed)."""
    assert card["hiddenAtStart"] == {"hidden": True, "note": None, "events": [HIDE]}
    assert card["stillHidden"]["events"] == [HIDE]  # fired on changes only
    assert card["shownAgain"] == {"hidden": False, "note": None, "events": [HIDE, SHOW]}
    assert card["hiddenAgain"] == {"hidden": True, "note": None, "events": [HIDE, SHOW, HIDE]}
    assert card["visible"] == {"hidden": False, "note": None, "events": []}
    assert card["today"]["hidden"] is True
    assert card["todayPossible"]["hidden"] is False


def test_card_stays_visible_in_edit_mode_with_a_note(card):
    assert card["note"] == NOTE.format("active")
    assert card["preview"] == {"hidden": False, "note": NOTE.format("active"), "events": []}
    assert card["previewOff"] == {"hidden": True, "note": None, "events": [HIDE]}
    assert card["previewOn"] == {
        "hidden": False, "note": NOTE.format("active"), "events": [HIDE, SHOW],
    }
    # Older frontends only set `editMode`.
    assert card["editModeOnly"] == {"hidden": False, "note": NOTE.format("today"), "events": []}
    assert card["previewGetter"] == [True, False, True]
    assert card["previewWithParcels"] == {"hidden": False, "note": None, "events": []}


def test_open_add_form_keeps_the_card(card):
    assert card["formOpen"] == {"hidden": False, "note": None, "events": []}
    assert card["formClosed"] == {"hidden": True, "note": None, "events": [HIDE]}


def test_config_change_on_a_built_card_takes_effect(card):
    assert card["configChanged"] == {"hidden": False, "note": None, "events": [HIDE, SHOW]}
    assert card["configChangedBack"]["hidden"] is True


def test_source_names_the_sensor_and_has_the_note_line():
    assert 'const ACTIVE_ENTITY = "sensor.pakete_unterwegs";' in SOURCE
    assert 'id="hidden-note"' in SOURCE
    assert "card-visibility-changed" in SOURCE
