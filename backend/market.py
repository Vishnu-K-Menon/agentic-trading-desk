"""Share prices and daily price history, from Massive or a simulator when no key is set.

Real and simulated prices are never mixed: with a key set, a price is either real
(fresh or last known) or the lookup fails. Everything fetched is cached in the database,
so the API and every MCP server process share it and stay inside Massive's rate limit.

On a plan without live prices (the free plan), one grouped daily request fetches the
previous trading day's close for every US ticker, which then serves every lookup.
"""

import sys
import time
from datetime import date, datetime, timedelta, timezone
from massive import RESTClient
from .config import MASSIVE_API_KEY
from .market_simulator import simulated_price
from .database import (
    read_price, write_prices, read_meta, write_meta, read_bars, write_bars, extend_bars,
    claim_api_slot, record_api_call,
)

massive_api_key = MASSIVE_API_KEY

LIVE_TTL = 60  # seconds a live price stays fresh
DAILY_TTL = 6 * 60 * 60  # seconds before checking for a newer daily close
RETRY_AFTER = 60  # seconds to wait after a failed Massive call before trying again
PROBE_EVERY = 24 * 60 * 60  # how often to re-check whether the plan has live prices
MARKET_STATUS_TTL = 60
LOOKBACK_DAYS = 7  # how far back to look for the last trading day
HISTORY_DAYS = 420  # calendar days of daily bars kept per symbol
FREE_PLAN_CALLS_PER_MINUTE = 4  # Massive allows 5; leave one spare
MAX_THROTTLE_WAIT = 20  # seconds to wait for a free slot before giving up


class RateLimited(RuntimeError):
    """Massive's request allowance is used up for the moment."""


def _client() -> RESTClient:
    return RESTClient(massive_api_key)


def _age(meta) -> float:
    """Seconds since a market_meta row was written; infinite if it never was."""
    return time.time() - meta[1] if meta else float("inf")


def _plan_has_live_prices() -> bool:
    """Whether this key can fetch live prices; remembered so we only ask once a day."""
    live = read_meta("live_plan")
    if live and _age(live) < PROBE_EVERY:
        return bool(live[0])
    return True  # unknown: the next live lookup settles it


def _throttle(max_wait: float = MAX_THROTTLE_WAIT):
    """On a rate-limited plan, take a request slot, waiting briefly for one if need be.

    The count is kept in the database, so every process shares the one limit. Gives up
    with RateLimited rather than hold the caller for long.
    """
    live = read_meta("live_plan")
    if live and live[0]:
        return  # plans with live prices are not rate limited
    deadline = time.time() + max_wait
    while True:
        free_at = claim_api_slot("massive", FREE_PLAN_CALLS_PER_MINUTE)
        if not free_at:
            return
        if free_at > deadline:
            raise RateLimited("the market data rate limit is reached; try again in a minute")
        time.sleep(max(0.5, free_at - time.time()))


# Current prices

def _last_trade(client: RESTClient, symbol: str) -> float:
    return float(client.get_last_trade(symbol).price)


def _snapshot(client: RESTClient, symbol: str) -> float:
    snapshot = client.get_snapshot_ticker("stocks", symbol)
    return float(snapshot.min.close or snapshot.prev_day.close)


# Live prices, best first. Plans without them reject both calls.
live_price_methods = [_last_trade, _snapshot]


def get_share_price(symbol: str) -> float:
    """Return the current price for a symbol, from Massive or the simulator.

    With a Massive key, returns 0 for a symbol Massive does not know, and raises
    if no real price can be had at all.
    """
    if not massive_api_key:
        return simulated_price(symbol)
    return get_share_price_massive(symbol.strip().upper())


def get_share_price_massive(symbol: str) -> float:
    """Best real price the plan allows, served from the shared cache where possible."""
    if _plan_has_live_prices():
        cached = read_price(symbol)
        if cached and time.time() - cached[1] < LIVE_TTL:
            return cached[0]
        price = _live_price(symbol)
        if price is not None:
            write_prices({symbol: price})
            return price
    return _daily_price(symbol)


def _live_price(symbol: str) -> float | None:
    """A live price, or None if the plan does not allow one or the call failed."""
    client = _client()
    errors = []
    for method in live_price_methods:
        try:
            price = method(client, symbol)
            write_meta("live_plan", 1)
            return price
        except Exception as e:
            errors.append(str(e))
    if any("NOT_AUTHORIZED" in error for error in errors):
        write_meta("live_plan", 0)
    return None


def _ensure_daily():
    """Refresh the whole market's daily closes if they are due."""
    if _age(read_meta("daily_refreshed")) > DAILY_TTL and _age(read_meta("daily_attempt")) > RETRY_AFTER:
        try:
            _refresh_daily_prices()
        except Exception as e:
            print(f"Massive daily prices unavailable ({e}); using last known prices", file=sys.stderr)


def _daily_price(symbol: str) -> float:
    """The last trading day's close, refreshing the whole market in one request."""
    _ensure_daily()
    cached = read_price(symbol)
    if cached:
        return cached[0]
    if read_meta("daily_refreshed"):
        return 0.0  # the market is loaded and this symbol is not in it
    raise RuntimeError(f"No Massive price available for {symbol}")


def _refresh_daily_prices() -> None:
    """Cache the close of every US ticker for the most recent trading day."""
    write_meta("daily_attempt", 1)
    client = _client()
    now = datetime.now(timezone.utc)
    # Today's bars exist only after the US close, so do not spend a request on them before then.
    first = 0 if now.hour >= 22 else 1
    for days_back in range(first, LOOKBACK_DAYS + 1):
        candidate = now.date() - timedelta(days=days_back)
        if candidate.weekday() >= 5:
            continue  # the market is shut at weekends; no need to ask
        day = candidate.isoformat()
        try:
            _throttle(max_wait=70)  # every price depends on this one request, so it may wait its turn
            bars = client.get_grouped_daily_aggs(day)
        except Exception as e:
            if "NOT_AUTHORIZED" in str(e):
                continue  # today's bars are not available on this plan until the day ends
            raise
        prices = {bar.ticker: float(bar.close) for bar in bars if bar.close}
        if prices:
            write_prices(prices)
            # The same request extends the stored history of every symbol we follow.
            extend_bars(day, {
                bar.ticker: (bar.open, bar.high, bar.low, bar.close, bar.volume) for bar in bars if bar.close
            })
            write_meta("daily_day", date.fromisoformat(day).toordinal())
            write_meta("daily_refreshed", 1)
            return
    raise RuntimeError("no trading day found")


def price_is_delayed() -> bool:
    """True when prices are the previous trading day's close rather than live."""
    return bool(massive_api_key) and not _plan_has_live_prices()


# Daily history

def get_daily_bars(symbol: str, days: int = 365) -> list[dict]:
    """Daily bars for the last `days` calendar days, oldest first.

    Each bar is {day, open, high, low, close, volume}. A history costs one Massive call
    the first time a symbol is asked for; after that the daily whole-market refresh
    keeps it up to date, and lookups are served from the database.
    """
    symbol = symbol.strip().upper()
    since = (date.today() - timedelta(days=days)).isoformat()
    if not massive_api_key:
        return [bar for bar in _simulated_bars(symbol) if bar["day"] >= since]
    key = f"bars:{symbol}"
    live = _plan_has_live_prices()
    if not live:
        _ensure_daily()
    latest = read_bars(symbol)[-1:]
    market_day = read_meta("daily_day")
    if not latest or live:
        stale = _age(read_meta(key)) > DAILY_TTL
    else:
        stale = bool(market_day) and date.fromisoformat(latest[0]["day"]).toordinal() < market_day[0] - 3
    if stale and _age(read_meta(f"{key}:attempt")) > RETRY_AFTER:
        try:
            _throttle()
            write_meta(f"{key}:attempt", 1)
            start = (date.today() - timedelta(days=HISTORY_DAYS)).isoformat()
            fetched = _client().list_aggs(symbol, 1, "day", start, date.today().isoformat(), limit=5000)
            bars = [
                {
                    "day": datetime.fromtimestamp(bar.timestamp / 1000, timezone.utc).date().isoformat(),
                    "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in fetched
                if bar.close
            ]
            if bars:
                write_bars(symbol, bars)
            write_meta(key, 1)
        except RateLimited:
            if not latest:
                raise RuntimeError(
                    f"The price history for {symbol} is not loaded yet and the market data rate limit is reached. "
                    "Use lookup_share_price for now and ask for the history of this symbol again in a minute."
                )
        except Exception as e:
            print(f"Massive history unavailable for {symbol} ({e}); using stored bars", file=sys.stderr)
    return read_bars(symbol, since)


def _simulated_bars(symbol: str) -> list[dict]:
    bars = []
    for days_back in range(HISTORY_DAYS, 0, -1):
        day = date.today() - timedelta(days=days_back)
        if day.weekday() >= 5:
            continue
        close = simulated_price(symbol, datetime(day.year, day.month, day.day, 21, tzinfo=timezone.utc))
        open_ = simulated_price(symbol, datetime(day.year, day.month, day.day, 14, 30, tzinfo=timezone.utc))
        bars.append({
            "day": day.isoformat(), "open": open_, "high": max(open_, close), "low": min(open_, close),
            "close": close, "volume": 0,
        })
    return bars


# Market hours

def is_market_open() -> bool:
    """Whether the US market is open; True on simulated data or if Massive is unreachable."""
    if not massive_api_key:
        return True
    status = read_meta("market_open")
    if status and _age(status) < MARKET_STATUS_TTL:
        return bool(status[0])
    try:
        _throttle(max_wait=0)
        is_open = _client().get_market_status().market == "open"
    except Exception:
        # Keep the last answer we had (open, if we never had one) and do not ask again for a minute.
        is_open = bool(status[0]) if status else True
    write_meta("market_open", int(is_open))
    return is_open
