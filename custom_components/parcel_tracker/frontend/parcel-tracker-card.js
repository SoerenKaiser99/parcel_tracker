const CARRIER_ICONS = {"dhl": {"path": "M4.22 10.303l-.767 1.043h4.18c.21 0 .208.078.105.218-.105.142-.28.39-.386.534-.054.073-.154.207.171.207h1.71l.505-.69c.314-.426.028-1.312-1.095-1.312H4.22zM11.424 10.303l-1.475 2.002h5.39l1.473-2.002H14.61l-.843 1.146h-.985l.846-1.146h-2.203zM17.529 10.303l-1.474 2.002h2.334l1.472-2.002H17.53zM4.684 11.603l-1.54 2.094h3.754c1.24 0 1.932-.844 2.145-1.136h-2.56c-.326 0-.226-.133-.172-.207.107-.143.283-.388.388-.53.104-.14.107-.22-.105-.22h-1.91zM9.762 12.562l-.836 1.136h2.203l.836-1.136H9.762zM12.947 12.562l-.836 1.136h2.203l.836-1.136h-2.203zM15.865 12.562s-.159.22-.238.326c-.276.374-.033.81.87.81h3.538l.834-1.136h-5.004z", "color": "#FFCC00", "mark": "#D40511"}, "dpd": {"path": "M16.01 10.71a.364.364 0 01-.343-.006l-.558-.331a.43.43 0 01-.182-.312l-.014-.65a.363.363 0 01.165-.3l6.7-3.902L12.377.085A.799.799 0 0012 0a.798.798 0 00-.377.085l-9.4 5.124 10.53 6.13c.098.054.172.181.172.295v8.944c0 .112-.08.241-.178.294l-.567.315c-.171.062-.256.043-.361 0l-.569-.315a.362.362 0 01-.175-.294v-7.973a.223.223 0 00-.095-.156L1.702 7.048v10.579c0 .236.167.528.371.648l9.556 5.636c.102.06.237.09.371.089a.745.745 0 00.371-.09l9.557-5.635a.835.835 0 00.37-.648V7.047Z", "color": "#DC0032"}, "amazon": {"path": "M.045 18.02c.072-.116.187-.124.348-.022 3.636 2.11 7.594 3.166 11.87 3.166 2.852 0 5.668-.533 8.447-1.595l.315-.14c.138-.06.234-.1.293-.13.226-.088.39-.046.525.13.12.174.09.336-.12.48-.256.19-.6.41-1.006.654-1.244.743-2.64 1.316-4.185 1.726a17.617 17.617 0 01-10.951-.577 17.88 17.88 0 01-5.43-3.35c-.1-.074-.151-.15-.151-.22 0-.047.021-.09.051-.13zm6.565-6.218c0-1.005.247-1.863.743-2.577.495-.71 1.17-1.25 2.04-1.615.796-.335 1.756-.575 2.912-.72.39-.046 1.033-.103 1.92-.174v-.37c0-.93-.105-1.558-.3-1.875-.302-.43-.78-.65-1.44-.65h-.182c-.48.046-.896.196-1.246.46-.35.27-.575.63-.675 1.096-.06.3-.206.465-.435.51l-2.52-.315c-.248-.06-.372-.18-.372-.39 0-.046.007-.09.022-.15.247-1.29.855-2.25 1.82-2.88.976-.616 2.1-.975 3.39-1.05h.54c1.65 0 2.957.434 3.888 1.29.135.15.27.3.405.48.12.165.224.314.283.45.075.134.15.33.195.57.06.254.105.42.135.51.03.104.062.3.076.615.01.313.02.493.02.553v5.28c0 .376.06.72.165 1.036.105.313.21.54.315.674l.51.674c.09.136.136.256.136.36 0 .12-.06.226-.18.314-1.2 1.05-1.86 1.62-1.963 1.71-.165.135-.375.15-.63.045a6.062 6.062 0 01-.526-.496l-.31-.347a9.391 9.391 0 01-.317-.42l-.3-.435c-.81.886-1.603 1.44-2.4 1.665-.494.15-1.093.227-1.83.227-1.11 0-2.04-.343-2.76-1.034-.72-.69-1.08-1.665-1.08-2.94l-.05-.076zm3.753-.438c0 .566.14 1.02.425 1.364.285.34.675.512 1.155.512.045 0 .106-.007.195-.02.09-.016.134-.023.166-.023.614-.16 1.08-.553 1.424-1.178.165-.28.285-.58.36-.91.09-.32.12-.59.135-.8.015-.195.015-.54.015-1.005v-.54c-.84 0-1.484.06-1.92.18-1.275.36-1.92 1.17-1.92 2.43l-.035-.02zm9.162 7.027c.03-.06.075-.11.132-.17.362-.243.714-.41 1.05-.5a8.094 8.094 0 011.612-.24c.14-.012.28 0 .41.03.65.06 1.05.168 1.172.33.063.09.099.228.099.39v.15c0 .51-.149 1.11-.424 1.8-.278.69-.664 1.248-1.156 1.68-.073.06-.14.09-.197.09-.03 0-.06 0-.09-.012-.09-.044-.107-.12-.064-.24.54-1.26.806-2.143.806-2.64 0-.15-.03-.27-.087-.344-.145-.166-.55-.257-1.224-.257-.243 0-.533.016-.87.046-.363.045-.7.09-1 .135-.09 0-.148-.014-.18-.044-.03-.03-.036-.047-.02-.077 0-.017.006-.03.02-.063v-.06z", "color": "#FF9900"}, "ups": {"path": "M11.668 14.544l-.028-5.226c.138-.055.387-.111.608-.111.995 0 1.41.774 1.41 2.682 0 1.853-.47 2.765-1.438 2.765-.22 0-.441-.055-.552-.11zM3.124 7.438c4.203-3.843 9.29-4.866 14.018-4.866 1.3 0 2.544.083 3.76.194h-.028v11.253c0 2.184-.774 3.926-2.295 5.171-1.355 1.134-5.447 2.959-6.581 3.456-1.161-.525-5.253-2.378-6.581-3.456-1.493-1.244-2.295-3.014-2.295-5.171V7.438zm12.664 2.599c.028.912.276 1.576 1.687 2.406.747.442 1.051.747 1.051 1.272 0 .581-.387.94-1.023.94-.553 0-1.189-.304-1.631-.691v1.576c.553.304 1.217.525 1.88.525 1.687 0 2.433-1.189 2.461-2.267.028-.995-.249-1.742-1.659-2.571-.608-.387-1.134-.636-1.106-1.244 0-.581.525-.802.995-.802.581 0 1.161.332 1.521.691V8.378c-.304-.221-.94-.581-1.88-.553-1.135.028-2.296.829-2.296 2.212zm-5.834 9.484h1.714l-.028-3.594c.166.028.415.083.774.083 1.908 0 2.986-1.687 2.986-4.175 0-2.461-1.106-4.009-3.152-4.009-.94 0-1.687.221-2.295.608v11.087zm-5.945-6.166c0 1.797.829 2.71 2.516 2.71 1.051 0 1.908-.249 2.571-.691V7.991H7.41v6.387c-.194.138-.47.221-.802.221-.774 0-.885-.719-.885-1.189V7.991H4.009v5.364zM22.12 2.295v11.723c0 2.516-.94 4.645-2.765 6.111-1.549 1.3-6.332 3.429-7.355 3.871-1.023-.442-5.806-2.571-7.355-3.843-1.797-1.465-2.765-3.594-2.765-6.111V2.295C4.756.747 8.074 0 12 0s7.244.747 10.12 2.295zm-.304.221c-2.71-1.465-6-2.184-9.788-2.184s-7.079.746-9.788 2.184v11.502c0 2.433.912 4.452 2.627 5.862 1.576 1.3 6.581 3.484 7.161 3.76.581-.249 5.585-2.433 7.161-3.733 1.714-1.41 2.627-3.429 2.627-5.862V2.516zm-2.433 20.295c0 .47-.387.829-.829.829a.831.831 0 0 1-.829-.829c0-.47.387-.829.829-.829.441 0 .801.359.829.829zm-.166 0a.679.679 0 0 0-.664-.691c-.359 0-.664.332-.664.691 0 .359.304.664.664.664a.673.673 0 0 0 .664-.664zm-.553.055c.028.055.304.442.304.442h-.221s-.276-.387-.276-.415h-.028v.415h-.194v-.995l.304-.028c.249 0 .332.166.332.304s-.083.25-.221.277zm.027-.276c0-.055 0-.138-.166-.138h-.083v.304h.028c.194 0 .221-.083.221-.166z", "color": "var(--primary-text-color)"}, "ebay": {"path": "M6.056 12.132v-4.92h1.2v3.026c.59-.703 1.402-.906 2.202-.906 1.34 0 2.828.904 2.828 2.855 0 .233-.015.457-.06.668.24-.953 1.274-1.305 2.896-1.344.51-.018 1.095-.018 1.56-.018v-.135c0-.885-.556-1.244-1.53-1.244-.72 0-1.245.3-1.305.81h-1.275c.136-1.29 1.5-1.62 2.686-1.62 1.064 0 1.995.27 2.415 1.02l-.436-.84h1.41l2.055 4.125 2.055-4.126H24l-3.72 7.305h-1.346l1.07-2.04-2.33-4.38c.13.255.2.555.2.93v2.46c0 .346.01.69.04 1.005H16.8a6.543 6.543 0 01-.046-.765c-.603.734-1.32.96-2.32.96-1.48 0-2.272-.78-2.272-1.695 0-.15.015-.284.037-.405-.3 1.246-1.36 2.086-2.767 2.086-.87 0-1.694-.315-2.2-.93 0 .24-.015.494-.04.734h-1.18c.02-.39.04-.855.04-1.245v-1.05h-4.83c.065 1.095.818 1.74 1.853 1.74.718 0 1.355-.3 1.568-.93h1.24c-.24 1.29-1.61 1.725-2.79 1.725C.95 15.009 0 13.822 0 12.232c0-1.754.982-2.91 3.116-2.91 1.688 0 2.93.886 2.94 2.806v.005zm9.137.183c-1.095.034-1.77.233-1.77.95 0 .465.36.97 1.305.97 1.26 0 1.935-.69 1.935-1.814v-.13c-.45 0-.99.006-1.484.022h.012zm-6.06 1.875c1.11 0 1.876-.806 1.876-2.02s-.768-2.02-1.893-2.02c-1.11 0-1.89.806-1.89 2.02s.765 2.02 1.875 2.02h.03zm-4.35-2.514c-.044-1.125-.854-1.546-1.725-1.546-.944 0-1.694.474-1.815 1.546z", "color": "#E53238"}};
const CARRIER_LABEL = { dhl: "DHL", dpd: "DPD", gls: "GLS", hermes: "Hermes", ups: "UPS", amazon: "Amazon", ebay: "eBay", other: "17track" };
// Simple Icons' "hermes" is not used for the parcel service, it has no GLS logo, and
// "other" has no logo: a coloured dot with letters instead.
const DOTS = {
  gls: { color: "#061AB1", letter: "G", size: 13, y: 16.5 },
  hermes: { color: "#0091CD", letter: "H", size: 13, y: 16.5 },
  other: { color: "#757575", letter: "17", size: 10, y: 15.5 },
};
const QUOTA_ENTITY = "sensor.paket_tracker_17track_kontingent";
const SHOPS = ["amazon", "ebay"];
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
  carrier_not_found: "Carrier nicht gefunden – wähle den Carrier aus",
  not_found: "Noch keine Daten vom Carrier",
  unavailable: "Carrier gerade nicht erreichbar",
  rate_limited: "Zu viele Abfragen – nächster Versuch später",
  ups_auth: "UPS-Zugangsdaten abgelehnt – in den Integrations-Optionen prüfen",
  ups_budget: "UPS-Monatsbudget verbraucht – Status bis Monatsende aus Mails",
  track17_not_registered: "Bei 17track nicht mehr angemeldet",
};

// "auth" means the DHL key, except for UPS parcels (UPS client ID/secret).
// Merged parcels (e.g. Amazon + UPS mail) are polled at their tracking carrier.
// Carrier errors that only say "the carrier delivers nothing".
const GAP_ERRORS = new Set(["missing_key", "not_found", "carrier_not_found"]);

// 17track fills that gap: the parcel is registered there and shows a real status.
function coveredBy17track(a, s) {
  return a.track17 === true && !!s && s !== "unknown" && GAP_ERRORS.has(a.last_error);
}

function errorLine(a, s) {
  if (!a.last_error || coveredBy17track(a, s)) return null;
  const polled = a.tracking_carrier || a.carrier;
  const key = a.last_error === "auth" && polled === "ups" ? "ups_auth" : a.last_error;
  return ERROR_TEXT[key] || null;
}

// The warning line under a parcel: its error, else a note that the shown state is old.
function staleLine(a, s) {
  const msg = errorLine(a, s);
  if (msg || coveredBy17track(a, s)) return msg;
  return a.stale && a.last_update ? `Stand ${fmtTime(a.last_update)}, Carrier nicht erreichbar` : null;
}

const SERVICE_ERRORS = {
  duplicate: "Dieses Paket ist schon in der Liste.",
  amazon: "Amazon-Nummern (TBA…) lassen sich nicht direkt verfolgen. Leite die Amazon-Mails ins Paket-Postfach weiter.",
  empty: "Gib eine Sendungsnummer ein.",
  unknown_carrier: "Unbekannter Carrier.",
  not_tracked: "Dieses Paket ist nicht in der Liste.",
  track17_off: "Kein 17track-API-Key eingetragen. Trag ihn in den Optionen von Paket Tracker ein.",
  track17_carrier: "17track hat den Carrier dieser Nummer nicht erkannt.",
  track17_quota: "Das 17track-Kontingent ist erschöpft.",
  track17_auth: "17track hat den API-Key abgelehnt. Prüf ihn in den Optionen von Paket Tracker.",
  track17_unavailable: "17track ist gerade nicht erreichbar. Versuch es später noch einmal.",
  track17_not_possible: "Dieses Paket lässt sich nicht an 17track schicken (zugestellt oder noch keine Sendungsnummer).",
};

function errorText(e) {
  const keys = [e && e.translation_key, e && e.code, e && e.error && e.error.translation_key, e && e.error && e.error.code];
  for (const k of keys) {
    if (typeof k === "string" && Object.prototype.hasOwnProperty.call(SERVICE_ERRORS, k)) return SERVICE_ERRORS[k];
  }
  const msg = e && (e.message || (e.error && e.error.message));
  return "Das hat nicht geklappt: " + esc(msg == null ? "" : msg);
}

// A shop's first stage is an order, not a carrier announcement.
const stateLabel = (hass, st) => (st.state === "pre_transit" && SHOPS.includes(st.attributes.carrier)
  ? "Bestellt"
  : (hass.formatEntityState ? hass.formatEntityState(st) : st.state));

const MONTH_SHORT = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sep.", "Okt.", "Nov.", "Dez."];
const parseDay = (iso) => {
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return { y, m, d, t: Date.UTC(y, m - 1, d) };
};
const fmtDay = (p) => `${p.d}. ${MONTH_SHORT[p.m - 1]}`;

function rangeText(a) {
  const first = parseDay(a.eta_date);
  const last = parseDay(a.eta_latest);
  const lastDays = a.days_until + Math.round((last.t - first.t) / 864e5);
  if (lastDays < 0) return "Termin überschritten";
  if (a.days_until <= 0) return `Bis ${fmtDay(last)}`;
  return first.m === last.m ? `${first.d}.–${fmtDay(last)}` : `${fmtDay(first)}–${fmtDay(last)}`;
}

const carrierLabel = (key) => CARRIER_LABEL[key] || String(key).toUpperCase();

// "eBay · Unterwegs · via Hermes": carrier, state, place, carrier a shop mail named.
// A place 17track filled in for a carrier says so ("Ort via 17track").
function subText(label, a, s) {
  const hint = a.shipping_carrier_hint ? `via ${CARRIER_LABEL[a.shipping_carrier_hint] || a.shipping_carrier_hint}` : null;
  const place = s === PICKUP ? a.pickup_point : a.location;
  const via17 = s !== PICKUP && place && a.location_source === "17track" && a.carrier !== "other"
    ? "Ort via 17track" : null;
  const carrier = a.carrier ? (a.carrier_name || carrierLabel(a.carrier)) : null;
  return [carrier, label, place, via17, hint].filter(Boolean).map(esc).join(" · ");
}

function etaText(state, a) {
  if (state === DONE) {
    if (!a.delivered_at) return "Zugestellt";
    const d = Math.round((new Date().setHours(0,0,0,0) - new Date(a.delivered_at).setHours(0,0,0,0)) / 864e5);
    return d === 0 ? "Zugestellt heute" : d === 1 ? "Zugestellt gestern" : `Zugestellt am ${fmtDate(a.delivered_at)}`;
  }
  if (a.days_until == null) return "Noch kein Termin";
  if (a.eta_latest && a.eta_date && a.eta_latest !== a.eta_date) return rangeText(a);
  if (a.days_until < 0) return "Termin überschritten";
  if (a.days_until === 0) {
    return a.eta_from && a.eta_to ? `Heute ${fmtTime(a.eta_from)}–${fmtTime(a.eta_to)} Uhr` : "Heute";
  }
  if (a.days_until === 1) return "Morgen";
  return `In ${a.days_until} Tagen`;
}

// 17track is offered only with a key: then the quota sensor is available.
function track17State(hass) {
  const st = hass && hass.states ? hass.states[QUOTA_ENTITY] : null;
  const on = !!st && st.state !== "unavailable";
  const n = on && st.state !== "unknown" && st.state !== "" ? Number(st.state) : NaN;
  return { on, rest: Number.isFinite(n) ? n : null };
}

// Registering costs a number: not offered once none is left (a count not read yet still is).
const canSpend17 = (t17) => t17.on && t17.rest !== 0;

// Not for delivered parcels, parcels already at 17track, or shop orders without a carrier number.
const canTrack17 = (a, s, t17) => canSpend17(t17) && s !== DONE && !a.track17
  && !(SHOPS.includes(a.carrier) && !a.tracking_ref);

const track17Question = (rest) => (rest == null
  ? "Verbraucht 1 17track-Nummer. Fortfahren?"
  : `Verbraucht 1 von ${rest} verbleibenden 17track-Nummern. Fortfahren?`);

class ParcelTrackerCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._open = new Set();
    this._renaming = new Map(); // number -> current input text
    this._confirming = new Set(); // numbers awaiting delete confirmation
    this._code = new Map(); // number -> "ask" | "show" (delivery code reveal)
    this._t17ask = new Set(); // numbers awaiting the 17track confirmation
    this._addAsk = false; // adding with "Andere (über 17track)" awaits confirmation
    this._addAskText = null; // the question currently shown in #addask
    this._pendingFocus = null; // {number, a} to focus after the next render
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
      + "|del:" + Array.from(this._confirming).sort().join(",")
      + "|code:" + Array.from(this._code.entries()).map(([n, v]) => `${n}=${v}`).sort().join(",")
      + "|t17:" + Array.from(this._t17ask).sort().join(",")
      + "|quota:" + (h.states[QUOTA_ENTITY] ? `${h.states[QUOTA_ENTITY].state}@${h.states[QUOTA_ENTITY].last_updated}` : "");
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
        .code { align-items:center; font-size:13px; }
        .code strong { font-size:16px; letter-spacing:2px; color:var(--primary-text-color); }
        svg { width:18px; height:18px; flex:none; }
        svg.dhl { width:30px; }
        [hidden] { display:none !important; }
        .actions span { align-self:center; }
      </style>
      <ha-card>
        <div class="head"><div class="title"><ha-icon icon="mdi:package-variant"></ha-icon>Pakete</div><span class="badge" id="today"></span></div>
        <div class="row">
          <input id="num" placeholder="Sendungsnummer" autocomplete="off">
          <select id="car"><option value="auto">Automatisch</option><option value="dhl">DHL</option><option value="dpd">DPD</option><option value="gls">GLS</option><option value="hermes">Hermes</option><option value="ups">UPS</option></select>
        </div>
        <div class="row">
          <input id="nm" placeholder="Name (optional), z. B. Druckerpatronen">
          <button id="add">Hinzufügen</button>
        </div>
        <div class="actions" id="addask" role="group" aria-label="17track bestätigen" hidden></div>
        <div class="err" id="err"></div>
        <div id="list"></div>
      </ha-card>`;
    const $ = (id) => this._root.getElementById(id);
    // The confirmation was for the number as it stood: another number asks again.
    $("num").addEventListener("input", () => { this._setError(""); this._dismissAddAsk(); });
    $("add").addEventListener("click", () => this._add());
    $("num").addEventListener("keydown", (e) => { if (e.key === "Enter") this._add(); });
    $("car").addEventListener("change", () => this._dismissAddAsk());
  }

  async _add(confirmed = false) {
    const $ = (id) => this._root.getElementById(id);
    const number = $("num").value.trim();
    if (!number) { this._setError(SERVICE_ERRORS.empty); return; }
    const carrier = $("car").value;
    if (carrier === "other" && !confirmed) {
      // Adding via 17track spends one of the account's numbers: ask first.
      this._addAsk = true;
      this._renderAddAsk(track17State(this._hass));
      return;
    }
    this._addAsk = false;
    this._renderAddAsk(track17State(this._hass));
    try {
      await this._hass.callService("parcel_tracker", "add_parcel", {
        number, carrier, ...($("nm").value.trim() ? { name: $("nm").value.trim() } : {}),
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
    const dot = DOTS[carrier];
    if (dot) {
      return `<svg viewBox="0 0 24 24" width="18" height="18" aria-label="${esc(carrier)}"><circle cx="12" cy="12" r="11" fill="${dot.color}"/><text x="12" y="${dot.y}" text-anchor="middle" font-size="${dot.size}" font-weight="700" font-family="sans-serif" fill="#fff">${dot.letter}</text></svg>`;
    }
    const ic = CARRIER_ICONS[carrier];
    if (!ic) return `<ha-icon icon="mdi:package-variant-closed"></ha-icon>`;
    if (ic.mark) {
      // DHL: the letters of the wordmark (x 3.1-20.9, y 10.3-13.7 of the 24x24 box) in red on
      // a yellow rounded badge. The viewBox crops the box to the letters: 30x18 px.
      return `<svg class="dhl" viewBox="1.6 5.76 20.8 12.48" width="30" height="18" aria-label="${esc(carrier)}"><rect x="1.6" y="5.76" width="20.8" height="12.48" rx="2.1" fill="${ic.color}"/><path fill="${ic.mark}" d="${ic.path}"/></svg>`;
    }
    // A theme colour (UPS: the text colour, readable on light and dark) needs a style.
    const fill = ic.color.startsWith("var(") ? `style="fill:${ic.color}"` : `fill="${ic.color}"`;
    return `<svg viewBox="0 0 24 24" width="18" height="18" aria-label="${esc(carrier)}"><path ${fill} d="${ic.path}"/></svg>`;
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

  _codeHtml(a) {
    if (!a.delivery_code) return "";
    const n = esc(a.number);
    const mode = this._code.get(a.number);
    if (mode === "show") {
      return `<div class="actions code" role="group" aria-label="Zustell-Code">
        <span>Zustell-Code <strong>${esc(a.delivery_code)}</strong></span>
        <button type="button" data-a="code-hide" data-number="${n}">Verbergen</button></div>`;
    }
    if (mode === "ask") {
      return `<div class="actions code" role="group" aria-label="Zustell-Code anzeigen?">
        <span>Zustell-Code anzeigen?</span>
        <button type="button" data-a="code-confirm" data-number="${n}">Anzeigen</button>
        <button type="button" data-a="code-cancel" data-number="${n}">Abbrechen</button></div>`;
    }
    return `<div class="actions code"><button type="button" data-a="code" data-number="${n}">Code anzeigen</button></div>`;
  }

  _track17Html(a, s, t17) {
    if (!canTrack17(a, s, t17)) return "";
    const n = esc(a.number);
    if (this._t17ask.has(a.number)) {
      return `<div class="actions" role="group" aria-label="17track bestätigen">
        <span>${esc(track17Question(t17.rest))}</span>
        <button type="button" data-a="t17-confirm" data-number="${n}">Fortfahren</button>
        <button type="button" data-a="t17-cancel" data-number="${n}">Abbrechen</button></div>`;
    }
    return `<div class="actions"><button type="button" data-a="t17" data-number="${n}">Details über 17track holen</button></div>`;
  }

  // "Andere (über 17track)" only while a 17track key is configured and a number is left.
  _syncOther(t17) {
    const on = canSpend17(t17);
    const sel = this._root.getElementById("car");
    const opt = sel.querySelector('option[value="other"]');
    if (on && !opt) {
      sel.insertAdjacentHTML("beforeend", '<option value="other">Andere (über 17track)</option>');
    } else if (!on && opt) {
      if (sel.value === "other") sel.value = "auto";
      opt.remove();
    }
  }

  _dismissAddAsk() {
    if (!this._addAsk) return;
    this._addAsk = false;
    this._renderAddAsk(track17State(this._hass));
  }

  _renderAddAsk(t17) {
    const box = this._root.getElementById("addask");
    if (!this._addAsk || !canSpend17(t17)) {
      this._addAsk = false;
      if (!box.hidden || this._addAskText !== null) {
        this._addAskText = null;
        box.hidden = true;
        box.innerHTML = "";
      }
      return;
    }
    const text = track17Question(t17.rest);
    // Same question as shown: keep the buttons, so the keyboard focus stays on them.
    if (!box.hidden && this._addAskText === text) return;
    this._addAskText = text;
    box.hidden = false;
    box.innerHTML = `<span>${esc(text)}</span>
      <button type="button" id="addask-yes">Fortfahren</button>
      <button type="button" id="addask-no">Abbrechen</button>`;
    // Either button removes both: put the keyboard focus back on the number field.
    const toNumber = () => this._root.getElementById("num").focus();
    box.querySelector("#addask-yes").addEventListener("click", () => { this._add(true); toNumber(); });
    box.querySelector("#addask-no").addEventListener("click", () => { this._dismissAddAsk(); toNumber(); });
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
    const code = (mode, focus) => {
      mode ? this._code.set(num, mode) : this._code.delete(num);
      this._pendingFocus = { number: num, a: focus };
      this._renderList();
    };
    on("code", () => code("ask", "code-confirm"));
    on("code-cancel", () => code(null, "code"));
    on("code-confirm", () => code("show", "code-hide"));
    on("code-hide", () => code(null, "code"));
    const ask17 = (asking, focus) => {
      asking ? this._t17ask.add(num) : this._t17ask.delete(num);
      this._pendingFocus = { number: num, a: focus };
      this._renderList();
    };
    on("t17", () => ask17(true, "t17-confirm"));
    on("t17-cancel", () => ask17(false, "t17"));
    on("t17-confirm", async () => {
      if (await this._call("track_17track", { number: num })) {
        this._t17ask.delete(num);
        // The confirm button is gone now: put the focus on the parcel's row.
        this._pendingFocus = { number: num, a: "toggle" };
        this._renderList();
      }
    });
    on("remove", () => { this._renaming.delete(num); this._confirming.add(num); this._renderList(); });
    on("remove-cancel", () => { this._confirming.delete(num); this._renderList(); });
    on("remove-confirm", async () => {
      if (await this._call("remove_parcel", { number: num })) {
        this._confirming.delete(num);
        this._open.delete(num);
        this._code.delete(num);
        this._renderList();
      }
    });
  }

  _renderList() {
    const list = this._root.getElementById("list");
    const focused = this._root.activeElement;
    const focusKey = this._pendingFocus || (
      focused && list.contains(focused) && focused.dataset && focused.dataset.number != null
        ? { number: focused.dataset.number, a: focused.dataset.a,
            selStart: focused.selectionStart, selEnd: focused.selectionEnd }
        : null);
    this._pendingFocus = null;
    const t17 = track17State(this._hass);
    this._syncOther(t17);
    this._renderAddAsk(t17);
    const parcels = this._parcels();
    const today = this._hass.states["sensor.pakete_heute"];
    this._root.getElementById("today").textContent = `${today ? today.state : 0} heute`;
    list.innerHTML = "";
    for (const st of parcels) {
      const a = st.attributes;
      const s = st.state;
      const label = stateLabel(this._hass, st);
      const item = document.createElement("div");
      item.className = "item" + (s === DONE ? " done" : "");
      const bar = a.progress
        ? `<div class="bar">${Array.from({ length: STEPS }, (_, i) => `<i class="${i < a.progress ? "on" : ""}"></i>`).join("")}</div>`
        : "";
      const right = s === PICKUP
        ? `<span class="pickup">Abholbereit</span>`
        : `<span class="eta ${a.days_until === 0 && s !== DONE ? "today" : ""}">${esc(etaText(s, a))}</span>`;
      const sub = subText(label, a, s);
      const staleMsg = staleLine(a, s);
      const stale = staleMsg ? `<div class="stale">${esc(staleMsg)}</div>` : "";
      const open = this._open.has(a.number);
      const events = (a.events || []).map((e) => `${fmtDateTime(e.timestamp)} · ${esc(e.text)}${e.location ? " · " + esc(e.location) : ""}`).join("<br>");
      item.innerHTML = `
        <button type="button" class="row-toggle" aria-expanded="${open ? "true" : "false"}" data-number="${esc(a.number)}" data-a="toggle">
          <span class="top"><span class="name">${this._icon(a.carrier)}<span>${esc(a.name || a.number)}</span></span>${right}</span>
        </button>
        <div class="sub">${sub}</div>${bar}${stale}
        ${open ? `<div class="detail">${events || "Noch keine Ereignisse"}</div>${this._codeHtml(a)}${this._track17Html(a, s, t17)}${this._actionsHtml(a)}` : ""}`;
      item.querySelector(".row-toggle").addEventListener("click", () => {
        if (open) {
          this._open.delete(a.number);
          this._code.delete(a.number); // hide the code again on collapse
          this._t17ask.delete(a.number);
        } else {
          this._open.add(a.number);
        }
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

if (!customElements.get("parcel-tracker-card")) {
  customElements.define("parcel-tracker-card", ParcelTrackerCard);
  window.customCards = window.customCards || [];
  window.customCards.push({ type: "parcel-tracker-card", name: "Paket Tracker", description: "Pakete verfolgen und eintragen" });
}
