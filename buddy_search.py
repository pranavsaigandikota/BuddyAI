"""
buddy_search.py — Web search and news via DuckDuckGo for Buddy AI.
Run standalone to test: python buddy_search.py
"""
from __future__ import annotations
import re

def web_search(query: str, max_results: int = 4) -> str:
    """Return a readable summary of DuckDuckGo web results."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "No results found."
        parts = []          
        for r in results:
            title = r.get("title", "")
            body  = r.get("body",  "")
            parts.append(f"{title}: {body}")
        return " | ".join(parts)
    except ImportError:
        # Fallback to basic HTML scrape if duckduckgo_search not installed
        import httpx, urllib.parse
        headers = {"User-Agent": "Mozilla/5.0"}
        r = httpx.get(f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}", headers=headers, timeout=8)
        snippets = re.findall(r'class="result__snippet">(.*?)</a>', r.text)[:max_results]
        clean = [re.sub(r"<.*?>", "", s).strip() for s in snippets]
        return " | ".join(clean) if clean else "No results found."
    except Exception as e:
        return f"Search failed: {e}"

def news_search(topic: str, max_results: int = 5) -> str:
    """Return recent news headlines for a topic."""
    try:
        from ddgs import DDGS
        query = f"Orlando Florida local news" if topic.strip().lower() in ("", "local") else topic
        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=max_results))
        if not results:
            return "No news found."
        parts = []
        for r in results:
            title  = r.get("title", "")
            source = r.get("source", "")
            parts.append(f"{title} ({source})" if source else title)
        return " | ".join(parts)
    except ImportError:
        # Fallback to Google News RSS
        import httpx, urllib.parse
        q = "Orlando Florida local news" if topic.strip().lower() in ("", "local") else topic
        r = httpx.get(f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en-US&gl=US&ceid=US:en", timeout=8)
        titles = re.findall(r"<title>(.*?)</title>", r.text)[1:max_results+1]
        return " | ".join(titles) if titles else "No news found."
    except Exception as e:
        return f"News search failed: {e}"


if __name__ == "__main__":
    print("=== Web Search Test ===")
    print(web_search("latest SpaceX news"))
    print()
    print("=== News Test ===")
    print(news_search("local"))
