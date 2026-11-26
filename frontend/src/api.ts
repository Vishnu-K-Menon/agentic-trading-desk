// Typed access to the backend. Reads are open; changes carry the admin token when one is set.

export interface Config {
  traders: { name: string; lastname: string }[];
  models: { id: string; label: string }[];
  limits: { max_position_pct: number; min_cash_pct: number };
  initial_balance: number;
  benchmark: string;
  browser_enabled: boolean;
  token_required: boolean;
}

export interface Market {
  source: "massive" | "simulator";
  delayed: boolean;
  is_market_open: boolean;
}

export interface FloorStatus {
  running: boolean;
  paused: boolean;
  scheduler_enabled: boolean;
  round_no: number;
  next_run_at: number | null;
  interval_minutes: number;
  rounds_today: number;
  max_rounds_per_day: number;
  last_skip_reason: string;
}

export interface Standing {
  name: string;
  lastname: string;
  model: string;
  model_name: string;
  balance: number;
  cash_pct: number;
  portfolio_value: number;
  pnl: number;
  return_pct: number;
  max_drawdown_pct: number;
  positions: number;
  trades: number;
  risk: { approve: number; resize: number; reject: number };
  vs_benchmark_pct: number | null;
}

export interface Leaderboard {
  standings: Standing[];
  benchmark: { symbol: string; return_pct: number | null };
  chart: { t: number[]; series: Record<string, (number | null)[]> };
}

export interface Holding {
  symbol: string;
  quantity: number;
  price: number;
  avg_cost: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pct: number;
  weight_pct: number;
}

export interface Trade {
  ts: number;
  symbol: string;
  quantity: number;
  price: number;
  value: number;
  rationale: string;
}

export interface TraderDetail extends Omit<Standing, "risk" | "vs_benchmark_pct"> {
  strategy: string;
  holdings: Holding[];
  transactions: Trade[];
  time_series: { t: number; value: number }[];
}

export interface LogRow {
  id: number;
  ts: number;
  type: string;
  message: string;
}

export interface Round {
  round_no: number;
  kind: string;
  model: string;
  started_at: number;
  ended_at: number | null;
  final_output: string | null;
  error: string | null;
}

export interface RiskReview {
  created_at: number;
  symbol: string;
  side: string;
  requested: number;
  approved: number;
  decision: "approve" | "resize" | "reject";
  reason: string;
  rationale: string;
  source: string;
}

export interface StrategyHistory {
  strategy: string;
  changes: { created_at: number; strategy: string; source: string }[];
}

export interface Memory {
  graph: {
    entities: { name: string; type: string; observations: string[] }[];
    relations: { source: string; target: string; type: string }[];
  };
  notes: { id: string; created_at: number; trader: string; topic: string; symbols: string[]; text: string }[];
  library_size: number;
}

const TOKEN_KEY = "atd-admin-token";

export const adminToken = {
  get: () => sessionStorage.getItem(TOKEN_KEY) ?? "",
  set: (token: string) => sessionStorage.setItem(TOKEN_KEY, token),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["content-type"] = "application/json";
  if (method !== "GET" && adminToken.get()) headers["x-admin-token"] = adminToken.get();
  let response: Response;
  try {
    response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "The trading floor is not reachable");
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
      else if (Array.isArray(data.detail) && data.detail[0]?.msg) detail = data.detail[0].msg;
    } catch {
      // keep the generic message
    }
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

const trader = (name: string) => `/api/traders/${encodeURIComponent(name.toLowerCase())}`;

export const api = {
  config: () => request<Config>("/api/config"),
  market: () => request<Market>("/api/market"),
  floor: () => request<FloorStatus>("/api/floor"),
  leaderboard: () => request<Leaderboard>("/api/leaderboard"),
  trader: (name: string) => request<TraderDetail>(trader(name)),
  logs: (name: string, afterId = 0, lastN = 200) =>
    request<LogRow[]>(`${trader(name)}/logs?last_n=${lastN}&after_id=${afterId}`),
  rounds: (name: string) => request<Round[]>(`${trader(name)}/rounds`),
  risk: (name: string, limit = 60) => request<RiskReview[]>(`${trader(name)}/risk?limit=${limit}`),
  strategy: (name: string) => request<StrategyHistory>(`${trader(name)}/strategy`),
  memory: (name: string) => request<Memory>(`${trader(name)}/memory`),

  checkAdmin: () => request<{ ok: boolean }>("/api/admin/check", "POST"),
  runRound: () => request<FloorStatus>("/api/floor/run", "POST"),
  pause: () => request<FloorStatus>("/api/floor/pause", "POST"),
  resume: () => request<FloorStatus>("/api/floor/resume", "POST"),
  reset: (forgetMemory: boolean) => request<FloorStatus>("/api/floor/reset", "POST", { forget_memory: forgetMemory }),
  setModel: (name: string, model: string) => request<{ model_name: string }>(`${trader(name)}/model`, "PUT", { model }),
  setStrategy: (name: string, strategy: string) => request<{ strategy: string }>(`${trader(name)}/strategy`, "PUT", { strategy }),
};
