"""Technical indicators and performance statistics, as plain functions over price lists."""

import math
from .config import BENCHMARK
from .market import get_daily_bars

TRADING_DAYS = 252


def sma(closes: list[float], window: int) -> float | None:
    """Simple moving average of the last `window` closes."""
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def rsi(closes: list[float], window: int = 14) -> float | None:
    """Wilder's relative strength index, 0 to 100."""
    if len(closes) <= window:
        return None
    changes = [later - earlier for earlier, later in zip(closes, closes[1:])]
    gain = sum(max(change, 0) for change in changes[:window]) / window
    loss = sum(max(-change, 0) for change in changes[:window]) / window
    for change in changes[window:]:
        gain = (gain * (window - 1) + max(change, 0)) / window
        loss = (loss * (window - 1) + max(-change, 0)) / window
    if loss == 0:
        return 100.0
    return 100 - 100 / (1 + gain / loss)


def period_return(closes: list[float], sessions: int) -> float | None:
    """Fractional return over the last `sessions` trading days."""
    if len(closes) <= sessions:
        return None
    return closes[-1] / closes[-1 - sessions] - 1


def volatility(closes: list[float], sessions: int = 60) -> float | None:
    """Annualised standard deviation of daily returns."""
    recent = closes[-(sessions + 1):]
    if len(recent) < 20:
        return None
    returns = [later / earlier - 1 for earlier, later in zip(recent, recent[1:])]
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(TRADING_DAYS)


def max_drawdown(values: list[float]) -> float:
    """Largest fall from a peak, as a negative fraction (0 if it never fell)."""
    peak, worst = None, 0.0
    for value in values:
        if peak is None or value > peak:
            peak = value
        if peak:
            worst = min(worst, value / peak - 1)
    return worst


def _rounded(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


def _percent(value: float | None) -> float | None:
    return None if value is None else round(value * 100, 2)


def indicators(symbol: str) -> dict:
    """Trend, momentum and risk measures for a symbol from its daily closes."""
    bars = get_daily_bars(symbol, 400)
    if not bars:
        return {"symbol": symbol.upper(), "error": "No price history for this symbol"}
    closes = [bar["close"] for bar in bars]
    year = bars[-TRADING_DAYS:]
    high, low = max(bar["high"] for bar in year), min(bar["low"] for bar in year)
    last = closes[-1]
    averages = {window: sma(closes, window) for window in (20, 50, 200)}
    return {
        "symbol": symbol.upper(),
        "as_of": bars[-1]["day"],
        "close": last,
        "sma_20": _rounded(averages[20]),
        "sma_50": _rounded(averages[50]),
        "sma_200": _rounded(averages[200]),
        "above_sma_50": None if averages[50] is None else last > averages[50],
        "above_sma_200": None if averages[200] is None else last > averages[200],
        "rsi_14": _rounded(rsi(closes), 1),
        "return_1m_pct": _percent(period_return(closes, 21)),
        "return_3m_pct": _percent(period_return(closes, 63)),
        "return_12m_pct": _percent(period_return(closes, TRADING_DAYS)),
        "volatility_annual_pct": _percent(volatility(closes)),
        "high_52w": high,
        "low_52w": low,
        "below_52w_high_pct": _percent(last / high - 1),
        "sessions_available": len(closes),
    }


def compare_to_benchmark(symbol: str, days: int = 90) -> dict:
    """A symbol's return against the benchmark's over the same calendar window."""
    own, bench = get_daily_bars(symbol, days), get_daily_bars(BENCHMARK, days)
    if len(own) < 2 or len(bench) < 2:
        return {"symbol": symbol.upper(), "error": "Not enough price history to compare"}
    own_return = own[-1]["close"] / own[0]["close"] - 1
    bench_return = bench[-1]["close"] / bench[0]["close"] - 1
    return {
        "symbol": symbol.upper(),
        "benchmark": BENCHMARK,
        "from": own[0]["day"],
        "to": own[-1]["day"],
        "return_pct": _percent(own_return),
        "benchmark_return_pct": _percent(bench_return),
        "excess_return_pct": _percent(own_return - bench_return),
    }
