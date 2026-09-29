const CARRIER_ICONS = {"dhl": {"path": "M4.22 10.303l-.767 1.043h4.18c.21 0 .208.078.105.218-.105.142-.28.39-.386.534-.054.073-.154.207.171.207h1.71l.505-.69c.314-.426.028-1.312-1.095-1.312H4.22zm7.204 0l-1.475 2.002h5.39l1.473-2.002H14.61l-.843 1.146h-.985l.846-1.146h-2.203zm6.105 0l-1.474 2.002h2.334l1.472-2.002H17.53zm-12.845 1.3l-1.54 2.094h3.754c1.24 0 1.932-.844 2.145-1.136h-2.56c-.326 0-.226-.133-.172-.207.107-.143.283-.388.388-.53.104-.14.107-.22-.105-.22h-1.91zM0 12.562v.242h3.398l.176-.242H0zm9.762 0l-.836 1.136h2.203l.836-1.136H9.762zm3.185 0l-.836 1.136h2.203l.836-1.136h-2.203zm2.918 0s-.159.22-.238.326c-.276.374-.033.81.87.81h3.538l.834-1.136h-5.004zm5.408 0l-.177.242H24v-.242h-2.727zM0 13.01v.24h3.068l.178-.24H0zm20.943 0l-.175.24H24v-.24h-3.057zM0 13.457v.24h2.74l.176-.24H0zm20.615 0l-.177.24H24v-.24h-3.385z", "color": "#FFCC00"}, "dpd": {"path": "M16.01 10.71a.364.364 0 01-.343-.006l-.558-.331a.43.43 0 01-.182-.312l-.014-.65a.363.363 0 01.165-.3l6.7-3.902L12.377.085A.799.799 0 0012 0a.798.798 0 00-.377.085l-9.4 5.124 10.53 6.13c.098.054.172.181.172.295v8.944c0 .112-.08.241-.178.294l-.567.315c-.171.062-.256.043-.361 0l-.569-.315a.362.362 0 01-.175-.294v-7.973a.223.223 0 00-.095-.156L1.702 7.048v10.579c0 .236.167.528.371.648l9.556 5.636c.102.06.237.09.371.089a.745.745 0 00.371-.09l9.557-5.635a.835.835 0 00.37-.648V7.047Z", "color": "#DC0032"}};
const STEPS = 5;
const PICKUP = "awaiting_pickup";
const DONE = "delivered";
const hasDate = (a) => a.days_until != null && a.days_until >= 0;
const ORDER = (s, a) => {
  if (s === DONE) return 5;
  if (a.days_until === 0) return 0;
  if (s === PICKUP) return 1;
  if (hasDate(a)) return 2;
  return 3;
};

const fmtTime = (iso) => new Date(iso).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
const fmtDate = (iso) => new Date(iso).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
const isLocalMidnight = (iso) => {
  const d = new Date(iso);
  return d.getHours() === 0 && d.getMinutes() === 0 && d.getSeconds() === 0;
};
const fmtDateTime = (iso) => (isLocalMidnight(iso) ? fmtDate(iso) : `${fmtDate(iso)} ${fmtTime(iso)}`);

const ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g, (c) => ESC_MAP[c]));

const ERROR_TEXT = {
  missing_key: "DHL-API-Key fehlt – in den Integrations-Optionen eintragen",
  auth: "DHL-API-Key abgelehnt – in den Integrations-Optionen prüfen",
  carrier_not_found: "Carrier nicht gefunden – bitte auswählen",
  not_found: "Noch keine Daten vom Carrier",
  unavailable: "Carrier gerade nicht erreichbar",
  rate_limited: "Zu viele Abfragen – nächster Versuch später",
};

const SERVICE_ERRORS = {
  duplicate: "Dieses Paket ist schon in der Liste.",
  amazon: "Amazon-eigene Nummern werden noch nicht unterstützt.",
  empty: "Gib eine Sendungsnummer ein.",
  unknown_carrier: "Unbekannter Carrier.",
  not_tracked: "Dieses Paket ist nicht in der Liste.",
};

function errorText(e) {
  const keys = [e && e.translation_key, e && e.code, e && e.error && e.error.translation_key, e && e.error && e.error.code];
  for (const k of keys) {
    if (typeof k === "string" && Object.prototype.hasOwnProperty.call(SERVICE_ERRORS, k)) return SERVICE_ERRORS[k];
  }
  const msg = e && (e.message || (e.error && e.error.message));
  return "Das hat nicht geklappt: " + esc(msg == null ? "" : msg);
}

function etaText(state, a) {
  if (state === DONE) {
    if (!a.delivered_at) return "Zugestellt";
    const d = Math.round((new Date().setHours(0,0,0,0) - new Date(a.delivered_at).setHours(0,0,0,0)) / 864e5);
    return d === 0 ? "Zugestellt heute" : d === 1 ? "Zugestellt gestern" : `Zugestellt am ${fmtDate(a.delivered_at)}`;
  }
  if (a.days_until != null && a.days_until < 0) return "Termin überschritten";
  if (a.days_until == null) return "Noch kein Termin";
  if (a.days_until === 0) {
    return a.eta_from && a.eta_to ? `Heute ${fmtTime(a.eta_from)}–${fmtTime(a.eta_to)} Uhr` : "Heute";
  }
  if (a.days_until === 1) return "Morgen";
  return `In ${a.days_until} Tagen`;
}

class ParcelTrackerCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._open = new Set();
    this._renaming = new Map(); // number -> current input text
    this._confirming = new Set(); // numbers awaiting delete confirmation
    this._error = "";
  }

  getCardSize() { return 4; }

  set hass(hass) {
    this._hass = hass;
    if (!this._root) {
      this._build();
      this._renderList();
      return;
    }
    const sig = this._signature();
    if (sig === this._lastSig) return;
    this._renderList();
  }

  _signature() {
    const h = this._hass;
    const today = h.states["sensor.pakete_heute"];
    const parcels = this._parcels();
    return parcels.map((st) => `${st.entity_id}:${st.last_updated}`).join(",")
      + "|today:" + (today ? today.last_updated : "")
      + "|open:" + Array.from(this._open).sort().join(",")
      + "|ren:" + Array.from(this._renaming.keys()).sort().join(",")
      + "|del:" + Array.from(this._confirming).sort().join(",");
  }

  _parcels() {
    const h = this._hass;
    return Object.keys(h.entities || {})
      .filter((id) => h.entities[id].platform === "parcel_tracker" && id.startsWith("sensor.paket_"))
      .map((id) => h.states[id])
      .filter((st) => st && st.attributes && st.attributes.number != null)
      .sort((x, y) => ORDER(x.state, x.attributes) - ORDER(y.state, y.attributes)
        || (hasDate(x.attributes) ? x.attributes.days_until : 99) - (hasDate(y.attributes) ? y.attributes.days_until : 99));
  }

  _build() {
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `
      <style>
        ha-card { padding: 16px; }
        .head { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
        .title { font-size:16px; font-weight:500; display:flex; gap:8px; align-items:center; }
        .badge { font-size:12px; padding:2px 10px; border-radius:8px; background:var(--primary-color); color:var(--text-primary-color); }
        .row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; margin-bottom:8px; }
        input, select { font:inherit; padding:8px; border-radius:6px; border:1px solid var(--divider-color); background:var(--card-background-color); color:var(--primary-text-color); min-width:0; }
        button { font:inherit; padding:8px 12px; border-radius:6px; border:1px solid var(--divider-color); background:none; color:var(--primary-text-color); cursor:pointer; }
        .err { color:var(--error-color); font-size:13px; min-height:18px; }
        .item { border-top:1px solid var(--divider-color); padding:12px 0; }
        .row-toggle { display:block; width:100%; border:none; background:none; padding:0; margin:0; text-align:left; font:inherit; color:inherit; cursor:pointer; }
        .top { display:flex; justify-content:space-between; gap:8px; align-items:baseline; }
        .name { font-weight:500; display:flex; gap:8px; align-items:center; min-width:0; }
        .name span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .eta { font-size:13px; white-space:nowrap; color:var(--secondary-text-color); }
        .eta.today { color:var(--success-color); font-weight:500; }
        .sub { font-size:13px; color:var(--secondary-text-color); margin:2px 0 8px; }
        .bar { display:grid; grid-template-columns:repeat(${STEPS},1fr); gap:3px; }
        .bar i { height:4px; border-radius:2px; background:var(--divider-color); }
        .bar i.on { background:var(--primary-color); }
        .pickup { font-size:12px; padding:2px 8px; border-radius:6px; background:var(--warning-color); color:var(--text-primary-color); }
        .done { opacity:.55; }
        .detail { margin-top:10px; font-size:12px; color:var(--secondary-text-color); line-height:1.6; }
        .actions { display:flex; gap:8px; margin-top:8px; flex-wrap:wrap; }
        .actions input { flex:1 1 140px; }
        button.danger { color:var(--error-color); border-color:var(--error-color); }
        .stale { font-size:12px; color:var(--warning-color); }
        svg { width:18px; height:18px; flex:none; }
      </style>
      <ha-card>
        <div class="head"><div class="title"><ha-icon icon="mdi:package-variant"></ha-icon>Pakete</div><span class="badge" id="today"></span></div>
        <div class="row">
          <input id="num" placeholder="Sendungsnummer" autocomplete="off">
          <select id="car"><option value="auto">Automatisch</option><option value="dhl">DHL</option><option value="dpd">DPD</option></select>
        </div>
        <div class="row">
          <input id="nm" placeholder="Name (optional), z. B. Druckerpatronen">
          <button id="add">Hinzufügen</button>
        </div>
        <div class="err" id="err"></div>
        <div id="list"></div>
      </ha-card>`;
    const $ = (id) => this._root.getElementById(id);
    $("num").addEventListener("input", () => { this._setError(""); });
    $("add").addEventListener("click", () => this._add());
    $("num").addEventListener("keydown", (e) => { if (e.key === "Enter") this._add(); });
  }

  async _add() {
    const $ = (id) => this._root.getElementById(id);
    const number = $("num").value.trim();
    if (!number) { this._setError(SERVICE_ERRORS.empty); return; }
    try {
      await this._hass.callService("parcel_tracker", "add_parcel", {
        number, carrier: $("car").value, ...($("nm").value.trim() ? { name: $("nm").value.trim() } : {}),
      }, undefined, false);
      this._setError("");
      $("num").value = ""; $("nm").value = ""; $("car").value = "auto";
    } catch (e) {
      this._setError(errorText(e));
    }
  }

  _setError(html) {
    this._error = html;
    this._root.getElementById("err").innerHTML = html;
  }

  async _call(service, data) {
    try {
      await this._hass.callService("parcel_tracker", service, data, undefined, false);
      this._setError("");
      return true;
    } catch (e) {
      this._setError(errorText(e));
      return false;
    }
  }

  _icon(carrier) {
    const ic = CARRIER_ICONS[carrier];
    if (!ic) return `<ha-icon icon="mdi:package-variant-closed"></ha-icon>`;
    return `<svg viewBox="0 0 24 24" aria-label="${esc(carrier)}"><path fill="${ic.color}" d="${ic.path}"/></svg>`;
  }

  _actionsHtml(a) {
    const n = esc(a.number);
    if (this._renaming.has(a.number)) {
      return `<div class="actions">
        <input type="text" data-a="rename-input" data-number="${n}" aria-label="Neuer Name" value="${esc(this._renaming.get(a.number))}" autocomplete="off">
        <button type="button" data-a="rename-save" data-number="${n}">Speichern</button>
        <button type="button" data-a="rename-cancel" data-number="${n}">Abbrechen</button></div>`;
    }
    if (this._confirming.has(a.number)) {
      return `<div class="actions" role="group" aria-label="Löschen bestätigen">
        <button type="button" class="danger" data-a="remove-confirm" data-number="${n}">Wirklich löschen?</button>
        <button type="button" data-a="remove-cancel" data-number="${n}">Abbrechen</button></div>`;
    }
    return `<div class="actions"><button type="button" data-a="rename" data-number="${n}">Umbenennen</button><button type="button" data-a="remove" data-number="${n}">Löschen</button></div>`;
  }

  _wireActions(item, a) {
    const on = (act, fn) => {
      const el = item.querySelector(`[data-a="${act}"]`);
      if (el) el.addEventListener("click", fn);
    };
    const num = a.number;
    on("rename", () => { this._confirming.delete(num); this._renaming.set(num, a.name || ""); this._renderList(); });
    on("rename-cancel", () => { this._renaming.delete(num); this._renderList(); });
    const save = async () => {
      const name = this._renaming.get(num);
      if (name === undefined) return;
      if (await this._call("rename_parcel", { number: num, name: name.trim() })) {
        this._renaming.delete(num);
        this._renderList();
      }
    };
    on("rename-save", save);
    const input = item.querySelector('[data-a="rename-input"]');
    if (input) {
      input.addEventListener("input", () => this._renaming.set(num, input.value));
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); save(); }
        else if (e.key === "Escape") { e.preventDefault(); this._renaming.delete(num); this._renderList(); }
      });
    }
    on("remove", () => { this._renaming.delete(num); this._confirming.add(num); this._renderList(); });
    on("remove-cancel", () => { this._confirming.delete(num); this._renderList(); });
    on("remove-confirm", async () => {
      if (await this._call("remove_parcel", { number: num })) {
        this._confirming.delete(num);
        this._open.delete(num);
        this._renderList();
      }
    });
  }

  _renderList() {
    const list = this._root.getElementById("list");
    const focused = this._root.activeElement;
    const focusKey =
      focused && list.contains(focused) && focused.dataset && focused.dataset.number != null
        ? { number: focused.dataset.number, a: focused.dataset.a,
            selStart: focused.selectionStart, selEnd: focused.selectionEnd }
        : null;
    const parcels = this._parcels();
    const today = this._hass.states["sensor.pakete_heute"];
    this._root.getElementById("today").textContent = `${today ? today.state : 0} heute`;
    list.innerHTML = "";
    for (const st of parcels) {
      const a = st.attributes;
      const s = st.state;
      const label = this._hass.formatEntityState ? this._hass.formatEntityState(st) : s;
      const item = document.createElement("div");
      item.className = "item" + (s === DONE ? " done" : "");
      const bar = a.progress
        ? `<div class="bar">${Array.from({ length: STEPS }, (_, i) => `<i class="${i < a.progress ? "on" : ""}"></i>`).join("")}</div>`
        : "";
      const right = s === PICKUP
        ? `<span class="pickup">Abholbereit</span>`
        : `<span class="eta ${a.days_until === 0 && s !== DONE ? "today" : ""}">${esc(etaText(s, a))}</span>`;
      const sub = [a.carrier ? a.carrier.toUpperCase() : null, label, s === PICKUP ? a.pickup_point : a.location]
        .filter(Boolean).map(esc).join(" · ");
      const errMsg = a.last_error && ERROR_TEXT[a.last_error] ? ERROR_TEXT[a.last_error] : null;
      const stale = errMsg
        ? `<div class="stale">${esc(errMsg)}</div>`
        : (a.stale && a.last_update ? `<div class="stale">Stand ${fmtTime(a.last_update)}, Carrier nicht erreichbar</div>` : "");
      const open = this._open.has(a.number);
      const events = (a.events || []).map((e) => `${fmtDateTime(e.timestamp)} · ${esc(e.text)}${e.location ? " · " + esc(e.location) : ""}`).join("<br>");
      item.innerHTML = `
        <button type="button" class="row-toggle" aria-expanded="${open ? "true" : "false"}" data-number="${esc(a.number)}" data-a="toggle">
          <span class="top"><span class="name">${this._icon(a.carrier)}<span>${esc(a.name || a.number)}</span></span>${right}</span>
        </button>
        <div class="sub">${sub}</div>${bar}${stale}
        ${open ? `<div class="detail">${events || "Noch keine Ereignisse"}</div>${this._actionsHtml(a)}` : ""}`;
      item.querySelector(".row-toggle").addEventListener("click", () => {
        open ? this._open.delete(a.number) : this._open.add(a.number);
        this._renderList();
      });
      this._wireActions(item, a);
      list.appendChild(item);
    }
    if (!parcels.length) list.innerHTML = `<div class="sub">Noch keine Pakete. Trag oben eine Sendungsnummer ein.</div>`;
    if (focusKey) {
      for (const el of list.querySelectorAll("[data-a]")) {
        if (el.dataset.number === focusKey.number && el.dataset.a === focusKey.a) {
          el.focus();
          if (focusKey.selStart != null && el.setSelectionRange) {
            try { el.setSelectionRange(focusKey.selStart, focusKey.selEnd); } catch (_) { /* not a text input */ }
          }
          break;
        }
      }
    }
    this._lastSig = this._signature();
  }

  static getStubConfig() { return {}; }
}

customElements.define("parcel-tracker-card", ParcelTrackerCard);
window.customCards = window.customCards || [];
window.customCards.push({ type: "parcel-tracker-card", name: "Paket Tracker", description: "Pakete verfolgen und eintragen" });
