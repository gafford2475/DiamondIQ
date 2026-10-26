/* DiamondIQ mobile web app. Plain JS, no build step; served by the API at /app/. */
"use strict";

// ---------------------------------------------------------------- utilities

const $view = document.getElementById("view");
const $title = document.getElementById("title");
const $back = document.getElementById("back");

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v; // only used with static strings
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

/** Replace an element's children, flattening arrays and skipping null/false (DOM replaceChildren does neither). */
function fill(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false)
    .map((c) => (c instanceof Node ? c : document.createTextNode(String(c)))));
}

const svgNS = "http://www.w3.org/2000/svg";
function s(tag, attrs, ...children) {
  const el = document.createElementNS(svgNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) el.setAttribute(k, v);
  for (const c of children.flat()) if (c !== null && c !== undefined) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

function toast(msg, ms = 2600) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), ms);
}

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function api(path, opts = {}) {
  const init = { method: opts.method || "GET", headers: {} };
  if (opts.json !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.json);
  } else if (opts.form) {
    init.body = opts.form;
  }
  const res = await fetch(path, init); // a TypeError here means "offline"
  if (res.status === 204) return null;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const d = data && data.detail;
    const msg = Array.isArray(d) ? d.map((e) => `${(e.loc || []).slice(-1)[0]}: ${e.msg}`).join("; ") : d || res.statusText;
    if (res.status === 401 && !path.startsWith("/auth/")) signInRequired();
    throw new ApiError(msg, res.status);
  }
  return data;
}

const store = {
  get(k, dflt) {
    try { const v = localStorage.getItem("diq." + k); return v === null ? dflt : JSON.parse(v); } catch { return dflt; }
  },
  set(k, v) {
    try { localStorage.setItem("diq." + k, JSON.stringify(v)); } catch { /* private mode: keep going without persistence */ }
  },
};

const fmt = {
  pct: (x, d = 1) => (x === null || x === undefined ? "–" : (x * 100).toFixed(d) + "%"),
  rate: (x) => (x === null || x === undefined ? "–" : x.toFixed(3).replace(/^0/, "")),
  n: (x, d = 1) => (x === null || x === undefined ? "–" : Number(x).toFixed(d)),
  age: (birth) => {
    if (!birth) return null;
    const ms = Date.now() - new Date(birth + "T00:00:00").getTime();
    return (ms / (365.25 * 864e5)).toFixed(1);
  },
  height: (inches) => (inches ? `${Math.floor(inches / 12)}'${Math.round(inches % 12)}"` : null),
  today: () => new Date().toISOString().slice(0, 10),
};

function formData(form) {
  const out = {};
  for (const el of form.elements) {
    if (!el.name || el.disabled) continue;
    if (el.type === "checkbox") { out[el.name] = el.checked; continue; }
    const v = el.value.trim();
    if (v === "") continue;
    out[el.name] = el.type === "number" ? Number(v) : v;
  }
  return out;
}

function field(label, input) {
  return h("label", { class: "field" }, label, input);
}
function input(name, attrs = {}) {
  return h("input", { name, ...attrs });
}
function select(name, options, value, attrs = {}) {
  return h("select", { name, ...attrs },
    options.map((o) => {
      const [v, l] = Array.isArray(o) ? o : [o, o];
      return h("option", { value: v, selected: String(v) === String(value) ? true : null }, l);
    }));
}

function busy(btn, promise) {
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "Working…";
  return promise.finally(() => { btn.disabled = false; btn.textContent = label; });
}

function errorBox(e) {
  return h("div", { class: "card" }, h("strong", {}, "Something went wrong"), h("p", { class: "ink2" }, e.message || String(e)));
}

let LEVELS = null;
async function levels() {
  if (!LEVELS) {
    try { LEVELS = await api("/levels"); store.set("levels", LEVELS); } catch { LEVELS = store.get("levels", []); }
  }
  return LEVELS;
}
function levelName(code) {
  const l = (LEVELS || []).find((x) => x.code === code);
  return l ? l.name : code || "–";
}
const LEVEL_SHORT = { NCAA_D1_P4: "D1 Power", NCAA_D1: "D1", NCAA_D2: "D2", NCAA_D3: "D3", JUCO: "JUCO", JUCO_D2: "JUCO D2", JUCO_D3: "JUCO D3", A_PLUS: "High-A", A: "Single-A", HS_JV: "JV", SHOWCASE: "Showcase", INDY_TOP: "Atlantic", INDY: "Indy", OUT: "Out of baseball" };
const short = (code) => LEVEL_SHORT[code] || code;

// ---------------------------------------------------------------- offline pitch queue

// Pitches are always queued first, then flushed in order. If the phone has no
// signal the queue persists in localStorage and is retried when it reconnects.
const queue = {
  items() { return store.get("queue", []); },
  save(q) { store.set("queue", q); renderSync(); },
  forGame(gameId) { return this.items().filter((x) => x.gameId === gameId); },
  push(gameId, body) {
    const q = this.items();
    q.push({ gameId, body, qid: Date.now() + Math.random() });
    this.save(q);
  },
  popLast(gameId) {
    const q = this.items();
    for (let i = q.length - 1; i >= 0; i--) if (q[i].gameId === gameId) { q.splice(i, 1); this.save(q); return true; }
    return false;
  },
  async flush() {
    if (this._flushing) return this._flushing;
    this._flushing = (async () => {
      let q = this.items();
      let sent = 0;
      while (q.length) {
        const item = q[0];
        try {
          await api(`/games/${item.gameId}/pitches`, { method: "POST", json: item.body });
        } catch (e) {
          if (!(e instanceof ApiError) || e.status === 401) break; // offline or signed out: keep the queue and retry later
          toast(`A queued pitch was rejected: ${e.message}`);
        }
        q = this.items().filter((x) => x.qid !== item.qid);
        this.save(q);
        sent++;
      }
      // Screens holding a copy of server pitches (the charting view) refresh on this.
      if (sent) window.dispatchEvent(new CustomEvent("diq-synced"));
    })().finally(() => { this._flushing = null; });
    return this._flushing;
  },
};
function renderSync() {
  const n = queue.items().length;
  const el = document.getElementById("sync");
  el.hidden = n === 0;
  el.textContent = `${n} pitch${n === 1 ? "" : "es"} to sync`;
}
window.addEventListener("online", () => queue.flush());
setInterval(() => queue.items().length && queue.flush(), 20000);

// ---------------------------------------------------------------- router

const routes = [
  [/^#\/players\/new$/, () => playerForm()],
  [/^#\/players\/(\d+)\/edit$/, (id) => playerForm(+id)],
  [/^#\/players\/(\d+)(?:\/(\w+))?$/, (id, tab) => playerView(+id, tab || "overview")],
  [/^#\/players$/, () => playersView()],
  [/^#\/games\/new$/, () => gameForm()],
  [/^#\/games\/(\d+)\/chart$/, (id) => chartView(+id)],
  [/^#\/games\/(\d+)$/, (id) => gameSummaryView(+id)],
  [/^#\/games$/, () => gamesView()],
  [/^#\/account$/, () => accountView()],
  [/^#\/chart$/, () => {
    const g = store.get("lastGame", null);
    location.replace(g ? `#/games/${g}/chart` : "#/games");
  }],
];

async function route() {
  if (!ME) return showAuth();
  const hash = location.hash || "#/players";
  const tab = hash.endsWith("/chart") ? "chart" : hash.split("/")[1];
  document.querySelectorAll(".tabbar a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
  for (const [re, fn] of routes) {
    const m = hash.match(re);
    if (m) {
      $back.hidden = hash.split("/").length <= 2;
      fill($view, h("p", { class: "muted" }, "Loading…"));
      try { await fn(...m.slice(1)); } catch (e) { fill($view, errorBox(e)); }
      $view.focus({ preventScroll: true });
      return;
    }
  }
  location.replace("#/players");
}
$back.addEventListener("click", () => history.back());
window.addEventListener("hashchange", route);

function setTitle(t) {
  $title.textContent = t;
  document.title = t === "DiamondIQ" ? t : `${t} · DiamondIQ`;
}

// ---------------------------------------------------------------- players

async function playersView() {
  setTitle("Players");
  await levels();
  const state = store.get("playerFilters", { q: "", type: "", level: "", watchlist: "" });
  const results = h("ul", { class: "list cards" });
  let watchlists = [];
  try { watchlists = await api("/watchlists"); } catch { /* offline */ }

  async function load() {
    store.set("playerFilters", state);
    fill(results, h("p", { class: "muted" }, "Loading…"));
    try {
      let players;
      if (state.watchlist) {
        players = (await api(`/watchlists/${state.watchlist}`)).players;
        if (state.q) players = players.filter((p) => `${p.first_name} ${p.last_name} ${p.current_team || ""}`.toLowerCase().includes(state.q.toLowerCase()));
        if (state.type) players = players.filter((p) => p.player_type === state.type);
        if (state.level) players = players.filter((p) => p.current_level === state.level);
      } else {
        const qs = new URLSearchParams();
        if (state.q) qs.set("q", state.q);
        if (state.type) qs.set("player_type", state.type);
        if (state.level) qs.set("level", state.level);
        players = await api(`/players?${qs}`);
      }
      fill(results, 
        ...(players.length ? players.map(playerRow) : [h("p", { class: "muted" }, "No players yet. Tap “Add player” to create one.")])
      );
    } catch (e) {
      fill(results, errorBox(e));
    }
  }

  const search = h("input", { class: "input", type: "search", placeholder: "Search name or team", value: state.q, "aria-label": "Search players" });
  let t;
  search.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { state.q = search.value.trim(); load(); }, 250); });

  const typeChips = h("div", { class: "chips", role: "group", "aria-label": "Player type" },
    [["", "All"], ["hitter", "Hitters"], ["pitcher", "Pitchers"], ["two_way", "Two-way"]].map(([v, l]) =>
      h("button", { class: "chip", "aria-pressed": String(state.type === v), onclick: (e) => {
        state.type = v;
        e.target.parentElement.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c === e.target)));
        load();
      } }, l)));
  const levelSel = select("level", [["", "All levels"], ...LEVELS.map((l) => [l.code, l.name])], state.level, { class: "input", "aria-label": "Level" });
  levelSel.addEventListener("change", () => { state.level = levelSel.value; load(); });
  const wlSel = select("watchlist", [["", "All players"], ...watchlists.map((w) => [w.id, `★ ${w.name} (${w.player_count})`])], state.watchlist, { class: "input", "aria-label": "Watchlist" });
  wlSel.addEventListener("change", () => { state.watchlist = wlSel.value; load(); });

  fill($view, 
    search,
    h("div", { class: "row", style: "margin-top:8px" }, levelSel, wlSel),
    h("div", { style: "margin-top:8px" }, typeChips),
    results,
    h("a", { class: "btn primary fab write", href: "#/players/new" }, "+ Add player")
  );
  load();
}

function playerRow(p) {
  const bits = [p.primary_position, short(p.current_level), p.current_team, p.grad_year && `’${String(p.grad_year).slice(2)}`].filter(Boolean);
  return h("li", {}, h("a", { class: "list-item", href: `#/players/${p.id}` },
    h("div", { class: "grow" },
      h("div", { class: "name" }, `${p.first_name} ${p.last_name}`),
      h("div", { class: "small ink2" }, bits.join(" · "))),
    h("span", { class: "badge" }, p.player_type === "two_way" ? "2-way" : p.player_type === "pitcher" ? "P" : "H"),
    h("span", { class: "chev", "aria-hidden": "true" }, "›")));
}

async function playerForm(id) {
  await levels();
  const p = id ? await api(`/players/${id}`) : { player_type: "hitter", bats: "R", throws: "R" };
  setTitle(id ? "Edit player" : "New player");
  const form = h("form", { class: "stack" },
    h("div", { class: "grid2" },
      field("First name", input("first_name", { required: true, value: p.first_name || "", autocomplete: "off" })),
      field("Last name", input("last_name", { required: true, value: p.last_name || "", autocomplete: "off" }))),
    h("div", { class: "grid2" },
      field("Type", select("player_type", [["hitter", "Hitter"], ["pitcher", "Pitcher"], ["two_way", "Two-way"]], p.player_type)),
      field("Position", select("primary_position", ["", "P", "C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "OF", "IF", "DH"], p.primary_position))),
    h("div", { class: "grid2" },
      field("Bats", select("bats", ["R", "L", "S"], p.bats)),
      field("Throws", select("throws", ["R", "L"], p.throws))),
    h("div", { class: "grid2" },
      field("Birth date", input("birth_date", { type: "date", value: p.birth_date || "" })),
      field("Grad year", input("grad_year", { type: "number", inputmode: "numeric", value: p.grad_year || "" }))),
    h("div", { class: "grid2" },
      field("Height (in)", input("height_in", { type: "number", inputmode: "decimal", step: "0.5", value: p.height_in || "", placeholder: "e.g. 73" })),
      field("Weight (lb)", input("weight_lb", { type: "number", inputmode: "numeric", value: p.weight_lb || "" }))),
    field("Current level", select("current_level", [["", "Select…"], ...LEVELS.map((l) => [l.code, l.name])], p.current_level, { required: true })),
    field("Team / school", input("current_team", { value: p.current_team || "" })),
    field("Commitment", input("commitment", { value: p.commitment || "", placeholder: "College commit (optional)" })),
    field("Notes", h("textarea", { name: "notes" }, p.notes || "")),
    h("button", { class: "btn primary block", type: "submit" }, id ? "Save changes" : "Create player"),
    id ? h("button", { class: "btn danger block", type: "button", onclick: async () => {
      if (!confirm(`Delete ${p.first_name} ${p.last_name} and all of their data?`)) return;
      await api(`/players/${id}`, { method: "DELETE" });
      toast("Player deleted");
      location.hash = "#/players";
    } }, "Delete player") : null
  );
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type=submit]");
    try {
      const body = formData(form);
      const saved = await busy(btn, api(id ? `/players/${id}` : "/players", { method: id ? "PATCH" : "POST", json: body }));
      toast(id ? "Saved" : "Player created");
      location.replace(`#/players/${saved.id}`);
    } catch (err) { toast(err.message, 5000); }
  });
  fill($view, form);
}

const PLAYER_TABS = [["overview", "Overview"], ["scouting", "Scouting"], ["stats", "Stats"], ["tracking", "Tracking"], ["mechanics", "Mechanics"], ["projection", "Projection"]];

async function playerView(id, tab) {
  await levels();
  const prof = await api(`/players/${id}/profile`);
  const p = prof.player;
  setTitle(`${p.first_name} ${p.last_name}`);
  const tabs = h("div", { class: "chips tabs", role: "tablist" },
    PLAYER_TABS.map(([k, l]) => h("button", { class: "chip", role: "tab", "aria-pressed": String(k === tab), onclick: () => location.replace(`#/players/${id}/${k}`) }, l)));
  const body = h("div");
  fill($view, tabs, body);
  const renderers = { overview: overviewTab, scouting: scoutingTab, stats: statsTab, tracking: trackingTab, mechanics: mechanicsTab, projection: projectionTab };
  await renderers[tab](body, prof);
}

async function overviewTab(el, prof) {
  const p = prof.player;
  const age = fmt.age(p.birth_date);
  const facts = [
    ["Level", levelName(p.current_level)], ["Team", p.current_team], ["Position", p.primary_position],
    ["Age", age], ["B/T", `${p.bats || "?"}/${p.throws || "?"}`], ["Ht / Wt", [fmt.height(p.height_in), p.weight_lb && `${p.weight_lb} lb`].filter(Boolean).join(" · ")],
    ["Grad year", p.grad_year], ["Commitment", p.commitment],
  ].filter(([, v]) => v);
  const sc = prof.scouting[p.player_type === "pitcher" ? "pitcher" : "hitter"] || prof.scouting.pitcher || prof.scouting.hitter;
  const proj = prof.latest_projection;
  const mech = prof.mechanics.find((m) => m.status === "done");

  let watchlists = [];
  try { watchlists = await api("/watchlists"); } catch { /* ignore */ }
  const wlSel = select("wl", [["", "Add to watchlist…"], ...watchlists.map((w) => [w.id, w.name]), ["__new", "+ New watchlist"]], "", { class: "input" });
  wlSel.addEventListener("change", async () => {
    let wid = wlSel.value;
    if (!wid) return;
    try {
      if (wid === "__new") {
        const name = prompt("Watchlist name");
        if (!name) { wlSel.value = ""; return; }
        wid = (await api("/watchlists", { method: "POST", json: { name } })).id;
      }
      await api(`/watchlists/${wid}/players/${p.id}`, { method: "PUT" });
      toast("Added to watchlist");
    } catch (e) { toast(e.message); }
    wlSel.value = "";
  });

  fill(el, 
    h("div", { class: "card" },
      h("div", { class: "grid2" }, facts.map(([k, v]) => h("div", {}, h("div", { class: "small muted" }, k), h("div", {}, v)))),
      p.notes ? h("p", { class: "ink2" }, p.notes) : null,
      h("div", { class: "row", style: "margin-top:12px" },
        h("a", { class: "btn write", href: `#/players/${p.id}/edit` }, "Edit"), h("div", { class: "write" }, wlSel))),
    h("h2", {}, "Projection"),
    proj
      ? h("div", { class: "card" },
          h("p", { style: "margin-top:0" }, proj.summary),
          h("a", { href: `#/players/${p.id}/projection` }, "See the full projection ›"))
      : h("div", { class: "card" }, h("p", { class: "ink2", style: "margin-top:0" }, "No projection yet."),
          h("a", { class: "btn primary", href: `#/players/${p.id}/projection` }, "Run projection")),
    h("h2", {}, "Snapshot"),
    h("div", { class: "tiles" },
      tile(sc && sc.ofp ? sc.ofp : "–", "Scouting OFP"),
      tile(sc ? sc.report_count : 0, "Reports"),
      tile(mech ? Math.round(mech.scores.mechanics_score) : "–", `Mechanics (${mech ? mech.motion_type : "no video"})`),
      p.player_type !== "hitter" ? tile(fmt.n(prof.tracking.pitching && prof.tracking.pitching.fb_velo_avg), "FB velo") : null,
      p.player_type !== "pitcher" ? tile(fmt.n(prof.tracking.hitting && prof.tracking.hitting.ev_max), "Max EV") : null),
    mech && mech.top_priorities.length ? h("div", { class: "card" }, h("strong", {}, "Mechanics flags"), h("ul", {}, mech.top_priorities.map((t) => h("li", {}, t)))) : null
  );
}

function tile(v, k) {
  return h("div", { class: "tile" }, h("div", { class: "v" }, v), h("div", { class: "k" }, k));
}

// ---------------------------------------------------------------- sheets

function openSheet(title, content) {
  const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => e.key === "Escape" && close();
  const backdrop = h("div", { class: "sheet-backdrop", onclick: (e) => e.target === backdrop && close() },
    h("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("div", { class: "row" }, h("h2", {}, title), h("button", { class: "icon-btn", style: "flex:none", "aria-label": "Close", onclick: () => close() }, "×")),
      content));
  document.addEventListener("keydown", onKey);
  document.body.append(backdrop);
  const first = backdrop.querySelector("input, select, textarea, button:not(.icon-btn)");
  if (first) first.focus();
  return close;
}

// ---------------------------------------------------------------- scouting

const TOOLS = {
  hitter: [["hit", "Hit"], ["raw_power", "Raw power"], ["game_power", "Game power"], ["approach", "Approach"], ["run", "Run"], ["arm", "Arm"], ["field", "Field"]],
  pitcher: [["fastball", "Fastball"], ["sinker", "Sinker"], ["cutter", "Cutter"], ["slider", "Slider"], ["sweeper", "Sweeper"], ["curveball", "Curveball"],
    ["changeup", "Changeup"], ["splitter", "Splitter"], ["control", "Control"], ["command", "Command"]],
};
const MEASURABLES = {
  hitter: [["sixty_time", "60-yd (s)"], ["home_to_first", "Home→1B (s)"], ["inf_velo", "INF velo"], ["of_velo", "OF velo"], ["pop_time", "Pop time (s)"], ["exit_velo_max", "Max EV"]],
  pitcher: [["fb_velo_low", "FB low"], ["fb_velo_high", "FB high"], ["fb_velo_max", "FB max"], ["time_to_plate", "Time to plate (s)"]],
};
const GRADES = ["", 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80];

function reportType(p) {
  return p.player_type === "pitcher" ? "pitcher" : "hitter";
}

async function scoutingTab(el, prof) {
  const p = prof.player;
  const reports = await api(`/players/${p.id}/scouting-reports`);
  const sections = [];
  for (const type of ["hitter", "pitcher"]) {
    const c = prof.scouting[type];
    if (!c) continue;
    const order = TOOLS[type].map(([k]) => k);
    const tools = Object.entries(c.tools).sort((a, b) => (order.indexOf(a[0]) + 99) % 99 - (order.indexOf(b[0]) + 99) % 99);
    sections.push(
      h("h2", {}, `${type === "pitcher" ? "Pitching" : "Hitting"} consensus`),
      h("p", { class: "small ink2" }, `${c.report_count} report${c.report_count === 1 ? "" : "s"} · ${c.scouts.join(", ")}`),
      h("div", { class: "card table-wrap" },
        h("table", {},
          h("thead", {}, h("tr", {}, h("th", {}, "Tool"), h("th", {}, "Present"), h("th", {}, "Future"), h("th", {}, "Range"))),
          h("tbody", {}, tools.map(([tool, g]) => h("tr", {},
            h("td", {}, (TOOLS[type].find(([k]) => k === tool) || [tool, tool.replace(/_/g, " ")])[1]),
            h("td", {}, g.present ? Math.round(g.present.mean) : "–"),
            h("td", {}, h("strong", {}, g.future ? Math.round(g.future.mean) : "–")),
            h("td", { class: "muted" }, g.future && g.future.n > 1 ? `${g.future.min}–${g.future.max}` : "")))),
          c.ofp ? h("tfoot", {}, h("tr", {}, h("td", {}, h("strong", {}, "OFP")), h("td", {}), h("td", {}, h("strong", {}, Math.round(c.ofp))), h("td", {}))) : null)));
  }
  fill(el, 
    h("button", { class: "btn primary block write", style: "margin-top:8px", onclick: () => reportForm(p) }, "+ New scouting report"),
    ...sections,
    h("h2", {}, "Reports"),
    reports.length
      ? h("ul", { class: "list" }, reports.map((r) => h("li", { class: "card" },
          h("div", { class: "row" },
            h("strong", {}, `${r.report_date} · ${r.scout_name}`),
            h("span", { style: "flex:none", class: "badge" }, r.ofp ? `OFP ${Math.round(r.ofp)}` : r.report_type)),
          h("div", { class: "small ink2" }, [r.level_seen && levelName(r.level_seen), r.event, r.role_projection, r.risk && `${r.risk} risk`].filter(Boolean).join(" · ")),
          r.summary ? h("p", {}, r.summary) : null,
          r.strengths ? h("p", { class: "small" }, h("strong", {}, "Strengths: "), r.strengths) : null,
          r.weaknesses ? h("p", { class: "small" }, h("strong", {}, "Weaknesses: "), r.weaknesses) : null,
          Object.keys(r.measurables || {}).length ? h("p", { class: "small muted" }, Object.entries(r.measurables).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")) : null)))
      : h("p", { class: "muted" }, "No reports yet.")
  );
}

function reportForm(p) {
  let type = reportType(p);
  const toolsBox = h("div");
  const measBox = h("div");
  const renderTools = () => {
    fill(toolsBox, 
      h("div", { class: "grid3 small muted", style: "margin-bottom:4px" }, h("span", {}, "Tool"), h("span", {}, "Present"), h("span", {}, "Future")),
      TOOLS[type].map(([k, l]) => h("div", { class: "grid3", style: "margin-bottom:6px;align-items:center" },
        h("span", {}, l),
        select(`present.${k}`, GRADES, "", { class: "input", "aria-label": `${l} present` }),
        select(`future.${k}`, GRADES, "", { class: "input", "aria-label": `${l} future` }))));
    fill(measBox, h("div", { class: "grid2" },
      MEASURABLES[type].map(([k, l]) => field(l, input(`m.${k}`, { type: "number", inputmode: "decimal", step: "0.01" })))));
  };
  const typeSel = select("report_type", [["hitter", "Hitter"], ["pitcher", "Pitcher"]], type);
  typeSel.addEventListener("change", () => { type = typeSel.value; renderTools(); });
  renderTools();
  const form = h("form", { class: "stack" },
    h("div", { class: "grid2" },
      field("Scout", input("scout_name", { required: true, value: store.get("scoutName", ""), autocomplete: "name" })),
      field("Date", input("report_date", { type: "date", required: true, value: fmt.today() }))),
    h("div", { class: "grid2" },
      field("Report type", typeSel),
      field("Level seen", select("level_seen", [["", "–"], ...LEVELS.map((l) => [l.code, l.name])], p.current_level))),
    field("Event", input("event", { placeholder: "Game, showcase, workout, video…" })),
    h("h3", {}, "Tool grades (20–80)"), toolsBox,
    h("div", { class: "grid3" },
      field("OFP", select("ofp", GRADES, "")),
      field("Projectability", select("projectability", GRADES, "")),
      field("Makeup", select("makeup", GRADES, ""))),
    h("div", { class: "grid2" },
      field("Risk", select("risk", ["", "low", "medium", "high", "extreme"], "")),
      field("Role", input("role_projection", { placeholder: "e.g. everyday SS" }))),
    h("details", {}, h("summary", {}, "Measurables"), measBox),
    field("Physical", h("textarea", { name: "physical_description" })),
    field("Strengths", h("textarea", { name: "strengths" })),
    field("Weaknesses", h("textarea", { name: "weaknesses" })),
    field("Summary", h("textarea", { name: "summary" })),
    h("button", { class: "btn primary block", type: "submit" }, "Save report"));
  const close = openSheet("New scouting report", form);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const raw = formData(form);
    const body = { tool_grades: {}, measurables: {} };
    for (const [k, v] of Object.entries(raw)) {
      const [a, b] = k.split(".");
      if (b && (a === "present" || a === "future")) (body.tool_grades[b] = body.tool_grades[b] || {})[a] = Number(v);
      else if (b && a === "m") body.measurables[b] = Number(v);
      else body[k] = ["ofp", "projectability", "makeup"].includes(k) ? Number(v) : v;
    }
    store.set("scoutName", body.scout_name);
    try {
      await busy(form.querySelector("button[type=submit]"), api(`/players/${p.id}/scouting-reports`, { method: "POST", json: body }));
      close();
      toast("Report saved");
      route();
    } catch (err) { toast(err.message, 5000); }
  });
}

// ---------------------------------------------------------------- stats

const HIT_FIELDS = ["pa", "ab", "h", "2b", "3b", "hr", "bb", "so", "hbp", "sf", "sb", "cs"];
const PIT_FIELDS = ["ip", "bf", "h", "er", "bb", "so", "hr", "hbp", "g", "gs"];

async function statsTab(el, prof) {
  const p = prof.player;
  const lines = await api(`/players/${p.id}/stats`);
  const hit = lines.filter((l) => l.kind === "hitting");
  const pit = lines.filter((l) => l.kind === "pitching");
  const label = (l) => h("td", {}, h("div", {}, `${l.season} ${short(l.level)}`), h("div", { class: "small muted" }, l.team || ""));
  fill(el, 
    h("button", { class: "btn primary block write", style: "margin-top:8px", onclick: () => statForm(p) }, "+ Add season"),
    hit.length ? [h("h2", {}, "Hitting"), h("div", { class: "card table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Season", "PA", "AVG", "OBP", "SLG", "ISO", "K%", "BB%", "wOBA"].map((x) => h("th", {}, x)))),
      h("tbody", {}, hit.map((l) => h("tr", {}, label(l), h("td", {}, l.rates.pa),
        ["avg", "obp", "slg", "iso"].map((k) => h("td", {}, fmt.rate(l.rates[k]))),
        h("td", {}, fmt.pct(l.rates.k_pct)), h("td", {}, fmt.pct(l.rates.bb_pct)), h("td", {}, fmt.rate(l.rates.woba)))))))] : null,
    pit.length ? [h("h2", {}, "Pitching"), h("div", { class: "card table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Season", "IP", "ERA", "FIP", "WHIP", "K%", "BB%", "K-BB%"].map((x) => h("th", {}, x)))),
      h("tbody", {}, pit.map((l) => h("tr", {}, label(l), h("td", {}, fmt.n(l.rates.ip)), h("td", {}, fmt.n(l.rates.era, 2)),
        h("td", {}, fmt.n(l.rates.fip, 2)), h("td", {}, fmt.n(l.rates.whip, 2)),
        h("td", {}, fmt.pct(l.rates.k_pct)), h("td", {}, fmt.pct(l.rates.bb_pct)), h("td", {}, fmt.pct(l.rates.k_minus_bb_pct)))))))] : null,
    !lines.length ? h("p", { class: "muted" }, "No stats yet.") : null
  );
}

function statForm(p) {
  let kind = p.player_type === "pitcher" ? "pitching" : "hitting";
  const box = h("div");
  const render = () => fill(box, h("div", { class: "grid3" },
    (kind === "hitting" ? HIT_FIELDS : PIT_FIELDS).map((k) => field(k.toUpperCase(),
      input(`s.${k}`, { type: k === "ip" ? "text" : "number", inputmode: "decimal", placeholder: k === "ip" ? "e.g. 42.1" : "" })))));
  const kindSel = select("kind", [["hitting", "Hitting"], ["pitching", "Pitching"]], kind);
  kindSel.addEventListener("change", () => { kind = kindSel.value; render(); });
  render();
  const form = h("form", { class: "stack" },
    h("div", { class: "grid2" },
      field("Season", input("season", { type: "number", required: true, value: new Date().getFullYear(), inputmode: "numeric" })),
      field("Kind", kindSel)),
    field("Level", select("level", LEVELS.map((l) => [l.code, l.name]), p.current_level, { required: true })),
    field("Team", input("team", { value: p.current_team || "" })),
    box,
    h("button", { class: "btn primary block", type: "submit" }, "Save season"));
  const close = openSheet("Add season", form);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const raw = formData(form);
    const body = { stats: {} };
    for (const [k, v] of Object.entries(raw)) {
      if (k.startsWith("s.")) body.stats[k.slice(2)] = k === "s.ip" ? v : Number(v);
      else body[k] = v;
    }
    try {
      await busy(form.querySelector("button[type=submit]"), api(`/players/${p.id}/stats`, { method: "POST", json: body }));
      close();
      toast("Season saved");
      route();
    } catch (err) { toast(err.message, 5000); }
  });
}

// ---------------------------------------------------------------- tracking

async function trackingTab(el, prof) {
  const p = prof.player;
  const t = prof.tracking;
  const pi = t.pitching;
  const hi = t.hitting;
  let sources = [];
  try { sources = await api("/integrations"); } catch { /* offline */ }
  const file = h("input", { type: "file", name: "file", accept: ".csv,.json,text/csv,application/json", required: true, class: "input" });
  const form = h("form", { class: "stack" },
    field("Export file", file),
    field("Source", select("source", [["", "Detect automatically"], ...sources.filter((x) => x.name !== "generic").map((x) => [x.name, x.description])], "")),
    h("label", { class: "row small" }, h("input", { type: "checkbox", name: "only_this", checked: true, style: "flex:none;width:20px;height:20px" }),
      h("span", {}, `Every row belongs to ${p.first_name} (Rapsodo, Blast and similar per-athlete exports)`)),
    h("button", { class: "btn primary block", type: "submit" }, "Import"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData();
    fd.append("file", file.files[0]);
    const src = form.elements.source.value;
    if (src) fd.append("source", src);
    if (form.elements.only_this.checked) fd.append("player_id", p.id);
    try {
      const r = await busy(form.querySelector("button[type=submit]"), api("/integrations/import", { method: "POST", form: fd }));
      toast(`Imported ${r.events} events from ${r.source} (${r.matched} matched)`, 4000);
      route();
    } catch (err) { toast(err.message, 5000); }
  });
  fill(el, 
    h("p", { class: "small ink2" }, t.sources.length ? `Sources: ${t.sources.join(", ")} · ${t.event_counts.pitches} pitches, ${t.event_counts.batted_balls} batted balls, ${t.event_counts.swings} swings` : "No tracking data yet."),
    pi ? [
      h("h2", {}, "Pitching"),
      h("div", { class: "tiles" },
        tile(fmt.n(pi.fb_velo_avg), "FB velo avg"), tile(fmt.n(pi.fb_velo_max), "FB velo max"), tile(fmt.n(pi.fb_ivb_avg), "FB IVB (in)"),
        tile(fmt.pct(pi.zone_pct, 0), "Zone %"), tile(fmt.n(pi.extension_avg, 2), "Extension (ft)"), tile(fmt.n(pi.release_height_avg, 2), "Release ht (ft)")),
      h("h3", {}, "Arsenal"),
      h("div", { class: "card table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ["Pitch", "Use", "Velo", "Max", "Spin", "IVB", "HB", "Whiff"].map((x) => h("th", {}, x)))),
        h("tbody", {}, Object.entries(pi.arsenal).map(([pt, a]) => h("tr", {}, h("td", {}, PITCH_NAMES[pt] || pt), h("td", {}, fmt.pct(a.usage, 0)),
          h("td", {}, fmt.n(a.velo_avg)), h("td", {}, fmt.n(a.velo_max)), h("td", {}, fmt.n(a.spin_avg, 0)), h("td", {}, fmt.n(a.ivb_avg)), h("td", {}, fmt.n(a.hb_avg)),
          h("td", {}, fmt.pct(a.whiff_pct, 0)))))))] : null,
    hi ? [
      h("h2", {}, "Hitting"),
      h("div", { class: "tiles" },
        tile(fmt.n(hi.ev_avg), "EV avg"), tile(fmt.n(hi.ev_90th), "EV 90th pct"), tile(fmt.n(hi.ev_max), "EV max"),
        tile(fmt.pct(hi.hard_hit_pct, 0), "Hard-hit %"), tile(fmt.pct(hi.barrel_pct, 0), "Barrel %"), tile(fmt.n(hi.la_avg), "Launch angle"),
        tile(fmt.pct(hi.sweet_spot_pct, 0), "Sweet spot %"), tile(fmt.n(hi.bat_speed_avg), "Bat speed"), tile(fmt.n(hi.attack_angle_avg), "Attack angle"))] : null,
    h("div", { class: "write" },
      h("h2", {}, "Import device data"),
      h("p", { class: "small ink2" }, "TrackMan, Rapsodo, HitTrax, Hawk-Eye/Statcast, Blast and TrackMan-format exports."),
      h("div", { class: "card" }, form))
  );
}

// ---------------------------------------------------------------- mechanics

async function mechanicsTab(el, prof) {
  const p = prof.player;
  const list = await api(`/players/${p.id}/analyses`);
  const motionDefault = p.player_type === "pitcher" ? "pitching" : "hitting";
  const file = h("input", { type: "file", accept: "video/*", capture: "environment", required: true, class: "input" });
  const form = h("form", { class: "stack" },
    field("Video", file),
    field("Motion", select("motion_type", [["pitching", "Pitching"], ["hitting", "Hitting"]], motionDefault)),
    field("Camera", select("camera_view", [["open_side", "Side view (open side)"], ["closed_side", "Side view (closed side)"], ["behind", "Behind"], ["front", "Front"]], "open_side")),
    h("p", { class: "small muted" }, "Best results: slow-motion (120–240 fps), whole body in frame, phone held still, camera side-on to the throw or swing."),
    h("button", { class: "btn primary block", type: "submit" }, "Upload & analyze"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData();
    fd.append("file", file.files[0]);
    fd.append("motion_type", form.elements.motion_type.value);
    fd.append("camera_view", form.elements.camera_view.value);
    fd.append("recorded_on", fmt.today());
    try {
      const r = await busy(form.querySelector("button[type=submit]"), api(`/players/${p.id}/videos`, { method: "POST", form: fd }));
      toast("Uploaded. Analysis is running…", 4000);
      pollAnalysis(r.analysis_id, p);
      route();
    } catch (err) { toast(err.message, 5000); }
  });

  fill(el, 
    h("details", { class: "card write", open: list.length ? null : true }, h("summary", {}, "Upload a video"), form),
    h("h2", {}, "Analyses"),
    list.length
      ? h("ul", { class: "list" }, list.map((a) => h("li", {}, h("button", { class: "list-item", style: "width:100%;text-align:left;cursor:pointer", onclick: () => analysisDetail(a.id, list, p) },
          h("div", { class: "grow" },
            h("div", { class: "name" }, [a.motion_type === "pitching" ? "Pitching" : "Hitting", a.recorded_on].filter(Boolean).join(" · ")),
            h("div", { class: "small ink2" }, a.status === "done" ? (a.scores.top_priorities || []).join(" · ") || "No major flags" : a.status === "failed" ? "Analysis failed" : "Processing…")),
          a.status === "done" ? h("span", { class: "score", style: "font-size:1.5rem" }, Math.round(a.scores.mechanics_score)) : h("span", { class: "badge" }, a.status),
          h("span", { class: "chev", "aria-hidden": "true" }, "›")))))
      : h("p", { class: "muted" }, "No analyses yet.")
  );
}

function pollAnalysis(id, p, tries = 0) {
  setTimeout(async () => {
    try {
      const a = await api(`/analyses/${id}`);
      if (a.status === "done") { toast(`Analysis ready: mechanics score ${Math.round(a.scores.mechanics_score)}`, 4000); if (location.hash.includes(`/players/${p.id}/mechanics`)) route(); return; }
      if (a.status === "failed") { toast(`Analysis failed: ${a.error}`, 6000); if (location.hash.includes(`/players/${p.id}/mechanics`)) route(); return; }
    } catch { /* keep polling */ }
    if (tries < 120) pollAnalysis(id, p, tries + 1);
  }, 4000);
}

async function analysisDetail(id, list, p) {
  const a = await api(`/analyses/${id}`);
  if (a.status !== "done") {
    openSheet("Analysis", h("p", {}, a.status === "failed" ? `Failed: ${a.error}` : "Still processing. Check back in a minute."));
    return;
  }
  const sc = a.scores;
  const items = [...a.feedback].sort((x, y) => ({ flag: 0, watch: 1, optimal: 2, unavailable: 3 }[x.status] - { flag: 0, watch: 1, optimal: 2, unavailable: 3 }[y.status]) || y.priority - x.priority);
  const older = list.filter((x) => x.id !== a.id && x.motion_type === a.motion_type && x.status === "done");
  const compareSel = older.length ? select("cmp", [["", "Compare with…"], ...older.map((x) => [x.id, `${x.recorded_on || "#" + x.id} (score ${Math.round(x.scores.mechanics_score)})`])], "", { class: "input" }) : null;
  const cmpBox = h("div");
  if (compareSel) compareSel.addEventListener("change", async () => {
    if (!compareSel.value) return fill(cmpBox);
    const c = await api(`/analyses/${compareSel.value}/compare/${a.id}`);
    fill(cmpBox, 
      h("p", {}, `Score ${fmt.n(c.mechanics_score.before, 0)} → ${fmt.n(c.mechanics_score.after, 0)}`),
      c.improved.length ? h("p", { class: "small" }, h("strong", {}, "Improved: "), c.improved.map(metricLabel(a)).join(", ")) : null,
      c.regressed.length ? h("p", { class: "small" }, h("strong", {}, "Regressed: "), c.regressed.map(metricLabel(a)).join(", ")) : null,
      h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Metric"), h("th", {}, "Before"), h("th", {}, "After"), h("th", {}, "Δ"))),
        h("tbody", {}, Object.entries(c.metrics).filter(([k]) => a.feedback.some((i) => i.metric === k)).map(([k, m]) =>
          h("tr", {}, h("td", {}, metricLabel(a)(k)), h("td", {}, m.before), h("td", {}, m.after), h("td", {}, (m.change > 0 ? "+" : "") + m.change)))))));
  });
  openSheet(`${a.motion_type === "pitching" ? "Pitching" : "Hitting"} mechanics`, h("div", { class: "stack" },
    h("div", { class: "row" },
      h("div", {}, h("div", { class: "score" }, Math.round(sc.mechanics_score)), h("div", { class: "small muted" }, `Mechanics score · ${sc.level_band} targets`)),
      sc.arm_stress ? h("div", {}, h("div", { class: "small muted" }, "Arm-stress screen"), h("span", { class: `status ${{ low: "optimal", moderate: "watch", elevated: "flag" }[sc.arm_stress]}` }, sc.arm_stress)) : null),
    (sc.warnings || []).map((w) => h("p", { class: "small", style: "color:var(--serious)" }, w)),
    sc.arm_stress_detail ? h("p", { class: "small muted" }, sc.arm_stress_detail.note) : null,
    compareSel, cmpBox,
    h("ul", { class: "list" }, items.map((i) => h("li", { class: "card" },
      h("div", { class: "row" }, h("strong", {}, i.label), h("span", { style: "flex:none", class: `status ${i.status}` }, i.status === "optimal" ? "Optimal" : i.status === "watch" ? "Watch" : i.status === "flag" ? "Fix" : "N/A")),
      i.value !== null && typeof i.value !== "boolean"
        ? h("div", { class: "small ink2 num" }, `${i.value} ${i.unit}`, i.optimal ? h("span", { class: "muted" }, ` · target ${i.optimal[0]}–${i.optimal[1]}`) : null)
        : null,
      i.status !== "optimal" && i.status !== "unavailable" ? h("p", { style: "margin:6px 0" }, i.message) : null,
      i.drills && i.drills.length ? h("details", {}, h("summary", { class: "small" }, "Drills"), h("ul", {}, i.drills.map((d) => h("li", { class: "small" }, d)))) : null,
      h("details", {}, h("summary", { class: "small" }, "Why it matters"), h("p", { class: "small ink2" }, i.why)))))));
}
const metricLabel = (a) => (k) => (a.feedback.find((i) => i.metric === k) || { label: k }).label;
const PITCH_NAMES = { FF: "Four-seam", SI: "Sinker", FC: "Cutter", SL: "Slider", ST: "Sweeper", SV: "Slurve", CU: "Curveball", KC: "Knuckle-curve", CH: "Changeup", FS: "Splitter", KN: "Knuckleball", UN: "Unknown" };

// ---------------------------------------------------------------- projection

const REF_LEVELS = ["MLB", "AAA", "AA", "A_PLUS", "A", "ROOKIE", "NCAA_D1", "NCAA_D2", "JUCO", "HS"];

async function projectionTab(el, prof) {
  const p = prof.player;
  const hist = await api(`/players/${p.id}/projections`);
  const out = h("div");
  const prefs = store.get("projPrefs", { years: 6, pathway: "auto" });
  const yearsSel = select("years", [3, 4, 5, 6, 8, 10, 12], prefs.years, { class: "input", "aria-label": "Years to project" });
  const pathSel = select("pathway", [["auto", "Best available path"], ["college", "Four-year college"], ["juco", "Junior college"], ["pro", "Turn pro"]], prefs.pathway, { class: "input", "aria-label": "Pathway" });
  const typeSel = p.player_type === "two_way" ? select("as_type", [["hitter", "As hitter"], ["pitcher", "As pitcher"]], "hitter", { class: "input" }) : null;
  const run = h("button", { class: "btn primary block", onclick: async () => {
    const body = { years: +yearsSel.value, pathway: pathSel.value };
    if (typeSel) body.as_type = typeSel.value;
    store.set("projPrefs", body);
    try {
      const r = await busy(run, api(`/players/${p.id}/projections`, { method: "POST", json: body }));
      renderProjection(out, r);
      toast("Projection updated");
    } catch (e) { toast(e.message, 5000); }
  } }, hist.length ? "Re-run projection" : "Run projection");
  fill(el, 
    h("div", { class: "card stack write" }, h("div", { class: "row" }, yearsSel, pathSel, typeSel), run,
      h("p", { class: "small muted", style: "margin:0" }, "Uses every stat line, scouting report, tracking session and mechanics analysis on file.")),
    out);
  if (hist.length) renderProjection(out, await api(`/projections/${hist[hist.length - 1].id}`));
}

function renderProjection(el, r) {
  const o = r.outcomes;
  let yearIdx = Math.min(3, r.years.length - 1);
  const levelTable = h("div");
  const yearChips = h("div", { class: "chips", role: "group", "aria-label": "Projection year" },
    r.years.map((y, i) => h("button", { class: "chip", "aria-pressed": String(i === yearIdx), onclick: (e) => {
      yearIdx = i;
      yearChips.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c === e.target)));
      drawLevelTable();
    } }, i === 0 ? `Now (${Math.round(y.age)})` : `+${i} yr (${Math.round(y.age)})`)));
  const drawLevelTable = () => fill(levelTable, statsByLevelTable(r, r.years[yearIdx]));
  drawLevelTable();

  const comps = Object.entries(r.current_talent.components);
  fill(el, 
    h("h2", {}, "Outlook"),
    h("div", { class: "card" }, h("p", { style: "margin-top:0" }, r.summary),
      h("div", { class: "tiles" },
        tile(Math.round(r.current_talent.overall), "Current talent"),
        tile(Math.round(o.peak_talent.median), "Projected peak"),
        tile(fmt.pct(o.probability_reach_pro_level.MLB || 0, 0), "Reach MLB"),
        tile(o.risk, "Risk"))),
    h("h2", {}, "Overall talent by age"),
    h("p", { class: "small ink2" }, "Line: most likely. Band: 80% range (10th–90th percentile). Dashed lines mark the average player at each level."),
    fanChart(r),
    h("h2", {}, "Chance to reach each pro level"),
    h("p", { class: "small ink2" }, `Within ${r.years.length - 1} years.`),
    bars(Object.entries(o.probability_reach_pro_level).map(([k, v]) => [short(k), v])),
    h("h2", {}, "Career outcome mix"),
    h("p", { class: "small ink2" }, "Based on projected peak talent."),
    bars(o.tier_probabilities.map((t) => [t.tier, t.probability])),
    h("h2", {}, "Projected stat lines by level"),
    yearChips,
    levelTable,
    h("h2", {}, "Where the estimate comes from"),
    h("div", { class: "card" }, comps.map(([name, c]) => h("details", {},
      h("summary", {}, `${name.replace(/_/g, " ")}: ${Math.round(c.talent)} ± ${Math.round(c.sd)}`),
      h("div", { class: "bars small" }, c.sources.map((src) => [
        h("span", { class: "lab" }, src.source),
        h("div", { class: "track" }, h("div", { class: "fill", style: `width:${Math.max(2, src.weight * 100)}%` })),
        h("span", { class: "val" }, `${Math.round(src.weight * 100)}% → ${Math.round(src.estimate)}`),
      ])),
      h("ul", { class: "small muted" }, c.sources.filter((x) => x.detail).map((x) => h("li", {}, x.detail))),
      (r.growth_multipliers[name] || { reasons: [] }).reasons.length
        ? h("p", { class: "small" }, h("strong", {}, `Growth ×${r.growth_multipliers[name].multiplier}: `), r.growth_multipliers[name].reasons.join("; "))
        : null))),
    h("p", { class: "small muted" }, r.assumptions.note)
  );
}

function bars(rows) {
  return h("div", { class: "card bars", role: "table", style: "grid-template-columns: minmax(0, 46%) 1fr auto" }, rows.map(([label, v]) => [
    h("span", { class: "lab", role: "cell" }, label),
    h("div", { class: "track", role: "presentation", title: `${label}: ${fmt.pct(v, 0)}` }, h("div", { class: "fill", style: `width:${Math.max(0.5, v * 100)}%` })),
    h("span", { class: "val", role: "cell" }, fmt.pct(v, 0)),
  ]));
}

function statsByLevelTable(r, y) {
  const lv = y.projected_by_level;
  const hitter = r.player_type === "hitter";
  const cols = hitter
    ? [["avg", "AVG", fmt.rate], ["obp", "OBP", fmt.rate], ["slg", "SLG", fmt.rate], ["k_pct", "K%", (x) => fmt.pct(x, 0)], ["bb_pct", "BB%", (x) => fmt.pct(x, 0)], ["woba", "wOBA", fmt.rate]]
    : [["k_pct", "K%", (x) => fmt.pct(x, 0)], ["bb_pct", "BB%", (x) => fmt.pct(x, 0)], ["k_minus_bb_pct", "K-BB%", (x) => fmt.pct(x, 0)], ["hr_pct", "HR%", (x) => fmt.pct(x, 1)], ["era_fip_est", "ERA est", (x) => fmt.n(x, 2)]];
  const key = hitter ? "woba" : "era_fip_est";
  const keyFmt = hitter ? fmt.rate : (x) => fmt.n(x, 2);
  return h("div", { class: "card table-wrap" },
    h("p", { class: "small ink2", style: "margin-top:0" }, `Age ${y.age}: most likely at ${levelName(y.most_likely_level)}. Medians shown; the last column is the 80% range.`),
    h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Level"), cols.map(([, l]) => h("th", {}, l)), h("th", {}, `${hitter ? "wOBA" : "ERA"} range`))),
      h("tbody", {}, Object.entries(lv).reverse().map(([code, line]) => h("tr", { style: code === y.most_likely_level ? "font-weight:700" : null },
        h("td", {}, short(code), code === y.most_likely_level ? " ★" : ""),
        cols.map(([k, , f]) => h("td", {}, f(line[k].median))),
        h("td", { class: "muted" }, `${keyFmt(line[key].p10)}–${keyFmt(line[key].p90)}`))))));
}

function fanChart(r) {
  const ys = r.years;
  const W = 400, H = 250, m = { l: 26, r: 62, t: 14, b: 26 };
  const lo = Math.floor(Math.min(...ys.map((y) => y.overall_talent.p10)) - 2);
  const hi = Math.ceil(Math.max(...ys.map((y) => y.overall_talent.p90)) + 2);
  const x = (i) => m.l + (ys.length === 1 ? 0 : (i / (ys.length - 1)) * (W - m.l - m.r));
  const y = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Projected overall talent from age ${ys[0].age} to ${ys[ys.length - 1].age}` });

  for (let t = Math.ceil(lo / 5) * 5; t <= hi; t += 5) {
    svg.append(s("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), stroke: "var(--grid)", "stroke-width": 1 }),
      s("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end", "font-size": 11, fill: "var(--muted)", class: "num" }, t));
  }
  let lastLabelY = -99;
  for (const code of REF_LEVELS) {
    const L = (LEVELS || []).find((l) => l.code === code);
    if (!L || L.talent_mean < lo || L.talent_mean > hi) continue;
    const yy = y(L.talent_mean);
    svg.append(s("line", { x1: m.l, x2: W - m.r, y1: yy, y2: yy, stroke: "var(--axis)", "stroke-width": 1, "stroke-dasharray": "3 4" }));
    if (Math.abs(yy - lastLabelY) >= 13) {
      svg.append(s("text", { x: W - m.r + 6, y: yy + 4, "font-size": 11, fill: "var(--muted)" }, short(code)));
      lastLabelY = yy;
    }
  }
  const band = ys.map((d, i) => `${x(i)},${y(d.overall_talent.p90)}`).concat(ys.map((d, i) => `${x(i)},${y(d.overall_talent.p10)}`).reverse());
  svg.append(s("polygon", { points: band.join(" "), fill: "var(--band)" }));
  svg.append(s("polyline", { points: ys.map((d, i) => `${x(i)},${y(d.overall_talent.median)}`).join(" "), fill: "none", stroke: "var(--series-1)", "stroke-width": 2, "stroke-linejoin": "round" }));
  ys.forEach((d, i) => svg.append(s("circle", { cx: x(i), cy: y(d.overall_talent.median), r: 4, fill: "var(--series-1)", stroke: "var(--surface)", "stroke-width": 2 })));
  ys.forEach((d, i) => svg.append(s("text", { x: x(i), y: H - 8, "text-anchor": "middle", "font-size": 11, fill: "var(--muted)", class: "num" }, Math.round(d.age))));
  const last = ys[ys.length - 1];
  svg.append(s("text", { x: x(ys.length - 1) - 8, y: y(last.overall_talent.median) - 10, "text-anchor": "end", "font-size": 12, "font-weight": 600, fill: "var(--ink)" }, Math.round(last.overall_talent.median)));

  const cross = s("line", { y1: m.t, y2: H - m.b, stroke: "var(--ink-2)", "stroke-width": 1, visibility: "hidden" });
  const hot = s("rect", { x: m.l - 10, y: 0, width: W - m.l - m.r + 20, height: H, fill: "transparent", style: "cursor:crosshair" });
  svg.append(cross, hot);
  const tip = h("div", { class: "tip", hidden: true });
  const wrap = h("div", { class: "card chart" }, svg, tip);
  const show = (evt) => {
    const box = svg.getBoundingClientRect();
    const px = ((evt.clientX - box.left) / box.width) * W;
    const i = Math.max(0, Math.min(ys.length - 1, Math.round(((px - m.l) / (W - m.l - m.r)) * (ys.length - 1))));
    const d = ys[i];
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    const top = d.level_distribution[0];
    fill(tip, 
      h("div", { class: "muted" }, `Age ${d.age}${i === 0 ? " (now)" : ""}`),
      h("div", {}, h("strong", {}, Math.round(d.overall_talent.median)), ` talent · range ${Math.round(d.overall_talent.p10)}–${Math.round(d.overall_talent.p90)}`),
      h("div", {}, `Likely ${short(top.level)} (${fmt.pct(top.probability, 0)})`));
    tip.hidden = false;
    const left = (x(i) / W) * box.width;
    tip.style.left = `${Math.min(Math.max(0, left - 70), box.width - 160)}px`;
    tip.style.top = "4px";
  };
  hot.addEventListener("pointermove", show);
  hot.addEventListener("pointerdown", show);
  hot.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); });

  const table = h("div", { class: "table-wrap", hidden: true }, h("table", {},
    h("thead", {}, h("tr", {}, ["Age", "10th", "Median", "90th", "Most likely level"].map((t) => h("th", {}, t)))),
    h("tbody", {}, ys.map((d) => h("tr", {}, h("td", {}, d.age), h("td", {}, d.overall_talent.p10), h("td", {}, d.overall_talent.median),
      h("td", {}, d.overall_talent.p90), h("td", {}, `${short(d.most_likely_level)} (${fmt.pct(d.level_distribution[0].probability, 0)})`))))));
  wrap.append(h("button", { class: "chip", style: "margin-top:8px", onclick: (e) => { table.hidden = !table.hidden; e.target.textContent = table.hidden ? "Show table" : "Hide table"; } }, "Show table"), table);
  return wrap;
}

// ---------------------------------------------------------------- games

async function gamesView() {
  setTitle("Games");
  let games = [];
  try { games = await api("/games"); store.set("games", games); } catch { games = store.get("games", []); toast("Offline: showing saved games"); }
  fill($view, 
    games.length
      ? h("ul", { class: "list cards" }, games.map((g) => h("li", {}, h("div", { class: "list-item" },
          h("a", { class: "grow", href: `#/games/${g.id}`, style: "color:inherit;text-decoration:none" },
            h("div", { class: "name" }, `${g.away_team} @ ${g.home_team}`),
            h("div", { class: "small ink2" }, [g.game_date, g.level && short(g.level), g.location].filter(Boolean).join(" · "))),
          h("a", { class: "btn primary write", style: "flex:none;min-height:40px", href: `#/games/${g.id}/chart` }, "Chart")))))
      : h("p", { class: "muted" }, "No games yet. Create one to start charting pitches."),
    h("a", { class: "btn primary fab write", href: "#/games/new" }, "+ New game"));
}

async function gameForm() {
  setTitle("New game");
  await levels();
  const form = h("form", { class: "stack" },
    field("Date", input("game_date", { type: "date", required: true, value: fmt.today() })),
    h("div", { class: "grid2" },
      field("Away team", input("away_team", { required: true })),
      field("Home team", input("home_team", { required: true }))),
    field("Level", select("level", [["", "–"], ...LEVELS.map((l) => [l.code, l.name])], store.get("lastLevel", ""))),
    field("Location", input("location")),
    field("Scout", input("scout_name", { value: store.get("scoutName", "") })),
    field("Weather / conditions", input("weather")),
    h("button", { class: "btn primary block", type: "submit" }, "Create & start charting"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = formData(form);
    store.set("lastLevel", body.level || "");
    if (body.scout_name) store.set("scoutName", body.scout_name);
    try {
      const g = await busy(form.querySelector("button[type=submit]"), api("/games", { method: "POST", json: body }));
      location.replace(`#/games/${g.id}/chart`);
    } catch (err) { toast(err.message, 5000); }
  });
  fill($view, form);
}

async function gameSummaryView(id) {
  const sm = await api(`/games/${id}/summary`);
  setTitle(sm.matchup);
  const pitcherCards = Object.entries(sm.pitchers).map(([name, l]) => h("div", { class: "card" },
    h("h3", { style: "margin-top:0" }, name),
    h("div", { class: "tiles" },
      tile(l.pitches, "Pitches"), tile(l.batters_faced, "Batters"), tile(`${l.strikeouts} / ${l.walks}`, "K / BB"), tile(l.hits, "Hits"),
      tile(fmt.pct(l.strike_pct, 0), "Strike %"), tile(fmt.pct(l.first_pitch_strike_pct, 0), "1st-pitch strike %"), tile(fmt.pct(l.csw_pct, 0), "CSW %"), tile(fmt.pct(l.whiff_pct, 0), "Whiff %")),
    h("div", { class: "table-wrap", style: "margin-top:10px" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Pitch", "#", "Use", "Velo", "Range", "Strike", "Whiff"].map((t) => h("th", {}, t)))),
      h("tbody", {}, Object.entries(l.pitch_mix).map(([pt, x]) => h("tr", {}, h("td", {}, PITCH_NAMES[pt] || pt), h("td", {}, x.count), h("td", {}, fmt.pct(x.usage, 0)),
        h("td", {}, fmt.n(x.velo_avg)), h("td", {}, x.velo_min ? `${fmt.n(x.velo_min)}–${fmt.n(x.velo_max)}` : "–"), h("td", {}, fmt.pct(x.strike_pct, 0)), h("td", {}, fmt.pct(x.whiff_pct, 0))))))),
    Object.keys(l.fb_velo_by_inning).length ? h("p", { class: "small ink2" }, "Fastball velo by inning: ",
      Object.entries(l.fb_velo_by_inning).map(([inn, v]) => `${inn}: ${fmt.n(v.avg)} (max ${fmt.n(v.max)})`).join(" · ")) : null,
    l.time_to_plate_avg ? h("p", { class: "small ink2" }, `Time to plate: ${l.time_to_plate_avg}s`) : null));
  const batterRows = Object.entries(sm.batters).map(([name, b]) => h("tr", {}, h("td", {}, name), h("td", {}, b.plate_appearances), h("td", {}, b.pitches_seen),
    h("td", {}, fmt.pct(b.whiff_pct, 0)), h("td", {}, fmt.pct(b.chase_pct, 0)), h("td", {}, fmt.n(b.ev_max)), h("td", { style: "text-align:left" }, b.outcomes.join(", "))));
  fill($view, 
    h("p", { class: "ink2" }, `${sm.date} · ${sm.total_pitches} pitches charted`),
    h("a", { class: "btn primary block write", href: `#/games/${id}/chart` }, "Continue charting"),
    h("h2", {}, "Pitchers"), pitcherCards.length ? pitcherCards : h("p", { class: "muted" }, "No pitches yet."),
    batterRows.length ? [h("h2", {}, "Hitters"), h("div", { class: "card table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Hitter", "PA", "Pitches", "Whiff", "Chase", "Max EV", "Results"].map((t) => h("th", {}, t)))), h("tbody", {}, batterRows)))] : null,
    sm.notes.length ? [h("h2", {}, "Notes"), h("ul", { class: "list" }, sm.notes.map((n) => h("li", { class: "card small" }, h("strong", {}, `Inn ${n.inning || "–"} · ${n.category || "note"}: `), n.text)))] : null);
}

// ---------------------------------------------------------------- pitch charting

const PTYPES = ["FF", "SI", "FC", "SL", "ST", "CU", "CH", "FS"];
const RESULTS = [
  ["ball", "Ball", "ball"], ["called_strike", "Called strike", "strike"], ["swinging_strike", "Swinging strike", "strike"],
  ["foul", "Foul", ""], ["in_play", "In play", "inplay"], ["hit_by_pitch", "Hit by pitch", ""],
];
const IN_PLAY = [["out", "Out"], ["single", "Single"], ["double", "Double"], ["triple", "Triple"], ["home_run", "Home run"], ["error", "Error"],
  ["double_play", "Double play"], ["sac_fly", "Sac fly"], ["fielders_choice", "Fielder’s choice"]];
const OUTS_ON = { out: 1, strikeout: 1, double_play: 2, sac_fly: 1, fielders_choice: 1 };
// Statcast zone numbering from the catcher's view: 1-9 in the zone, 11-14 chase quadrants.
const ZONE_X = [-1.2, -0.47, 0, 0.47, 1.2];
const ZONE_Z = [4.0, 3.17, 2.5, 1.83, 1.0];

function zoneFor(r, c) {
  if (r >= 1 && r <= 3 && c >= 1 && c <= 3) return (r - 1) * 3 + c;
  // Outer ring: quadrants split at the zone's center (middle row/column cells go low/left).
  const top = r < 2;
  const left = c <= 2;
  return top ? (left ? 11 : 12) : (left ? 13 : 14);
}

/** Situation after a pitch, given the pitch's pre-pitch state and its result. */
function nextState(p) {
  const st = { inning: p.inning, top_bottom: p.top_bottom || "T", outs: p.outs || 0, balls: p.balls, strikes: p.strikes, pitcher: p.pitcher_name, pitcher_id: p.pitcher_id, batter: p.batter_name, batter_id: p.batter_id };
  let paOver = !!p.pa_outcome;
  if (!paOver) {
    if (p.result === "ball") st.balls++;
    else if (p.result === "foul") st.strikes = Math.min(2, st.strikes + 1);
    else if (["called_strike", "swinging_strike", "foul_tip"].includes(p.result)) st.strikes++;
  }
  if (paOver) {
    st.outs += OUTS_ON[p.pa_outcome] || 0;
    st.balls = 0; st.strikes = 0; st.batter = ""; st.batter_id = null;
    if (st.outs >= 3) {
      st.outs = 0;
      if (st.top_bottom === "T") st.top_bottom = "B"; else { st.top_bottom = "T"; st.inning++; }
      st.pitcher = ""; st.pitcher_id = null; // the other team's pitcher is up next
      st.halfChanged = true;
    }
  }
  return st;
}

/** Decide the plate-appearance outcome a result implies (strikeout / walk / HBP), or null. */
function impliedOutcome(st, result) {
  if (result === "ball" && st.balls === 3) return "walk";
  if (["called_strike", "swinging_strike", "foul_tip"].includes(result) && st.strikes === 2) return "strikeout";
  if (result === "hit_by_pitch") return "hbp";
  return null;
}

async function chartView(gameId) {
  if (ME.role === "viewer") {
    setTitle("Chart");
    fill($view, h("p", { class: "ink2" }, "Your account is read-only, so it can't chart pitches. Game summaries are under Games."));
    return;
  }
  store.set("lastGame", gameId);
  let game, serverPitches, people;
  try {
    [game, serverPitches, people] = await Promise.all([
      api("/games").then((gs) => gs.find((g) => g.id === gameId)),
      api(`/games/${gameId}/pitches`),
      api("/players?limit=500"),
    ]);
    store.set(`game.${gameId}`, { game, serverPitches, people });
  } catch (e) {
    if (e instanceof ApiError) throw e;
    ({ game, serverPitches, people } = store.get(`game.${gameId}`, { game: null, serverPitches: [], people: [] }));
    toast("Offline: pitches will sync when you reconnect", 4000);
  }
  setTitle(game ? `${game.away_team} @ ${game.home_team}` : `Game ${gameId}`);
  queue.flush();

  const allPitches = () => serverPitches.concat(queue.forGame(gameId).map((q) => ({ ...q.body, pending: true })));
  const fresh = { inning: 1, top_bottom: "T", outs: 0, balls: 0, strikes: 0, pitcher: "", batter: "" };
  // Resume where this phone left off; otherwise rebuild the situation from the last charted pitch.
  const stateAfter = (last) => {
    if (!last) return { ...fresh };
    const next = { ...nextState(last), batter_side: last.pa_outcome ? "" : last.batter_side };
    delete next.halfChanged;
    return next;
  };
  let st = store.get(`chartState.${gameId}`, null) || stateAfter(allPitches()[allPitches().length - 1]);
  const draft = { pitch_type: store.get(`lastType.${gameId}`, "FF"), velocity: "", zone: null };

  const byName = (name) => people.find((x) => `${x.first_name} ${x.last_name}`.toLowerCase() === (name || "").trim().toLowerCase());
  const dl = h("datalist", { id: "people" }, people.map((x) => h("option", { value: `${x.first_name} ${x.last_name}` })));

  const situation = h("div", { class: "situation" });
  const pitcherIn = h("input", { class: "input", list: "people", placeholder: "Pitcher", value: st.pitcher || "", autocomplete: "off", "aria-label": "Pitcher" });
  const batterIn = h("input", { class: "input", list: "people", placeholder: "Batter", value: st.batter || "", autocomplete: "off", "aria-label": "Batter" });
  const sideSel = select("side", [["", "Bats"], ["R", "RHH"], ["L", "LHH"]], st.batter_side || "", { class: "input", style: "flex:0 0 92px", "aria-label": "Batter side" });
  pitcherIn.addEventListener("change", () => { st.pitcher = pitcherIn.value.trim(); persist(); drawMini(); });
  batterIn.addEventListener("change", () => {
    st.batter = batterIn.value.trim();
    const pl = byName(st.batter);
    if (pl && pl.bats && pl.bats !== "S") sideSel.value = pl.bats;
    persist();
  });
  sideSel.addEventListener("change", () => { st.batter_side = sideSel.value; persist(); });

  const ptypeBox = h("div", { class: "ptypes", role: "group", "aria-label": "Pitch type" }, PTYPES.map((t) =>
    h("button", { type: "button", "aria-pressed": String(draft.pitch_type === t), title: PITCH_NAMES[t], onclick: (e) => {
      draft.pitch_type = t;
      ptypeBox.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget)));
      veloIn.placeholder = lastVelo(t) || "mph";
    } }, t)));
  const lastVelo = (t) => {
    const ps = allPitches().filter((p) => p.pitch_type === t && p.velocity && p.pitcher_name === st.pitcher);
    return ps.length ? ps[ps.length - 1].velocity : null;
  };
  const veloIn = h("input", { type: "number", inputmode: "decimal", step: "0.1", class: "input", placeholder: lastVelo(draft.pitch_type) || "mph", "aria-label": "Velocity (mph)" });
  const bump = (d) => { const base = Number(veloIn.value || veloIn.placeholder) || 0; if (base) veloIn.value = (base + d).toFixed(0); };
  const zoneBox = h("div", { class: "zone", role: "group", "aria-label": "Pitch location, catcher's view" });
  for (let r = 0; r < 5; r++) for (let c = 0; c < 5; c++) {
    const z = zoneFor(r, c);
    const inside = z <= 9;
    zoneBox.append(h("button", { type: "button", class: inside ? "in" : "", "aria-pressed": "false", "aria-label": inside ? `Zone ${z}` : `Outside zone ${z}`,
      "data-r": r, "data-c": c, onclick: (e) => {
        const on = e.currentTarget.getAttribute("aria-pressed") !== "true";
        zoneBox.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
        e.currentTarget.setAttribute("aria-pressed", String(on));
        draft.zone = on ? { zone: z, x: ZONE_X[c], z: ZONE_Z[r] } : null;
      } }, inside ? z : ""));
  }
  const resultBox = h("div", { class: "results" }, RESULTS.map(([v, l, cls]) =>
    h("button", { type: "button", class: cls, onclick: () => record(v) }, l)));

  const mini = h("div", { class: "card small" });
  const logList = h("ul", { class: "list log" });

  function persist() { store.set(`chartState.${gameId}`, st); }

  function drawSituation() {
    const dots = (n, max) => h("span", { class: "dots", "aria-hidden": "true" }, Array.from({ length: max }, (_, i) => h("i", { class: i < n ? "on" : "" })));
    fill(situation, 
      h("button", { type: "button", onclick: editSituation, "aria-label": "Edit inning" },
        h("div", { class: "big" }, `${st.top_bottom === "T" ? "▲" : "▼"} ${st.inning}`), h("div", { class: "k" }, "Inning")),
      h("button", { type: "button", onclick: editSituation, "aria-label": `Count ${st.balls} balls ${st.strikes} strikes` },
        h("div", { class: "big" }, `${st.balls}-${st.strikes}`), h("div", { class: "k" }, "Count")),
      h("button", { type: "button", onclick: editSituation, "aria-label": `${st.outs} outs` },
        h("div", { class: "big" }, dots(st.outs, 2)), h("div", { class: "k" }, `${st.outs} out${st.outs === 1 ? "" : "s"}`)));
  }

  function drawMini() {
    const ps = allPitches().filter((p) => p.pitcher_name && p.pitcher_name === st.pitcher);
    if (!ps.length) { fill(mini, h("span", { class: "muted" }, st.pitcher ? `No pitches yet for ${st.pitcher}.` : "Enter the pitcher to start.")); return; }
    const strikes = ps.filter((p) => p.result !== "ball" && p.result !== "hit_by_pitch").length;
    const types = {};
    ps.forEach((p) => { const t = (types[p.pitch_type || "UN"] = types[p.pitch_type || "UN"] || { n: 0, v: [] }); t.n++; if (p.velocity) t.v.push(p.velocity); });
    fill(mini, 
      h("div", {}, h("strong", {}, st.pitcher), ` · ${ps.length} pitches · ${fmt.pct(strikes / ps.length, 0)} strikes`),
      h("div", { class: "ink2 num" }, Object.entries(types).sort((a, b) => b[1].n - a[1].n).map(([t, x]) =>
        `${t} ${x.n}${x.v.length ? ` (${(x.v.reduce((a, b) => a + b, 0) / x.v.length).toFixed(1)}, max ${Math.max(...x.v).toFixed(1)})` : ""}`).join(" · ")));
  }

  function drawLog() {
    const ps = allPitches().slice(-10).reverse();
    fill(logList, ...ps.map((p) => h("li", {},
      h("span", { class: "seq" }, p.sequence || "·"),
      h("span", { class: "grow" }, `${p.pitch_type || "?"} ${p.velocity || ""} · ${(RESULTS.find((r) => r[0] === p.result) || [0, p.result])[1]}`,
        p.pa_outcome ? h("strong", {}, ` → ${p.pa_outcome.replace(/_/g, " ")}`) : null,
        h("span", { class: "muted" }, ` · ${p.batter_name || ""} (${p.balls}-${p.strikes})`)),
      p.pending ? h("span", { class: "pending" }, "unsynced") : null)));
  }

  function redraw() { drawSituation(); drawMini(); drawLog(); pitcherIn.value = st.pitcher || ""; batterIn.value = st.batter || ""; sideSel.value = st.batter_side || ""; }

  function resetDraft() {
    veloIn.value = "";
    veloIn.placeholder = lastVelo(draft.pitch_type) || "mph";
    draft.zone = null;
    zoneBox.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
  }

  async function record(result) {
    st.pitcher = pitcherIn.value.trim();
    st.batter = batterIn.value.trim();
    if (!st.pitcher) { toast("Enter the pitcher first"); pitcherIn.focus(); return; }
    let outcome = impliedOutcome(st, result);
    let extra = {};
    if (result === "in_play") {
      const picked = await inPlaySheet();
      if (!picked) return;
      outcome = picked.outcome;
      extra = { batted_ball_type: picked.bbt || null, exit_velocity: picked.ev || null };
    }
    const pl = byName(st.pitcher), bt = byName(st.batter);
    const body = {
      pitcher_id: pl ? pl.id : null, pitcher_name: st.pitcher, batter_id: bt ? bt.id : null, batter_name: st.batter || null,
      batter_side: sideSel.value || null, inning: st.inning, top_bottom: st.top_bottom, outs: st.outs, balls: st.balls, strikes: st.strikes,
      pitch_type: draft.pitch_type, velocity: veloIn.value ? Number(veloIn.value) : null,
      zone: draft.zone ? draft.zone.zone : null, plate_x: draft.zone ? draft.zone.x : null, plate_z: draft.zone ? draft.zone.z : null,
      result, pa_outcome: outcome, ...extra,
    };
    store.set(`lastType.${gameId}`, draft.pitch_type);
    queue.push(gameId, body);
    const prevPitcher = st.pitcher;
    st = { ...nextState(body), batter_side: outcome ? "" : sideSel.value };
    if (!st.halfChanged) st.pitcher = prevPitcher;
    if (st.halfChanged) toast(`Side retired. ${st.top_bottom === "T" ? "Top" : "Bottom"} ${st.inning}: enter the new pitcher.`, 3500);
    else if (outcome) toast(`${outcome.replace(/_/g, " ")} · ${st.outs} out${st.outs === 1 ? "" : "s"}`);
    delete st.halfChanged;
    persist();
    resetDraft();
    if (document.activeElement === veloIn) veloIn.blur(); // next number key picks the pitch type again
    redraw();
    if (navigator.vibrate) navigator.vibrate(15);
    await queue.flush();
    await refreshServer();
  }

  async function refreshServer() {
    try { serverPitches = await api(`/games/${gameId}/pitches`); store.set(`game.${gameId}`, { game, serverPitches, people }); } catch { /* offline */ }
    drawLog();
  }
  const onSynced = () => (location.hash === `#/games/${gameId}/chart` ? refreshServer() : window.removeEventListener("diq-synced", onSynced));
  window.addEventListener("diq-synced", onSynced);

  function inPlaySheet() {
    return new Promise((resolve) => {
      const pick = { outcome: null, bbt: null, ev: null };
      const outcomeBox = h("div", { class: "outcomes" }, IN_PLAY.map(([v, l]) => h("button", { type: "button", "aria-pressed": "false", onclick: (e) => {
        pick.outcome = v;
        outcomeBox.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget)));
      } }, l)));
      const bbtBox = h("div", { class: "outcomes" }, [["ground_ball", "Ground ball"], ["line_drive", "Line drive"], ["fly_ball", "Fly ball"], ["popup", "Popup"], ["bunt", "Bunt"]].map(([v, l]) =>
        h("button", { type: "button", "aria-pressed": "false", onclick: (e) => {
          pick.bbt = pick.bbt === v ? null : v;
          bbtBox.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget && pick.bbt === v)));
        } }, l)));
      const ev = h("input", { type: "number", inputmode: "decimal", class: "input", placeholder: "Exit velo (optional)" });
      let done = false;
      const close = openSheet("Ball in play", h("div", { class: "stack" },
        h("h3", {}, "Result"), outcomeBox, h("h3", {}, "Batted ball"), bbtBox, ev,
        h("button", { class: "btn primary block", onclick: () => {
          if (!pick.outcome) { toast("Pick the result"); return; }
          pick.ev = ev.value ? Number(ev.value) : null;
          done = true;
          close();
          resolve(pick);
        } }, "Save pitch")));
      const obs = new MutationObserver(() => { if (!document.querySelector(".sheet-backdrop")) { obs.disconnect(); if (!done) resolve(null); } });
      obs.observe(document.body, { childList: true });
    });
  }

  function editSituation() {
    const f = h("form", { class: "stack" },
      h("div", { class: "grid2" },
        field("Inning", input("inning", { type: "number", min: 1, value: st.inning, inputmode: "numeric" })),
        field("Half", select("top_bottom", [["T", "Top"], ["B", "Bottom"]], st.top_bottom))),
      h("div", { class: "grid3" },
        field("Balls", select("balls", [0, 1, 2, 3], st.balls)),
        field("Strikes", select("strikes", [0, 1, 2], st.strikes)),
        field("Outs", select("outs", [0, 1, 2], st.outs))),
      h("button", { class: "btn primary block", type: "submit" }, "Update"));
    const close = openSheet("Game situation", f);
    f.addEventListener("submit", (e) => {
      e.preventDefault();
      const v = formData(f);
      Object.assign(st, { inning: Number(v.inning), top_bottom: v.top_bottom, balls: Number(v.balls), strikes: Number(v.strikes), outs: Number(v.outs) });
      persist(); close(); redraw();
    });
  }

  async function undo() {
    let removed;
    const pending = queue.forGame(gameId);
    if (pending.length) {
      removed = pending[pending.length - 1].body;
      queue.popLast(gameId);
    } else {
      try {
        // Re-read first so we restore the situation of the pitch the server actually deletes.
        serverPitches = await api(`/games/${gameId}/pitches`);
        removed = serverPitches[serverPitches.length - 1];
        if (!removed) return;
        await api(`/games/${gameId}/pitches/last`, { method: "DELETE" });
        serverPitches = serverPitches.slice(0, -1);
      } catch (e) { toast(e instanceof ApiError ? e.message : "Can't undo a synced pitch while offline"); return; }
    }
    // Every pitch stores the situation before it was thrown, so undo restores exactly that.
    st = { inning: removed.inning, top_bottom: removed.top_bottom || "T", outs: removed.outs || 0, balls: removed.balls, strikes: removed.strikes,
      pitcher: removed.pitcher_name || "", batter: removed.batter_name || "", batter_side: removed.batter_side || "" };
    persist(); redraw();
    toast("Last pitch removed");
  }

  function addNote() {
    const f = h("form", { class: "stack" },
      field("Category", select("category", ["", "delivery", "arm action", "swing", "approach", "defense", "baserunning", "makeup", "body", "other"], "")),
      field("Note", h("textarea", { name: "text", required: true })),
      h("button", { class: "btn primary block", type: "submit" }, "Save note"));
    const close = openSheet("Scouting note", f);
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const v = formData(f);
      const who = byName(st.batter) || byName(st.pitcher);
      try {
        await api(`/games/${gameId}/notes`, { method: "POST", json: { ...v, inning: st.inning, player_id: who ? who.id : null } });
        close(); toast("Note saved");
      } catch (err) { toast(err instanceof ApiError ? err.message : "Offline: note not saved"); }
    });
  }

  // Keyboard charting for laptops: number keys pick the pitch, letters record the result.
  const KEYS = { b: "ball", c: "called_strike", s: "swinging_strike", f: "foul", x: "in_play", h: "hit_by_pitch" };
  const onKey = (e) => {
    if (location.hash !== `#/games/${gameId}/chart`) { document.removeEventListener("keydown", onKey); return; }
    if (e.metaKey || e.altKey || document.querySelector(".sheet-backdrop")) return;
    const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName) && e.target !== veloIn;
    const k = e.key.toLowerCase();
    if (e.ctrlKey) { if (k === "z" && !typing) { e.preventDefault(); undo(); } return; }
    if (typing) return;
    // Digits typed into the velocity box are velocity, not pitch-type shortcuts.
    if (/^[1-8]$/.test(k) && e.target !== veloIn) { e.preventDefault(); ptypeBox.querySelectorAll("button")[+k - 1].click(); veloIn.focus(); veloIn.select(); }
    else if (KEYS[k]) { e.preventDefault(); record(KEYS[k]); }
    else if (k === "z") { e.preventDefault(); undo(); }
    else if (k === "n") { e.preventDefault(); addNote(); }
    else if (k === "v") { e.preventDefault(); veloIn.focus(); veloIn.select(); }
  };
  document.addEventListener("keydown", onKey);
  const kbd = (key, label) => h("span", {}, h("kbd", {}, key), " ", label);

  fill($view, dl,
    h("div", { class: "chart-layout" },
      h("div", { class: "chart-input" },
        situation,
        h("div", { class: "row", style: "margin-top:10px" }, pitcherIn),
        h("div", { class: "row", style: "margin-top:8px" }, batterIn, sideSel),
        h("h3", {}, "Pitch"), ptypeBox,
        h("div", { class: "velo-row", style: "margin-top:8px" },
          h("button", { type: "button", class: "btn", onclick: () => bump(-1), "aria-label": "Velocity minus one" }, "−"), veloIn,
          h("button", { type: "button", class: "btn", onclick: () => bump(1), "aria-label": "Velocity plus one" }, "+")),
        h("h3", {}, "Location ", h("span", { class: "small muted" }, "(catcher's view, optional)")), zoneBox,
        h("h3", {}, "Result"), resultBox,
        h("div", { class: "row", style: "margin-top:12px" },
          h("button", { type: "button", class: "btn", onclick: undo }, "↶ Undo"),
          h("button", { type: "button", class: "btn", onclick: addNote }, "✎ Note"),
          h("a", { class: "btn", href: `#/games/${gameId}` }, "Summary"))),
      h("div", { class: "chart-side" },
        h("div", { class: "card small shortcuts desktop-only" },
          h("strong", {}, "Keyboard: "),
          kbd("1–8", "pitch type"), kbd("V", "velo"), kbd("B", "ball"), kbd("C", "called"), kbd("S", "swinging"),
          kbd("F", "foul"), kbd("X", "in play"), kbd("H", "HBP"), kbd("Z", "undo"), kbd("N", "note")),
        h("h3", {}, "Current pitcher"), mini,
        h("h3", {}, "Recent pitches"), logList)));
  redraw();
}

// ---------------------------------------------------------------- accounts

let ME = null;

function setMe(user) {
  ME = user;
  if (user) store.set("me", user); else store.set("me", null);
  document.body.classList.toggle("signed-out", !user);
  document.body.classList.toggle("role-viewer", !!user && user.role === "viewer");
  document.getElementById("account-name").textContent = user ? user.name : "";
}

function signInRequired() {
  if (!ME) return;
  setMe(null);
  toast("Please sign in again");
  showAuth();
}

async function showAuth() {
  setMe(null);
  $back.hidden = true;
  let needsSetup = false;
  try { needsSetup = (await api("/auth/status")).needs_setup; } catch { /* offline: show sign-in */ }
  setTitle(needsSetup ? "Set up DiamondIQ" : "Sign in");
  const pw = (name, auto) => input(name, { type: "password", required: true, minlength: 10, autocomplete: auto });
  const form = needsSetup
    ? h("form", { class: "stack auth-card card" },
        h("p", { class: "ink2", style: "margin-top:0" }, "Create the first admin account. The setup code is printed in the server's log (the terminal or your host's log page) when it starts."),
        field("Setup code", input("setup_code", { required: true, autocomplete: "off", placeholder: "XXXX-XXXX-XXXX" })),
        field("Your name", input("name", { required: true, autocomplete: "name" })),
        field("Email", input("email", { type: "email", required: true, autocomplete: "email" })),
        field("Password (10+ characters)", pw("password", "new-password")),
        h("button", { class: "btn primary block", type: "submit" }, "Create admin account"))
    : h("form", { class: "stack auth-card card" },
        field("Email", input("email", { type: "email", required: true, autocomplete: "username" })),
        field("Password", pw("password", "current-password")),
        h("button", { class: "btn primary block", type: "submit" }, "Sign in"),
        h("p", { class: "small muted", style: "margin-bottom:0" }, "Forgot your password? Ask an admin to reset it."));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = formData(form);
    try {
      const r = await busy(form.querySelector("button[type=submit]"), api(needsSetup ? "/auth/setup" : "/auth/login", { method: "POST", json: body }));
      setMe(needsSetup ? r : r.user);
      toast(`Welcome, ${ME.name}`);
      queue.flush();
      route();
    } catch (err) { toast(err.message, 5000); }
  });
  fill($view, h("div", { class: "auth-wrap" }, h("img", { src: "icon.svg", alt: "", width: 64, height: 64 }), h("h2", {}, "DiamondIQ"), form));
}

async function accountView() {
  setTitle("Account");
  const pwForm = h("form", { class: "stack" },
    field("Current password", input("current_password", { type: "password", required: true, autocomplete: "current-password" })),
    field("New password (10+ characters)", input("new_password", { type: "password", required: true, minlength: 10, autocomplete: "new-password" })),
    h("button", { class: "btn block", type: "submit" }, "Change password"));
  pwForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await busy(pwForm.querySelector("button"), api("/auth/me/password", { method: "POST", json: formData(pwForm) }));
      pwForm.reset();
      toast("Password changed. Other devices were signed out.");
    } catch (err) { toast(err.message, 5000); }
  });
  const users = h("div");
  fill($view,
    h("div", { class: "card" },
      h("div", { class: "name" }, ME.name), h("div", { class: "ink2" }, ME.email),
      h("span", { class: "badge" }, { admin: "Admin", scout: "Scout", viewer: "Viewer (read-only)" }[ME.role])),
    h("h2", {}, "Password"), h("div", { class: "card" }, pwForm),
    h("button", { class: "btn block", style: "margin-top:12px", onclick: async () => {
      if (queue.items().length && !confirm("Some charted pitches haven't synced yet. They stay on this device and sync after you sign back in. Sign out anyway?")) return;
      try { await api("/auth/logout", { method: "POST" }); } catch { /* offline: still clear locally */ }
      setMe(null);
      showAuth();
    } }, "Sign out"),
    ME.role === "admin" ? [h("h2", {}, "Users"), users] : null);
  if (ME.role === "admin") drawUsers(users);
}

async function drawUsers(el) {
  const list = await api("/auth/users");
  const roleLabel = { admin: "Admin", scout: "Scout", viewer: "Viewer" };
  fill(el,
    h("p", { class: "small ink2" }, "Admins manage users. Scouts can add and edit everything. Viewers can only look."),
    h("button", { class: "btn primary block", onclick: () => userSheet(null, () => drawUsers(el)) }, "+ Add user"),
    h("ul", { class: "list" }, list.map((u) => h("li", {}, h("button", { class: "list-item", style: "width:100%;text-align:left;cursor:pointer", onclick: () => userSheet(u, () => drawUsers(el)) },
      h("div", { class: "grow" }, h("div", { class: "name" }, u.name, u.is_active ? "" : " (disabled)"), h("div", { class: "small ink2" }, u.email)),
      h("span", { class: "badge" }, roleLabel[u.role]), h("span", { class: "chev", "aria-hidden": "true" }, "›"))))));
}

function userSheet(u, done) {
  const isSelf = u && u.id === ME.id;
  const form = h("form", { class: "stack" },
    u ? h("p", { class: "ink2", style: "margin:0" }, u.email) : field("Email", input("email", { type: "email", required: true })),
    field("Name", input("name", { required: true, value: u ? u.name : "" })),
    field("Role", select("role", [["scout", "Scout (add & edit)"], ["viewer", "Viewer (read-only)"], ["admin", "Admin (everything + users)"]], u ? u.role : "scout", { disabled: isSelf || null })),
    field(u ? "New password (leave blank to keep)" : "Temporary password (10+ characters)", input("password", { type: "password", minlength: 10, required: !u || null, autocomplete: "new-password" })),
    u && !isSelf ? h("label", { class: "row small" }, h("input", { type: "checkbox", name: "is_active", checked: u.is_active || null, style: "flex:none;width:20px;height:20px" }), h("span", {}, "Account active (unchecking signs them out)")) : null,
    h("button", { class: "btn primary block", type: "submit" }, u ? "Save" : "Create user"),
    !u ? h("p", { class: "small muted" }, "Share the temporary password with them privately; they can change it under Account.") : null);
  const close = openSheet(u ? "Edit user" : "Add user", form);
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = formData(form);
    try {
      await busy(form.querySelector("button[type=submit]"), u
        ? api(`/auth/users/${u.id}`, { method: "PATCH", json: body })
        : api("/auth/users", { method: "POST", json: body }));
      close(); toast("Saved"); done();
    } catch (err) { toast(err.message, 5000); }
  });
}

// ---------------------------------------------------------------- boot

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
renderSync();
(async () => {
  try { setMe(await api("/auth/me")); } catch (e) {
    // Offline with a still-valid session cookie: let the scout keep charting from cached data.
    if (!(e instanceof ApiError)) setMe(store.get("me", null));
  }
  if (ME) store.set("me", ME);
  route();
})();
