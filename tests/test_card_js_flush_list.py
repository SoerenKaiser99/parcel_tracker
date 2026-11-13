"""Card: no divider above the first parcel when nothing stands above the list (v0.3.48).

``header: false`` together with ``add_form: never`` leaves no head, no "Paket
hinzufügen" line and no form: the first line of the list loses its top border. With a
head (or the line, or the form) the divider stays. Run in Node.
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
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const Card = defined["parcel-tracker-card"];

function mount(config) {
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
  card.hass = {
    states: { "sensor.pakete_heute": { entity_id: "sensor.pakete_heute", state: "0",
      last_updated: "t0", attributes: { parcels: [] } } },
    entities: {}, user: { id: "u1" },
    callWS: async () => { throw new Error("unknown"); },
    callService: async () => {},
  };
  return els.list.className;
}

const out = {};
out.noHeadNever = mount({ header: false, add_form: "never" });
out.noHeadNeverText = mount({ header: "false", add_form: " Never " });
out.headNever = mount({ add_form: "never" });
out.head = mount({});
out.noHeadButton = mount({ header: false });
out.noHeadAlways = mount({ header: false, add_form: "always" });
out.headTrue = mount({ header: true, add_form: "never" });
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def card():
    if NODE is None:
        pytest.skip("node not installed")
    run = subprocess.run(
        [NODE, "-e", SCRIPT, str(BUNDLED_CARD)], capture_output=True, text=True, check=True
    )
    return json.loads(run.stdout)


def test_list_without_anything_above_is_flush(card):
    assert "flush" in card["noHeadNever"].split()
    assert "flush" in card["noHeadNeverText"].split()


@pytest.mark.parametrize("key", ["headNever", "head", "noHeadButton", "noHeadAlways", "headTrue"])
def test_divider_stays_with_a_head_the_line_or_the_form(card, key):
    assert "flush" not in card[key].split()


def test_css_removes_only_the_first_border():
    rule = re.search(r"\.flush\s*>\s*\.item:first-child\s*\{([^}]*)\}", SOURCE)
    assert rule is not None
    assert re.search(r"border-top\s*:\s*(none|0)", rule.group(1))
    assert ".item { border-top:1px solid var(--divider-color)" in SOURCE
