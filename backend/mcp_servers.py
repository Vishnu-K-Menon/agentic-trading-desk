"""The MCP servers the floor uses, and which agent gets which.

Most servers are stateless, so one copy of each is started per round and shared by all
four traders. Only the knowledge graph is private: each trader has its own.
"""

import os
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from agents.mcp import MCPServerStdio, create_static_tool_filter
from .config import ROOT, MEMORY_DIR, USE_BROWSER

TIMEOUT = 120


def _own(module: str, **kwargs) -> MCPServerStdio:
    """One of our own servers, run with this interpreter and this environment."""
    params = {"command": sys.executable, "args": ["-m", f"backend.{module}"], "cwd": str(ROOT), "env": dict(os.environ)}
    return MCPServerStdio(params, name=module, client_session_timeout_seconds=TIMEOUT, cache_tools_list=True, **kwargs)


def _external(name: str, command: str, args: list[str], env: dict | None = None, **kwargs) -> MCPServerStdio:
    params = {"command": command, "args": args}
    if env:
        params["env"] = env
    return MCPServerStdio(params, name=name, client_session_timeout_seconds=TIMEOUT, cache_tools_list=True, **kwargs)


@dataclass
class SharedServers:
    """Connected servers that every trader in a round uses."""

    accounts: MCPServerStdio
    push: MCPServerStdio
    market: MCPServerStdio
    fundamentals: MCPServerStdio
    library: MCPServerStdio
    fetch: MCPServerStdio
    search: MCPServerStdio
    browser: MCPServerStdio | None = None

    def for_trader(self) -> list[MCPServerStdio]:
        return [self.accounts, self.push, self.market, self.fundamentals]

    def for_researcher(self) -> list[MCPServerStdio]:
        servers = [self.library, self.search, self.fetch, self.market, self.fundamentals]
        if self.browser:
            servers.append(self.browser)
        return servers


async def start_shared_servers(stack: AsyncExitStack) -> SharedServers:
    """Start one of each shared server; they stop when the stack closes."""
    servers = SharedServers(
        # Trades go through the risk desk, so traders do not get the raw buy and sell tools.
        accounts=_own(
            "accounts_server",
            tool_filter=create_static_tool_filter(blocked_tool_names=["buy_shares", "sell_shares"]),
        ),
        push=_own("push_server"),
        market=_own("market_server"),
        fundamentals=_own("fundamentals_server"),
        library=_own("library_server"),
        fetch=_external("fetch", "uvx", ["--with", "mcp<2", "mcp-server-fetch"]),
        # Tavily's server offers several tools; plain search is all the researcher needs.
        search=_external(
            "tavily", "npx", ["-y", "tavily-mcp@latest"],
            env={"TAVILY_API_KEY": os.getenv("TAVILY_API_KEY", "")},
            tool_filter=create_static_tool_filter(allowed_tool_names=["tavily_search"]),
        ),
        browser=_own("browser_server") if USE_BROWSER else None,
    )
    for server in (servers.accounts, servers.push, servers.market, servers.fundamentals,
                   servers.library, servers.fetch, servers.search, servers.browser):
        if server:
            await stack.enter_async_context(server)
    return servers


def memory_server(name: str) -> MCPServerStdio:
    """A trader's private knowledge graph of entities and relations."""
    database = (MEMORY_DIR / f"{name}.db").as_posix()
    return _external("memory", "npx", ["-y", "mcp-memory-libsql"], env={"LIBSQL_URL": f"file:{database}"})
