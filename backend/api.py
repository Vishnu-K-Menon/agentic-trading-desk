"""The trading floor's API, scheduler host and web server, all in one process.

Reading is open to anyone. Anything that changes the floor needs the admin token.

    uv run uvicorn backend.api:app --port 8000
"""

import asyncio
import hmac
import ipaddress
import sqlite3
import threading
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from datetime import datetime, timedelta
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analytics, backup, library, market
from .accounts import Account
from .config import (
    ADMIN_TOKEN, BENCHMARK, FRONTEND_DIST, INITIAL_BALANCE, LASTNAMES, MAX_POSITION_WEIGHT,
    MEMORY_DIR, MIN_CASH_WEIGHT, MODEL_CHOICES, NAMES, ON_SPACE, USE_BROWSER,
)
from .database import close_interrupted_rounds, read_log, rows, write_log, write_setting
from .floor import Floor
from .reset import ensure_traders, reset_traders
from .traders import model_label, trader_model

floor = Floor()
MAX_CHART_POINTS = 400


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_traders()
    close_interrupted_rounds()
    asyncio.get_running_loop().run_in_executor(None, floor.snapshot_all)
    floor.start()
    yield
    await floor.stop()


app = FastAPI(title="Agentic Trading Desk", lifespan=lifespan)


# Who may change things

def require_admin(request: Request):
    """Allow a change only with the admin token, or from this machine when no token is set."""
    supplied = request.headers.get("x-admin-token", "")
    if ADMIN_TOKEN:
        if hmac.compare_digest(supplied.encode(), ADMIN_TOKEN.encode()):
            return
        raise HTTPException(status_code=401, detail="The admin token is missing or wrong")
    host = request.client.host if request.client else ""
    forwarded = "x-forwarded-for" in request.headers
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False
    # A page on another site must not be able to press the buttons through the owner's browser.
    origin = request.headers.get("origin")
    same_site = request.headers.get("sec-fetch-site", "same-origin") in ("same-origin", "none")
    local_origin = not origin or urlparse(origin).hostname in ("localhost", "127.0.0.1")
    if local and not forwarded and not ON_SPACE and same_site and local_origin:
        return
    raise HTTPException(status_code=403, detail="Controls are disabled until an ADMIN_TOKEN is set")


def backup_soon():
    """Save the data off-site after a change, so a restart does not undo it."""
    if backup.enabled():
        threading.Thread(target=backup.save, daemon=True).start()


def require_trader(name: str) -> str:
    for known in NAMES:
        if known.lower() == name.lower():
            return known
    raise HTTPException(status_code=404, detail=f"Unknown trader {name}")


# Shaping data for the page

def _epoch(local_timestamp: str) -> float:
    """Account timestamps are local wall-clock strings; the page wants seconds since 1970."""
    return datetime.strptime(local_timestamp, "%Y-%m-%d %H:%M:%S").timestamp()


def _utc_epoch(utc_timestamp: str) -> float:
    return datetime.strptime(utc_timestamp + "+0000", "%Y-%m-%d %H:%M:%S%z").timestamp()


def holdings_detail(account: Account, portfolio_value: float | None = None) -> list[dict]:
    """Current holdings with price, value, weight and unrealised profit."""
    details = []
    for symbol, quantity in account.holdings.items():
        price = account.holding_price(symbol)
        cost = account.average_cost(symbol)
        details.append({
            "symbol": symbol,
            "quantity": quantity,
            "price": price,
            "avg_cost": cost,
            "market_value": price * quantity,
            "unrealized_pnl": (price - cost) * quantity,
            "unrealized_pct": (price / cost - 1) * 100 if cost else 0.0,
        })
    total = portfolio_value or account.balance + sum(h["market_value"] for h in details)
    for holding in details:
        holding["weight_pct"] = holding["market_value"] / total * 100 if total else 0.0
    return sorted(details, key=lambda h: h["market_value"], reverse=True)


def trader_summary(name: str) -> dict:
    account = Account.get(name)
    holdings = holdings_detail(account)
    value = account.balance + sum(h["market_value"] for h in holdings)
    series = [value_ for _, value_ in account.portfolio_value_time_series] + [value]
    model = trader_model(name)
    return {
        "name": name,
        "lastname": LASTNAMES[name],
        "model": model,
        "model_name": model_label(model),
        "balance": account.balance,
        "cash_pct": account.balance / value * 100 if value else 0.0,
        "portfolio_value": value,
        "pnl": value - INITIAL_BALANCE,
        "return_pct": (value / INITIAL_BALANCE - 1) * 100,
        "max_drawdown_pct": analytics.max_drawdown(series) * 100,
        "positions": len(holdings),
        "trades": len(account.transactions),
        "strategy": account.strategy,
        "holdings": holdings,
        "_account": account,
    }


def _thin(points: list, limit: int = MAX_CHART_POINTS) -> list:
    if len(points) <= limit:
        return points
    step = len(points) / limit
    return [points[int(i * step)] for i in range(limit - 1)] + [points[-1]]


def _benchmark_price_on(bars: list[dict], when: float, delayed: bool) -> float | None:
    """The benchmark's price as the floor would have seen it at that moment."""
    day = datetime.fromtimestamp(when).date()
    if delayed:
        day -= timedelta(days=1)  # delayed plans value everything at the previous close
    seen = None
    for bar in bars:
        if bar["day"] > day.isoformat():
            break
        seen = bar["close"]
    return seen


# Read routes

@app.get("/api/config")
def get_config() -> dict:
    """Fixed facts the page needs to draw itself."""
    return {
        "traders": [{"name": name, "lastname": LASTNAMES[name]} for name in NAMES],
        "models": [{"id": model, "label": label} for model, label in MODEL_CHOICES.items()],
        "limits": {"max_position_pct": MAX_POSITION_WEIGHT * 100, "min_cash_pct": MIN_CASH_WEIGHT * 100},
        "initial_balance": INITIAL_BALANCE,
        "benchmark": BENCHMARK,
        "browser_enabled": USE_BROWSER,
        "token_required": bool(ADMIN_TOKEN) or ON_SPACE,
    }


@app.get("/api/traders")
def get_traders() -> list[dict]:
    """The four traders on the floor."""
    return [
        {"name": name, "lastname": LASTNAMES[name], "model": trader_model(name), "model_name": model_label(trader_model(name))}
        for name in NAMES
    ]


@app.get("/api/market")
def get_market() -> dict:
    """Which price source is in use, and whether the market is open."""
    return {
        "source": "massive" if market.massive_api_key else "simulator",
        "delayed": market.price_is_delayed(),
        "is_market_open": market.is_market_open(),
    }


@app.get("/api/floor")
def get_floor() -> dict:
    """What the scheduler is doing."""
    return floor.status()


@app.get("/api/leaderboard")
def get_leaderboard() -> dict:
    """Every trader's results side by side, with their value history and the benchmark, rebased to 100."""
    summaries = {name: trader_summary(name) for name in NAMES}
    histories = {
        name: [(_epoch(ts), value) for ts, value in summary["_account"].portfolio_value_time_series]
        for name, summary in summaries.items()
    }
    now = datetime.now().timestamp()
    times = _thin(sorted({t for history in histories.values() for t, _ in history} | {now}))

    series: dict[str, list[float | None]] = {}
    for name, history in histories.items():
        history = history + [(now, summaries[name]["portfolio_value"])]
        values, index, last = [], 0, None
        for t in times:
            while index < len(history) and history[index][0] <= t:
                last = history[index][1]
                index += 1
            values.append(None if last is None else round(last / INITIAL_BALANCE * 100, 3))
        series[name] = values

    benchmark_return = None
    try:
        bars = market.get_daily_bars(BENCHMARK, 400)
        delayed = market.price_is_delayed()
        prices = [_benchmark_price_on(bars, t, delayed) for t in times]
        base = next((price for price in prices if price), None)
        series[BENCHMARK] = [None if not price or not base else round(price / base * 100, 3) for price in prices]
        if base and prices[-1]:
            benchmark_return = (prices[-1] / base - 1) * 100
    except Exception:
        series[BENCHMARK] = [None] * len(times)

    reviews = rows("SELECT name, decision, COUNT(*) AS n FROM risk_reviews GROUP BY name, decision")
    standings = []
    for name, summary in summaries.items():
        counts = {row["decision"]: row["n"] for row in reviews if row["name"] == name.lower()}
        standing = {key: value for key, value in summary.items() if key not in ("_account", "holdings", "strategy")}
        standing["risk"] = {decision: counts.get(decision, 0) for decision in ("approve", "resize", "reject")}
        standing["vs_benchmark_pct"] = None if benchmark_return is None else summary["return_pct"] - benchmark_return
        standings.append(standing)
    standings.sort(key=lambda s: s["portfolio_value"], reverse=True)
    return {
        "standings": standings,
        "benchmark": {"symbol": BENCHMARK, "return_pct": benchmark_return},
        "chart": {"t": [round(t) for t in times], "series": series},
    }


@app.get("/api/traders/{name}")
def get_trader(name: str) -> dict:
    """A trader's full state: value, holdings, trades with the risk desk's decision, and history."""
    name = require_trader(name)
    summary = trader_summary(name)
    account = summary.pop("_account")
    history = [(_epoch(ts), value) for ts, value in account.portfolio_value_time_series]
    history.append((datetime.now().timestamp(), summary["portfolio_value"]))
    transactions = [
        {
            "ts": _epoch(t.timestamp), "symbol": t.symbol, "quantity": t.quantity, "price": t.price,
            "value": abs(t.quantity) * t.price, "rationale": t.rationale,
        }
        for t in reversed(account.transactions)
    ]
    return summary | {
        "transactions": transactions,
        "time_series": [{"t": round(t), "value": value} for t, value in _thin(history)],
    }


@app.get("/api/traders/{name}/logs")
def get_trader_logs(name: str, last_n: int = 40, after_id: int = 0) -> list[dict]:
    """Recent activity for a trader, oldest first. Pass after_id to fetch only what is new."""
    name = require_trader(name)
    return [
        {"id": row["id"], "ts": _utc_epoch(row["datetime"]), "type": row["type"], "message": row["message"]}
        for row in read_log(name, max(1, min(last_n, 500)), after_id)
    ]


@app.get("/api/traders/{name}/rounds")
def get_trader_rounds(name: str, limit: int = 30) -> list[dict]:
    """The trader's sessions, newest first, each with its closing appraisal or its error."""
    name = require_trader(name)
    return rows(
        "SELECT round_no, kind, model, started_at, ended_at, final_output, error FROM rounds "
        "WHERE name = ? ORDER BY id DESC LIMIT ?",
        (name.lower(), max(1, min(limit, 200))),
    )


@app.get("/api/traders/{name}/risk")
def get_trader_risk(name: str, limit: int = 60) -> list[dict]:
    """The risk desk's decisions on this trader's proposals, newest first."""
    name = require_trader(name)
    return rows(
        "SELECT created_at, symbol, side, requested, approved, decision, reason, rationale, source "
        "FROM risk_reviews WHERE name = ? ORDER BY id DESC LIMIT ?",
        (name.lower(), max(1, min(limit, 300))),
    )


@app.get("/api/traders/{name}/strategy")
def get_trader_strategy(name: str) -> dict:
    """The current strategy and every change the trader (or an admin) has made to it."""
    name = require_trader(name)
    changes = rows(
        "SELECT created_at, strategy, source FROM strategy_changes WHERE name = ? ORDER BY id DESC LIMIT 30",
        (name.lower(),),
    )
    return {"strategy": Account.get(name).strategy, "changes": changes}


@app.get("/api/traders/{name}/memory")
def get_trader_memory(name: str) -> dict:
    """What the trader has remembered: its knowledge graph and its notes in the research library."""
    name = require_trader(name)
    graph = {"entities": [], "relations": []}
    path = MEMORY_DIR / f"{name}.db"
    if path.exists():
        try:
            with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5) as conn:
                conn.row_factory = sqlite3.Row
                observations: dict[str, list[str]] = {}
                for row in conn.execute("SELECT entity_name, content FROM observations ORDER BY id"):
                    observations.setdefault(row["entity_name"], []).append(row["content"])
                graph["entities"] = [
                    {"name": row["name"], "type": row["entity_type"], "observations": observations.get(row["name"], [])}
                    for row in conn.execute("SELECT name, entity_type FROM entities ORDER BY created_at DESC LIMIT 200")
                ]
                graph["relations"] = [
                    {"source": row["source"], "target": row["target"], "type": row["relation_type"]}
                    for row in conn.execute("SELECT source, target, relation_type FROM relations LIMIT 400")
                ]
        except sqlite3.Error:
            pass  # the graph is being written to, or has not been created yet
    notes = [note | {"symbols": [s for s in note["symbols"].split(",") if s]} for note in library.list_notes(name)]
    library_size = rows("SELECT COUNT(*) AS n FROM research_notes")[0]["n"]
    return {"graph": graph, "notes": notes, "library_size": library_size}


# Change routes (admin only)

class ModelChange(BaseModel):
    model: str


class StrategyChange(BaseModel):
    strategy: str = Field(min_length=20, max_length=4000)


class ResetRequest(BaseModel):
    forget_memory: bool = False


@app.post("/api/admin/check", dependencies=[Depends(require_admin)])
def check_admin() -> dict:
    """Lets the page confirm a token before showing the controls."""
    return {"ok": True}


@app.post("/api/floor/run", dependencies=[Depends(require_admin)])
async def run_round_now() -> dict:
    if not floor.request_round():
        raise HTTPException(status_code=409, detail="A round is already running")
    return floor.status() | {"running": True}


@app.post("/api/floor/pause", dependencies=[Depends(require_admin)])
def pause_floor() -> dict:
    floor.pause()
    backup_soon()
    return floor.status()


@app.post("/api/floor/resume", dependencies=[Depends(require_admin)])
def resume_floor() -> dict:
    floor.resume()
    backup_soon()
    return floor.status()


@app.post("/api/floor/reset", dependencies=[Depends(require_admin)])
def reset_floor(request: ResetRequest) -> dict:
    if floor.running:
        raise HTTPException(status_code=409, detail="Wait for the current round to finish before resetting")
    reset_traders(request.forget_memory)
    floor.snapshot_all()
    backup_soon()
    return floor.status()


@app.put("/api/traders/{name}/model", dependencies=[Depends(require_admin)])
def set_trader_model(name: str, change: ModelChange) -> dict:
    name = require_trader(name)
    if change.model not in MODEL_CHOICES:
        raise HTTPException(status_code=422, detail="That model is not on the list")
    write_setting(f"model:{name.lower()}", change.model)
    write_log(name, "account", f"Model changed to {model_label(change.model)}")
    backup_soon()
    return {"name": name, "model": change.model, "model_name": model_label(change.model)}


@app.put("/api/traders/{name}/strategy", dependencies=[Depends(require_admin)])
def set_trader_strategy(name: str, change: StrategyChange) -> dict:
    name = require_trader(name)
    Account.get(name).change_strategy(change.strategy.strip(), source="admin")
    backup_soon()
    return {"name": name, "strategy": change.strategy.strip()}


# The built frontend, when there is one (in development Vite serves it instead)

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        file = (FRONTEND_DIST / path).resolve()
        if path and file.is_file() and FRONTEND_DIST.resolve() in file.parents:
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
