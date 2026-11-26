"""Backend tests that need no API keys: they run on simulated prices in a temporary data folder.

    uv run python tests/test_backend.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ.update({
    "ATD_NO_DOTENV": "1",
    "DATA_DIR": tempfile.mkdtemp(prefix="atd-test-"),
    "MASSIVE_API_KEY": "",
    "SCHEDULER_ENABLED": "false",
    "ADMIN_TOKEN": "let-me-in",
    "HF_BACKUP_REPO": "",
})
os.environ.pop("SPACE_ID", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from backend import analytics, api, risk  # noqa: E402
from backend.accounts import Account  # noqa: E402
from backend.config import INITIAL_BALANCE, MAX_POSITION_WEIGHT, MIN_CASH_WEIGHT, SPREAD  # noqa: E402
from backend.database import rows  # noqa: E402
from backend.market import get_share_price  # noqa: E402
from backend.reset import reset_traders  # noqa: E402

ADMIN = {"x-admin-token": "let-me-in"}


def fresh(name: str = "Warren") -> Account:
    reset_traders()
    return Account.get(name)


def approve_all(monkey_verdict=None):
    """Replace the risk manager model with a canned verdict."""
    async def fake(account, symbol, side, quantity, rationale, limits):
        if isinstance(monkey_verdict, Exception):
            raise monkey_verdict
        if monkey_verdict:
            return monkey_verdict(quantity)
        return risk.Verdict(decision="approve", approved_quantity=quantity, reason="Fits the strategy.")
    risk._ask_risk_manager = fake


# Hard limits

def test_limits_cap_an_oversized_buy():
    account = fresh()
    price = get_share_price("AAPL")
    limits = risk.apply_limits(account, "AAPL", "buy", 10_000, price)
    assert 0 < limits.allowed < 10_000
    assert limits.allowed * price <= MAX_POSITION_WEIGHT * INITIAL_BALANCE
    assert (limits.allowed + 1) * price * (1 + SPREAD) > MAX_POSITION_WEIGHT * INITIAL_BALANCE
    assert "single position" in limits.note


def test_limits_keep_a_cash_floor():
    account = fresh()
    for symbol in ("AAPL", "MSFT", "NVDA", "JPM"):  # four positions of just under a quarter each
        price = get_share_price(symbol)
        allowed = risk.apply_limits(account, symbol, "buy", 10_000, price).allowed
        account.buy_shares(symbol, allowed, "test")
        account = Account.get("Warren")
    value = account.calculate_portfolio_value()
    assert account.balance >= MIN_CASH_WEIGHT * value - 1e-6
    price = get_share_price("KO")
    limits = risk.apply_limits(account, "KO", "buy", 10_000, price)
    assert account.balance - limits.allowed * price * (1 + SPREAD) >= MIN_CASH_WEIGHT * value - 1e-6


def test_limits_on_bad_orders():
    account = fresh()
    price = get_share_price("AAPL")
    assert risk.apply_limits(account, "AAPL", "buy", 0, price).allowed == 0
    assert risk.apply_limits(account, "AAPL", "buy", -5, price).allowed == 0
    assert risk.apply_limits(account, "NOPE", "buy", 5, 0.0).allowed == 0
    assert risk.apply_limits(account, "AAPL", "sell", 5, price).allowed == 0
    account.buy_shares("AAPL", 3, "test")
    assert risk.apply_limits(Account.get("Warren"), "AAPL", "sell", 5, price).allowed == 3


# Review and execution

def test_approved_trade_executes_and_is_recorded():
    fresh()
    approve_all()
    result = asyncio.run(risk.review_and_execute("Warren", "aapl", "BUY", 2, "Quality at a fair price"))
    assert result["executed"] and result["decision"] == "approve" and result["executed_quantity"] == 2
    assert Account.get("Warren").holdings == {"AAPL": 2}
    review = rows("SELECT * FROM risk_reviews WHERE name = 'warren'")[-1]
    assert (review["decision"], review["requested"], review["approved"]) == ("approve", 2, 2)


def test_resize_and_reject():
    fresh()
    approve_all(lambda quantity: risk.Verdict(decision="resize", approved_quantity=1, reason="Too large."))
    result = asyncio.run(risk.review_and_execute("Warren", "AAPL", "buy", 4, "Momentum"))
    assert result["decision"] == "resize" and result["executed_quantity"] == 1
    approve_all(lambda quantity: risk.Verdict(decision="reject", approved_quantity=0, reason="Off strategy."))
    result = asyncio.run(risk.review_and_execute("Warren", "MSFT", "buy", 4, "Momentum"))
    assert not result["executed"] and result["decision"] == "reject"
    assert Account.get("Warren").holdings == {"AAPL": 1}


def test_manager_cannot_exceed_the_limits():
    fresh()
    approve_all(lambda quantity: risk.Verdict(decision="approve", approved_quantity=quantity * 50, reason="Go big."))
    result = asyncio.run(risk.review_and_execute("Warren", "AAPL", "buy", 10_000, "All in"))
    account = Account.get("Warren")
    assert result["decision"] == "resize"
    assert account.holdings["AAPL"] * get_share_price("AAPL") <= MAX_POSITION_WEIGHT * INITIAL_BALANCE


def test_limits_still_apply_when_the_manager_is_down():
    fresh()
    approve_all(RuntimeError("model unavailable"))
    result = asyncio.run(risk.review_and_execute("Warren", "AAPL", "buy", 10_000, "All in"))
    assert result["executed"] and result["decision"] == "resize"
    assert Account.get("Warren").holdings["AAPL"] * get_share_price("AAPL") <= MAX_POSITION_WEIGHT * INITIAL_BALANCE


def test_simultaneous_proposals_cannot_breach_the_cash_floor():
    fresh()
    approve_all()

    async def burst():
        symbols = ["AAPL", "MSFT", "NVDA", "JPM", "KO", "PG", "XOM"]
        return await asyncio.gather(*[risk.review_and_execute("Warren", s, "buy", 10_000, "test") for s in symbols])

    asyncio.run(burst())
    account = Account.get("Warren")
    assert account.balance >= MIN_CASH_WEIGHT * account.calculate_portfolio_value() - 1e-6
    assert account.balance >= 0


def test_unknown_side_and_bad_symbol():
    fresh()
    approve_all()
    assert asyncio.run(risk.review_and_execute("Warren", "AAPL", "short", 1, "x"))["decision"] == "reject"


# Analytics

def test_indicators():
    rising = [float(i) for i in range(1, 300)]
    assert analytics.sma(rising, 20) == sum(rising[-20:]) / 20
    assert analytics.rsi(rising) == 100.0
    assert analytics.rsi(list(reversed(rising))) < 1
    assert analytics.sma([1.0, 2.0], 20) is None
    assert abs(analytics.max_drawdown([100, 120, 90, 130]) - (90 / 120 - 1)) < 1e-9
    assert analytics.max_drawdown([100, 110, 120]) == 0
    result = analytics.indicators("AAPL")
    assert result["sma_200"] and 0 <= result["rsi_14"] <= 100


# API

def test_api_reads_and_admin_rules():
    fresh()
    approve_all()
    asyncio.run(risk.review_and_execute("Cathie", "IBIT", "buy", 3, "Core bitcoin exposure"))
    with TestClient(api.app) as client:
        assert [t["name"] for t in client.get("/api/traders").json()] == ["Warren", "George", "Ray", "Cathie"]
        assert client.get("/api/market").json()["source"] == "simulator"
        assert client.get("/api/config").json()["token_required"] is True
        assert client.get("/api/floor").json()["running"] is False

        cathie = client.get("/api/traders/cathie").json()
        assert cathie["holdings"][0]["symbol"] == "IBIT" and cathie["transactions"][0]["rationale"]
        assert abs(cathie["balance"] + cathie["holdings"][0]["market_value"] - cathie["portfolio_value"]) < 1e-6
        assert client.get("/api/traders/nobody").status_code == 404
        assert client.get("/api/traders/cathie/risk").json()[0]["decision"] == "approve"
        assert client.get("/api/traders/cathie/logs").json()[-1]["type"] in ("account", "risk")
        assert client.get("/api/traders/cathie/rounds").json() == []
        assert client.get("/api/traders/cathie/memory").json()["graph"] == {"entities": [], "relations": []}

        board = client.get("/api/leaderboard").json()
        assert len(board["standings"]) == 4 and set(board["chart"]["series"]) == {"Warren", "George", "Ray", "Cathie", "SPY"}
        assert all(len(values) == len(board["chart"]["t"]) for values in board["chart"]["series"].values())

        # Every change is refused without the token, and with a wrong one.
        changes = [
            ("post", "/api/floor/run", None), ("post", "/api/floor/pause", None), ("post", "/api/floor/resume", None),
            ("post", "/api/floor/reset", {}), ("post", "/api/admin/check", None),
            ("put", "/api/traders/ray/model", {"model": "gpt-5.5"}),
            ("put", "/api/traders/ray/strategy", {"strategy": "Buy broad index funds and hold them."}),
        ]
        for method, path, body in changes:
            assert client.request(method, path, json=body).status_code == 401, path
            assert client.request(method, path, json=body, headers={"x-admin-token": "wrong"}).status_code == 401, path

        assert client.post("/api/admin/check", headers=ADMIN).json() == {"ok": True}
        assert client.post("/api/floor/pause", headers=ADMIN).json()["paused"] is True
        assert client.post("/api/floor/resume", headers=ADMIN).json()["paused"] is False
        assert client.put("/api/traders/ray/model", json={"model": "gpt-5.5"}, headers=ADMIN).json()["model_name"] == "GPT 5.5"
        assert client.get("/api/traders").json()[2]["model"] == "gpt-5.5"
        assert client.put("/api/traders/ray/model", json={"model": "made-up"}, headers=ADMIN).status_code == 422
        new_strategy = "Hold a balanced, all-weather mix of broad index funds."
        assert client.put("/api/traders/ray/strategy", json={"strategy": new_strategy}, headers=ADMIN).status_code == 200
        history = client.get("/api/traders/ray/strategy").json()
        assert history["strategy"] == new_strategy and history["changes"][0]["source"] == "admin"
        assert client.put("/api/traders/ray/strategy", json={"strategy": "short"}, headers=ADMIN).status_code == 422

        assert client.post("/api/floor/reset", json={"forget_memory": True}, headers=ADMIN).status_code == 200
        assert client.get("/api/traders/cathie").json()["holdings"] == []

        # With no token configured, a request that is not from this machine is refused.
        api.ADMIN_TOKEN = ""
        try:
            assert client.post("/api/floor/pause").status_code == 403
        finally:
            api.ADMIN_TOKEN = "let-me-in"


if __name__ == "__main__":
    tests = [value for name, value in list(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print("ok  ", test.__name__)
    print(f"{len(tests)} tests passed")
