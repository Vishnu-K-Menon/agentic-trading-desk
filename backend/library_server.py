"""MCP server for the firm's shared research library (vector memory on Qdrant)."""

from mcp.server.fastmcp import FastMCP
from . import library

mcp = FastMCP("library_server")


@mcp.tool()
async def search_research(query: str, symbol: str = "") -> dict:
    """Search the firm's research library for earlier findings, matched by meaning rather
    than exact words. Every trader's researcher contributes to it. Search it before going
    to the web, so that past work is reused.

    Args:
        query: what you want to know, in plain words
        symbol: optionally, only return notes tagged with this ticker symbol
    """
    return library.search_research(query, symbol)


@mcp.tool()
async def store_research(trader: str, text: str, topic: str = "", symbols: list[str] | None = None) -> dict:
    """Save a finding to the firm's research library so it can be recalled in later sessions.
    Store one self-contained finding per note, with the facts, figures, dates and source.

    Args:
        trader: the name of the trader you are researching for
        text: the finding, written so that it makes sense on its own
        topic: a short title for the note
        symbols: ticker symbols the note is about, if any
    """
    return library.store_research(trader, text, topic, symbols)


if __name__ == "__main__":
    # Load the embedding model and open Qdrant before the server starts reading requests.
    # On Windows, loading numpy's native libraries later, while another thread is blocked
    # reading stdin, can hang until the next message arrives, which made first calls time out.
    library.warm_up()
    mcp.run(transport="stdio")
