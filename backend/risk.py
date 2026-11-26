"""The risk desk: every trade a trader proposes is checked here before it executes.

Two layers. Hard limits are arithmetic and are enforced in code, so no model can talk its
way past them. Within those limits, a risk manager agent judges whether the trade fits
the trader's strategy and is sensibly sized.
"""

import asyncio
import json
import math
import time
from typing import Literal
from pydantic import BaseModel, Field
from agents import Agent, Runner, function_tool
from .accounts import Account
from .config import MAX_POSITION_WEIGHT, MIN_CASH_WEIGHT, RISK_MODEL, SPREAD, public_error
from .database import execute, write_log
from .market import get_share_price
from .models import get_model
from .templates import risk_manager_instructions


class Verdict(BaseModel):
    decision: Literal["approve", "resize", "reject"]
    approved_quantity: int = Field(description="Shares to trade: the proposed quantity, fewer, or 0 to reject")
    reason: str = Field(description="One or two plain sentences explaining the decision")


class Limits(BaseModel):
    """What the hard limits allow for one proposed trade, with the facts behind it."""

    allowed: int
    note: str
    price: float
    portfolio_value: float
    cash: float
    held: int
    weight_before: float
    weight_after: float
    cash_after: float


def apply_limits(account: Account, symbol: str, side: str, quantity: int, price: float) -> Limits:
    """The most shares the hard limits allow, up to the quantity asked for. Pure arithmetic."""
    portfolio_value = account.calculate_portfolio_value()
    held = account.holdings.get(symbol, 0)
    cash = account.balance
    allowed, note = quantity, ""

    if quantity <= 0:
        allowed, note = 0, "The quantity must be a positive whole number."
    elif not price:
        allowed, note = 0, f"{symbol} is not a recognised symbol."
    elif side == "sell":
        if held == 0:
            allowed, note = 0, f"You hold no {symbol} to sell."
        elif quantity > held:
            allowed, note = held, f"You hold only {held} shares of {symbol}."
    else:
        fill = price * (1 + SPREAD)
        by_position = math.floor((MAX_POSITION_WEIGHT * portfolio_value - held * price) / fill)
        by_cash = math.floor((cash - MIN_CASH_WEIGHT * portfolio_value) / fill)
        cap = max(0, min(by_position, by_cash))
        if cap < quantity:
            allowed = cap
            if by_position <= by_cash:
                note = f"A single position may not exceed {MAX_POSITION_WEIGHT:.0%} of the portfolio."
            else:
                note = f"At least {MIN_CASH_WEIGHT:.0%} of the portfolio must stay in cash."

    signed = allowed if side == "buy" else -allowed
    fill = price * (1 + SPREAD if side == "buy" else 1 - SPREAD)
    value = portfolio_value or 1.0
    return Limits(
        allowed=allowed,
        note=note,
        price=price,
        portfolio_value=portfolio_value,
        cash=cash,
        held=held,
        weight_before=held * price / value,
        weight_after=(held + signed) * price / value,
        cash_after=cash - signed * fill,
    )


def _record(name: str, symbol: str, side: str, requested: int, approved: int, decision: str,
            reason: str, rationale: str, source: str):
    execute(
        "INSERT INTO risk_reviews (name, created_at, symbol, side, requested, approved, decision, reason, rationale, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (name.lower(), time.time(), symbol, side, requested, approved, decision, reason, rationale, source),
    )
    summary = {"approve": "Approved", "resize": "Resized", "reject": "Rejected"}[decision]
    detail = f"{side} {requested} {symbol}" if approved == requested else f"{side} {requested} {symbol} -> {approved}"
    write_log(name, "risk", f"{summary} {detail}: {reason}")


async def _ask_risk_manager(account: Account, symbol: str, side: str, quantity: int, rationale: str,
                            limits: Limits) -> Verdict:
    other_holdings = {held: shares for held, shares in account.holdings.items() if held != symbol}
    request = f"""Trader: {account.name.title()}
Strategy:
{account.strategy.strip() or "(none recorded)"}

Proposed trade: {side} {quantity} shares of {symbol}
Trader's rationale: {rationale.strip() or "(none given)"}

Facts:
- Price per share: ${limits.price:,.2f}; order value ${quantity * limits.price:,.2f}
- Portfolio value: ${limits.portfolio_value:,.2f}; cash now ${limits.cash:,.2f}, after the trade ${limits.cash_after:,.2f}
- {symbol} weight in the portfolio: {limits.weight_before:.1%} now, {limits.weight_after:.1%} after
- Other holdings (shares): {json.dumps(other_holdings) if other_holdings else "none"}
"""
    manager = Agent(
        name="Risk Manager",
        instructions=risk_manager_instructions(),
        model=get_model(RISK_MODEL),
        output_type=Verdict,
    )
    result = await Runner.run(manager, request, max_turns=3)
    return result.final_output


_locks: dict[str, asyncio.Lock] = {}


async def review_and_execute(name: str, symbol: str, side: str, quantity: int, rationale: str) -> dict:
    """Check a proposed trade, execute what is allowed, and say what happened.

    A trader's proposals are handled one at a time, so that several made at once cannot
    each pass the limits separately and breach them together.
    """
    async with _locks.setdefault(name.lower(), asyncio.Lock()):
        return await _review_and_execute(name, symbol, side, quantity, rationale)


async def _review_and_execute(name: str, symbol: str, side: str, quantity: int, rationale: str) -> dict:
    symbol = symbol.strip().upper()
    side = side.strip().lower()
    if side not in ("buy", "sell"):
        return {"executed": False, "decision": "reject", "reason": "side must be 'buy' or 'sell'."}
    account = Account.get(name)
    try:
        price = await asyncio.to_thread(get_share_price, symbol)
    except Exception as e:
        return {"executed": False, "decision": "reject", "reason": f"No price available for {symbol}: {e}"}

    limits = await asyncio.to_thread(apply_limits, account, symbol, side, quantity, price)
    if limits.allowed == 0:
        _record(name, symbol, side, quantity, 0, "reject", limits.note, rationale, "limits")
        return {"executed": False, "decision": "reject", "reason": limits.note}

    try:
        verdict = await _ask_risk_manager(account, symbol, side, limits.allowed, rationale, limits)
        approved = max(0, min(verdict.approved_quantity, limits.allowed))
        decision, reason, source = verdict.decision, verdict.reason, "risk manager"
        if decision == "reject" or approved == 0:
            decision, approved = "reject", 0
    except Exception as e:
        # If the reviewer cannot be reached, the hard limits still stand on their own.
        approved, decision, source = limits.allowed, "approve", "limits"
        print(f"Risk manager unavailable for {name}: {e}")
        reason = f"Risk manager unavailable ({public_error(e)}); allowed within the hard limits."
    if decision != "reject" and approved < quantity:
        decision = "resize"
        if limits.allowed < quantity and approved == limits.allowed:
            reason = f"{limits.note} {reason}".strip()

    _record(name, symbol, side, quantity, approved, decision, reason, rationale, source)
    if decision == "reject":
        return {"executed": False, "decision": decision, "reason": reason}

    account = Account.get(name)  # reread: the review took time
    try:
        trade = account.buy_shares if side == "buy" else account.sell_shares
        await asyncio.to_thread(trade, symbol, approved, rationale)
    except Exception as e:
        return {"executed": False, "decision": decision, "reason": f"Approved, but the order failed: {e}"}
    return {
        "executed": True,
        "decision": decision,
        "requested_quantity": quantity,
        "executed_quantity": approved,
        "reason": reason,
        "cash": round(account.balance, 2),
        "holdings": account.holdings,
    }


def make_propose_trade(name: str):
    """The trading tool given to one trader, bound to that trader's account."""

    @function_tool
    async def propose_trade(symbol: str, side: str, quantity: int, rationale: str) -> str:
        """Propose a trade to the risk manager. If approved it is executed at once, possibly at a
        reduced size. Returns the decision, the reason, and your updated cash and holdings.

        Args:
            symbol: the ticker symbol of the stock or ETF
            side: "buy" or "sell"
            quantity: how many shares
            rationale: why you want this trade and how it fits your strategy
        """
        return json.dumps(await review_and_execute(name, symbol, side, quantity, rationale))

    return propose_trade
