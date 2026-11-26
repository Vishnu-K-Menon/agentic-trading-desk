// Formatting and small DOM helpers shared by every view.

const money2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
const money0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const whole = new Intl.NumberFormat("en-US");

export const usd = (value: number) => money2.format(value);
export const usdRound = (value: number) => money0.format(value);
export const count = (value: number) => whole.format(value);

/** A change in dollars with its sign, e.g. +$12.40 or -$3.10. */
export function signedUsd(value: number): string {
  const text = money2.format(Math.abs(value));
  return (value > 0 ? "+" : value < 0 ? "−" : "") + text;
}

/** A change in percent with its sign, e.g. +1.24%. */
export function signedPct(value: number, places = 2): string {
  const text = Math.abs(value).toFixed(places) + "%";
  return (value > 0 ? "+" : value < 0 ? "−" : "") + text;
}

export const pct = (value: number, places = 1) => value.toFixed(places) + "%";

/** The colour class for a change: good, bad, or neutral when it is zero. */
export function tone(value: number | null | undefined): string {
  if (!value || Math.abs(value) < 0.005) return "flat";
  return value > 0 ? "up" : "down";
}

const timeFormat = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });
const timeSeconds = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
const dayFormat = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

export const clock = (epoch: number) => timeFormat.format(new Date(epoch * 1000));
export const clockSeconds = (epoch: number) => timeSeconds.format(new Date(epoch * 1000));

/** "Today 14:02", "Yesterday 09:30" or "Nov 21, 15:10". */
export function when(epoch: number): string {
  const date = new Date(epoch * 1000);
  const days = Math.round((startOfDay(new Date()) - startOfDay(date)) / 86_400_000);
  if (days === 0) return `Today ${timeFormat.format(date)}`;
  if (days === 1) return `Yesterday ${timeFormat.format(date)}`;
  return `${dayFormat.format(date)}, ${timeFormat.format(date)}`;
}

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** How long until a moment, in words: "in 42 min", "in 1 h 5 min", "now". */
export function until(epoch: number): string {
  const seconds = Math.round(epoch - Date.now() / 1000);
  if (seconds <= 30) return "now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `in ${minutes} min`;
  return `in ${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

export function duration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  return total < 60 ? `${total} s` : `${Math.floor(total / 60)} m ${total % 60} s`;
}

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

/** Escape text for use inside an HTML template. Everything from the API goes through this. */
export const esc = (text: unknown) => String(text ?? "").replace(/[&<>"']/g, (char) => ESCAPES[char]);

export function $(selector: string, root: ParentNode = document): HTMLElement {
  const found = root.querySelector<HTMLElement>(selector);
  if (!found) throw new Error(`Missing element ${selector}`);
  return found;
}

/** Each trader keeps one colour everywhere it is drawn. */
export const TRADER_COLORS: Record<string, string> = {
  Warren: "var(--trader-1)",
  George: "var(--trader-2)",
  Ray: "var(--trader-3)",
  Cathie: "var(--trader-4)",
};

export const traderColor = (name: string) => TRADER_COLORS[name] ?? "var(--text)";

export const DECISION_LABEL: Record<string, string> = { approve: "Approved", resize: "Resized", reject: "Rejected" };
