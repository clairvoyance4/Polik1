"""
PolyMarket Research Bot
-----------------------
Uses Claude (claude-opus-4-6) with tool use to research PolyMarket markets,
identify potentially interesting opportunities, and find where edge might exist.

Usage:
    python polymarket_bot.py
    python polymarket_bot.py --query "US elections"
    python polymarket_bot.py --top 20 --min-volume 10000
"""

import argparse
import json
import os
import sys
import time
from typing import Any

import anthropic
import requests
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.table import Table

load_dotenv()

console = Console()

GAMMA_API = os.getenv("POLYMARKET_GAMMA_API", "https://gamma-api.polymarket.com")
CLOB_API = os.getenv("POLYMARKET_CLOB_API", "https://clob.polymarket.com")

HEADERS = {
    "User-Agent": "PolyMarket-Research-Bot/1.0",
    "Accept": "application/json",
}

# ---------------------------------------------------------------------------
# PolyMarket API helpers
# ---------------------------------------------------------------------------

def _get(url: str, params: dict | None = None, timeout: int = 15) -> Any:
    """GET request with error handling."""
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


def api_get_active_markets(
    limit: int = 20,
    offset: int = 0,
    order_by: str = "volume24hr",
    ascending: bool = False,
    tag: str | None = None,
) -> dict:
    """
    Fetch active, non-closed markets from PolyMarket Gamma API.
    order_by options: volume24hr, liquidity, startDate, endDate
    """
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


def api_get_market_details(market_id: str) -> dict:
    """Fetch full details of a single market by its Gamma market ID."""
    return _get(f"{GAMMA_API}/markets/{market_id}")


def api_search_markets(
    query: str,
    limit: int = 20,
    active_only: bool = True,
) -> dict:
    """Search markets by keyword."""
    params: dict = {
        "q": query,
        "limit": limit,
    }
    if active_only:
        params["active"] = "true"
        params["closed"] = "false"

    data = _get(f"{GAMMA_API}/markets", params=params)
    if isinstance(data, list):
        return {"markets": data, "count": len(data)}
    return data


def api_get_market_orderbook(token_id: str) -> dict:
    """
    Fetch the current order book for a market token from the CLOB API.
    token_id is the outcome token ID (found in market details under 'clobTokenIds').
    Returns bids/asks to assess liquidity and spread.
    """
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


def api_get_markets_by_tag(tag: str, limit: int = 20) -> dict:
    """Fetch markets filtered by a specific tag/category."""
    return api_get_active_markets(limit=limit, tag=tag)


# ---------------------------------------------------------------------------
# Tool definitions for Claude
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "get_active_markets",
        "description": (
            "Fetch active markets from PolyMarket sorted by a given criterion. "
            "Use this to get an overview of the most liquid/active markets. "
            "order_by options: 'volume24hr' (default), 'liquidity', 'startDate', 'endDate'. "
            "Returns market list with prices, volume, liquidity, and end dates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of markets to fetch (1-50)", "default": 20},
                "offset": {"type": "integer", "description": "Pagination offset", "default": 0},
                "order_by": {
                    "type": "string",
                    "description": "Sort field: volume24hr, liquidity, startDate, endDate",
                    "default": "volume24hr",
                },
                "ascending": {"type": "boolean", "description": "Sort ascending if true", "default": False},
                "tag": {"type": "string", "description": "Optional category tag to filter by (e.g. 'Politics', 'Crypto', 'Sports')"},
            },
            "required": [],
        },
    },
    {
        "name": "search_markets",
        "description": (
            "Search PolyMarket markets by keyword. Use this to find markets on a specific topic "
            "(e.g., 'bitcoin', 'trump', 'fed rate', 'super bowl'). Returns relevant active markets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword or phrase"},
                "limit": {"type": "integer", "description": "Max results to return", "default": 20},
                "active_only": {"type": "boolean", "description": "Only return active/open markets", "default": True},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_market_details",
        "description": (
            "Get full details for a specific market by its ID. "
            "Returns complete market info including description, outcomes, current prices, "
            "total volume, liquidity, start/end dates, and CLOB token IDs for orderbook lookup."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "market_id": {"type": "string", "description": "The PolyMarket market ID (slug or numeric ID)"},
            },
            "required": ["market_id"],
        },
    },
    {
        "name": "get_market_orderbook",
        "description": (
            "Get the live order book for a specific outcome token. "
            "Returns best bid/ask prices, spread, and top 5 levels on each side. "
            "Use this to assess liquidity depth and identify wide spreads (potential inefficiency). "
            "Get the token_id from get_market_details (field: clobTokenIds)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "token_id": {"type": "string", "description": "The CLOB outcome token ID"},
            },
            "required": ["token_id"],
        },
    },
    {
        "name": "get_markets_by_tag",
        "description": (
            "Fetch markets filtered by category tag. "
            "Common tags: 'Politics', 'Crypto', 'Sports', 'Finance', 'Science', 'Entertainment', 'World'. "
            "Use this to explore a specific sector."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tag": {"type": "string", "description": "Category tag name"},
                "limit": {"type": "integer", "description": "Max markets to return", "default": 20},
            },
            "required": ["tag"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def dispatch_tool(name: str, input_args: dict) -> str:
    """Execute a tool call and return result as JSON string."""
    try:
        if name == "get_active_markets":
            result = api_get_active_markets(**input_args)
        elif name == "search_markets":
            result = api_search_markets(**input_args)
        elif name == "get_market_details":
            result = api_get_market_details(**input_args)
        elif name == "get_market_orderbook":
            result = api_get_market_orderbook(**input_args)
        elif name == "get_markets_by_tag":
            result = api_get_markets_by_tag(**input_args)
        else:
            result = {"error": f"Unknown tool: {name}"}
    except Exception as e:
        result = {"error": f"Tool execution error: {e}"}

    return json.dumps(result, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert prediction market analyst specializing in PolyMarket.

Your goal is to research active markets and identify where a trader could find EDGE —
situations where the market price (implied probability) appears mispriced relative to
the true probability of the outcome.

## Framework for finding edge

1. **Mispriced probability**: Market price significantly differs from what the evidence suggests.
   - Example: A market at 15% for something that looks more like 35-40% based on base rates.

2. **Information asymmetry**: You have access to better information or analysis than the
   typical market participant.

3. **Liquidity inefficiency**: Wide bid-ask spreads, thin order books — the market hasn't
   attracted enough capital to be efficient. This can mean easier entry/exit AND mispricing.

4. **Recency bias / narrative-driven pricing**: Markets often over-react to recent news
   or compelling narratives, creating temporary mispricings.

5. **Base rate neglect**: Market prices often ignore base rates (historical frequency of
   similar events).

6. **Correlation opportunities**: Related markets priced inconsistently with each other.

## Research process

1. Start by surveying the landscape — get top markets by volume and liquidity.
2. Also explore specific categories (Crypto, Politics, Finance, Sports) to find
   less-trafficked opportunities.
3. For promising markets, dig deeper: get full details, check the order book.
4. Look for markets where you can articulate WHY the price might be wrong.
5. Assess risk: how binary is the outcome? What's the resolution mechanism? When does it close?

## Output format

After your research, produce a structured report with:
- **Executive Summary**: 2-3 key findings
- **Top Opportunities**: 3-5 specific markets with edge thesis, current price, your estimate, and edge rationale
- **Markets to Watch**: 3-5 markets that are interesting but need more information
- **Market Landscape**: Brief overview of what you observed across categories
- **Methodology Notes**: Any limitations or caveats

Be specific and quantitative where possible. Back every claim with data from the tools.
"""


# ---------------------------------------------------------------------------
# Main bot logic
# ---------------------------------------------------------------------------

def build_initial_prompt(query: str | None, top_n: int, min_volume: float) -> str:
    parts = [
        f"Please research PolyMarket and find the most interesting opportunities for finding edge.",
        f"Focus on the top {top_n} most active/liquid markets, but also explore multiple categories.",
    ]
    if query:
        parts.append(f"Pay special attention to markets related to: '{query}'.")
    if min_volume > 0:
        parts.append(f"Filter for markets with at least ${min_volume:,.0f} in 24h volume where relevant.")
    parts.append(
        "Use the available tools iteratively to gather data. "
        "Check order books for specific markets that look interesting. "
        "Then produce your full research report."
    )
    return " ".join(parts)


def run_research_bot(
    query: str | None = None,
    top_n: int = 20,
    min_volume: float = 0,
    max_tool_calls: int = 25,
) -> None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red bold]Error:[/] ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    console.print(Panel.fit(
        "[bold cyan]PolyMarket Research Bot[/]\n"
        "[dim]Powered by Claude claude-opus-4-6 with adaptive thinking[/]",
        border_style="cyan",
    ))
    console.print()

    initial_prompt = build_initial_prompt(query, top_n, min_volume)
    console.print(f"[dim]Research query:[/] {initial_prompt}")
    console.print()

    messages: list[dict] = [{"role": "user", "content": initial_prompt}]
    tool_call_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Claude is thinking and researching...", total=None)

        while tool_call_count < max_tool_calls:
            progress.update(task, description=f"Claude is working... ({tool_call_count} tool calls so far)")

            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=8192,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            # Append assistant response
            messages.append({"role": "assistant", "content": response.content})

            # Check stop reason
            if response.stop_reason == "end_turn":
                break

            if response.stop_reason != "tool_use":
                break

            # Process tool calls
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_call_count += 1
                tool_name = block.name
                tool_input = block.input

                progress.update(
                    task,
                    description=f"[cyan]Tool call {tool_call_count}:[/] {tool_name}({json.dumps(tool_input)[:60]}...)",
                )

                result_str = dispatch_tool(tool_name, tool_input)

                # Log tool call to console (below progress bar)
                _preview = json.loads(result_str)
                if isinstance(_preview, dict) and "markets" in _preview:
                    count = _preview.get("count", len(_preview["markets"]))
                    progress.console.print(
                        f"  [dim]↳ {tool_name}[/] → [green]{count} markets returned[/]"
                    )
                elif isinstance(_preview, dict) and "error" in _preview:
                    progress.console.print(
                        f"  [dim]↳ {tool_name}[/] → [red]Error: {_preview['error'][:80]}[/]"
                    )
                else:
                    progress.console.print(f"  [dim]↳ {tool_name}[/] → [green]OK[/]")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })

            messages.append({"role": "user", "content": tool_results})

    # Extract final text response
    console.print()
    console.print(Rule("[bold cyan]Research Report[/]", style="cyan"))
    console.print()

    final_text = ""
    for block in response.content:
        if hasattr(block, "type") and block.type == "text":
            final_text = block.text
            break

    if final_text:
        console.print(Markdown(final_text))
    else:
        console.print("[yellow]No text output from Claude. Check API response.[/]")

    # Summary stats
    console.print()
    console.print(Rule(style="dim"))
    console.print(
        f"[dim]Tool calls made: {tool_call_count} | "
        f"Messages in conversation: {len(messages)} | "
        f"Input tokens: {response.usage.input_tokens} | "
        f"Output tokens: {response.usage.output_tokens}[/]"
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PolyMarket Research Bot — find edge using Claude AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python polymarket_bot.py
  python polymarket_bot.py --query "bitcoin ETF"
  python polymarket_bot.py --query "2024 elections" --top 30
  python polymarket_bot.py --top 15 --min-volume 5000
        """,
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        default=None,
        help="Focus research on markets matching this keyword/topic",
    )
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=20,
        help="Number of top markets to survey (default: 20)",
    )
    parser.add_argument(
        "--min-volume",
        type=float,
        default=0,
        help="Minimum 24h volume filter in USD (default: 0)",
    )
    parser.add_argument(
        "--max-tools",
        type=int,
        default=25,
        help="Maximum number of tool calls (default: 25)",
    )

    args = parser.parse_args()

    run_research_bot(
        query=args.query,
        top_n=args.top,
        min_volume=args.min_volume,
        max_tool_calls=args.max_tools,
    )


if __name__ == "__main__":
    main()
