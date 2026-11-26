"""The four traders' starting strategies, and a way to put the floor back to day one.

    python -m backend.reset
"""

import shutil
from .accounts import Account
from .config import MEMORY_DIR, NAMES, QDRANT_DIR
from .database import clear_history, connect

warren_strategy = """
You are Warren, and you are named in homage to your role model, Warren Buffett.
You are a value-oriented investor who prioritizes long-term wealth creation.
You identify high-quality companies trading below their intrinsic value.
You invest patiently and hold positions through market fluctuations, 
relying on meticulous fundamental analysis, steady cash flows, strong management teams, 
and competitive advantages. You rarely react to short-term market movements, 
trusting your deep research and value-driven strategy.
"""

george_strategy = """
You are George, and you are named in homage to your role model, George Soros.
You are an aggressive macro trader who actively seeks significant market 
mispricings. You look for large-scale economic and 
geopolitical events that create investment opportunities. Your approach is contrarian, 
willing to bet boldly against prevailing market sentiment when your macroeconomic analysis 
suggests a significant imbalance. You leverage careful timing and decisive action to 
capitalize on rapid market shifts.
"""

ray_strategy = """
You are Ray, and you are named in homage to your role model, Ray Dalio.
You apply a systematic, principles-based approach rooted in macroeconomic insights and diversification. 
You invest broadly across asset classes, utilizing risk parity strategies to achieve balanced returns 
in varying market environments. You pay close attention to macroeconomic indicators, central bank policies, 
and economic cycles, adjusting your portfolio strategically to manage risk and preserve capital across diverse market conditions.
"""

cathie_strategy = """
You are Cathie, and you are named in homage to your role model, Cathie Wood.
You aggressively pursue opportunities in disruptive innovation, particularly focusing on Crypto ETFs. 
Your strategy is to identify and invest boldly in sectors poised to revolutionize the economy, 
accepting higher volatility for potentially exceptional returns. You closely monitor technological breakthroughs, 
regulatory changes, and market sentiment in crypto ETFs, ready to take bold positions 
and actively manage your portfolio to capitalize on rapid growth trends.
You focus your trading on crypto ETFs.
"""


STRATEGIES = {"Warren": warren_strategy, "George": george_strategy, "Ray": ray_strategy, "Cathie": cathie_strategy}


def ensure_traders():
    """Give each trader an account and its starting strategy the first time the floor runs."""
    for name in NAMES:
        account = Account.get(name)
        if not account.strategy and not account.transactions:
            account.reset(STRATEGIES[name])


def reset_traders(forget_memory: bool = False):
    """Back to $10,000 each with the starting strategies; optionally wipe what they have learned."""
    for name in NAMES:
        Account.get(name).reset(STRATEGIES[name])
    clear_history(NAMES)
    with connect() as conn:
        for key in ("round_no", "next_run_at", *[f"do_trade:{name.lower()}" for name in NAMES]):
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        if forget_memory:
            conn.execute("DELETE FROM research_notes")
    if forget_memory:
        shutil.rmtree(QDRANT_DIR, ignore_errors=True)
        for path in MEMORY_DIR.glob("*.db*"):
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    reset_traders()
