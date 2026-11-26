// Owner controls: run the floor, choose models, edit strategies, reset.

import { adminToken, api, ApiError } from "../api";
import { $, esc, pct, traderColor, until } from "../format";
import type { App, View } from "../main";

const RESET_WORD = "RESET";

export class ControlsView implements View {
  title = "Controls";
  private root!: HTMLElement;
  private rendered = "";

  constructor(private readonly app: App) {}

  mount(root: HTMLElement): void {
    this.root = root;
    root.innerHTML = `<div class="page narrow">
      <header class="title-row"><div><h1>Controls</h1>
        <p class="subline">Run the floor, choose each trader's model and strategy. Changes take effect from the next round.</p></div></header>
      <div id="controls-body"></div></div>`;
    root.addEventListener("click", (event) => void this.onClick(event));
    root.addEventListener("submit", (event) => void this.onSubmit(event));
    root.addEventListener("input", (event) => this.onInput(event));
  }

  destroy(): void {}

  async refresh(): Promise<void> {
    const state = this.app.unlocked ? "open" : "locked";
    if (this.rendered !== state) {
      this.rendered = state;
      if (state === "locked") this.renderLocked();
      else await this.renderOpen();
    }
    if (state === "open") this.renderFloorStatus();
  }

  private body(): HTMLElement {
    return $("#controls-body", this.root);
  }

  private renderLocked(): void {
    this.body().innerHTML = `<section class="setting">
      <div class="setting-label"><h2>Owner access</h2>
        <p>This floor is public to watch. Changing it needs the owner's admin token, which is kept only in this browser tab.</p></div>
      <form class="panel" id="unlock-form" novalidate>
        <label class="field"><span>Admin token</span>
          <input type="password" name="token" autocomplete="current-password" required aria-describedby="unlock-error"/></label>
        <p class="field-error" id="unlock-error" role="alert" hidden></p>
        <div class="panel-actions"><button class="button primary" type="submit">Unlock controls</button></div>
      </form></section>`;
  }

  private async renderOpen(): Promise<void> {
    const { config } = this.app;
    const traders = await Promise.all(config.traders.map((t) => api.trader(t.name)));
    this.body().innerHTML = `
      <section class="setting">
        <div class="setting-label"><h2>The floor</h2>
          <p>A round gives every trader one session. Rounds run every ${this.app.floor?.interval_minutes ?? 60} minutes
            while the US market is open, up to ${this.app.floor?.max_rounds_per_day ?? 7} a day.</p></div>
        <div class="panel"><dl class="facts" id="floor-facts"></dl>
          <div class="panel-actions" id="floor-buttons"></div></div>
      </section>
      ${traders
        .map(
          (t) => `<section class="setting">
            <div class="setting-label"><h2><span class="trader-dot" style="background:${traderColor(t.name)}"></span>${esc(t.name)} ${esc(t.lastname)}</h2>
              <p>${esc(t.name)} may also rewrite its own strategy after reviewing its results.
                <a href="#/trader/${t.name.toLowerCase()}/sessions">See its changes</a>.</p></div>
            <form class="panel trader-form" data-trader="${esc(t.name)}" novalidate>
              <label class="field"><span>Model</span>
                <select name="model">${config.models
                  .map((m) => `<option value="${esc(m.id)}" ${m.id === t.model ? "selected" : ""}>${esc(m.label)}</option>`)
                  .join("")}</select></label>
              <label class="field"><span>Strategy</span>
                <textarea name="strategy" rows="7" minlength="20" maxlength="4000" required
                  aria-describedby="strategy-hint-${esc(t.name)}">${esc(t.strategy.trim())}</textarea>
                <small id="strategy-hint-${esc(t.name)}">Between 20 and 4,000 characters. Written to the trader as its standing instructions.</small></label>
              <div class="panel-actions"><span class="saved" role="status"></span>
                <button class="button primary" type="submit" disabled>Save changes</button></div>
            </form></section>`,
        )
        .join("")}
      <section class="setting">
        <div class="setting-label"><h2>Reset the floor</h2>
          <p>Puts all four traders back to $10,000 with their starting strategies and clears their trades, sessions and
            risk desk history. This cannot be undone.</p></div>
        <form class="panel danger" id="reset-form" novalidate>
          <label class="check"><input type="checkbox" name="forget"/> Also erase the research library and every trader's knowledge graph</label>
          <label class="field"><span>Type ${RESET_WORD} to confirm</span>
            <input type="text" name="confirm" autocomplete="off" spellcheck="false"/></label>
          <div class="panel-actions"><button class="button danger" type="submit" disabled>Reset all four traders</button></div>
        </form>
      </section>
      ${
        config.token_required
          ? `<section class="setting"><div class="setting-label"><h2>Owner access</h2><p>Unlocked in this browser tab.</p></div>
              <div class="panel"><div class="panel-actions start"><button class="button" data-action="lock" type="button">Lock controls</button></div></div></section>`
          : ""
      }`;
  }

  private renderFloorStatus(): void {
    const floor = this.app.floor;
    const facts = this.root.querySelector<HTMLElement>("#floor-facts");
    const buttons = this.root.querySelector<HTMLElement>("#floor-buttons");
    if (!facts || !buttons || !floor) return;

    let state: string;
    if (floor.running) state = `Round ${floor.round_no} is running`;
    else if (!floor.scheduler_enabled) state = "Automatic rounds are off; rounds run only when started here";
    else if (floor.paused) state = "Paused";
    else if (floor.next_run_at) state = `Next round ${until(floor.next_run_at)}`;
    else state = "Waiting";
    const market = this.app.market;
    const prices = !market ? "–" : market.source === "simulator" ? "Simulated" : market.delayed ? "Previous trading day's close" : "Live";
    const limits = this.app.config.limits;

    const factsHtml = [
      ["Status", state],
      ["Rounds today", `${floor.rounds_today} of ${floor.max_rounds_per_day}`],
      ["Prices", prices],
      ["Risk limits", `${pct(limits.max_position_pct, 0)} per position, ${pct(limits.min_cash_pct, 0)} cash kept`],
      ...(floor.last_skip_reason ? [["Last skipped", floor.last_skip_reason]] : []),
    ]
      .map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`)
      .join("");
    if (facts.innerHTML !== factsHtml) facts.innerHTML = factsHtml;

    const buttonsHtml = `${
      floor.scheduler_enabled
        ? `<button class="button" data-action="${floor.paused ? "resume" : "pause"}" type="button">${floor.paused ? "Resume schedule" : "Pause schedule"}</button>`
        : ""
    }<button class="button primary" data-action="run" type="button" ${floor.running ? "disabled" : ""}>${floor.running ? "Round in progress" : "Run a round now"}</button>`;
    if (buttons.innerHTML !== buttonsHtml) buttons.innerHTML = buttonsHtml;
  }

  private fail(error: unknown, fallback: string): void {
    if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
      this.app.setUnlocked(false);
      this.app.toast("The admin token is no longer accepted. Unlock the controls again.", true);
      void this.refresh();
      return;
    }
    this.app.toast(error instanceof ApiError ? error.message : fallback, true);
  }

  private onInput(event: Event): void {
    const target = event.target as HTMLElement;
    const traderForm = target.closest<HTMLFormElement>(".trader-form");
    if (traderForm) {
      traderForm.querySelector<HTMLButtonElement>("button[type=submit]")!.disabled = false;
      traderForm.querySelector<HTMLElement>(".saved")!.textContent = "";
    }
    const resetForm = target.closest<HTMLFormElement>("#reset-form");
    if (resetForm) {
      const typed = (resetForm.elements.namedItem("confirm") as HTMLInputElement).value.trim();
      resetForm.querySelector<HTMLButtonElement>("button[type=submit]")!.disabled = typed !== RESET_WORD;
    }
  }

  private async onClick(event: Event): Promise<void> {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-action]");
    if (!button) return;
    const action = button.dataset.action;
    if (action === "lock") {
      this.app.setUnlocked(false);
      void this.refresh();
      return;
    }
    button.disabled = true;
    try {
      if (action === "run") {
        await api.runRound();
        this.app.toast("Round started. This takes a few minutes.");
      } else if (action === "pause") {
        await api.pause();
        this.app.toast("Schedule paused. No rounds will start by themselves.");
      } else if (action === "resume") {
        await api.resume();
        this.app.toast("Schedule resumed.");
      }
      await this.app.refreshStatus();
    } catch (error) {
      this.fail(error, "That did not work");
    }
    button.disabled = false;
    this.renderFloorStatus();
  }

  private async onSubmit(event: Event): Promise<void> {
    event.preventDefault();
    const form = event.target as HTMLFormElement;
    const submit = form.querySelector<HTMLButtonElement>("button[type=submit]")!;

    if (form.id === "unlock-form") {
      const input = form.elements.namedItem("token") as HTMLInputElement;
      const error = $("#unlock-error", form);
      if (!input.value.trim()) {
        error.textContent = "Enter the admin token.";
        error.hidden = false;
        input.focus();
        return;
      }
      submit.disabled = true;
      adminToken.set(input.value.trim());
      try {
        await api.checkAdmin();
        this.app.setUnlocked(true);
        this.app.toast("Controls unlocked for this tab.");
        await this.refresh();
      } catch (problem) {
        adminToken.clear();
        error.textContent = problem instanceof ApiError && problem.status === 401
          ? "That token is not correct. Check the ADMIN_TOKEN secret and try again."
          : problem instanceof ApiError ? problem.message : "Could not check the token.";
        error.hidden = false;
        submit.disabled = false;
        input.select();
      }
      return;
    }

    if (form.id === "reset-form") {
      submit.disabled = true;
      try {
        await api.reset((form.elements.namedItem("forget") as HTMLInputElement).checked);
        this.app.toast("The floor has been reset. All four traders are back to $10,000.");
        form.reset();
        this.rendered = "";
        await this.app.refreshStatus();
        await this.refresh();
      } catch (error) {
        this.fail(error, "The reset did not go through");
        submit.disabled = false;
      }
      return;
    }

    const name = form.dataset.trader;
    if (!name) return;
    const model = (form.elements.namedItem("model") as HTMLSelectElement).value;
    const strategy = (form.elements.namedItem("strategy") as HTMLTextAreaElement).value.trim();
    const saved = form.querySelector<HTMLElement>(".saved")!;
    if (strategy.length < 20) {
      saved.textContent = "The strategy needs at least 20 characters.";
      saved.classList.add("bad");
      return;
    }
    submit.disabled = true;
    saved.classList.remove("bad");
    const modelField = form.elements.namedItem("model") as HTMLSelectElement;
    const strategyField = form.elements.namedItem("strategy") as HTMLTextAreaElement;
    const modelWas = Array.from(modelField.options).find((option) => option.defaultSelected)?.value;
    try {
      // Only what changed is sent, so the history shows real changes.
      if (model !== modelWas) {
        await api.setModel(name, model);
        Array.from(modelField.options).forEach((option) => (option.defaultSelected = option.value === model));
      }
      if (strategy !== strategyField.defaultValue.trim()) {
        await api.setStrategy(name, strategy);
        strategyField.defaultValue = strategy;
      }
      saved.textContent = "Saved. Applies from the next round.";
    } catch (error) {
      this.fail(error, "Could not save");
      submit.disabled = false;
    }
  }
}
