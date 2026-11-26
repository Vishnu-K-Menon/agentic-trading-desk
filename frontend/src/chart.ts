// A small SVG line chart drawn to the floor's rules: straight 2px lines, a few faint
// horizontal gridlines with round ticks, no axis lines, a label at the end of each line,
// and a cursor that reads every series at once. Colours come from CSS, so themes just work.

import { esc } from "./format";

export interface Series {
  name: string;
  values: (number | null)[];
  color: string;
  dashed?: boolean;
}

export interface ChartOptions {
  height?: number;
  format: (value: number) => string;
  endLabels?: boolean;
  emptyText?: string;
}

const dayLabel = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const timeLabel = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const fullLabel = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

/** Round tick values that enclose [low, high], about `target` of them. */
function niceTicks(low: number, high: number, target = 4): number[] {
  if (high - low < 1e-9) {
    const pad = Math.max(Math.abs(low) * 0.002, 0.01);
    low -= pad;
    high += pad;
  }
  const rough = (high - low) / target;
  const power = Math.pow(10, Math.floor(Math.log10(rough)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? 10 * power;
  const first = Math.floor(low / step) * step;
  const ticks: number[] = [];
  for (let tick = first; tick < high + step - 1e-9; tick += step) ticks.push(Number(tick.toPrecision(12)));
  return ticks;
}

export class LineChart {
  private times: number[] = [];
  private series: Series[] = [];
  private readonly observer: ResizeObserver;
  private width = 0;
  private height = 0;

  constructor(private readonly host: HTMLElement, private readonly options: ChartOptions) {
    host.classList.add("chart");
    this.observer = new ResizeObserver(() => {
      if (Math.abs(host.clientWidth - this.width) > 1 || Math.abs(this.targetHeight() - this.height) > 1) this.draw();
    });
    this.observer.observe(host);
  }

  set(times: number[], series: Series[]): void {
    this.times = times;
    this.series = series;
    this.draw();
  }

  destroy(): void {
    this.observer.disconnect();
  }

  /** The chart is as tall as its card allows, and never shorter than its set height. */
  private targetHeight(): number {
    const set = this.options.height ?? 240;
    const room = this.host.parentElement?.classList.contains("grow") ? this.host.clientHeight : 0;
    return Math.max(set, Math.floor(room));
  }

  private draw(): void {
    const host = this.host;
    this.width = host.clientWidth;
    const height = this.targetHeight();
    this.height = height;
    const drawn = this.series.filter((s) => s.values.some((v) => v !== null));
    if (!this.width || this.times.length < 2 || !drawn.length) {
      host.innerHTML = `<p class="empty" style="height:${height}px">${esc(this.options.emptyText ?? "No history yet.")}</p>`;
      return;
    }

    const values = drawn.flatMap((s) => s.values.filter((v): v is number => v !== null));
    const ticks = niceTicks(Math.min(...values), Math.max(...values));
    const [yMin, yMax] = [ticks[0], ticks[ticks.length - 1]];
    const tickText = ticks.map((tick) => this.options.format(tick));
    const narrow = this.width < 520;

    const left = Math.max(...tickText.map((text) => text.length)) * 6.6 + 14;
    const right = this.options.endLabels && !narrow ? 92 : 12;
    const top = 10;
    const bottom = 26;
    const plotW = this.width - left - right;
    const plotH = height - top - bottom;
    const [tMin, tMax] = [this.times[0], this.times[this.times.length - 1]];
    const x = (t: number) => left + ((t - tMin) / (tMax - tMin || 1)) * plotW;
    const y = (v: number) => top + (1 - (v - yMin) / (yMax - yMin)) * plotH;

    let svg = `<svg viewBox="0 0 ${this.width} ${height}" width="${this.width}" height="${height}" role="img" aria-label="${esc(
      drawn.map((s) => `${s.name} ${this.options.format(lastValue(s) ?? 0)}`).join(", "),
    )}">`;

    ticks.forEach((tick, i) => {
      const py = y(tick).toFixed(1);
      svg += `<line class="grid" x1="${left}" x2="${left + plotW}" y1="${py}" y2="${py}"/>`;
      svg += `<text class="tick" x="${left - 8}" y="${py}" dy="0.32em" text-anchor="end">${esc(tickText[i])}</text>`;
    });

    // Time labels: days when the window is long, clock times when it is short.
    const longWindow = tMax - tMin > 36 * 3600;
    const labelCount = narrow ? 3 : 5;
    for (let i = 0; i < labelCount; i++) {
      const t = tMin + ((tMax - tMin) * i) / (labelCount - 1);
      const text = (longWindow ? dayLabel : timeLabel).format(new Date(t * 1000));
      const anchor = i === 0 ? "start" : i === labelCount - 1 ? "end" : "middle";
      svg += `<text class="tick" x="${x(t).toFixed(1)}" y="${height - 6}" text-anchor="${anchor}">${esc(text)}</text>`;
    }

    for (const s of drawn) {
      let path = "";
      let pen = "M";
      s.values.forEach((value, i) => {
        if (value === null) return;
        path += `${pen}${x(this.times[i]).toFixed(1)} ${y(value).toFixed(1)}`;
        pen = "L";
      });
      svg += `<path class="line${s.dashed ? " dashed" : ""}" d="${path}" style="stroke:${s.color}"/>`;
    }

    if (this.options.endLabels && !narrow) {
      // Labels sit beside the end of their line; nudge apart any that would overlap.
      const labels = drawn
        .map((s) => ({ s, value: lastValue(s) as number }))
        .map((label) => ({ ...label, y: y(label.value) }))
        .sort((a, b) => a.y - b.y);
      for (let i = 1; i < labels.length; i++) labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 15);
      const overflow = labels.length ? labels[labels.length - 1].y - (top + plotH) : 0;
      if (overflow > 0) labels.forEach((label) => (label.y -= overflow));
      for (const { s, value, y: ly } of labels) {
        svg += `<text class="end-label" x="${left + plotW + 8}" y="${ly.toFixed(1)}" dy="0.32em" style="fill:${s.color}">${esc(
          s.name,
        )} <tspan class="end-value">${esc(this.options.format(value))}</tspan></text>`;
      }
    }

    svg += `<line class="cursor" y1="${top}" y2="${top + plotH}" x1="0" x2="0" visibility="hidden"/>`;
    svg += `<rect class="hit" x="${left}" y="${top}" width="${plotW}" height="${plotH}" fill="transparent"/></svg>`;
    host.innerHTML = svg + `<div class="chart-tip" hidden></div>`;
    host.querySelector("svg")!.style.position = "absolute";
    host.style.minHeight = `${this.options.height ?? 240}px`;

    const cursor = host.querySelector<SVGLineElement>(".cursor")!;
    const tip = host.querySelector<HTMLElement>(".chart-tip")!;
    const hit = host.querySelector<SVGRectElement>(".hit")!;
    const show = (clientX: number) => {
      const bounds = host.getBoundingClientRect();
      const t = tMin + ((clientX - bounds.left - left) / plotW) * (tMax - tMin);
      let nearest = 0;
      this.times.forEach((time, i) => {
        if (Math.abs(time - t) < Math.abs(this.times[nearest] - t)) nearest = i;
      });
      const px = x(this.times[nearest]);
      cursor.setAttribute("x1", px.toFixed(1));
      cursor.setAttribute("x2", px.toFixed(1));
      cursor.setAttribute("visibility", "visible");
      const rows = drawn
        .filter((s) => s.values[nearest] !== null)
        .sort((a, b) => (b.values[nearest] as number) - (a.values[nearest] as number))
        .map(
          (s) =>
            `<div><span class="dot" style="background:${s.color}"></span>${esc(s.name)}<b>${esc(
              this.options.format(s.values[nearest] as number),
            )}</b></div>`,
        )
        .join("");
      tip.innerHTML = `<time>${esc(fullLabel.format(new Date(this.times[nearest] * 1000)))}</time>${rows}`;
      tip.hidden = false;
      const flip = px > this.width / 2;
      tip.style.left = flip ? "" : `${px + 12}px`;
      tip.style.right = flip ? `${this.width - px + 12}px` : "";
    };
    const hide = () => {
      cursor.setAttribute("visibility", "hidden");
      tip.hidden = true;
    };
    hit.addEventListener("pointermove", (event) => show(event.clientX));
    hit.addEventListener("pointerleave", hide);
    hit.addEventListener("pointerdown", (event) => show(event.clientX));
  }
}

function lastValue(series: Series): number | null {
  for (let i = series.values.length - 1; i >= 0; i--) if (series.values[i] !== null) return series.values[i];
  return null;
}
