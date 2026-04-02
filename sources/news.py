"""
News source — Google News RSS + BBC RSS (no API key required).

Google News RSS is the primary source: it supports keyword search and
returns fresh, relevant articles from thousands of publishers globally.
"""

import html
import re
import time
from typing import Any

import feedparser
import requests

# RSS feed definitions: (name, url_template)
# For Google News: {query} is URL-encoded search term
_GOOGLE_NEWS_SEARCH = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

_STATIC_FEEDS = {
    "bbc_world": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "bbc_tech": "http://feeds.bbci.co.uk/news/technology/rss.xml",
    "bbc_business": "http://feeds.bbci.co.uk/news/business/rss.xml",
    "bbc_sport": "http://feeds.bbci.co.uk/news/sport/rss.xml",
    "bbc_science": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
}


def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def _parse_entry(entry: Any) -> dict:
    return {
        "title": _clean_html(entry.get("title", "")),
        "summary": _clean_html(entry.get("summary", ""))[:300],
        "published": entry.get("published", ""),
        "link": entry.get("link", ""),
        "source": entry.get("source", {}).get("title", "") if isinstance(entry.get("source"), dict) else "",
    }


def search_news(query: str, max_items: int = 10) -> dict:
    """
    Search recent news across the web via Google News RSS.
    Returns titles, summaries, publication dates, and source names.
    Useful for checking whether a market topic has recent developments.
    """
    url = _GOOGLE_NEWS_SEARCH.format(query=requests.utils.quote(query))
    try:
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            return {"error": f"Failed to parse Google News RSS for '{query}'", "query": query}
        items = [_parse_entry(e) for e in feed.entries[:max_items]]
        return {
            "query": query,
            "source": "Google News",
            "count": len(items),
            "articles": items,
        }
    except Exception as e:
        return {"error": str(e), "query": query}


def get_latest_news(topic: str = "world", max_items: int = 10) -> dict:
    """
    Get latest headlines from BBC RSS for a broad topic.
    topic options: world, business, tech, sport, science
    """
    feed_map = {
        "world": "bbc_world",
        "business": "bbc_business",
        "finance": "bbc_business",
        "tech": "bbc_tech",
        "technology": "bbc_tech",
        "sport": "bbc_sport",
        "sports": "bbc_sport",
        "science": "bbc_science",
    }
    feed_key = feed_map.get(topic.lower(), "bbc_world")
    url = _STATIC_FEEDS[feed_key]

    try:
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            return {"error": f"Failed to parse BBC RSS feed for topic '{topic}'"}
        items = [_parse_entry(e) for e in feed.entries[:max_items]]
        return {
            "topic": topic,
            "source": "BBC News",
            "count": len(items),
            "articles": items,
        }
    except Exception as e:
        return {"error": str(e), "topic": topic}
