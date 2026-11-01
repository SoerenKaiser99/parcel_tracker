"""Card: whom a parcel belongs to – the card options ``person`` and ``include_unassigned``,
the select „Gehört“ in an expanded parcel and in the add form (run in Node)."""

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
  + "\n;globalThis.__svc = SERVICE_ERRORS; globalThis.__show = shouldShow;", sandbox);
const Card = defined["parcel-tracker-card"];
const tick = () => new Promise((r) => setTimeout(r, 0));
const SWITCH = "switch.paket_tracker_geschenkmodus";

const blank = { days_until: null, events: [], status_text: null, progress: 0, last_error: null,
                gift: false, owner: null, owner_detected: false };
// A = Anna's (detected), B = Ben's (detected), D = Anna's by default, N = everybody's,
// G = a gift of Ben's.
const A = "00340999999999999971";
const B = "00340999999999999972";
const D = "00340999999999999973";
const N = "00340999999999999974";
const G = "00340999999999999975";
const PARCELS = [
  ["in_transit", { number: A, name: "Annas Buch", carrier: "dhl", days_until: 0,
                   owner: "person.anna", owner_detected: true }],
  ["in_transit", { number: B, name: "Bens Kabel", carrier: "dhl", days_until: 0,
                   owner: "person.ben", owner_detected: true }],
  ["in_transit", { number: D, name: "Standardpaket", carrier: "dhl",
                   owner: "person.anna", owner_detected: false }],
  ["in_transit", { number: N, name: "Familienpaket", carrier: "dhl" }],
  ["in_transit", { number: G, name: "Geschenk · DHL-Paket …9975", carrier: "dhl",
                   gift: true, owner: "person.ben", owner_detected: true }],
];
const item = (n) => ({ number: n, name: "x", carrier: "dhl", eta_from: null, eta_to: null });

function makeHass(opts) {
  const states = {};
  const entities = {};
  (opts.parcels || PARCELS).forEach(([state, attributes], i) => {
    const id = `sensor.paket_${i}`;
    states[id] = { entity_id: id, state, last_updated: "t",
      attributes: { ...blank, ...attributes } };
    entities[id] = { platform: "parcel_tracker" };
  });
  if (!opts.noPersons) {
    states["person.anna"] = { entity_id: "person.anna", state: "home", last_updated: "t",
      attributes: { friendly_name: "Anna", user_id: "u-anna" } };
    states["person.ben"] = { entity_id: "person.ben", state: "home", last_updated: "t",
      attributes: { friendly_name: opts.benName || "Ben", user_id: "u-ben" } };
  }
  // The persons set up in the integration and the default person (attributes of
  // sensor.pakete_heute): Anna and Ben, Anna by default, unless the test says otherwise;
  // `configured: null` leaves both attributes out (an integration from before).
  const configured = opts.configured === undefined
    ? ["person.anna", "person.ben"] : opts.configured;
  const defaultOwner = opts.defaultOwner === undefined ? "person.anna" : opts.defaultOwner;
  const persons = configured === null ? {}
    : { persons: configured, default_owner: defaultOwner };
  // Sure today: A and B; possible: N; delivered today: D (as a list entry only).
  states["sensor.pakete_heute"] = { entity_id: "sensor.pakete_heute", state: "2",
    last_updated: "t", attributes: { parcels: [item(A), item(B)], possible: [item(N)],
      possible_count: 1, delivered_today: [item(D)], delivered_today_count: 1, ...persons } };
  states["sensor.pakete_unterwegs"] = { entity_id: "sensor.pakete_unterwegs", state: "1",
    last_updated: "t", attributes: { parcels: [item(B)] } };
  if (opts.mode != null) {
    states[SWITCH] = { entity_id: SWITCH, state: opts.mode, last_updated: "t", attributes: {} };
  }
  const log = opts.log;
  return {
    states, entities, user: opts.user === null ? undefined : { id: opts.user || "u-anna" },
    callWS: async (msg) => {
      log.ws.push(msg);
      if (msg.type === "parcel_tracker/gift_viewer") return { viewer: !!opts.viewer };
      throw new Error("unknown");
    },
    callService: async (domain, service, data) => {
      log.svc.push([domain, service, data]);
      if (opts.refuse) { const e = new Error("x"); e.translation_key = opts.refuse; throw e; }
    },
  };
}

function mount(config, opts = {}) {
  const log = { ws: [], svc: [] };
  const card = new Card();
  const els = {};
  const root = {
    innerHTML: "", activeElement: null,
    getElementById(id) { return (els[id] ||= fakeEl()); },
  };
  card.attachShadow = () => root;
  card.setConfig(config);
  card.dispatchEvent = () => {};
  card.hass = makeHass({ ...opts, log });
  const rows = () => Object.fromEntries(els.list.children.map((it) => [
    /data-number="([^"]+)"/.exec(it.innerHTML)[1], it]));
  const html = () => Object.fromEntries(
    Object.entries(rows()).map(([n, it]) => [n, it.innerHTML]));
  const open = (n) => rows()[n].kids[".row-toggle"].listeners.click();
  const again = (more = {}) => { card.hass = makeHass({ ...opts, ...more, log }); };
  return { card, els, log, rows, html, open, again };
}

(async () => {
  const out = {};

  // ---- filter ----------------------------------------------------------------------
  const all = mount({});
  out.all = { shown: Object.keys(all.rows()), badges: all.els.today.innerHTML };
  const anna = mount({ person: "person.anna" });
  out.anna = { shown: Object.keys(anna.rows()), badges: anna.els.today.innerHTML };
  const strict = mount({ person: "person.anna", include_unassigned: false });
  out.strict = { shown: Object.keys(strict.rows()), badges: strict.els.today.innerHTML };
  const ben = mount({ person: "person.ben", include_unassigned: false });
  out.ben = { shown: Object.keys(ben.rows()), badges: ben.els.today.innerHTML };
  // show: active follows the filter (Anna has nothing on its way per sensor.pakete_unterwegs).
  const hassA = makeHass({ log: { ws: [], svc: [] } });
  out.showActive = {
    anna: sandbox.__show("active", hassA, new Set([A, D])),
    ben: sandbox.__show("active", hassA, new Set([B])),
    all: sandbox.__show("active", hassA, null),
  };
  // show: today / today_possible follow it too (sure: A, B; possible: N; delivered: D).
  out.showToday = {
    anna: sandbox.__show("today", hassA, new Set([A])),
    delivered: sandbox.__show("today", hassA, new Set([D])),
    possibleOnly: sandbox.__show("today", hassA, new Set([N])),
    possibleOnlyPossible: sandbox.__show("today_possible", hassA, new Set([N])),
    nothing: sandbox.__show("today_possible", hassA, new Set([G])),
  };
  // Nothing for the person: said by name (escaped).
  const none = mount({ person: "person.ben", include_unassigned: false },
    { parcels: [], benName: "<b>Ben</b>" });
  out.emptyPerson = none.els.list.innerHTML;
  out.emptyAll = mount({}, { parcels: [] }).els.list.innerHTML;

  // ---- person: auto (v0.3.47) ------------------------------------------------------------
  const rowsOf = (m) => Object.keys(m.rows()).sort();
  const au = mount({ person: "auto" });
  out.auto = { shown: rowsOf(au), badges: au.els.today.innerHTML };
  out.autoStrict = rowsOf(mount({ person: "auto", include_unassigned: false }));
  out.autoBen = rowsOf(mount({ person: "auto" }, { user: "u-ben" }));
  // A user switch on the same card re-resolves the person.
  const sw = mount({ person: "auto", include_unassigned: false });
  const before = rowsOf(sw);
  sw.again({ user: "u-ben" });
  const afterBen = rowsOf(sw);
  sw.again({ user: "u-nobody" });
  out.autoSwitch = { before, afterBen, nobody: rowsOf(sw), empty: sw.els.list.innerHTML };
  // Person states that arrive later.
  const late = mount({ person: "auto", include_unassigned: false }, { noPersons: true });
  const beforePersons = rowsOf(late);
  late.again({ noPersons: false });
  out.autoLate = { before: beforePersons, after: rowsOf(late) };
  // A user without a person sees the parcels of everybody only, and the plain empty text.
  const nob = mount({ person: "auto" }, { user: "u-nobody" });
  out.autoNobody = { shown: rowsOf(nob), badges: nob.els.today.innerHTML };
  out.autoNobodyStrict = mount({ person: "auto", include_unassigned: false }, { user: "u-nobody" })
    .els.list.innerHTML;
  out.autoNoUser = rowsOf(mount({ person: "auto" }, { user: null }));
  // The person of the user, escaped, when there is nothing for them.
  out.autoEscaped = mount({ person: "auto", include_unassigned: false },
    { parcels: [], benName: "<b>Ben</b>", user: "u-ben" }).els.list.innerHTML;
  // Explicit person: unchanged, even for another logged-in user.
  out.explicitOther = rowsOf(mount({ person: "person.anna" }, { user: "u-ben" }));

  // ---- select in the expanded parcel ---------------------------------------------------
  const s = mount({});
  for (const n of [A, D, N]) s.open(n);
  out.open = { A: s.html()[A], D: s.html()[D], N: s.html()[N] };
  // Changing the select calls set_owner.
  const sel = s.rows()[A].kids['[data-a="owner"]'];
  sel.value = "person.ben";
  await sel.listeners.change();
  const sel2 = s.rows()[N].kids['[data-a="owner"]'];
  sel2.value = "all";
  await sel2.listeners.change();
  out.setOwner = s.log.svc.slice();
  // The default person chosen explicitly: stored as the parcel's own.
  s.log.svc.length = 0;
  const sd = s.rows()[D].kids['[data-a="owner"]'];
  sd.value = "";
  await sd.listeners.change();
  out.standardNoop = s.log.svc.slice();
  sd.value = "person.anna";
  await sd.listeners.change();
  out.standardExplicit = s.log.svc.slice();
  // A refused change is said in German.
  const r = mount({}, { refuse: "gift_owner_not_allowed" });
  r.open(A);
  const rs = r.rows()[A].kids['[data-a="owner"]'];
  rs.value = "person.ben";
  await rs.listeners.change();
  out.refused = r.els.err.innerHTML;
  const u = mount({}, { refuse: "owner_unknown" });
  u.open(A);
  const us = u.rows()[A].kids['[data-a="owner"]'];
  us.value = "person.ben";
  await us.listeners.change();
  out.unknown = u.els.err.innerHTML;

  // ---- escaping ------------------------------------------------------------------------
  const e = mount({}, { benName: '<img src=x onerror="alert(1)">' });
  e.open(A);
  out.escaped = { row: e.html()[A], form: e.els.own.innerHTML };

  // ---- gifts ---------------------------------------------------------------------------
  const nv = mount({}, { mode: "on", viewer: false, user: "u-anna" });
  await tick();
  nv.open(G);
  out.giftOther = nv.html()[G];
  const vv = mount({}, { mode: "on", viewer: true, user: "u-anna" });
  await tick();
  vv.open(G);
  out.giftViewer = vv.html()[G];

  // ---- no persons: no select anywhere -------------------------------------------------
  const np = mount({}, { noPersons: true });
  np.open(A);
  out.noPersons = { row: np.html()[A], formHidden: np.els["own-row"].hidden };

  // ---- add form ------------------------------------------------------------------------
  const f = mount({ add_form: "always" }, { user: "u-ben" });
  out.form = { options: f.els.own.innerHTML, value: f.els.own.value,
               hidden: f.els["own-row"].hidden };
  f.els.car.value = "auto";
  f.els.num.value = "00340999999999999979";
  await f.card._add();
  out.form.call = f.log.svc[f.log.svc.length - 1];
  // A user without a person: „allen“.
  const g = mount({ add_form: "always" }, { user: "u-nobody" });
  out.form.nobody = g.els.own.value;
  g.els.car.value = "auto";
  g.els.num.value = "00340999999999999978";
  await g.card._add();
  out.form.nobodyCall = g.log.svc[g.log.svc.length - 1];
  // A choice made by hand stays across updates, and is sent.
  const h = mount({ add_form: "always" }, { user: "u-ben" });
  h.els.own.value = "all";
  h.els.own.listeners.change();
  h.again();
  out.form.kept = h.els.own.value;
  h.els.num.value = "00340999999999999977";
  await h.card._add();
  out.form.keptCall = h.log.svc[h.log.svc.length - 1];
  out.form.afterAdd = h.els.own.value;
  // Another user on the same card: the choice of the one before is gone.
  const us2 = mount({ add_form: "always" }, { user: "u-ben" });
  us2.els.own.value = "all";
  us2.els.own.listeners.change();
  us2.again({ user: "u-anna" });
  out.form.switched = us2.els.own.value;
  us2.els.own.value = "person.ben";
  us2.els.own.listeners.change();
  us2.again({ user: "u-nobody" });
  out.form.switchedNobody = us2.els.own.value;
  // Without persons: no owner sent, as before.
  const k = mount({ add_form: "always" }, { noPersons: true });
  k.els.car.value = "auto";
  k.els.num.value = "00340999999999999976";
  await k.card._add();
  out.form.noPersonsCall = k.log.svc[k.log.svc.length - 1];

  // ---- persons in Home Assistant, but none set up in the integration: as v0.3.40 -----
  for (const [key, configured] of [["notSetUp", []], ["oldIntegration", null]]) {
    const z = mount({ add_form: "always" }, { configured, defaultOwner: null, user: "u-anna" });
    z.open(A);
    z.els.car.value = "auto";
    z.els.num.value = "00340999999999999970";
    await z.card._add();
    out[key] = { row: z.html()[A], formHidden: z.els["own-row"].hidden,
                 call: z.log.svc[z.log.svc.length - 1] };
  }
  // Only the persons set up in the integration are offered.
  const only = mount({ add_form: "always" }, { configured: ["person.anna"], user: "u-ben" });
  only.open(N);
  out.onlyAnna = { row: only.html()[N], form: only.els.own.innerHTML, value: only.els.own.value };
  // Default „allen“: „Standard (allen)“ first, no separate „allen“.
  const dAll = mount({ add_form: "always" }, { defaultOwner: null, user: "u-nobody" });
  out.defaultAll = { form: dAll.els.own.innerHTML, value: dAll.els.own.value };
  dAll.els.car.value = "auto";
  dAll.els.num.value = "00340999999999999969";
  await dAll.card._add();
  out.defaultAll.call = dAll.log.svc[dAll.log.svc.length - 1];

  out.svc = sandbox.__svc;
  console.log(JSON.stringify(out));
})();
"""

A = "00340999999999999971"
B = "00340999999999999972"
D = "00340999999999999973"
N = "00340999999999999974"
G = "00340999999999999975"


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node is not installed")
    done = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)],
        capture_output=True, encoding="utf-8", check=True,
    )
    return json.loads(done.stdout)


def _options(html: str) -> list[tuple[str, str, bool]]:
    return [
        (value, label, "selected" in attrs)
        for value, attrs, label in re.findall(
            r'<option value="([^"]*)"([^>]*)>([^<]*)</option>', html
        )
    ]


def _badges(html: str) -> list[str]:
    return re.findall(r">([^<>]+)</span>", html)


def test_without_the_option_every_parcel_is_shown(card):
    assert sorted(card["all"]["shown"]) == sorted([A, B, D, N, G])
    assert _badges(card["all"]["badges"]) == ["2 heute", "1 möglich", "1 zugestellt"]


def test_person_shows_own_and_unassigned_parcels(card):
    assert sorted(card["anna"]["shown"]) == sorted([A, D, N])
    # The badges count only the parcels shown.
    assert _badges(card["anna"]["badges"]) == ["1 heute", "1 möglich", "1 zugestellt"]


def test_include_unassigned_false_hides_everybodys_parcels(card):
    assert sorted(card["strict"]["shown"]) == sorted([A, D])
    assert _badges(card["strict"]["badges"]) == ["1 heute", "1 zugestellt"]
    assert sorted(card["ben"]["shown"]) == sorted([B, G])
    assert _badges(card["ben"]["badges"]) == ["1 heute"]


def test_show_active_follows_the_filter(card):
    assert card["showActive"] == {"anna": False, "ben": True, "all": True}


def test_show_today_follows_the_filter(card):
    assert card["showToday"] == {
        "anna": True, "delivered": True, "possibleOnly": False,
        "possibleOnlyPossible": True, "nothing": False,
    }


def test_no_parcels_for_the_person_says_so_by_name(card):
    assert card["emptyPerson"] == '<div class="sub">Keine Pakete für &lt;b&gt;Ben&lt;/b&gt;.</div>'
    assert "Keine Pakete für" not in card["emptyAll"]
    assert "Noch keine Pakete." in card["emptyAll"]


def test_the_select_lists_everybody_and_every_person(card):
    html = card["open"]["A"]
    assert "Gehört:" in html
    select = r'<select [^>]*data-a="owner" data-number="' + A + r'"[^>]*aria-label="Gehört"'
    assert re.search(select, html)
    assert _options(html) == [
        ("all", "allen", False), ("person.anna", "Anna", True), ("person.ben", "Ben", False),
    ]
    assert _options(card["open"]["N"])[0] == ("all", "allen", True)


def test_a_default_owner_is_shown_as_standard_and_can_be_confirmed(card):
    assert _options(card["open"]["D"]) == [
        ("", "Standard (Anna)", True), ("all", "allen", False),
        ("person.anna", "Anna", False), ("person.ben", "Ben", False),
    ]
    assert "Standard" not in card["open"]["A"]
    assert "Standard" not in card["open"]["N"]
    # „Standard (…)“ itself stores nothing; the person chosen explicitly is stored.
    assert card["standardNoop"] == []
    assert card["standardExplicit"] == [
        ["parcel_tracker", "set_owner", {"number": D, "person": "person.anna"}],
    ]


def test_changing_the_select_calls_set_owner(card):
    assert card["setOwner"] == [
        ["parcel_tracker", "set_owner", {"number": A, "person": "person.ben"}],
        ["parcel_tracker", "set_owner", {"number": N, "person": "all"}],
    ]


def test_set_owner_errors_are_said_in_german(card):
    assert card["refused"] == card["svc"]["gift_owner_not_allowed"]
    assert card["refused"] == "Nur wer Geschenke sehen darf, kann ändern, wem ein Geschenk gehört."
    assert card["unknown"] == card["svc"]["owner_unknown"]
    assert card["unknown"] == "Diese Person ist im Paket Tracker nicht eingerichtet."


def test_person_names_are_escaped(card):
    for html in card["escaped"].values():
        assert "<img" not in html
        assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html


def test_a_gift_has_no_select_for_others(card):
    assert 'data-a="owner"' not in card["giftOther"]
    assert 'data-a="owner"' in card["giftViewer"]


def test_without_persons_there_is_no_select(card):
    assert 'data-a="owner"' not in card["noPersons"]["row"]
    assert "Gehört" not in card["noPersons"]["row"]
    assert card["noPersons"]["formHidden"] is True
    assert card["form"]["noPersonsCall"][2] == {
        "number": "00340999999999999976", "carrier": "auto",
    }


def test_the_add_form_preselects_the_logged_in_person(card):
    form = card["form"]
    assert form["hidden"] is False
    # With a default person: „Standard (Name)“, the persons, then „allen“.
    assert [o[:2] for o in _options(form["options"])] == [
        ("", "Standard (Anna)"), ("person.anna", "Anna"), ("person.ben", "Ben"), ("all", "allen"),
    ]
    assert form["value"] == "person.ben"
    assert form["call"] == ["parcel_tracker", "add_parcel", {
        "number": "00340999999999999979", "carrier": "auto", "owner": "person.ben",
    }]


def test_a_user_without_a_person_adds_with_the_standard(card):
    # „Standard“ sends no owner: the call is the one of v0.3.40.
    assert card["form"]["nobody"] == ""
    assert card["form"]["nobodyCall"] == ["parcel_tracker", "add_parcel", {
        "number": "00340999999999999978", "carrier": "auto",
    }]


def test_another_user_gets_their_own_person_preselected(card):
    assert card["form"]["switched"] == "person.anna"
    assert card["form"]["switchedNobody"] == ""


def test_a_choice_by_hand_is_kept_and_reset_after_adding(card):
    form = card["form"]
    assert form["kept"] == "all"
    assert form["keptCall"][2]["owner"] == "all"
    assert form["afterAdd"] == "person.ben"


@pytest.mark.parametrize("case", ["notSetUp", "oldIntegration"])
def test_persons_only_in_home_assistant_change_nothing(card, case):
    # Persons exist in Home Assistant, none is set up in the integration: no select
    # anywhere, and add_parcel is sent exactly as in v0.3.40 (no owner).
    got = card[case]
    assert 'data-a="owner"' not in got["row"]
    assert "Gehört" not in got["row"]
    assert got["formHidden"] is True
    assert got["call"] == ["parcel_tracker", "add_parcel", {
        "number": "00340999999999999970", "carrier": "auto",
    }]


def test_only_persons_set_up_in_the_integration_are_offered(card):
    got = card["onlyAnna"]
    assert _options(got["row"]) == [("all", "allen", True), ("person.anna", "Anna", False)]
    assert [o[:2] for o in _options(got["form"])] == [
        ("", "Standard (Anna)"), ("person.anna", "Anna"), ("all", "allen"),
    ]
    # Ben is no person set up here: his „Standard“ is preselected, not his person.
    assert got["value"] == ""


def test_default_all_shows_standard_allen_without_a_second_allen(card):
    got = card["defaultAll"]
    assert [o[:2] for o in _options(got["form"])] == [
        ("", "Standard (allen)"), ("person.anna", "Anna"), ("person.ben", "Ben"),
    ]
    assert got["value"] == ""
    assert got["call"] == ["parcel_tracker", "add_parcel", {
        "number": "00340999999999999969", "carrier": "auto",
    }]


def _sorted(*numbers):
    return sorted(numbers)


def test_auto_shows_the_parcels_of_the_logged_in_users_person(card):
    assert card["auto"]["shown"] == _sorted(A, D, N)
    assert _badges(card["auto"]["badges"]) == _badges(card["anna"]["badges"])
    assert card["autoBen"] == _sorted(B, G, N)


def test_auto_with_include_unassigned_false_hides_everybodys_parcels(card):
    assert card["autoStrict"] == _sorted(A, D)


def test_auto_follows_a_user_switch(card):
    assert card["autoSwitch"]["before"] == _sorted(A, D)
    assert card["autoSwitch"]["afterBen"] == _sorted(B, G)
    assert card["autoSwitch"]["nobody"] == []
    empty = card["autoSwitch"]["empty"]
    assert "Keine Pakete für" not in empty
    assert "Noch keine Pakete." in empty


def test_auto_picks_up_person_states_that_arrive_later(card):
    assert card["autoLate"] == {"before": [], "after": _sorted(A, D)}


def test_auto_without_a_person_shows_only_everybodys_parcels(card):
    assert card["autoNobody"]["shown"] == [N]
    assert _badges(card["autoNobody"]["badges"]) == ["1 möglich"]
    assert card["autoNoUser"] == [N]


def test_auto_without_a_person_and_nothing_to_show_has_no_bad_name(card):
    html = card["autoNobodyStrict"]
    assert "Keine Pakete für" not in html
    assert "auto" not in html
    assert "Noch keine Pakete." in html


def test_auto_escapes_the_persons_name(card):
    assert card["autoEscaped"] == '<div class="sub">Keine Pakete für &lt;b&gt;Ben&lt;/b&gt;.</div>'


def test_an_explicit_person_ignores_the_logged_in_user(card):
    assert card["explicitOther"] == _sorted(A, D, N)
