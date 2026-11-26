"""Company fundamentals: a profile from Massive, financial statements and filings from SEC EDGAR.

EDGAR is free and needs no key, but the SEC requires every automated client to identify
itself. Set SEC_USER_AGENT to a contact string such as "Your Name you@example.com".
"""

import httpx
from datetime import date
from .config import SEC_USER_AGENT, MASSIVE_API_KEY
from .database import read_cache, write_cache
from . import market

DAY = 24 * 60 * 60
NOT_CONFIGURED = (
    "SEC filings data is not configured: set the SEC_USER_AGENT environment variable to a "
    "contact string (name and email), as the SEC requires. Use web research instead."
)

# The figures we report, each with the XBRL tags that companies use for it, best first.
ANNUAL_FLOWS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capital_expenditure": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}
BALANCES = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "shareholders_equity": ["StockholdersEquity"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
}
FILING_FORMS = ("10-K", "10-Q", "8-K", "20-F", "6-K")


def _edgar(url: str) -> dict:
    response = httpx.get(url, headers={"User-Agent": SEC_USER_AGENT}, timeout=30, follow_redirects=True)
    response.raise_for_status()
    return response.json()


def _cik(symbol: str) -> tuple[str, str] | None:
    """(zero-padded CIK, company name) for a ticker, or None if the SEC does not list it."""
    tickers = read_cache("edgar:tickers", 7 * DAY)
    if tickers is None:
        listing = _edgar("https://www.sec.gov/files/company_tickers.json")
        tickers = {row["ticker"].upper(): [str(row["cik_str"]).zfill(10), row["title"]] for row in listing.values()}
        write_cache("edgar:tickers", tickers)
    found = tickers.get(symbol.upper().replace(".", "-"))
    return (found[0], found[1]) if found else None


def company_profile(symbol: str) -> dict:
    """Name, business description, sector, size and listing details for a symbol."""
    symbol = symbol.strip().upper()
    cached = read_cache(f"profile:{symbol}", 7 * DAY)
    if cached:
        return cached
    if not MASSIVE_API_KEY:
        return {"symbol": symbol, "error": "Company profiles need a Massive API key. Use web research instead."}
    try:
        market._throttle()
        details = market._client().get_ticker_details(symbol)
    except Exception as e:
        return {"symbol": symbol, "error": f"No profile available: {str(e)[:160]}"}
    kinds = {"CS": "common stock", "ETF": "exchange traded fund", "ADRC": "ADR", "ETN": "exchange traded note"}
    profile = {
        "symbol": symbol,
        "name": details.name,
        "type": kinds.get(details.type, details.type),
        "industry": details.sic_description,
        "description": (details.description or "")[:1200],
        "market_cap": details.market_cap,
        "employees": details.total_employees,
        "listed": details.list_date,
        "exchange": details.primary_exchange,
        "website": details.homepage_url,
    }
    write_cache(f"profile:{symbol}", profile)
    return profile


def _annual_series(facts: dict, tags: list[str], duration: bool) -> dict[str, float]:
    """{fiscal year end: value} from 10-K filings, for the first tag that has data."""
    best: dict[str, float] = {}
    for tag in tags:
        units = facts.get(tag, {}).get("units", {})
        series = {}
        for entries in units.values():
            for entry in entries:
                if entry.get("form") not in ("10-K", "20-F", "10-K/A") or "end" not in entry:
                    continue
                if duration:
                    if "start" not in entry:
                        continue
                    span = (date.fromisoformat(entry["end"]) - date.fromisoformat(entry["start"])).days
                    if not 340 <= span <= 380:
                        continue
                series[entry["end"]] = entry["val"]  # later filings restate earlier ones
        if series and (not best or max(series) > max(best)):
            best = series
    return best


def financials(symbol: str, years: int = 4) -> dict:
    """Annual income, cash flow and balance sheet figures from the company's 10-K filings."""
    symbol = symbol.strip().upper()
    if not SEC_USER_AGENT:
        return {"symbol": symbol, "error": NOT_CONFIGURED}
    cached = read_cache(f"financials:{symbol}", DAY)
    if cached:
        return cached
    try:
        company = _cik(symbol)
        if not company:
            return {"symbol": symbol, "error": "No SEC filings for this symbol (funds and ETFs do not report financials)."}
        cik, name = company
        facts = _edgar(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json").get("facts", {}).get("us-gaap", {})
    except Exception as e:
        return {"symbol": symbol, "error": f"SEC data unavailable: {str(e)[:160]}"}

    series = {name_: _annual_series(facts, tags, True) for name_, tags in ANNUAL_FLOWS.items()}
    series |= {name_: _annual_series(facts, tags, False) for name_, tags in BALANCES.items()}
    year_ends = sorted(series["revenue"] or series["net_income"], reverse=True)[:years]
    if not year_ends:
        return {"symbol": symbol, "company": name, "error": "No annual financial statements found."}

    annual = []
    for end in year_ends:
        row = {"fiscal_year_end": end} | {key: values.get(end) for key, values in series.items()}
        revenue, income = row.get("revenue"), row.get("net_income")
        if revenue and income is not None:
            row["net_margin_pct"] = round(income / revenue * 100, 1)
        if row.get("operating_cash_flow") is not None and row.get("capital_expenditure") is not None:
            row["free_cash_flow"] = row["operating_cash_flow"] - row["capital_expenditure"]
        annual.append(row)
    result = {"symbol": symbol, "company": name, "currency": "USD", "annual": annual}

    latest, previous = annual[0], annual[1] if len(annual) > 1 else {}
    if latest.get("revenue") and previous.get("revenue"):
        result["revenue_growth_pct"] = round((latest["revenue"] / previous["revenue"] - 1) * 100, 1)
    try:
        price = market.get_share_price(symbol)
        if price and latest.get("eps_diluted") and latest["eps_diluted"] > 0:
            result["price"] = price
            result["price_to_earnings"] = round(price / latest["eps_diluted"], 1)
    except Exception:
        pass
    write_cache(f"financials:{symbol}", result)
    return result


def recent_filings(symbol: str, limit: int = 8) -> dict:
    """The company's latest annual, quarterly and current reports, with links."""
    symbol = symbol.strip().upper()
    if not SEC_USER_AGENT:
        return {"symbol": symbol, "error": NOT_CONFIGURED}
    cached = read_cache(f"filings:{symbol}", DAY / 4)
    if cached:
        return cached
    try:
        company = _cik(symbol)
        if not company:
            return {"symbol": symbol, "error": "No SEC filings for this symbol."}
        cik, name = company
        recent = _edgar(f"https://data.sec.gov/submissions/CIK{cik}.json")["filings"]["recent"]
    except Exception as e:
        return {"symbol": symbol, "error": f"SEC data unavailable: {str(e)[:160]}"}
    filings = []
    for form, filed, accession, document, description in zip(
        recent["form"], recent["filingDate"], recent["accessionNumber"],
        recent["primaryDocument"], recent["primaryDocDescription"],
    ):
        if form not in FILING_FORMS:
            continue
        filings.append({
            "form": form,
            "filed": filed,
            "description": description,
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{document}",
        })
        if len(filings) >= limit:
            break
    result = {"symbol": symbol, "company": name, "filings": filings}
    write_cache(f"filings:{symbol}", result)
    return result
