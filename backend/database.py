"""One SQLite database shared by the API and every MCP server process."""

import json
import sqlite3
import time
from contextlib import contextmanager
from .config import DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (name TEXT PRIMARY KEY, account TEXT);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, datetime DATETIME, type TEXT, message TEXT);
CREATE INDEX IF NOT EXISTS logs_by_name ON logs (name, id);
CREATE TABLE IF NOT EXISTS prices (symbol TEXT PRIMARY KEY, price REAL, fetched_at REAL);
CREATE TABLE IF NOT EXISTS bars (
    symbol TEXT, day TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (symbol, day));
CREATE TABLE IF NOT EXISTS market_meta (key TEXT PRIMARY KEY, value REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS api_calls (service TEXT, called_at REAL);
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, fetched_at REAL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT, round_no INTEGER, name TEXT, kind TEXT, model TEXT,
    started_at REAL, ended_at REAL, final_output TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS risk_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, created_at REAL, symbol TEXT, side TEXT,
    requested INTEGER, approved INTEGER, decision TEXT, reason TEXT, rationale TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS research_notes (
    id TEXT PRIMARY KEY, created_at REAL, trader TEXT, topic TEXT, symbols TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS strategy_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, created_at REAL, strategy TEXT, source TEXT);
"""


@contextmanager
def connect():
    """A connection that commits on success and always closes."""
    conn = sqlite3.connect(DB, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


with connect() as _conn:
    _conn.execute("PRAGMA journal_mode=WAL")  # readers do not block the writing processes
    _conn.executescript(SCHEMA)


def rows(sql: str, params: tuple = ()) -> list[dict]:
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def execute(sql: str, params: tuple = ()) -> int:
    with connect() as conn:
        return conn.execute(sql, params).lastrowid


# Accounts

def write_account(name: str, account_dict: dict):
    execute(
        "INSERT INTO accounts (name, account) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET account=excluded.account",
        (name.lower(), json.dumps(account_dict)),
    )


def read_account(name: str):
    found = rows("SELECT account FROM accounts WHERE name = ?", (name.lower(),))
    return json.loads(found[0]["account"]) if found else None


# Logs

def write_log(name: str, type: str, message: str):
    execute(
        "INSERT INTO logs (name, datetime, type, message) VALUES (?, datetime('now'), ?, ?)",
        (name.lower(), type, message),
    )


def read_log(name: str, last_n: int = 10, after_id: int = 0) -> list[dict]:
    """The most recent log rows for a trader, oldest first."""
    found = rows(
        "SELECT id, datetime, type, message FROM logs WHERE name = ? AND id > ? ORDER BY id DESC LIMIT ?",
        (name.lower(), after_id, last_n),
    )
    return list(reversed(found))


def clear_history(names: list[str]):
    """Forget the logs, rounds and reviews of the given traders (used by a reset)."""
    with connect() as conn:
        for name in names:
            for table in ("logs", "rounds", "risk_reviews", "strategy_changes"):
                conn.execute(f"DELETE FROM {table} WHERE lower(name) = ?", (name.lower(),))


# Prices and market state

def write_prices(prices: dict[str, float]):
    now = time.time()
    with connect() as conn:
        conn.executemany(
            "INSERT INTO prices (symbol, price, fetched_at) VALUES (?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET price=excluded.price, fetched_at=excluded.fetched_at",
            [(symbol.upper(), price, now) for symbol, price in prices.items()],
        )


def read_price(symbol: str):
    """(price, fetched_at) for a cached symbol, or None."""
    found = rows("SELECT price, fetched_at FROM prices WHERE symbol = ?", (symbol.upper(),))
    return (found[0]["price"], found[0]["fetched_at"]) if found else None


def write_bars(symbol: str, bars: list[dict]):
    with connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO bars (symbol, day, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(symbol.upper(), b["day"], b["open"], b["high"], b["low"], b["close"], b["volume"]) for b in bars],
        )


def extend_bars(day: str, day_bars: dict[str, tuple]):
    """Add one day's bar to every symbol we already hold history for.

    day_bars maps symbol to (open, high, low, close, volume).
    """
    with connect() as conn:
        tracked = [row["symbol"] for row in conn.execute("SELECT DISTINCT symbol FROM bars")]
        conn.executemany(
            "INSERT OR REPLACE INTO bars (symbol, day, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(symbol, day, *day_bars[symbol]) for symbol in tracked if symbol in day_bars],
        )


def read_bars(symbol: str, since_day: str = "") -> list[dict]:
    return rows(
        "SELECT day, open, high, low, close, volume FROM bars WHERE symbol = ? AND day >= ? ORDER BY day",
        (symbol.upper(), since_day),
    )


def write_meta(key: str, value: float):
    execute(
        "INSERT INTO market_meta (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value, time.time()),
    )


def read_meta(key: str):
    """(value, updated_at) for a piece of market state, or None."""
    found = rows("SELECT value, updated_at FROM market_meta WHERE key = ?", (key,))
    return (found[0]["value"], found[0]["updated_at"]) if found else None


def claim_api_slot(service: str, limit: int, window: float = 60) -> float:
    """Take one of `limit` calls per `window` seconds, atomically across processes.

    Returns 0 if the slot was taken, otherwise the time at which one frees up.
    """
    now = time.time()
    conn = sqlite3.connect(DB, timeout=30, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM api_calls WHERE called_at < ?", (now - 3600,))
        calls = [row[0] for row in conn.execute(
            "SELECT called_at FROM api_calls WHERE service = ? AND called_at > ? ORDER BY called_at",
            (service, now - window),
        )]
        if len(calls) < limit:
            conn.execute("INSERT INTO api_calls (service, called_at) VALUES (?, ?)", (service, now))
            conn.execute("COMMIT")
            return 0.0
        conn.execute("COMMIT")
        return calls[0] + window + 1
    finally:
        conn.close()


def close_interrupted_rounds():
    """Sessions cut short by a restart would otherwise look as if they were still running."""
    execute(
        "UPDATE rounds SET ended_at = started_at, error = 'Interrupted by a restart' WHERE ended_at IS NULL"
    )


def record_api_call(service: str):
    with connect() as conn:
        conn.execute("DELETE FROM api_calls WHERE called_at < ?", (time.time() - 3600,))
        conn.execute("INSERT INTO api_calls (service, called_at) VALUES (?, ?)", (service, time.time()))


def recent_api_calls(service: str, seconds: float) -> list[float]:
    found = rows(
        "SELECT called_at FROM api_calls WHERE service = ? AND called_at > ? ORDER BY called_at",
        (service, time.time() - seconds),
    )
    return [row["called_at"] for row in found]


# A small JSON cache for slow, rarely changing lookups

def write_cache(key: str, value):
    execute(
        "INSERT INTO cache (key, value, fetched_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, fetched_at=excluded.fetched_at",
        (key, json.dumps(value), time.time()),
    )


def read_cache(key: str, max_age: float):
    found = rows("SELECT value, fetched_at FROM cache WHERE key = ?", (key,))
    if found and time.time() - found[0]["fetched_at"] < max_age:
        return json.loads(found[0]["value"])
    return None


# Settings

def write_setting(key: str, value):
    execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )


def read_setting(key: str, default=None):
    found = rows("SELECT value FROM settings WHERE key = ?", (key,))
    return json.loads(found[0]["value"]) if found else default
