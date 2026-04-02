"""
News source — Google News RSS + BBC RSS.
Uses only stdlib (xml.etree.ElementTree + requests) — no feedparser needed.
"""

import html
import re
import xml.etree.ElementTree as ET
from typing import Any

import requests

_GOOGLE_NEWS_SEARCH = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

_STATIC_FEEDS = {
    "bbc_world":    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "bbc_business": "http://feeds.bbci.co.uk/news/business/rss.xml",
    "bbc_tech":     "http://feeds.bbci.co.uk/news/technology/rss.xml",
    "bbc_sport":    "http://feeds.bbci.co.uk/news/sport/rss.xml",
    "bbc_science":  "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PolyMarket-Research-Bot/1.0; "
        "+https://github.com/clairvoyance4/polik1)"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()


def _parse_rss(xml_bytes: bytes) -> list[dict]:
    """Parse RSS XML and return list of article dicts."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    # Handle both RSS 2.0 and Atom namespaces
    ns = {"media": "http://search.yahoo.com/mrss/"}
    items = root.findall(".//item")
    articles = []
    for item in items:
        def t(tag: str) -> str:
            el = item.find(tag)
            return _clean(el.text or "") if el is not None else ""

        source_el = item.find("source")
        source = _clean(source_el.text or "") if source_el is not None else ""

        articles.append({
            "title":     t("title"),
            "summary":   t("description")[:300],
            "published": t("pubDate"),
            "link":      t("link"),
            "source":    source,
        })
    return articles


def _fetch_rss(url: str) -> tuple[list[dict], str | None]:
    """Fetch and parse an RSS feed. Returns (articles, error_or_None)."""
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        return _parse_rss(r.content), None
    except requests.exceptions.RequestException as e:
        return [], str(e)


def search_news(query: str, max_items: int = 10) -> dict:
    """
    Search recent news via Google News RSS (no API key).
    Returns titles, summaries, dates, and source names.
    """
    url = _GOOGLE_NEWS_SEARCH.format(query=requests.utils.quote(query))
    articles, err = _fetch_rss(url)
    if err and not articles:
        return {"error": f"Google News RSS failed for '{query}': {err}", "query": query}
    return {
        "query": query,
        "source": "Google News",
        "count": len(articles[:max_items]),
        "articles": articles[:max_items],
    }


def get_latest_news(topic: str = "world", max_items: int = 10) -> dict:
    """
    Latest BBC headlines for a broad topic.
    topic: world | business | finance | tech | technology | sport | sports | science
    """
    feed_map = {
        "world": "bbc_world", "business": "bbc_business",
        "finance": "bbc_business", "tech": "bbc_tech",
        "technology": "bbc_tech", "sport": "bbc_sport",
        "sports": "bbc_sport", "science": "bbc_science",
    }
    feed_key = feed_map.get(topic.lower(), "bbc_world")
    articles, err = _fetch_rss(_STATIC_FEEDS[feed_key])
    if err and not articles:
        return {"error": f"BBC RSS failed for topic '{topic}': {err}"}
    return {
        "topic": topic,
        "source": "BBC News",
        "count": len(articles[:max_items]),
        "articles": articles[:max_items],
    }
