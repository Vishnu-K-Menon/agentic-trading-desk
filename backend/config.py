"""Every setting for Agentic Trading Desk, read once from the environment.

Other modules import names from here rather than calling os.getenv themselves, so the
local app, each MCP server subprocess and the Hugging Face Space all agree.
"""

import os
import re
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Locally the keys live in a .env file; on a Space they are secrets, and
# values already in the environment must win.
ON_SPACE = bool(os.getenv("SPACE_ID"))
if not os.getenv("ATD_NO_DOTENV"):  # the tests set this to run without real keys
    load_dotenv(find_dotenv(usecwd=True) or find_dotenv(), override=not ON_SPACE)


def public_error(error: Exception) -> str:
    """A short description of a failure that is safe to show on a public page.

    Provider errors can quote account details, so keys and long identifiers are removed.
    """
    text = re.sub(r"(sk|key|org|proj|req|hf)[-_][A-Za-z0-9_\-*.]{6,}", "[removed]", str(error))
    text = re.sub(r"[A-Za-z0-9_\-]{32,}", "[removed]", text)
    return " ".join(text.split())[:240]


def flag(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# Where everything the app writes is kept: accounts, logs, memories, research library.
DATA_DIR = Path(os.getenv("DATA_DIR") or ROOT / "data").resolve()
MEMORY_DIR = DATA_DIR / "memory"
QDRANT_DIR = DATA_DIR / "qdrant"
DB = DATA_DIR / "accounts.db"
FRONTEND_DIST = ROOT / "frontend" / "dist"
for folder in (DATA_DIR, MEMORY_DIR):
    folder.mkdir(parents=True, exist_ok=True)

# The traders.
NAMES = ["Warren", "George", "Ray", "Cathie"]
LASTNAMES = {"Warren": "Patience", "George": "Bold", "Ray": "Systematic", "Cathie": "Crypto"}
DEFAULT_MODELS = {
    "Warren": "gpt-5.5",
    "George": "claude-sonnet-5-5",
    "Ray": "gpt-6-luna",
    "Cathie": "claude-haiku-5-5",
}
# Models offered in the control panel, with the label shown in the UI.
MODEL_CHOICES = {
    "gpt-5.5": "GPT 5.5",
    "gpt-6-luna": "GPT 6 Luna",
    "gpt-5.4-mini": "GPT 5.4 mini",
    "claude-opus-5-5": "Claude Opus 5.5",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "claude-haiku-5-5": "Claude Haiku 5.5",
}
RISK_MODEL = os.getenv("RISK_MODEL", "gpt-5.4-mini")

# The scheduler.
RUN_EVERY_N_MINUTES = int(os.getenv("RUN_EVERY_N_MINUTES", "60"))
RUN_EVEN_WHEN_MARKET_IS_CLOSED = flag("RUN_EVEN_WHEN_MARKET_IS_CLOSED", False)
MAX_ROUNDS_PER_DAY = int(os.getenv("MAX_ROUNDS_PER_DAY", "7"))
SCHEDULER_ENABLED = flag("SCHEDULER_ENABLED", True)
MAX_TURNS = 30

# The risk desk's hard limits, as fractions of the portfolio's value.
MAX_POSITION_WEIGHT = float(os.getenv("MAX_POSITION_WEIGHT", "0.25"))
MIN_CASH_WEIGHT = float(os.getenv("MIN_CASH_WEIGHT", "0.02"))

INITIAL_BALANCE = 10_000.0
SPREAD = 0.002
BENCHMARK = "SPY"

# Optional tools and services.
MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY")
USE_BROWSER = flag("USE_BROWSER", False)
# The SEC asks automated clients to identify themselves; set your own contact string if you can.
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "").strip() or "AgenticTradingDesk research client"

# The control panel. With no token set, changes are accepted from this machine only.
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()

# Backups of DATA_DIR to a private Hugging Face dataset, for Spaces without a disk.
HF_BACKUP_REPO = os.getenv("HF_BACKUP_REPO", "").strip()
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
