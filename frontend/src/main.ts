// Entry point: the shell (sidebar, status, theme), the router and the refresh loop.

import "./styles.css";
import { adminToken, api, ApiError, type Config, type FloorStatus, type Market } from "./api";
import { $, esc, traderColor, until } from "./format";
import { FloorView } from "./views/floor";
import { TraderView } from "./views/trader";
import { ControlsView } from "./views/controls";

export interface View {
  title: string;
  mount(root: HTMLElement): void;
  refresh(): Promise<void>;
  destroy(): void;
}

/** What every view can see and do. */
export interface App {
  config: Config;
  floor: FloorStatus | null;
  market: Market | null;
  unlocked: boolean;
  toast(message: string, bad?: boolean): void;
  refreshStatus(): Promise<void>;
  setUnlocked(unlocked: boolean): void;
}

const REFRESH_MS = 8000;
const canvas = $("#canvas");
let view: View | null = null;
let app: App;

// Theme

function applyTheme(dark: boolean): void {
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  localStorage.setItem("atd-theme", dark ? "dark" : "light");
  $("#theme-label").textContent = dark ? "Light theme" : "Dark theme";
  $("#theme-toggle").setAttribute("aria-pressed", String(dark));
}

// Toast

let toastTimer = 0;
function toast(message: string, bad = false): void {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("bad", bad);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => el.classList.remove("show"), 4200);
}

// Sidebar status

function renderStatus(): void {
  const { market, floor } = app;
  const marketEl = $("#status-market");
  if (!market || !floor) {
    marketEl.textContent = "Not reachable";
    marketEl.dataset.state = "bad";
    $("#status-prices").textContent = "–";
    $("#status-next").textContent = "–";
    return;
  }
  marketEl.textContent = market.is_market_open ? "Open" : "Closed";
  marketEl.dataset.state = market.is_market_open ? "good" : "idle";
  $("#status-prices").textContent =
    market.source === "simulator" ? "Simulated" : market.delayed ? "Previous close" : "Live";

  const next = $("#status-next");
  if (floor.running) next.textContent = `Round ${floor.round_no} running`;
  else if (!floor.scheduler_enabled) next.textContent = "Manual only";
  else if (floor.paused) next.textContent = "Paused";
  else if (floor.next_run_at) next.textContent = until(floor.next_run_at);
  else next.textContent = "–";
  next.dataset.state = floor.running ? "good" : floor.paused ? "idle" : "";
}

async function refreshStatus(): Promise<void> {
  try {
    [app.floor, app.market] = await Promise.all([api.floor(), api.market()]);
  } catch {
    app.floor = null;
    app.market = null;
  }
  renderStatus();
}

// Routing

function route(): void {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  view?.destroy();
  const traderName = app.config.traders.find((t) => t.name.toLowerCase() === (parts[1] ?? "").toLowerCase())?.name;

  if (parts[0] === "trader" && traderName) view = new TraderView(app, traderName, parts[2] ?? "overview");
  else if (parts[0] === "controls") view = new ControlsView(app);
  else view = new FloorView(app);

  const current = parts[0] === "trader" && traderName ? `trader:${traderName}` : parts[0] === "controls" ? "controls" : "floor";
  document.querySelectorAll<HTMLElement>(".nav-item").forEach((item) => {
    const active = item.dataset.route === current;
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });

  document.title = `${view.title} · Agentic Trading Desk`;
  $("#topbar-title").textContent = view.title;
  document.body.classList.remove("menu-open");
  // Each view gets its own element, so its listeners go away with it.
  const host = document.createElement("div");
  canvas.replaceChildren(host);
  canvas.scrollTop = 0;
  view.mount(host);
  void refreshView();
}

let refreshing: View | null = null;

async function refreshView(): Promise<void> {
  const current = view;
  if (!current || refreshing === current) return; // one refresh of a view at a time
  refreshing = current;
  try {
    await current.refresh();
    if (current === view) canvas.classList.remove("offline");
  } catch (error) {
    if (current !== view) return;
    canvas.classList.add("offline");
    if (!canvas.querySelector(".page")) {
      const message = error instanceof ApiError ? error.message : "Something went wrong loading this page";
      canvas.innerHTML = `<div class="page"><div class="notice bad"><strong>${esc(message)}.</strong>
        Start it with <code>uv run uvicorn backend.api:app --port 8000</code>; this page will retry by itself.</div></div>`;
    }
  } finally {
    if (refreshing === current) refreshing = null;
  }
}

// Start

function wireShell(): void {
  applyTheme(document.documentElement.dataset.theme === "dark");
  $("#theme-toggle").addEventListener("click", () => applyTheme(document.documentElement.dataset.theme !== "dark"));
  $("#menu-open").addEventListener("click", () => document.body.classList.add("menu-open"));
  $("#menu-close").addEventListener("click", () => document.body.classList.remove("menu-open"));
}

async function start(): Promise<void> {
  let config: Config;
  try {
    config = await api.config();
  } catch {
    canvas.innerHTML = `<div class="page"><h1>Agentic Trading Desk</h1><div class="notice bad">
      <strong>The trading floor is not reachable.</strong> Start the backend with
      <code>uv run uvicorn backend.api:app --port 8000</code>, then reload this page.</div></div>`;
    $("#status-market").textContent = "Not reachable";
    $("#status-market").dataset.state = "bad";
    window.setTimeout(() => void start(), 5000);
    return;
  }

  app = {
    config,
    floor: null,
    market: null,
    unlocked: !config.token_required,
    toast,
    refreshStatus,
    setUnlocked(unlocked: boolean) {
      app.unlocked = unlocked;
      if (!unlocked) adminToken.clear();
    },
  };

  // A token saved earlier in this browser session unlocks the controls again.
  if (config.token_required && adminToken.get()) {
    try {
      await api.checkAdmin();
      app.unlocked = true;
    } catch {
      adminToken.clear();
    }
  }

  $("#nav-traders").innerHTML = config.traders
    .map(
      (t) => `<a class="nav-item" href="#/trader/${t.name.toLowerCase()}" data-route="trader:${esc(t.name)}">
        <span class="trader-dot" style="background:${traderColor(t.name)}"></span>${esc(t.name)} ${esc(t.lastname)}</a>`,
    )
    .join("");

  // Table rows that open a trader behave like links from the keyboard too.
  canvas.addEventListener("keydown", (event) => {
    const row = (event.target as HTMLElement).closest<HTMLElement>("[data-href]");
    if (row && event.key === "Enter" && event.target === row) location.hash = row.dataset.href!;
  });

  await refreshStatus();
  window.addEventListener("hashchange", route);
  route();

  window.setInterval(() => {
    if (document.hidden) return;
    void refreshStatus();
    void refreshView();
  }, REFRESH_MS);
  window.setInterval(renderStatus, 20_000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      void refreshStatus();
      void refreshView();
    }
  });
}

wireShell();
void start();
