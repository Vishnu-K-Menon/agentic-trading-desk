"""MCP server for company fundamentals: profile, financial statements and SEC filings."""

import asyncio
from mcp.server.fastmcp import FastMCP
from . import fundamentals

mcp = FastMCP("fundamentals_server")


@mcp.tool()
async def get_company_profile(symbol: str) -> dict:
    """What a company or fund is: name, type, industry, business description, market value and size.

    Args:
        symbol: the ticker symbol of the stock or ETF
    """
    return await asyncio.to_thread(fundamentals.company_profile, symbol)


@mcp.tool()
async def get_financials(symbol: str) -> dict:
    """The last four years of a company's reported financials, from its annual SEC filings:
    revenue, operating income, net income, diluted EPS, cash flow, cash, debt and equity,
    plus net margin, revenue growth and price to earnings. Not available for ETFs.

    Args:
        symbol: the ticker symbol of the company
    """
    return await asyncio.to_thread(fundamentals.financials, symbol)


@mcp.tool()
async def list_recent_filings(symbol: str) -> dict:
    """A company's most recent SEC filings (annual 10-K, quarterly 10-Q, current 8-K), with a
    link to each document that can be read with the page-reading tools.

    Args:
        symbol: the ticker symbol of the company
    """
    return await asyncio.to_thread(fundamentals.recent_filings, symbol)


if __name__ == "__main__":
    mcp.run(transport="stdio")
