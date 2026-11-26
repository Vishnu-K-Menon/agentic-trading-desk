"""The trading floor: runs a round for every trader on a schedule, and can be controlled.

It lives inside the API process, so there is exactly one scheduler and the control panel
can pause it, resume it or start a round at once.
"""

import asyncio
import os
import time
from contextlib import AsyncExitStack
from datetime import datetime
from agents import add_trace_processor
from . import backup
from .accounts import Account
from .config import (
    MAX_ROUNDS_PER_DAY, NAMES, RUN_EVEN_WHEN_MARKET_IS_CLOSED, RUN_EVERY_N_MINUTES, SCHEDULER_ENABLED,
)
from .database import read_setting, rows, write_setting
from .market import is_market_open
from .mcp_servers import start_shared_servers
from .tracers import LogTracer
from .traders import Trader

CHECK_EVERY = 5  # seconds between looks at the clock


class Floor:
    def __init__(self):
        self.traders = [Trader(name) for name in NAMES]
        self.running = False
        self.last_skip_reason = ""
        self._run_now = asyncio.Event()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    # State kept in the database so it survives restarts

    @property
    def paused(self) -> bool:
        return read_setting("paused", False)

    @property
    def next_run_at(self) -> float:
        return read_setting("next_run_at", 0.0)

    @property
    def round_no(self) -> int:
        return read_setting("round_no", 0)

    def rounds_today(self) -> int:
        midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        found = rows("SELECT COUNT(DISTINCT round_no) AS n FROM rounds WHERE started_at >= ?", (midnight,))
        return found[0]["n"]

    def status(self) -> dict:
        return {
            "running": self.running,
            "paused": self.paused,
            "scheduler_enabled": SCHEDULER_ENABLED,
            "round_no": self.round_no,
            "next_run_at": None if self.paused or not SCHEDULER_ENABLED else self.next_run_at,
            "interval_minutes": RUN_EVERY_N_MINUTES,
            "rounds_today": self.rounds_today(),
            "max_rounds_per_day": MAX_ROUNDS_PER_DAY,
            "last_skip_reason": self.last_skip_reason,
        }

    # Controls

    def pause(self):
        write_setting("paused", True)

    def resume(self):
        write_setting("paused", False)

    def request_round(self) -> bool:
        """Ask for a round to start now. False if one is already running."""
        if self.running:
            return False
        self._run_now.set()
        return True

    # The loop

    def start(self):
        add_trace_processor(LogTracer())
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    def _why_not_now(self) -> str:
        """The reason a scheduled round should be skipped, or '' to go ahead."""
        if not (os.getenv("OPENAI_API_KEY") and os.getenv("ANTHROPIC_API_KEY")):
            return "API keys are not set"
        if self.rounds_today() >= MAX_ROUNDS_PER_DAY:
            return f"Daily limit of {MAX_ROUNDS_PER_DAY} rounds reached"
        if not RUN_EVEN_WHEN_MARKET_IS_CLOSED and not is_market_open():
            return "Market is closed"
        return ""

    async def _loop(self):
        while True:
            try:
                manual = self._run_now.is_set()
                due = SCHEDULER_ENABLED and not self.paused and time.time() >= self.next_run_at
                if manual or due:
                    self._run_now.clear()
                    reason = "" if manual else await asyncio.to_thread(self._why_not_now)
                    self.last_skip_reason = reason
                    if reason:
                        print(f"{reason}, skipping round")
                        write_setting("next_run_at", time.time() + RUN_EVERY_N_MINUTES * 60)
                    else:
                        await self.run_round()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(f"Floor loop error: {e}")
                write_setting("next_run_at", time.time() + RUN_EVERY_N_MINUTES * 60)
            try:
                await asyncio.wait_for(self._run_now.wait(), timeout=CHECK_EVERY)
            except asyncio.TimeoutError:
                pass

    async def run_round(self):
        """Run every trader once, sharing one set of MCP servers between them."""
        async with self._lock:
            self.running = True
            round_no = self.round_no + 1
            write_setting("round_no", round_no)
            try:
                async with AsyncExitStack() as stack:
                    shared = await start_shared_servers(stack)
                    await asyncio.gather(*[trader.run(shared, round_no) for trader in self.traders])
            finally:
                self.running = False
                write_setting("next_run_at", time.time() + RUN_EVERY_N_MINUTES * 60)
            await asyncio.to_thread(backup.save)

    def snapshot_all(self):
        """Record every trader's current value, so the charts have a point to draw."""
        for name in NAMES:
            try:
                Account.get(name).snapshot()
            except Exception as e:
                print(f"Could not snapshot {name}: {e}")
