"""
PolyMarket Research Bot
-----------------------
Uses Claude claude-opus-4-6 (adaptive thinking + tool use) to research PolyMarket
prediction markets and cross-reference with external data sources to find edge.

Data sources:
  - PolyMarket Gamma API & CLOB (market prices, liquidity, order books)
  - Google News RSS + BBC (no API key needed)
  - CoinGecko (crypto data, no API key needed)
  - TheSportsDB (sports data, no API key needed)
  - Open-Meteo (weather forecasts, no API key needed)

Usage:
    python polymarket_bot.py
    python polymarket_bot.py --query "bitcoin"
    python polymarket_bot.py --query "Premier League" --top 30
    python polymarket_bot.py --focus crypto
    python polymarket_bot.py --focus sports --top 20
"""

import argparse
import json
import os
import sys

import anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule

from sources import crypto, news, polymarket, sports, telegram, weather

load_dotenv()
console = Console()

# ---------------------------------------------------------------------------
# Tool definitions (schema exposed to Claude)
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    # ── PolyMarket ──────────────────────────────────────────────────────────
    {
        "name": "pm_get_active_markets",
        "description": (
            "Fetch active PolyMarket markets sorted by a criterion. "
            "order_by: 'volume24hr' (default), 'liquidity', 'startDate', 'endDate'. "
            "Returns market list with current prices, volume, liquidity, end dates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20, "description": "Markets to fetch (1-50)"},
                "offset": {"type": "integer", "default": 0},
                "order_by": {"type": "string", "default": "volume24hr"},
                "ascending": {"type": "boolean", "default": False},
                "tag": {"type": "string", "description": "Category filter: Politics, Crypto, Sports, Finance, Science…"},
            },
        },
    },
    {
        "name": "pm_search_markets",
        "description": "Search PolyMarket markets by keyword (e.g. 'bitcoin price', 'US election', 'Champions League').",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "active_only": {"type": "boolean", "default": True},
            },
            "required": ["query"],
        },
    },
    {
        "name": "pm_get_market_details",
        "description": (
            "Full details for a PolyMarket market: description, outcomes, current prices, "
            "total volume, liquidity, resolution criteria, and clobTokenIds for order book lookup."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"market_id": {"type": "string", "description": "Market slug or numeric ID"}},
            "required": ["market_id"],
        },
    },
    {
        "name": "pm_get_orderbook",
        "description": (
            "Live order book for an outcome token: best bid/ask, spread, mid price, top 5 levels. "
            "Wide spread = thin liquidity = potential inefficiency. "
            "token_id comes from pm_get_market_details (field: clobTokenIds)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"token_id": {"type": "string"}},
            "required": ["token_id"],
        },
    },
    {
        "name": "pm_get_markets_by_tag",
        "description": "Browse markets by category tag: Politics, Crypto, Sports, Finance, Science, Entertainment, World.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tag": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["tag"],
        },
    },

    # ── News ────────────────────────────────────────────────────────────────
    {
        "name": "news_search",
        "description": (
            "Search recent news articles on any topic via Google News RSS (no API key). "
            "Use this to check for recent developments that might affect a market's probability. "
            "Example queries: 'Fed interest rate decision', 'bitcoin ETF', 'Premier League standings'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (supports AND, OR, quotes)"},
                "max_items": {"type": "integer", "default": 10, "description": "Max articles to return"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "news_get_headlines",
        "description": "Latest headlines from BBC News for a broad topic: world, business, tech, sport, science.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "default": "world", "description": "world | business | tech | sport | science"},
                "max_items": {"type": "integer", "default": 10},
            },
        },
    },

    # ── Crypto ──────────────────────────────────────────────────────────────
    {
        "name": "crypto_get_coin_data",
        "description": (
            "Current market data for a cryptocurrency via CoinGecko (no API key). "
            "Returns price, 24h/7d/30d % change, market cap, volume, ATH distance. "
            "coin_id examples: bitcoin, ethereum, solana, chainlink, dogecoin, matic-network"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "coin_id": {"type": "string", "description": "CoinGecko coin ID (lowercase, hyphens)"},
            },
            "required": ["coin_id"],
        },
    },
    {
        "name": "crypto_get_price_history",
        "description": "Daily price history for a coin over N days. Useful for trend analysis and context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "coin_id": {"type": "string"},
                "days": {"type": "integer", "default": 30, "description": "1-365"},
            },
            "required": ["coin_id"],
        },
    },
    {
        "name": "crypto_search_coin",
        "description": "Find the CoinGecko coin ID for a ticker or name. Use before get_coin_data if unsure of ID.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Coin name or ticker, e.g. 'BTC', 'sol'"}},
            "required": ["query"],
        },
    },
    {
        "name": "crypto_global_market",
        "description": "Global crypto market overview: total market cap, BTC dominance, 24h volume, market cap change.",
        "input_schema": {"type": "object", "properties": {}},
    },

    # ── Sports ──────────────────────────────────────────────────────────────
    {
        "name": "sports_search_team",
        "description": (
            "Search for a sports team by name via TheSportsDB (free, no key). "
            "Returns team ID, league, country, and sport. "
            "Use team ID for get_team_results and get_team_fixtures."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"team_name": {"type": "string", "description": "E.g. 'Arsenal', 'Lakers', 'Barcelona'"}},
            "required": ["team_name"],
        },
    },
    {
        "name": "sports_get_team_results",
        "description": "Last 5 match results for a team (by TheSportsDB team ID). Shows form, scores, opponents.",
        "input_schema": {
            "type": "object",
            "properties": {"team_id": {"type": "string", "description": "TheSportsDB team ID"}},
            "required": ["team_id"],
        },
    },
    {
        "name": "sports_get_team_fixtures",
        "description": "Next 5 upcoming fixtures for a team (by TheSportsDB team ID). Shows dates and opponents.",
        "input_schema": {
            "type": "object",
            "properties": {"team_id": {"type": "string", "description": "TheSportsDB team ID"}},
            "required": ["team_id"],
        },
    },
    {
        "name": "sports_get_league_table",
        "description": (
            "Current league standings. "
            "Common IDs: 4328=EPL, 4335=La Liga, 4331=Bundesliga, 4332=Serie A, 4334=Ligue 1, "
            "4480=NBA, 4424=NFL. season format: '2023-2024' or '2024'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "league_id": {"type": "string"},
                "season": {"type": "string", "description": "Optional season, e.g. '2023-2024'"},
            },
            "required": ["league_id"],
        },
    },
    {
        "name": "sports_search_event",
        "description": "Search for a sporting event by name. E.g. 'Champions League Final', 'Super Bowl 2024'.",
        "input_schema": {
            "type": "object",
            "properties": {"event_name": {"type": "string"}},
            "required": ["event_name"],
        },
    },

    # ── Weather ─────────────────────────────────────────────────────────────
    {
        "name": "weather_get_forecast",
        "description": (
            "Weather forecast for a city (1-14 days) via Open-Meteo (free, no key). "
            "Returns daily max/min temp (°C), precipitation, wind, and condition description. "
            "Use for weather-related markets or events affected by weather."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name, e.g. 'London', 'New York', 'Tokyo'"},
                "days": {"type": "integer", "default": 7, "description": "Forecast days (1-14)"},
            },
            "required": ["city"],
        },
    },
    {
        "name": "weather_get_current",
        "description": "Current weather conditions for a city: temperature, feels-like, precipitation, wind, humidity.",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
]

# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

_DISPATCH = {
    "pm_get_active_markets":    lambda a: polymarket.get_active_markets(**a),
    "pm_search_markets":        lambda a: polymarket.search_markets(**a),
    "pm_get_market_details":    lambda a: polymarket.get_market_details(**a),
    "pm_get_orderbook":         lambda a: polymarket.get_market_orderbook(**a),
    "pm_get_markets_by_tag":    lambda a: polymarket.get_markets_by_tag(**a),
    "news_search":              lambda a: news.search_news(**a),
    "news_get_headlines":       lambda a: news.get_latest_news(**a),
    "crypto_get_coin_data":     lambda a: crypto.get_coin_data(**a),
    "crypto_get_price_history": lambda a: crypto.get_coin_price_history(**a),
    "crypto_search_coin":       lambda a: crypto.search_coin_id(**a),
    "crypto_global_market":     lambda a: crypto.get_global_crypto_market(),
    "sports_search_team":       lambda a: sports.search_team(**a),
    "sports_get_team_results":  lambda a: sports.get_team_last_results(**a),
    "sports_get_team_fixtures": lambda a: sports.get_team_next_fixtures(**a),
    "sports_get_league_table":  lambda a: sports.get_league_table(**a),
    "sports_search_event":      lambda a: sports.search_event(**a),
    "weather_get_forecast":     lambda a: weather.get_weather_forecast(**a),
    "weather_get_current":      lambda a: weather.get_current_weather(**a),
}


def dispatch_tool(name: str, input_args: dict) -> str:
    fn = _DISPATCH.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = fn(input_args)
    except Exception as e:
        result = {"error": f"Tool execution error: {e}"}
    return json.dumps(result, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an expert prediction market analyst specializing in PolyMarket.

Your goal is to find EDGE — situations where the market price (implied probability) is
meaningfully different from the true probability. You have access to both PolyMarket data
AND external data sources (news, crypto prices, sports stats, weather forecasts) to
cross-reference and validate your analysis.

## Sources available to you
- **PolyMarket**: active markets, order books, market details
- **News**: Google News search + BBC headlines (real-time, no key needed)
- **Crypto**: CoinGecko prices, history, global market data
- **Sports**: TheSportsDB team form, fixtures, league tables
- **Weather**: Open-Meteo forecasts for any city

## Edge detection framework

1. **Price vs reality mismatch** — Compare market price against external data:
   - Crypto market at 70% BTC hits $100k → check actual BTC price/trend
   - Sports market → check team form, head-to-head, league table
   - Weather event → check actual forecast
   - Political event → check recent polling/news

2. **Information lag** — News broke recently but market hasn't repriced yet.
   Always search for recent news on the market topic.

3. **Liquidity inefficiency** — Check order books. Wide spread + thin book =
   market hasn't attracted sophisticated capital = potential mispricing.

4. **Base rate neglect** — Market ignores historical base rates.
   Example: "Will X happen in 30 days?" — how often does this typically happen?

5. **Recency bias** — Market overweights recent dramatic events.

6. **Correlated markets inconsistency** — Two related markets priced inconsistently.

## Research workflow

1. Survey landscape: get top markets by volume, then browse key categories
2. For each interesting market: search for recent news, pull relevant external data
3. Check order books on the most interesting markets
4. Cross-reference: does external data support or contradict the market price?
5. Look for multiple opportunities to confirm a thesis

## Output format

Produce a structured research report with:

### Executive Summary
2-3 key findings in one sentence each.

### Top Opportunities (3-5)
For each:
- **Market**: [name + current price]
- **My estimate**: [probability I'd assign]
- **Edge**: [why price is wrong — backed by data]
- **Position**: [Yes/No, rough size tier: small/medium/large]
- **Risk**: [what could go wrong]

### Markets to Watch (3-5)
Interesting but need more info or upcoming catalysts.

### Market Landscape
Brief sector overview: what's hot, what's illiquid, any patterns.

### Data Notes
Any API errors, limitations, or caveats about your research.

Be specific and quantitative. Cite actual numbers from the tool outputs.
Don't hedge everything — make clear calls where the data supports it.
"""


# ---------------------------------------------------------------------------
# Main bot
# ---------------------------------------------------------------------------

def build_prompt(query: str | None, top_n: int, focus: str | None) -> str:
    parts = [f"Research PolyMarket and identify the best opportunities for finding edge."]
    parts.append(f"Start by surveying the top {top_n} most active markets.")
    if focus:
        parts.append(f"Give extra attention to the '{focus}' category.")
    if query:
        parts.append(f"Specifically investigate markets related to: '{query}'.")
    parts.append(
        "For each promising market, use external data sources (news, crypto, sports, weather) "
        "to cross-reference the market price against reality. "
        "Check order books on the most interesting markets. "
        "Produce a full research report at the end."
    )
    return " ".join(parts)


def _tg_credentials() -> tuple[str | None, str | None]:
    """Return (token, chat_id) from env, or (None, None) if not configured."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    return token, chat_id


def run_bot(
    query: str | None = None,
    top_n: int = 20,
    focus: str | None = None,
    max_tool_calls: int = 30,
    send_telegram: bool = False,
) -> None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[red bold]Error:[/] ANTHROPIC_API_KEY not set. Copy .env.example → .env and add your key.")
        sys.exit(1)

    tg_token, tg_chat_id = _tg_credentials()
    if send_telegram and (not tg_token or not tg_chat_id):
        console.print(
            "[red bold]Error:[/] --telegram requires TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID in your .env file."
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Header
    tg_badge = " · [green]→ Telegram[/]" if send_telegram else ""
    console.print(Panel.fit(
        "[bold cyan]PolyMarket Research Bot[/]\n"
        "[dim]Claude claude-opus-4-6 · adaptive thinking · "
        f"PolyMarket + News + Crypto + Sports + Weather{tg_badge}[/]",
        border_style="cyan",
    ))
    console.print()

    prompt = build_prompt(query, top_n, focus)
    console.print(f"[dim]Prompt:[/] {prompt}")
    console.print()

    messages: list[dict] = [{"role": "user", "content": prompt}]
    tool_call_count = 0
    response = None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Starting research...", total=None)

        while tool_call_count < max_tool_calls:
            progress.update(task, description=f"Claude thinking… ({tool_call_count} tool calls)")

            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=8192,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason in ("end_turn", None):
                break
            if response.stop_reason != "tool_use":
                break

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_call_count += 1
                result_str = dispatch_tool(block.name, block.input)

                # Pretty-print tool call progress
                try:
                    preview = json.loads(result_str)
                except Exception:
                    preview = {}

                if isinstance(preview, dict) and "error" in preview:
                    status = f"[red]error: {str(preview['error'])[:60]}[/]"
                elif isinstance(preview, dict) and "markets" in preview:
                    status = f"[green]{preview.get('count', '?')} markets[/]"
                elif isinstance(preview, dict) and "articles" in preview:
                    status = f"[green]{preview.get('count', '?')} articles[/]"
                elif isinstance(preview, dict) and "forecast" in preview:
                    status = f"[green]{preview.get('city', '?')} forecast OK[/]"
                else:
                    status = "[green]OK[/]"

                progress.console.print(
                    f"  [dim]{tool_call_count:02d}.[/] [cyan]{block.name}[/]"
                    f"({json.dumps(block.input)[:55]}…) → {status}"
                )

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })

            messages.append({"role": "user", "content": tool_results})

    # Output
    console.print()
    console.print(Rule("[bold cyan]Research Report[/]", style="cyan"))
    console.print()

    if response is None:
        console.print("[red]No response from Claude.[/]")
        return

    final_text = next(
        (block.text for block in response.content if hasattr(block, "type") and block.type == "text"),
        None,
    )

    if final_text:
        console.print(Markdown(final_text))
    else:
        console.print("[yellow]Claude returned no text. The model may have only used tools.[/]")

    # Stats footer
    console.print()
    console.print(Rule(style="dim"))
    console.print(
        f"[dim]Tool calls: {tool_call_count} | "
        f"Turns: {len(messages)} | "
        f"In: {response.usage.input_tokens:,} tok | "
        f"Out: {response.usage.output_tokens:,} tok[/]"
    )

    # ── Telegram ────────────────────────────────────────────────────────────
    if send_telegram and final_text and tg_token and tg_chat_id:
        import datetime
        console.print()
        console.print("[dim]Sending report to Telegram…[/]")

        focus_tag = f" #{focus}" if focus else ""
        query_tag = f" · {query}" if query else ""
        header = (
            f"📊 <b>PolyMarket Research Report</b>{query_tag}{focus_tag}\n"
            f"🕐 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} UTC\n"
            f"🔧 Tool calls: {tool_call_count}"
        )

        ok = telegram.send_report(tg_token, tg_chat_id, final_text, header=header)
        if ok:
            console.print("[green]✓ Report sent to Telegram.[/]")
        else:
            console.print("[red]✗ Telegram send failed. Check token/chat_id.[/]")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PolyMarket Research Bot — find edge with Claude + external data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python polymarket_bot.py
  python polymarket_bot.py --query "bitcoin"
  python polymarket_bot.py --query "Premier League" --focus sports
  python polymarket_bot.py --focus crypto --top 25 --telegram
  python polymarket_bot.py --query "US election" --top 30 --max-tools 40 --telegram
  python polymarket_bot.py --tg-test        # verify Telegram connection
        """,
    )
    parser.add_argument("--query", "-q", type=str, default=None,
                        help="Topic to investigate (market keyword)")
    parser.add_argument("--top", "-n", type=int, default=20,
                        help="Top N markets to survey (default: 20)")
    parser.add_argument("--focus", "-f", type=str, default=None,
                        help="Category to focus on: crypto, sports, politics, finance, science")
    parser.add_argument("--max-tools", type=int, default=30,
                        help="Max tool calls allowed (default: 30)")
    parser.add_argument("--telegram", "-t", action="store_true",
                        help="Send research report to Telegram after completion")
    parser.add_argument("--tg-test", action="store_true",
                        help="Test Telegram connection and exit")

    args = parser.parse_args()

    if args.tg_test:
        tg_token, tg_chat_id = _tg_credentials()
        if not tg_token or not tg_chat_id:
            console.print(
                "[red bold]Error:[/] Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env first."
            )
            sys.exit(1)
        console.print("[dim]Testing Telegram connection…[/]")
        result = telegram.test_connection(tg_token, tg_chat_id)
        if result["ok"]:
            console.print(f"[green]✓ {result['message']}[/]")
        else:
            console.print(f"[red]✗ {result['message']}[/]")
            sys.exit(1)
        return

    run_bot(
        query=args.query,
        top_n=args.top,
        focus=args.focus,
        max_tool_calls=args.max_tools,
        send_telegram=args.telegram,
    )


if __name__ == "__main__":
    main()
