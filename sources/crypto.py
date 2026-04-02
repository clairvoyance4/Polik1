"""
Crypto data source — CoinGecko public API (no API key needed for basic usage).
Provides current prices, market caps, volume, % changes, and historical data.
"""

import requests

_BASE = "https://api.coingecko.com/api/v3"
_HEADERS = {"Accept": "application/json", "User-Agent": "PolyMarket-Research-Bot/1.0"}


def _get(path: str, params: dict | None = None) -> dict:
    try:
        r = requests.get(f"{_BASE}{path}", params=params, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        # CoinGecko returns 429 on rate limit
        if e.response.status_code == 429:
            return {"error": "CoinGecko rate limit hit. Wait ~60s and retry."}
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


def get_coin_data(coin_id: str) -> dict:
    """
    Current market data for a coin.
    coin_id examples: bitcoin, ethereum, solana, chainlink, dogecoin, matic-network
    Returns: price (USD), 24h/7d/30d % change, market cap, volume, ATH, supply.
    """
    data = _get(
        f"/coins/{coin_id}",
        params={
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "false",
            "developer_data": "false",
        },
    )
    if "error" in data:
        return data
    md = data.get("market_data", {})
    return {
        "id": coin_id,
        "name": data.get("name"),
        "symbol": data.get("symbol", "").upper(),
        "price_usd": md.get("current_price", {}).get("usd"),
        "market_cap_usd": md.get("market_cap", {}).get("usd"),
        "volume_24h_usd": md.get("total_volume", {}).get("usd"),
        "change_24h_pct": md.get("price_change_percentage_24h"),
        "change_7d_pct": md.get("price_change_percentage_7d"),
        "change_30d_pct": md.get("price_change_percentage_30d"),
        "ath_usd": md.get("ath", {}).get("usd"),
        "ath_change_pct": md.get("ath_change_percentage", {}).get("usd"),
        "circulating_supply": md.get("circulating_supply"),
        "max_supply": md.get("max_supply"),
        "last_updated": data.get("last_updated"),
        "description_snippet": data.get("description", {}).get("en", "")[:300],
    }


def get_coin_price_history(coin_id: str, days: int = 30) -> dict:
    """
    Daily price history for a coin (last N days).
    Useful for spotting trends and comparing to market expectations.
    coin_id examples: bitcoin, ethereum, solana
    """
    data = _get(
        f"/coins/{coin_id}/market_chart",
        params={"vs_currency": "usd", "days": days, "interval": "daily"},
    )
    if "error" in data:
        return data
    prices = data.get("prices", [])
    # Return summary + recent data points
    if prices:
        start_price = prices[0][1]
        end_price = prices[-1][1]
        total_change_pct = round((end_price - start_price) / start_price * 100, 2)
        recent = [
            {"date": p[0], "price_usd": round(p[1], 4)}
            for p in prices[-7:]  # last 7 days
        ]
    else:
        total_change_pct = None
        recent = []

    return {
        "coin_id": coin_id,
        "period_days": days,
        "start_price_usd": round(prices[0][1], 4) if prices else None,
        "end_price_usd": round(prices[-1][1], 4) if prices else None,
        "total_change_pct": total_change_pct,
        "recent_7_days": recent,
    }


def search_coin_id(query: str) -> dict:
    """
    Find the CoinGecko coin ID for a given name or symbol.
    Use this before calling get_coin_data if you're unsure of the exact ID.
    query examples: 'BTC', 'eth', 'solana', 'dogecoin'
    """
    data = _get("/search", params={"query": query})
    if "error" in data:
        return data
    coins = data.get("coins", [])[:5]
    return {
        "query": query,
        "matches": [{"id": c["id"], "name": c["name"], "symbol": c["symbol"]} for c in coins],
    }


def get_global_crypto_market() -> dict:
    """
    Global crypto market overview: total market cap, BTC dominance, fear & greed context.
    Useful for assessing macro sentiment for any crypto-related market.
    """
    data = _get("/global")
    if "error" in data:
        return data
    gd = data.get("data", {})
    return {
        "total_market_cap_usd": gd.get("total_market_cap", {}).get("usd"),
        "total_volume_24h_usd": gd.get("total_volume", {}).get("usd"),
        "btc_dominance_pct": round(gd.get("market_cap_percentage", {}).get("btc", 0), 2),
        "eth_dominance_pct": round(gd.get("market_cap_percentage", {}).get("eth", 0), 2),
        "market_cap_change_24h_pct": gd.get("market_cap_change_percentage_24h_usd"),
        "active_cryptocurrencies": gd.get("active_cryptocurrencies"),
    }
