"""Yahoo Finance client: a single fetch attempt, the FX bridge for foreign
issuers, and the retrying public entry point (get_company_data). Moved
verbatim out of financial_analyzer.py (docs/spec/refactor-tasks.md T09).
"""

import math
import time
from datetime import datetime

# Try importing yfinance
try:
    import yfinance as yf

    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

from fundamental_express.data.errors import DataUnavailableError
from fundamental_express.data.sample import _sample_data


def _fx_rate(from_ccy, to_ccy):
    """USD-per-unit-of-from_ccy conversion rate, or None if it can't be fetched."""
    if from_ccy == to_ccy:
        return 1.0
    try:
        fx = yf.Ticker(f"{from_ccy}{to_ccy}=X")
        rate = fx.info.get("regularMarketPrice") or fx.info.get("previousClose")
        if rate:
            return float(rate)
    except Exception:
        pass
    return None


FALLBACK_BETA = 1.1
_BETA_LO, _BETA_HI = -1.0, 3.0


def _sanitize_beta(raw_beta):
    """V08 (docs/spec/issues/V08-beta-sanity-check.md): the old `info.get
    ("beta") or FALLBACK_BETA` only ever caught falsy values (None/0/0.0) -
    NaN is truthy in Python (`float("nan") or 1.1` evaluates to nan, not
    1.1), and a beta far outside any plausible equity range (negative, or
    >3 - usually a low-liquidity/small-float regression artifact) passed
    straight through into Ke = Rf + β×ERP with no signal anything was
    adjusted. Returns (beta, beta_is_fallback) - the latter lets the
    report disclose which case applied."""
    if not raw_beta:  # None, 0, 0.0, "" - yfinance's own "no data" signal, preserved from the pre-V08 `or` idiom
        return FALLBACK_BETA, True
    try:
        beta_f = float(raw_beta)
    except (TypeError, ValueError):
        beta_f = float("nan")
    if math.isnan(beta_f) or beta_f < _BETA_LO or beta_f > _BETA_HI:
        return FALLBACK_BETA, True
    return beta_f, False


# ── FINANCIAL DATA COLLECTOR ────────────────────────────────────────────
def _fetch_once(ticker):
    """Single real-data fetch attempt. Returns a data dict, or None on any failure."""
    if not YFINANCE_AVAILABLE:
        return None
    try:
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.info
        financials = ticker_obj.financials
        balance = ticker_obj.balance_sheet
        cashflow = ticker_obj.cashflow

        if financials.empty or balance.empty or cashflow.empty:
            return None

        if info.get("regularMarketPrice"):
            price, price_kind = info["regularMarketPrice"], "последняя сделка (regularMarketPrice)"
        elif info.get("currentPrice"):
            price, price_kind = info["currentPrice"], "последняя сделка (currentPrice)"
        elif info.get("previousClose"):
            price, price_kind = info["previousClose"], "цена предыдущего закрытия (previousClose)"
        else:
            price, price_kind = None, None
        shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        if not price or not shares:
            return None

        # regularMarketTime is a real exchange timestamp for the quote above;
        # fall back to "now" (script run time) only if yfinance omits it, and
        # say so plainly rather than implying it's a market timestamp.
        market_time_epoch = info.get("regularMarketTime")
        exchange_tz = info.get("exchangeTimezoneName")
        if market_time_epoch:
            from datetime import timezone as _tz
            quote_time = datetime.fromtimestamp(market_time_epoch, tz=_tz.utc)
            if exchange_tz:
                try:
                    from zoneinfo import ZoneInfo
                    quote_time = quote_time.astimezone(ZoneInfo(exchange_tz))
                except Exception:
                    pass
            quote_time_label = quote_time.strftime("%Y-%m-%d %H:%M %Z")
        else:
            quote_time_label = f"{datetime.now().strftime('%Y-%m-%d %H:%M')} (время запуска скрипта, не биржевое время)"

        beta, beta_is_fallback = _sanitize_beta(info.get("beta"))
        name = info.get("longName") or info.get("shortName") or ticker

        # Foreign issuers (e.g. TSM/TSMC) often report financial statements in
        # their home currency (TWD) while price/shares/market cap are quoted in
        # USD via the ADR. Mixing the two without converting corrupts every
        # dollar figure downstream (DCF fair value, fundamentals table) even
        # though ratio-based checks (current ratio, margins, YoY trends) stay
        # correct since they compare same-currency figures.
        financial_ccy = info.get("financialCurrency")
        trading_ccy = info.get("currency") or "USD"
        fx_rate = 1.0
        if financial_ccy and financial_ccy != trading_ccy:
            fx_rate = _fx_rate(financial_ccy, trading_ccy)
            if fx_rate is None:
                return None  # can't safely mix currencies - treat like any other fetch failure

        return {
            "ticker": ticker.upper(),
            "name": name,
            "price": float(price),
            "shares": int(shares),
            "beta": float(beta),
            "beta_is_fallback": beta_is_fallback,
            "financials": financials,
            "balance": balance,
            "cashflow": cashflow,
            "is_sample": False,
            "price_kind": price_kind,
            "quote_time_label": quote_time_label,
            "fx_rate": fx_rate,
            "financial_currency": financial_ccy or trading_ccy,
            "trading_currency": trading_ccy,
            # Raw info payload, kept only for the Forward Outlook section
            # (forwardPE/pegRatio/earningsGrowth/revenueGrowth) - never used
            # by compute_metrics()'s core sins/DCF logic.
            "info": info,
        }
    except Exception as e:
        print(f"  [{ticker}] fetch attempt failed: {e}")
        return None


def get_company_data(ticker, retries=5, retry_delay=5, allow_sample=False):
    """Fetch real financials for `ticker` from Yahoo Finance.

    Yahoo Finance is flaky (connection resets, timeouts, occasional empty
    responses) - most failures clear up on a retry a few seconds later, so
    we retry before giving up. By default this NEVER falls back to mock
    data: it raises DataUnavailableError so callers don't mistake a demo
    number for a real one. Pass allow_sample=True only for demos.
    """
    for attempt in range(1, retries + 1):
        data = _fetch_once(ticker)
        if data is not None:
            return data
        if attempt < retries:
            print(
                f"  [{ticker}] real data unavailable (attempt {attempt}/{retries}), "
                f"retrying in {retry_delay}s..."
            )
            time.sleep(retry_delay)

    if allow_sample:
        print(
            f"Warning: no real data for {ticker} after {retries} attempts - "
            f"using SAMPLE data (--allow-sample set). These numbers are NOT real."
        )
        return _sample_data(ticker)

    raise DataUnavailableError(ticker, retries)
