"""MCP server for market data: prices, daily history, indicators and benchmark comparison."""

import asyncio
from mcp.server.fastmcp import FastMCP
from . import analytics
from .market import get_share_price, get_daily_bars, price_is_delayed

mcp = FastMCP("market_server")


@mcp.tool()
async def lookup_share_price(symbol: str) -> dict:
    """The price a trade in this symbol would execute at right now (before the spread).

    Args:
        symbol: the ticker symbol of the stock or ETF
    """
    price = await asyncio.to_thread(get_share_price, symbol)
    if not price:
        return {"symbol": symbol.upper(), "error": "Unrecognized symbol"}
    basis = "previous trading day's close" if price_is_delayed() else "latest price"
    return {"symbol": symbol.upper(), "price": price, "basis": basis}


@mcp.tool()
async def get_price_history(symbol: str, days: int = 30) -> dict:
    """Daily closing prices for a symbol, oldest first.

    Args:
        symbol: the ticker symbol of the stock or ETF
        days: how many calendar days back to go, up to 365
    """
    bars = await asyncio.to_thread(get_daily_bars, symbol, max(2, min(days, 365)))
    step = max(1, len(bars) // 90)  # keep long histories readable
    closes = [{"day": bar["day"], "close": bar["close"]} for bar in bars[::-1][::step][::-1]]
    return {"symbol": symbol.upper(), "sessions": len(bars), "closes": closes}


@mcp.tool()
async def get_indicators(symbol: str) -> dict:
    """Trend, momentum and risk measures for a symbol: 20, 50 and 200 day moving averages,
    RSI, returns over 1, 3 and 12 months, annual volatility and distance from the 52 week high.

    Args:
        symbol: the ticker symbol of the stock or ETF
    """
    return await asyncio.to_thread(analytics.indicators, symbol)


@mcp.tool()
async def compare_to_benchmark(symbol: str, days: int = 90) -> dict:
    """A symbol's return against the S&P 500 (SPY) over the same period.

    Args:
        symbol: the ticker symbol of the stock or ETF
        days: how many calendar days back to compare, up to 365
    """
    return await asyncio.to_thread(analytics.compare_to_benchmark, symbol, max(5, min(days, 365)))


if __name__ == "__main__":
    mcp.run(transport="stdio")
