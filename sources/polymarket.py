"""PolyMarket API — Gamma (market data) and CLOB (order book)."""

import os
from typing import Any

import requests

GAMMA_API = os.getenv("POLYMARKET_GAMMA_API", "https://gamma-api.polymarket.com")
CLOB_API = os.getenv("POLYMARKET_CLOB_API", "https://clob.polymarket.com")

_HEADERS = {
    "User-Agent": "PolyMarket-Research-Bot/1.0",
    "Accept": "application/json",
}


def _get(url: str, params: dict | None = None, timeout: int = 15) -> Any:
    try:
        r = requests.get(url, params=params, headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


def get_active_markets(
    limit: int = 20,
    offset: int = 0,
    order_by: str = "volume24hr",
    ascending: bool = False,
    tag: str | None = None,
) -> dict:
    """Top active, non-closed markets. order_by: volume24hr | liquidity | startDate | endDate."""
    params: dict = {
        "active": "true",
        "closed": "false",
        "limit": limit,
        "offset": offset,
        "order": order_by,
        "ascending": str(ascending).lower(),
    }
    if tag:
        params["tag"] = tag
    data = _get(f"{GAMMA_API}/markets", params=params)
    if isinstance(data, list):
        return {"markets": data, "count": len(data)}
    return data


def get_market_details(market_id: str) -> dict:
    """Full market info: description, outcomes, prices, volume, clobTokenIds."""
    return _get(f"{GAMMA_API}/markets/{market_id}")


def search_markets(query: str, limit: int = 20, active_only: bool = True) -> dict:
    """Search markets by keyword."""
    params: dict = {"q": query, "limit": limit}
    if active_only:
        params["active"] = "true"
        params["closed"] = "false"
    data = _get(f"{GAMMA_API}/markets", params=params)
    if isinstance(data, list):
        return {"markets": data, "count": len(data)}
    return data


def get_markets_by_tag(tag: str, limit: int = 20) -> dict:
    """Markets filtered by category tag (Politics, Crypto, Sports, Finance…)."""
    return get_active_markets(limit=limit, tag=tag)


def get_market_orderbook(token_id: str) -> dict:
    """Live CLOB order book for an outcome token. Returns spread, mid, top bids/asks."""
    data = _get(f"{CLOB_API}/book", params={"token_id": token_id})
    if isinstance(data, dict) and "error" not in data:
        bids = data.get("bids", [])[:5]
        asks = data.get("asks", [])[:5]
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        spread = round(best_ask - best_bid, 4) if (best_bid and best_ask) else None
        mid = round((best_bid + best_ask) / 2, 4) if (best_bid and best_ask) else None
        return {
            "token_id": token_id,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "mid_price": mid,
            "top_bids": bids,
            "top_asks": asks,
        }
    return data
