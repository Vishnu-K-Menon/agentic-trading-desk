// The floor: who is winning, and are they beating the market?

import { api, ApiError, type Leaderboard, type RiskReview, type Round, type Standing } from "../api";
import { LineChart } from "../chart";
import { $, DECISION_LABEL, esc, pct, signedPct, tone, traderColor, usd, when } from "../format";
import type { App, View } from "../main";

interface DeskRow extends RiskReview {
  trader: string;
}

interface Appraisal extends Round {
  trader: string;
}

export class FloorView implements View {
  title = "Floor";
  private root!: HTMLElement;
  private chart: LineChart | null = null;
  private lastBoard = "";
  private lastRail = "";
  private tick = 0;

  constructor(private readonly app: App) {}

  mount(root: HTMLElement): void {
    this.root = root;
    root.innerHTML = `<div class="page">
      <header class="title-row">
        <div>
          <h1>Floor</h1>
          <p class="subline" id="finding"><span class="skeleton" style="width:22em"></span></p>
        </div>
        <div class="title-actions" id="floor-actions"></div>
      </header>
      <div class="split">
        <section class="card" aria-labelledby="standings-h">
          <div class="card-head"><h2 id="standings-h">Standings</h2><span class="meta" id="standings-meta"></span></div>
          <div id="standings">${skeletonRows(5)}</div>
        </section>
        <section class="card rail" aria-labelledby="desk-h">
          <div class="card-head"><h2 id="desk-h">Risk desk</h2><span class="meta">Latest decisions</span></div>
          <div id="desk">${skeletonRows(4)}</div>
        </section>
      </div>
      <div class="split">
        <section class="card grow" aria-labelledby="curve-h">
          <div class="card-head">
            <h2 id="curve-h">Growth of $100</h2>
            <span class="meta">Since each trader started with $10,000</span>
          </div>
          <div id="curve"></div>
        </section>
        <section class="card rail" aria-labelledby="appraisal-h">
          <div class="card-head"><h2 id="appraisal-h">Latest appraisals</h2></div>
          <div id="appraisals">${skeletonRows(3)}</div>
        </section>
      </div>
    </div>`;
    this.chart = new LineChart($("#curve", root), {
      height: 220,
      endLabels: true,
      format: (value) => value.toFixed(value >= 99.995 && value <= 100.005 ? 0 : 2),
      emptyText: "The curves appear after the first round.",
    });
    root.addEventListener("click", (event) => void this.onClick(event));
  }

  async refresh(): Promise<void> {
    const board = await api.leaderboard();
    this.renderActions();
    const signature = JSON.stringify(board);
    if (signature !== this.lastBoard) {
      this.lastBoard = signature;
      this.renderBoard(board);
    }
    // The side rail changes only when a round runs, so it is fetched less often.
    if (this.tick++ % 3 === 0 || this.app.floor?.running) await this.refreshRail();
  }

  destroy(): void {
    this.chart?.destroy();
  }

  private renderActions(): void {
    const { floor, unlocked } = this.app;
    const actions = $("#floor-actions", this.root);
    let html: string;
    if (floor?.running) html = `<span class="status-chip running">Round ${floor.round_no} is running</span>`;
    else if (unlocked) html = `<button class="button primary" data-action="run" type="button">Run a round now</button>`;
    else html = `<a class="button" href="#/controls">Owner controls</a>`;
    if (actions.innerHTML !== html) actions.innerHTML = html;
  }

  private renderBoard(board: Leaderboard): void {
    const { standings, benchmark } = board;
    const leader = standings[0];
    const ahead = standings.filter((s) => (s.vs_benchmark_pct ?? 0) > 0.005).length;
    const traded = standings.some((s) => s.trades > 0);

    let finding: string;
    if (!traded) finding = "No trades yet. Each trader starts with $10,000 and trades in rounds while the US market is open.";
    else {
      finding = `${leader.name} leads at ${signedPct(leader.return_pct)}`;
      if (benchmark.return_pct !== null)
        finding += `; ${ahead} of ${standings.length} are ahead of the S&P 500 (${signedPct(benchmark.return_pct)}).`;
      else finding += ".";
    }
    $("#finding", this.root).textContent = finding;
    $("#standings-meta", this.root).textContent = this.app.market?.delayed
      ? "Valued at the previous trading day's close"
      : this.app.market?.source === "simulator"
        ? "Simulated prices"
        : "";

    // The benchmark takes its place in the order, as one more competitor.
    type Row = { kind: "trader"; s: Standing } | { kind: "benchmark"; ret: number };
    const rows: Row[] = standings.map((s) => ({ kind: "trader", s }));
    if (benchmark.return_pct !== null) {
      const ret = benchmark.return_pct;
      const at = rows.findIndex((row) => row.kind === "trader" && row.s.return_pct < ret);
      rows.splice(at === -1 ? rows.length : at, 0, { kind: "benchmark", ret });
    }

    let rank = 0;
    const body = rows
      .map((row) => {
        if (row.kind === "benchmark")
          return `<tr class="benchmark-row">
            <td class="num rank"></td>
            <td><span class="who"><span class="trader-dot hollow"></span><span><span class="name">S&amp;P 500</span>
              <span class="sub">Buy and hold ${esc(benchmark.symbol)}</span></span></span></td>
            <td class="num">${usd(this.app.config.initial_balance * (1 + row.ret / 100))}</td>
            <td class="num ${tone(row.ret)}">${signedPct(row.ret)}</td>
            <td class="num col-wide muted">–</td><td class="num col-wide muted">–</td>
            <td class="num col-wide muted">–</td><td class="num col-mid muted">–</td><td class="col-wide"></td></tr>`;
        const s = row.s;
        rank += 1;
        const desk = s.risk.approve + s.risk.resize + s.risk.reject;
        return `<tr class="link-row" data-href="#/trader/${s.name.toLowerCase()}" tabindex="0" role="link"
            aria-label="${esc(s.name)} ${esc(s.lastname)}, ${usd(s.portfolio_value)}, ${signedPct(s.return_pct)}">
          <td class="num rank">${rank}</td>
          <td><span class="who"><span class="trader-dot" style="background:${traderColor(s.name)}"></span><span>
            <span class="name">${esc(s.name)} ${esc(s.lastname)}</span><span class="sub">${esc(s.model_name)}</span></span></span></td>
          <td class="num strong">${usd(s.portfolio_value)}</td>
          <td class="num ${tone(s.return_pct)}">${signedPct(s.return_pct)}</td>
          <td class="num col-wide ${tone(s.vs_benchmark_pct)}">${s.vs_benchmark_pct === null ? "–" : signedPct(s.vs_benchmark_pct)}</td>
          <td class="num col-wide">${s.max_drawdown_pct < -0.005 ? pct(s.max_drawdown_pct, 2) : "0.00%"}</td>
          <td class="num col-wide">${pct(s.cash_pct, 0)}</td>
          <td class="num col-mid">${s.trades}</td>
          <td class="col-wide desk-cell">${
            desk
              ? `<span title="Approved, resized, rejected">${s.risk.approve} <span class="muted">·</span> ${s.risk.resize} <span class="muted">·</span> ${s.risk.reject}</span>`
              : `<span class="muted">–</span>`
          }</td></tr>`;
      })
      .join("");

    $("#standings", this.root).innerHTML = `<table class="table standings">
      <thead><tr>
        <th class="num rank">#</th><th>Trader</th><th class="num">Value</th><th class="num">Return</th>
        <th class="num col-wide">vs S&amp;P 500</th><th class="num col-wide">Max drawdown</th>
        <th class="num col-wide">Cash</th><th class="num col-mid">Trades</th>
        <th class="col-wide desk-cell" title="Approved, resized, rejected">Risk desk</th>
      </tr></thead><tbody>${body}</tbody></table>`;

    const { t, series } = board.chart;
    this.chart?.set(
      t,
      Object.entries(series).map(([name, values]) =>
        name === benchmark.symbol
          ? { name: "S&P 500", values, color: "var(--chart-benchmark)", dashed: true }
          : { name, values, color: traderColor(name) },
      ),
    );
  }

  private async refreshRail(): Promise<void> {
    const names = this.app.config.traders.map((t) => t.name);
    const [reviews, rounds] = await Promise.all([
      Promise.all(names.map((name) => api.risk(name, 3).then((rows) => rows.map((row) => ({ ...row, trader: name }))))),
      Promise.all(names.map((name) => api.rounds(name).then((rows) => rows.map((row) => ({ ...row, trader: name }))))),
    ]);
    const desk: DeskRow[] = reviews.flat().sort((a, b) => b.created_at - a.created_at).slice(0, 3);
    const appraisals: Appraisal[] = rounds
      .map((list) => list.find((round) => round.final_output || round.error))
      .filter((round): round is Appraisal => Boolean(round))
      .sort((a, b) => (b.ended_at ?? 0) - (a.ended_at ?? 0));

    const signature = JSON.stringify([desk, appraisals]);
    if (signature === this.lastRail) return;
    this.lastRail = signature;

    $("#desk", this.root).innerHTML = desk.length
      ? `<ul class="rows">${desk
          .map(
            (row) => `<li>
              <div class="row-top"><span class="who small"><span class="trader-dot" style="background:${traderColor(row.trader)}"></span>
                <span class="name">${esc(row.trader)}</span></span>
                <span class="pill ${row.decision}">${DECISION_LABEL[row.decision]}</span></div>
              <div class="row-main">${row.side === "buy" ? "Buy" : "Sell"} ${
                row.approved === row.requested || row.decision === "reject"
                  ? row.requested
                  : `<s class="muted">${row.requested}</s> ${row.approved}`
              } ${esc(row.symbol)}</div>
              <p class="row-note clamp two" title="${esc(row.reason)}">${esc(row.reason)}</p></li>`,
          )
          .join("")}</ul>`
      : `<p class="empty">No trades have been proposed yet. Every proposal is checked here before it executes.</p>`;

    $("#appraisals", this.root).innerHTML = appraisals.length
      ? `<ul class="rows">${appraisals
          .map(
            (round) => `<li>
              <div class="row-top"><a class="who small" href="#/trader/${round.trader.toLowerCase()}/sessions">
                <span class="trader-dot" style="background:${traderColor(round.trader)}"></span>
                <span class="name">${esc(round.trader)}</span></a>
                <span class="meta">${round.ended_at ? esc(when(round.ended_at)) : ""}</span></div>
              <p class="row-note clamp two ${round.error ? "down" : ""}">${esc(round.error ? `Session failed: ${round.error}` : round.final_output)}</p></li>`,
          )
          .join("")}</ul>`
      : `<p class="empty">Each trader closes a session with a short appraisal. They appear here after the first round.</p>`;
  }

  private async onClick(event: Event): Promise<void> {
    const target = event.target as HTMLElement;
    const row = target.closest<HTMLElement>("[data-href]");
    if (row && !target.closest("a, button")) {
      location.hash = row.dataset.href!;
      return;
    }
    const button = target.closest<HTMLButtonElement>("[data-action='run']");
    if (!button) return;
    button.disabled = true;
    try {
      await api.runRound();
      this.app.toast("Round started. The traders are at work; this takes a few minutes.");
      await this.app.refreshStatus();
      this.renderActions();
    } catch (error) {
      this.app.toast(error instanceof ApiError ? error.message : "Could not start a round", true);
      button.disabled = false;
    }
  }
}

export function skeletonRows(count: number): string {
  return `<div class="skeleton-rows" aria-hidden="true">${`<span class="skeleton"></span>`.repeat(count)}</div>`;
}
