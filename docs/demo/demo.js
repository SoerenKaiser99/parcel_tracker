// Demo and developer preview for the Paket Tracker card: a mock `hass` with invented
// parcels. Nothing here is real - numbers are 9-style placeholders, places do not exist.
//
//   ?theme=dark   dark theme
//   ?open=<n>     expand the n-th parcel of the list (or a parcel number)
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
  const day = (days) => {
    const d = at(days);
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  };
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
    parcel("in_transit", "dhl", "00340999999999999901", "Druckerpatronen", {
      eta_days: 0, eta_from: stamp(0, 14, 0), eta_to: stamp(0, 16, 0),
      location: "Paketzentrum Musterstadt",
      events: [
        event(0, 6, 48, "Im Ziel-Paketzentrum bearbeitet", "Musterstadt"),
        event(-1, 21, 15, "Im Start-Paketzentrum bearbeitet", "Beispielstadt"),
        event(-1, 16, 2, "Vom Absender eingeliefert", "Beispielstadt"),
        event(-2, 11, 30, "Elektronisch angekündigt"),
      ],
    }),
    parcel("out_for_delivery", "dpd", "09999999999901", "Laufschuhe", {
      eta_days: 0, location: "Depot Musterstadt", location_source: "17track", track17: true,
      events: [
        event(0, 7, 20, "In Zustellung", "Musterstadt"),
        event(-1, 19, 5, "Im Paketzustellzentrum", "Musterstadt"),
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
    parcel("in_transit", "ebay", "EBAY999999999906", "Fahrradklingel", {
      eta_days: 4, shipping_carrier_hint: "hermes",
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
    parcel("delivered", "dhl", "00340999999999999909", "Kinderbuch", {
      delivered_at: stamp(-1, 11, 24),
      events: [event(-1, 11, 24, "Die Sendung wurde zugestellt.", "Musterstadt")],
    }),
  ];

  // --- the mock hass ----------------------------------------------------------------
  const STATE_LABEL = { pre_transit: "Angekündigt", in_transit: "Unterwegs",
    at_delivery_depot: "Im Zustelldepot", out_for_delivery: "In Zustellung",
    awaiting_pickup: "Abholbereit", delivered: "Zugestellt", exception: "Problem",
    unknown: "Unbekannt" };
  const states = {};
  const entities = {};
  const add = (entity_id, state, attributes) => {
    states[entity_id] = { entity_id, state, attributes, last_updated: UPDATED, last_changed: UPDATED };
    entities[entity_id] = { entity_id, platform: "parcel_tracker" };
  };
  for (const p of PARCELS) {
    add(`sensor.paket_${p.attributes.number.toLowerCase()}`, p.state, p.attributes);
  }
  const today = PARCELS.filter((p) => p.attributes.days_until === 0 && p.state !== "delivered");
  add("sensor.pakete_heute", String(today.length), {
    friendly_name: "Pakete heute",
    parcels: today.map((p) => ({ number: p.attributes.number, name: p.attributes.name,
      carrier: p.attributes.carrier, eta_from: p.attributes.eta_from, eta_to: p.attributes.eta_to })),
  });
  add("sensor.paket_tracker_17track_kontingent", "187", {
    friendly_name: "Paket Tracker 17track-Kontingent", total: 200, used: 13 });

  const hass = {
    states,
    entities,
    formatEntityState: (st) => STATE_LABEL[st.state] || st.state,
    callService: (domain, service, data) => {
      console.log(`[Demo] Dienst ${domain}.${service} (nicht ausgeführt)`, data);
      return Promise.resolve();
    },
  };

  const card = document.createElement("parcel-tracker-card");
  card.setConfig({ type: "custom:parcel-tracker-card" });
  card.hass = hass;
  document.getElementById("card").appendChild(card);

  // ?open=<n>: click the n-th row (or the row of that parcel number) like a user would.
  const open = params.get("open");
  if (open) {
    const rows = Array.from(card.shadowRoot.querySelectorAll(".row-toggle"));
    const row = rows.find((r) => r.dataset.number === open) || rows[Number(open) - 1];
    if (row) row.click();
  }

  window.demo = { hass, card };
  // For the screenshot script: the page is rendered, and this is how tall its content is.
  const main = document.querySelector("main");
  document.documentElement.dataset.height = String(Math.ceil(main.getBoundingClientRect().height));
})();
