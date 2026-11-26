"""A trader: an agent with a researcher, market tools and a line to the risk desk."""

import asyncio
import json
import time
from contextlib import AsyncExitStack
from agents import Agent, Runner, Tool, trace
from .accounts import Account
from .config import DEFAULT_MODELS, LASTNAMES, MAX_TURNS, MODEL_CHOICES, public_error
from .database import execute, read_setting, write_log, write_setting
from .mcp_servers import SharedServers, memory_server
from .models import get_model
from .risk import make_propose_trade
from .templates import (
    researcher_instructions, trader_instructions, trade_message, rebalance_message, research_tool,
)
from .tracers import make_trace_id

RESEARCHER_MAX_TURNS = 15


def trader_model(name: str) -> str:
    """The model a trader runs on: the control panel's choice, or the default."""
    return read_setting(f"model:{name.lower()}", DEFAULT_MODELS[name])


def model_label(model_name: str) -> str:
    return MODEL_CHOICES.get(model_name, model_name)


class Trader:
    def __init__(self, name: str):
        self.name = name
        self.lastname = LASTNAMES.get(name, "Trader")

    @property
    def do_trade(self) -> bool:
        """Rounds alternate between looking for new trades and rebalancing; remembered across restarts."""
        return read_setting(f"do_trade:{self.name.lower()}", True)

    async def researcher_tool(self, servers: list, model_name: str) -> Tool:
        researcher = Agent(
            name="Researcher",
            instructions=researcher_instructions(self.name),
            model=get_model(model_name),
            mcp_servers=servers,
        )
        return researcher.as_tool(
            tool_name="Researcher", tool_description=research_tool(), max_turns=RESEARCHER_MAX_TURNS
        )

    def account_report(self) -> str:
        account = json.loads(Account.get(self.name).report())
        account.pop("portfolio_value_time_series", None)
        return json.dumps(account)

    async def run_agent(self, shared: SharedServers, memory, model_name: str) -> str:
        researcher = await self.researcher_tool(shared.for_researcher() + [memory], model_name)
        agent = Agent(
            name=self.name,
            instructions=trader_instructions(self.name),
            model=get_model(model_name),
            tools=[researcher, make_propose_trade(self.name)],
            mcp_servers=shared.for_trader(),
        )
        strategy = Account.get(self.name).get_strategy()
        report = await asyncio.to_thread(self.account_report)
        message_for = trade_message if self.do_trade else rebalance_message
        result = await Runner.run(agent, message_for(self.name, strategy, report), max_turns=MAX_TURNS)
        return str(result.final_output)

    async def run(self, shared: SharedServers, round_no: int):
        """One session for this trader. Never raises: a failure is recorded and the floor carries on."""
        kind = "trading" if self.do_trade else "rebalancing"
        model_name = trader_model(self.name)
        round_id = execute(
            "INSERT INTO rounds (round_no, name, kind, model, started_at) VALUES (?, ?, ?, ?, ?)",
            (round_no, self.name.lower(), kind, model_name, time.time()),
        )
        final_output, error = None, "Interrupted before it finished"
        try:
            with trace(f"{self.name}-{kind}", trace_id=make_trace_id(self.name.lower())):
                async with AsyncExitStack() as stack:
                    memory = await stack.enter_async_context(memory_server(self.name))
                    final_output = await self.run_agent(shared, memory, model_name)
            error = None
            write_log(self.name, "response", f"Final answer: {final_output}")
        except Exception as e:
            error = public_error(e)
            print(f"Error running trader {self.name}: {e}")  # the full detail stays in the server log
            write_log(self.name, "response", f"Run failed: {error}")
        finally:
            # Also reached when the round is cancelled, so no session is left looking unfinished.
            execute(
                "UPDATE rounds SET ended_at = ?, final_output = ?, error = ? WHERE id = ?",
                (time.time(), final_output, error, round_id),
            )
        await asyncio.to_thread(Account.get(self.name).snapshot)
        write_setting(f"do_trade:{self.name.lower()}", not self.do_trade)
