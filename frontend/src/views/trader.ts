// One trader: what it holds, what it did and why, and what the risk desk said.

import { api, type LogRow, type Memory, type RiskReview, type Round, type StrategyHistory, type TraderDetail } from "../api";
import { LineChart } from "../chart";
import {
  $, clockSeconds, count, DECISION_LABEL, duration, esc, pct, signedPct, signedUsd, tone, traderColor, usd, usdRound, when,
} from "../format";
import type { App, View } from "../main";
import { skeletonRows } from "./floor";

const TABS = [
  ["overview", "Overview"],
  ["trades", "Trades"],
  ["risk", "Risk desk"],
  ["sessions", "Sessions"],
  ["memory", "Memory"],
  ["activity", "Activity"],
] as const;

const LOG_LABELS: Record<string, string> = {
  trace: "Session", agent: "Agent", function: "Tool", generation: "Thinking", response: "Answer",
  account: "Account", risk: "Risk desk", mcp_tools: "Tools", task: "Task", turn: "Turn",
};
const QUIET_LOG_TYPES = new Set(["mcp_tools", "task", "turn", "generation"]);

export class TraderView implements View {
  title: string;
  private root!: HTMLElement;
  private chart: LineChart | null = null;
  private last: Record<string, string> = {};
  private lastLogId = 0;
  private showAllLogs = false;

  constructor(private readonly app: App, private readonly name: string, private tab: string) {
    const trader = app.config.traders.find((t) => t.name === name)!;
    this.title = `${trader.name} ${trader.lastname}`;
    if (!TABS.some(([id]) => id === tab)) this.tab = "overview";
  }

  mount(root: HTMLElement): void {
    this.root = root;
    const base = `#/trader/${this.name.toLowerCase()}`;
    root.innerHTML = `<div class="page">
      <header class="title-row">
        <div>
          <h1><span class="trader-dot large" style="background:${traderColor(this.name)}"></span>${esc(this.title)}</h1>
          <p class="subline" id="trader-sub"><span class="skeleton" style="width:16em"></span></p>
        </div>
      </header>
      <section class="card kpis" id="kpis" aria-label="Key figures">${skeletonRows(1)}</section>
      <nav class="tabs" aria-label="${esc(this.title)}">${TABS.map(
        ([id, label]) =>
          `<a href="${base}${id === "overview" ? "" : `/${id}`}" class="${id === this.tab ? "active" : ""}" ${
            id === this.tab ? 'aria-current="page"' : ""
          }>${label}</a>`,
      ).join("")}</nav>
      <div id="tab-body">${skeletonRows(4)}</div>
    </div>`;
    root.addEventListener("change", (event) => {
      const toggle = (event.target as HTMLElement).closest<HTMLInputElement>("#log-all");
      if (!toggle) return;
      this.showAllLogs = toggle.checked;
      this.lastLogId = 0;
      void this.refresh();
    });
  }

  destroy(): void {
    this.chart?.destroy();
  }

  async refresh(): Promise<void> {
    const detail = await api.trader(this.name);
    this.renderHeader(detail);
    if (this.tab === "overview") this.renderOverview(detail, await api.rounds(this.name));
    else if (this.tab === "trades") this.renderTrades(detail, await api.risk(this.name, 200));
    else if (this.tab === "risk") this.renderRisk(await api.risk(this.name, 200));
    else if (this.tab === "sessions") this.renderSessions(await api.rounds(this.name), await api.strategy(this.name));
    else if (this.tab === "memory") this.renderMemory(await api.memory(this.name));
    else await this.renderActivity();
  }

  /** Re-render a region only when its data changed, so scrolling and selection survive refreshes. */
  private changed(key: string, data: unknown): boolean {
    const signature = JSON.stringify(data);
    if (this.last[key] === signature) return false;
    this.last[key] = signature;
    return true;
  }

  private renderHeader(d: TraderDetail): void {
    if (!this.changed("header", [d.portfolio_value, d.balance, d.trades, d.positions, d.model_name, d.max_drawdown_pct])) return;
    $("#trader-sub", this.root).textContent = `Runs on ${d.model_name}`;
    const cells: [string, string, string?, string?][] = [
      ["Portfolio value", usd(d.portfolio_value), "lead"],
      ["Return", signedPct(d.return_pct), tone(d.return_pct), `${signedUsd(d.pnl)} on ${usdRound(this.app.config.initial_balance)}`],
      ["Cash", usd(d.balance), "", `${pct(d.cash_pct, 0)} of the portfolio`],
      ["Positions", count(d.positions), "", `${count(d.trades)} ${d.trades === 1 ? "trade" : "trades"} so far`],
      ["Max drawdown", d.max_drawdown_pct < -0.005 ? pct(d.max_drawdown_pct, 2) : "0.00%", "", "Largest fall from a peak"],
    ];
    $("#kpis", this.root).innerHTML = cells
      .map(
        ([label, value, cls, note]) => `<div class="kpi"><div class="kpi-label">${label}</div>
          <div class="kpi-value ${cls ?? ""}">${value}</div>${note ? `<div class="kpi-note">${esc(note)}</div>` : ""}</div>`,
      )
      .join("");
  }

  private body(): HTMLElement {
    return $("#tab-body", this.root);
  }

  private renderOverview(d: TraderDetail, rounds: Round[]): void {
    const latest = rounds.find((round) => round.final_output || round.error);
    if (!this.changed("overview", [d.holdings, d.time_series.length, d.strategy, latest])) return;
    this.chart?.destroy();
    this.body().innerHTML = `<div class="split even">
        <section class="card grow" aria-labelledby="value-h">
          <div class="card-head"><h2 id="value-h">Portfolio value</h2></div><div id="value-chart"></div>
        </section>
        <div class="stack">
          <section class="card" aria-labelledby="strategy-h">
            <div class="card-head"><h2 id="strategy-h">Strategy</h2></div>
            <p class="prose flow">${esc(d.strategy.trim()) || `<span class="muted">No strategy recorded yet.</span>`}</p>
          </section>
          <section class="card" aria-labelledby="latest-h">
            <div class="card-head"><h2 id="latest-h">Latest appraisal</h2>
              <span class="meta">${latest?.ended_at ? esc(when(latest.ended_at)) : ""}</span></div>
            ${
              latest
                ? `<p class="prose ${latest.error ? "down" : ""}">${esc(latest.error ? `The session failed: ${latest.error}` : latest.final_output)}</p>`
                : `<p class="empty">${esc(this.name)} writes a short appraisal at the end of each session.</p>`
            }
          </section>
        </div>
      </div>
      <section class="card" aria-labelledby="holdings-h">
        <div class="card-head"><h2 id="holdings-h">Holdings</h2>
          <span class="meta">${d.holdings.length ? `${d.holdings.length} ${d.holdings.length === 1 ? "position" : "positions"} and ${usd(d.balance)} cash` : ""}</span></div>
        ${
          d.holdings.length
            ? `<table class="table"><thead><tr><th>Symbol</th><th class="num">Shares</th><th class="num col-mid">Avg cost</th>
                <th class="num col-mid">Price</th><th class="num">Value</th><th class="num col-wide">Weight</th>
                <th class="num">Gain or loss</th></tr></thead><tbody>${d.holdings
                  .map(
                    (h) => `<tr><td class="strong">${esc(h.symbol)}</td><td class="num">${count(h.quantity)}</td>
                      <td class="num col-mid">${usd(h.avg_cost)}</td><td class="num col-mid">${usd(h.price)}</td>
                      <td class="num">${usd(h.market_value)}</td>
                      <td class="num col-wide"><span class="weight"><span style="width:${Math.min(100, h.weight_pct * (100 / this.app.config.limits.max_position_pct)).toFixed(1)}%"></span></span>${pct(h.weight_pct)}</td>
                      <td class="num ${tone(h.unrealized_pnl)}">${signedUsd(h.unrealized_pnl)}<span class="sub">${signedPct(h.unrealized_pct)}</span></td></tr>`,
                  )
                  .join("")}</tbody></table>
                <p class="foot-note">The weight bar fills at the risk desk's limit of ${pct(this.app.config.limits.max_position_pct, 0)} per position.</p>`
            : `<p class="empty">All ${usd(d.balance)} is in cash. Holdings appear here after ${esc(this.name)}'s first approved trade.</p>`
        }
      </section>`;
    this.chart = new LineChart($("#value-chart", this.root), {
      height: 232,
      format: (value) => usdRound(value),
      emptyText: "The value history starts with the first round.",
    });
    this.chart.set(
      d.time_series.map((point) => point.t),
      [{ name: this.name, values: d.time_series.map((point) => point.value), color: traderColor(this.name) }],
    );
  }

  private renderTrades(d: TraderDetail, reviews: RiskReview[]): void {
    if (!this.changed("trades", [d.transactions, reviews.length])) return;
    // Match each executed trade to the risk desk's decision on it.
    const verdicts = reviews.filter((review) => review.decision !== "reject");
    const verdictFor = (symbol: string, quantity: number, ts: number) =>
      verdicts.find(
        (review) =>
          review.symbol === symbol && review.approved === Math.abs(quantity) &&
          (review.side === "buy") === quantity > 0 && Math.abs(review.created_at - ts) < 180,
      );
    this.body().innerHTML = `<section class="card" aria-labelledby="trades-h">
      <div class="card-head"><h2 id="trades-h">Trades</h2>
        <span class="meta">${d.transactions.length ? `${d.transactions.length} executed, newest first` : ""}</span></div>
      ${
        d.transactions.length
          ? `<table class="table trades"><thead><tr><th>When</th><th>Trade</th><th class="num">Value</th>
              <th class="col-wide">Risk desk</th><th class="col-mid">Rationale</th></tr></thead><tbody>${d.transactions
                .map((t) => {
                  const verdict = verdictFor(t.symbol, t.quantity, t.ts);
                  return `<tr><td class="nowrap muted">${esc(when(t.ts))}</td>
                    <td class="nowrap"><span class="side ${t.quantity > 0 ? "buy" : "sell"}">${t.quantity > 0 ? "Buy" : "Sell"}</span>
                      <span class="strong">${count(Math.abs(t.quantity))} ${esc(t.symbol)}</span><span class="sub">at ${usd(t.price)}</span></td>
                    <td class="num">${usd(t.value)}</td>
                    <td class="col-wide">${verdict ? `<span class="pill ${verdict.decision}">${DECISION_LABEL[verdict.decision]}</span>` : `<span class="muted">–</span>`}</td>
                    <td class="col-mid rationale">${esc(t.rationale)}</td></tr>`;
                })
                .join("")}</tbody></table>`
          : `<p class="empty">No trades yet. ${esc(this.name)} trades in rounds while the US market is open.</p>`
      }
    </section>`;
  }

  private renderRisk(reviews: RiskReview[]): void {
    if (!this.changed("risk", reviews)) return;
    const tally = { approve: 0, resize: 0, reject: 0 };
    reviews.forEach((review) => (tally[review.decision] += 1));
    const limits = this.app.config.limits;
    this.body().innerHTML = `<section class="card" aria-labelledby="risk-h">
      <div class="card-head"><h2 id="risk-h">Risk desk decisions</h2>
        <span class="meta">${reviews.length ? `${tally.approve} approved, ${tally.resize} resized, ${tally.reject} rejected` : ""}</span></div>
      <p class="foot-note top">Every trade ${esc(this.name)} proposes is checked before it executes. Two limits are enforced
        in code: no position above ${pct(limits.max_position_pct, 0)} of the portfolio, and at least ${pct(limits.min_cash_pct, 0)}
        kept in cash. Within them, a risk manager agent judges fit and size.</p>
      ${
        reviews.length
          ? `<ul class="rows wide">${reviews
              .map(
                (r) => `<li><div class="row-top">
                    <span><span class="side ${r.side}">${r.side === "buy" ? "Buy" : "Sell"}</span>
                      <span class="strong">${
                        r.decision === "resize" ? `<s class="muted">${count(r.requested)}</s> ${count(r.approved)}` : count(r.requested)
                      } ${esc(r.symbol)}</span></span>
                    <span class="row-right"><span class="meta">${esc(when(r.created_at))} · ${r.source === "limits" ? "Hard limit" : "Risk manager"}</span>
                      <span class="pill ${r.decision}">${DECISION_LABEL[r.decision]}</span></span></div>
                  <p class="row-note"><span class="strong">Decision.</span> ${esc(r.reason)}</p>
                  ${r.rationale ? `<p class="row-note muted"><span>${esc(this.name)}'s case.</span> ${esc(r.rationale)}</p>` : ""}</li>`,
              )
              .join("")}</ul>`
          : `<p class="empty">Nothing has been proposed yet.</p>`
      }
    </section>`;
  }

  private renderSessions(rounds: Round[], history: StrategyHistory): void {
    if (!this.changed("sessions", [rounds, history])) return;
    this.body().innerHTML = `<div class="split even">
      <section class="card" aria-labelledby="sessions-h">
        <div class="card-head"><h2 id="sessions-h">Sessions</h2><span class="meta">${rounds.length ? "Newest first" : ""}</span></div>
        ${
          rounds.length
            ? `<ul class="rows wide">${rounds
                .map(
                  (r) => `<li><div class="row-top"><span class="strong">Round ${r.round_no} · ${r.kind === "trading" ? "New trades" : "Rebalancing"}</span>
                      <span class="meta">${esc(when(r.started_at))}${r.ended_at ? ` · ${duration(r.ended_at - r.started_at)}` : ""} · ${esc(
                        this.app.config.models.find((m) => m.id === r.model)?.label ?? r.model,
                      )}</span></div>
                    <p class="row-note ${r.error ? "down" : ""}">${
                      r.error ? esc(`Failed: ${r.error}`) : r.final_output ? esc(r.final_output) : `<span class="muted">In progress</span>`
                    }</p></li>`,
                )
                .join("")}</ul>`
            : `<p class="empty">No sessions yet. A session is one trader's turn within a round.</p>`
        }
      </section>
      <section class="card" aria-labelledby="changes-h">
        <div class="card-head"><h2 id="changes-h">Strategy changes</h2></div>
        ${
          history.changes.length
            ? `<ul class="rows wide">${history.changes
                .map(
                  (c) => `<li><div class="row-top"><span class="strong">${c.source === "admin" ? "Edited by the owner" : `Rewritten by ${esc(this.name)}`}</span>
                    <span class="meta">${esc(when(c.created_at))}</span></div><p class="row-note">${esc(c.strategy.trim())}</p></li>`,
                )
                .join("")}</ul>`
            : `<p class="empty">${esc(this.name)} can rewrite its own strategy after reviewing its results. No changes so far.</p>`
        }
      </section></div>`;
  }

  private renderMemory(memory: Memory): void {
    if (!this.changed("memory", memory)) return;
    const { entities, relations } = memory.graph;
    this.body().innerHTML = `<div class="split even">
      <section class="card" aria-labelledby="notes-h">
        <div class="card-head"><h2 id="notes-h">Research library</h2>
          <span class="meta">${memory.notes.length} of ${memory.library_size} notes on the floor</span></div>
        ${
          memory.notes.length
            ? `<ul class="rows wide">${memory.notes
                .map(
                  (n) => `<li><div class="row-top"><span class="strong">${esc(n.topic || "Untitled note")}</span>
                    <span class="meta">${esc(when(n.created_at))}</span></div>
                    ${n.symbols.length ? `<div class="chips">${n.symbols.map((s) => `<span class="chip">${esc(s)}</span>`).join("")}</div>` : ""}
                    <p class="row-note">${esc(n.text)}</p></li>`,
                )
                .join("")}</ul>`
            : `<p class="empty">Findings ${esc(this.name)}'s researcher saves are stored here and can be recalled by meaning by every trader.</p>`
        }
      </section>
      <section class="card" aria-labelledby="graph-h">
        <div class="card-head"><h2 id="graph-h">Knowledge graph</h2>
          <span class="meta">${entities.length ? `${entities.length} entities, ${relations.length} relations` : ""}</span></div>
        ${
          entities.length
            ? `<ul class="rows wide">${entities
                .map((e) => {
                  const links = relations.filter((r) => r.source === e.name).slice(0, 6);
                  return `<li><div class="row-top"><span class="strong">${esc(e.name)}</span><span class="chip">${esc(e.type)}</span></div>
                    ${e.observations.length ? `<ul class="bullets">${e.observations.map((o) => `<li>${esc(o)}</li>`).join("")}</ul>` : ""}
                    ${links.length ? `<p class="row-note muted">${links.map((l) => `${esc(l.type.replace(/_/g, " ").toLowerCase())} ${esc(l.target)}`).join(" · ")}</p>` : ""}</li>`;
                })
                .join("")}</ul>`
            : `<p class="empty">${esc(this.name)}'s private notes on companies and markets, kept as entities and relations.</p>`
        }
      </section></div>`;
  }

  private async renderActivity(): Promise<void> {
    if (!this.root.querySelector("#log")) {
      this.body().innerHTML = `<section class="card" aria-labelledby="log-h">
        <div class="card-head"><h2 id="log-h">Activity</h2>
          <label class="check"><input type="checkbox" id="log-all" ${this.showAllLogs ? "checked" : ""}/> Show every step</label></div>
        <ol class="log" id="log" aria-live="polite"></ol></section>`;
      this.lastLogId = 0;
    }
    const log = $("#log", this.root);
    const fresh = await api.logs(this.name, this.lastLogId, this.lastLogId ? 500 : 300);
    if (!this.lastLogId) log.innerHTML = "";
    if (fresh.length) this.lastLogId = fresh[fresh.length - 1].id;
    const shown = fresh.filter((row) => this.showAllLogs || !isRoutine(row));
    // Stay pinned to the newest line only if the reader was already there.
    const pinned = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
    log.insertAdjacentHTML("beforeend", shown.map(logLine).join(""));
    if (!log.children.length) log.innerHTML = `<li class="empty">Nothing yet. Each step ${esc(this.name)} takes during a round is listed here as it happens.</li>`;
    else log.querySelector(".empty")?.remove();
    if (pinned) log.scrollTop = log.scrollHeight;
  }
}

/** Steps that only mark the start or end of a model call or a tool, with nothing else to say. */
function isRoutine(row: LogRow): boolean {
  if (QUIET_LOG_TYPES.has(row.type)) return true;
  if (row.type === "response" && /^(Started|Ended) response$/.test(row.message)) return true;
  return /^Ended (function|agent) \S+$/.test(row.message);
}

function logLine(row: LogRow): string {
  const message = row.message
    .replace(/^Started function /, "Called ")
    .replace(/^(Started|Ended) (function|agent|trace|generation|response|task|turn|mcp_tools) ?/, "$1 ");
  return `<li class="log-${esc(row.type)}"><time>${esc(clockSeconds(row.ts))}</time><span class="log-type">${esc(
    LOG_LABELS[row.type] ?? row.type,
  )}</span><span class="log-message">${esc(message)}</span></li>`;
}
