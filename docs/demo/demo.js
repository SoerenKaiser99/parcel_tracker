// Demo and developer preview for the Paket Tracker card: a mock `hass` with invented
// parcels. Nothing here is real - numbers are 9-style placeholders, places do not exist.
//
//   ?theme=dark   dark theme
//   ?open=<n>     expand the n-th parcel of the list (or a parcel number)
//   ?add=open     open the add form behind the plus button (default: collapsed)
//   ?add=always   card option add_form: always (form always shown, no plus button)
//   ?add=never    card option add_form: never (no form, no plus button)
//   ?hint=1       pretend the integration was updated: the card shows its reload hint
//   ?shot=1       only the card (used for the README screenshots)
(function () {
  "use strict";
  const params = new URLSearchParams(location.search);
  if (params.get("theme") === "dark") document.documentElement.dataset.theme = "dark";
  if (params.has("shot")) document.documentElement.dataset.shot = "1";

  // Minimal stand-ins for the two Home Assistant elements the card uses.
  if (!customElements.get("ha-card")) {
    customElements.define("ha-card", class extends HTMLElement {
      constructor() {
        super();
        this.attachShadow({ mode: "open" }).innerHTML = `
          <style>
            :host {
              display: block; box-sizing: border-box;
              background: var(--ha-card-background, var(--card-background-color));
              color: var(--primary-text-color);
              border: 1px solid var(--ha-card-border-color, var(--divider-color));
              border-radius: var(--ha-card-border-radius, 12px);
            }
          </style><slot></slot>`;
      }
    });
  }
  if (!customElements.get("ha-icon")) {
    // One own, simple box drawing for every icon name.
    customElements.define("ha-icon", class extends HTMLElement {
      constructor() {
        super();
        this.attachShadow({ mode: "open" }).innerHTML = `
          <style>:host { display: inline-flex; width: 24px; height: 24px; }</style>
          <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor"
               stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round" aria-hidden="true">
            <path d="M12 3 20 7v10l-8 4-8-4V7z"/><path d="M4 7l8 4 8-4M12 11v10M8 5l8 4"/>
          </svg>`;
      }
    });
  }

  // --- dates relative to today, so the page never looks stale -----------------------
  const pad = (n) => String(n).padStart(2, "0");
  const at = (days, hour = 0, minute = 0) => {
    const d = new Date();
    d.setDate(d.getDate() + days);
    d.setHours(hour, minute, 0, 0);
    return d;
  };
  const stamp = (days, hour, minute) => at(days, hour, minute).toISOString();
  const localDay = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const day = (days) => localDay(at(days));
  const event = (days, hour, minute, text, location = null) => (
    { timestamp: stamp(days, hour, minute), text, location });
  const UPDATED = stamp(0, 9, 12);

  const STEP = { pre_transit: 1, in_transit: 2, at_delivery_depot: 3, out_for_delivery: 4,
    awaiting_pickup: 4, delivered: 5, exception: 0, unknown: 0 };
  const CARRIER_NAME = { dhl: "DHL", dpd: "DPD", gls: "GLS", hermes: "Hermes", ups: "UPS",
    amazon: "Amazon", ebay: "eBay", other: "17track" };

  // The attributes of sensor.paket_<nummer> (see sensor.py), with defaults.
  function parcel(state, carrier, number, name, extra = {}) {
    const eta = extra.eta_days;
    const attrs = {
      carrier, carrier_name: CARRIER_NAME[carrier], number, name,
      eta_date: eta == null ? null : day(eta),
      eta_latest: null, eta_from: null, eta_to: null,
      days_until: eta == null ? null : eta,
      location: null, location_source: null, pickup_point: null, pickup_until: null,
      status_text: null, last_update: UPDATED, stale: false, last_error: null,
      progress: STEP[state], delivered_at: null, events: [],
      tracking_ref: null, tracking_carrier: null, shipping_carrier_hint: null,
      delivery_code: null, track17: false, track17_carrier: null,
      friendly_name: name,
    };
    delete extra.eta_days;
    return { state, attributes: Object.assign(attrs, extra) };
  }

  const PARCELS = [
    // Comes today for sure: in delivery, with a fixed day and a time window.
    parcel("out_for_delivery", "dhl", "00340999999999999901", "Druckerpatronen", {
      eta_days: 0, eta_from: stamp(0, 14, 0), eta_to: stamp(0, 16, 0),
      location: "Zustellbasis Musterstadt",
      events: [
        event(0, 8, 31, "Die Sendung wurde in das Zustellfahrzeug geladen.", "Musterstadt"),
        event(0, 6, 48, "Im Ziel-Paketzentrum bearbeitet", "Musterstadt"),
        event(-1, 21, 15, "Im Start-Paketzentrum bearbeitet", "Beispielstadt"),
        event(-1, 16, 2, "Vom Absender eingeliefert", "Beispielstadt"),
        event(-2, 11, 30, "Elektronisch angekündigt"),
      ],
    }),
    parcel("in_transit", "dpd", "09999999999901", "Laufschuhe", {
      eta_days: 1, location: "Depot Musterstadt", location_source: "17track", track17: true,
      events: [
        event(0, 7, 20, "Im Paketzustellzentrum", "Musterstadt"),
        event(-1, 19, 5, "Unterwegs", "Beispielstadt"),
      ],
    }),
    parcel("at_delivery_depot", "gls", "99999999902", "Kaffeebohnen", {
      eta_days: 1, location: "Depot Beispielstadt",
      events: [event(0, 5, 40, "Das Paket ist im Zustelldepot eingetroffen.", "Beispielstadt")],
    }),
    parcel("pre_transit", "hermes", "H9999999999999999903", "Geburtstagsgeschenk", {
      eta_days: 2, eta_latest: day(4),
      events: [event(0, 8, 10, "Die Sendung wurde Hermes elektronisch angekündigt.")],
    }),
    parcel("in_transit", "ups", "1Z9999999999999904", "Schreibtischlampe", {
      eta_days: 3, location: "Umschlagzentrum Musterdorf",
      events: [event(-1, 22, 30, "Abfahrt vom Standort", "Musterdorf")],
    }),
    parcel("in_transit", "amazon", "AMZ99999999999999905", "Wasserfilter, 3er-Pack", {
      eta_days: 1, delivery_code: "990099",
      events: [event(0, 4, 55, "Versandt")],
    }),
    // Possible today: the delivery window ("Bis …") starts today, no fixed day yet.
    parcel("in_transit", "ebay", "EBAY999999999906", "Fahrradklingel", {
      eta_days: 0, eta_latest: day(2), shipping_carrier_hint: "hermes",
      events: [event(-1, 15, 20, "Versandt")],
    }),
    parcel("in_transit", "other", "999999999907", "Ersatzteil Kaffeemaschine", {
      eta_days: 5, location: "Sortierzentrum Beispielhausen", location_source: "17track",
      track17: true,
      events: [event(-1, 13, 45, "Im Sortierzentrum angekommen", "Beispielhausen")],
    }),
    parcel("in_transit", "dpd", "09999999999908", "Gartenschlauch", {
      eta_days: 2, stale: true, last_error: "unavailable",
      events: [event(-1, 18, 0, "Im Paketzustellzentrum", "Musterdorf")],
    }),
    // Delivered today: the third badge ("zugestellt").
    parcel("delivered", "gls", "99999999910", "Hundefutter", {
      delivered_at: stamp(0, 9, 5),
      events: [
        event(0, 9, 5, "Das Paket wurde zugestellt.", "Musterstadt"),
        event(0, 6, 20, "Das Paket ist in der Zustellung.", "Musterstadt"),
      ],
    }),
    parcel("delivered", "dhl", "00340999999999999909", "Kinderbuch", {
      delivered_at: stamp(-1, 11, 24),
      events: [event(-1, 11, 24, "Die Sendung wurde zugestellt.", "Musterstadt")],
    }),
  ];

  // --- the mock hass ----------------------------------------------------------------
  const states = {};
  const entities = {};
  const add = (entity_id, state, attributes) => {
    states[entity_id] = { entity_id, state, attributes, last_updated: UPDATED, last_changed: UPDATED };
    entities[entity_id] = { entity_id, platform: "parcel_tracker" };
  };
  for (const p of PARCELS) {
    add(`sensor.paket_${p.attributes.number.toLowerCase()}`, p.state, p.attributes);
  }
  // sensor.pakete_heute, by the rule of today_group() in schedule.py: "sure" is in delivery
  // or a fixed day today, "possible" a delivery window of several days that includes today.
  // In delivery ends with the estimate; without one it holds on the day of the last change
  // (here: the newest event, the demo's parcels carry no other time of change).
  const todayGroup = (p) => {
    const a = p.attributes;
    if (p.state === "delivered") return null;
    if (p.state === "out_for_delivery") {
      const end = a.eta_latest || a.eta_date;
      if (end) return end >= day(0) ? "sure" : null;
      const changed = a.events && a.events[0] ? a.events[0].timestamp : null;
      return changed && localDay(new Date(changed)) === day(0) ? "sure" : null;
    }
    if (a.eta_date == null) return null;
    if (a.eta_latest == null || a.eta_latest <= a.eta_date) return a.days_until === 0 ? "sure" : null;
    return a.eta_date <= day(0) && day(0) <= a.eta_latest ? "possible" : null;
  };
  // Delivered today, by the rule of delivered_today() in schedule.py: the time of delivery
  // decides, without one the day of the last change (here again: the newest event).
  const deliveredToday = (p) => {
    const a = p.attributes;
    if (p.state !== "delivered") return false;
    const when = a.delivered_at || (a.events && a.events[0] ? a.events[0].timestamp : null);
    return !!when && localDay(new Date(when)) === day(0);
  };
  const item = (p) => (
    { number: p.attributes.number, name: p.attributes.name, carrier: p.attributes.carrier,
      eta_from: p.attributes.eta_from, eta_to: p.attributes.eta_to });
  const items = (group) => PARCELS.filter((p) => todayGroup(p) === group).map(item);
  const delivered = PARCELS.filter(deliveredToday).map(item);
  add("sensor.pakete_heute", String(items("sure").length), {
    friendly_name: "Pakete heute",
    parcels: items("sure"), possible: items("possible"),
    possible_count: items("possible").length,
    delivered_today: delivered,
    delivered_today_count: delivered.length,
    // CARD_VERSION is the card's own constant: equal means "no reload needed".
    integration_version: params.has("hint") ? `${CARD_VERSION}-neu` : CARD_VERSION,
  });
  add("sensor.paket_tracker_17track_kontingent", "187", {
    friendly_name: "Paket Tracker 17track-Kontingent", total: 200, used: 13 });

  const hass = {
    states,
    entities,
    callService: (domain, service, data) => {
      console.log(`[Demo] Dienst ${domain}.${service} (nicht ausgeführt)`, data);
      return Promise.resolve();
    },
  };

  const card = document.createElement("parcel-tracker-card");
  const addForm = params.get("add");
  card.setConfig({
    type: "custom:parcel-tracker-card",
    ...(addForm === "always" || addForm === "never" ? { add_form: addForm } : {}),
  });
  card.hass = hass;
  document.getElementById("card").appendChild(card);

  // ?open=<n>: click the n-th row (or the row of that parcel number) like a user would.
  const open = params.get("open");
  if (open) {
    const rows = Array.from(card.shadowRoot.querySelectorAll(".row-toggle"));
    const row = rows.find((r) => r.dataset.number === open) || rows[Number(open) - 1];
    if (row) row.click();
  }
  // ?add=open: click the plus button like a user would.
  if (addForm === "open") card.shadowRoot.getElementById("toggle").click();

  window.demo = { hass, card, todayGroup, deliveredToday };
  // For the screenshot script: the page is rendered, and this is how tall its content is.
  const main = document.querySelector("main");
  document.documentElement.dataset.height = String(Math.ceil(main.getBoundingClientRect().height));
})();
