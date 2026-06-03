from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORTFOLIO = ROOT / "portfolio.json"
DEFAULT_DIGEST_DIR = ROOT / "digests"


@dataclass
class Holding:
    ticker: str
    company: str
    thesis: str
    tags: list[str]
    bucket: str
    yahoo_symbol: str
    isin: str


@dataclass
class NewsItem:
    ticker: str
    company: str
    title: str
    link: str
    published: str
    source: str


def load_environment() -> None:
    if load_dotenv:
        load_dotenv(ROOT / ".env")


def load_portfolio_data(path: Path = DEFAULT_PORTFOLIO) -> dict[str, Any]:
    if not path.exists():
        return {"portfolio": [], "watchlist": [], "custom_feeds": []}

    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("portfolio", [])
    data.setdefault("watchlist", [])
    data.setdefault("custom_feeds", [])
    return data


def load_portfolio(path: Path = DEFAULT_PORTFOLIO) -> tuple[list[Holding], list[str]]:
    data = load_portfolio_data(path)
    holdings: list[Holding] = []

    for bucket in ("portfolio", "watchlist"):
        for item in data.get(bucket, []):
            holdings.append(
                Holding(
                    ticker=item["ticker"].upper(),
                    company=item.get("company", item["ticker"].upper()),
                    thesis=item.get("thesis", ""),
                    tags=item.get("tags", []),
                    bucket=bucket,
                    yahoo_symbol=item.get("yahoo_symbol", item["ticker"]).upper(),
                    isin=item.get("isin", ""),
                )
            )

    feeds = data.get("custom_feeds", [])
    return holdings, feeds


def save_portfolio_data(data: dict[str, Any], path: Path = DEFAULT_PORTFOLIO) -> None:
    normalized = {
        "portfolio": data.get("portfolio", []),
        "watchlist": data.get("watchlist", []),
        "custom_feeds": data.get("custom_feeds", []),
    }
    path.write_text(json.dumps(normalized, indent=2) + "\n", encoding="utf-8")


def normalize_tags(raw_tags: str) -> list[str]:
    return [tag.strip() for tag in raw_tags.split(",") if tag.strip()]


def add_holding(
    *,
    bucket: str,
    ticker: str,
    company: str,
    thesis: str,
    tags: str,
    yahoo_symbol: str = "",
    isin: str = "",
    path: Path = DEFAULT_PORTFOLIO,
) -> None:
    if bucket not in {"portfolio", "watchlist"}:
        raise ValueError("Bucket must be portfolio or watchlist.")

    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        raise ValueError("Ticker is required.")

    data = load_portfolio_data(path)
    all_items = data["portfolio"] + data["watchlist"]
    if any(item.get("ticker", "").upper() == normalized_ticker for item in all_items):
        raise ValueError(f"{normalized_ticker} already exists.")

    data[bucket].append(
        {
            "ticker": normalized_ticker,
            "yahoo_symbol": (yahoo_symbol.strip() or normalized_ticker).upper(),
            "company": company.strip() or normalized_ticker,
            "thesis": thesis.strip(),
            "tags": normalize_tags(tags),
            "isin": isin.strip(),
        }
    )
    save_portfolio_data(data, path)


def remove_holding(bucket: str, ticker: str, path: Path = DEFAULT_PORTFOLIO) -> bool:
    if bucket not in {"portfolio", "watchlist"}:
        return False

    data = load_portfolio_data(path)
    normalized_ticker = ticker.strip().upper()
    original_count = len(data[bucket])
    data[bucket] = [
        item for item in data[bucket] if item.get("ticker", "").upper() != normalized_ticker
    ]
    if len(data[bucket]) == original_count:
        return False

    save_portfolio_data(data, path)
    return True


def add_custom_feed(url: str, path: Path = DEFAULT_PORTFOLIO) -> None:
    normalized_url = url.strip()
    if not normalized_url:
        raise ValueError("Feed URL is required.")

    data = load_portfolio_data(path)
    if normalized_url in data["custom_feeds"]:
        raise ValueError("Feed already exists.")

    data["custom_feeds"].append(normalized_url)
    save_portfolio_data(data, path)


def remove_custom_feed(url: str, path: Path = DEFAULT_PORTFOLIO) -> bool:
    data = load_portfolio_data(path)
    original_count = len(data["custom_feeds"])
    data["custom_feeds"] = [item for item in data["custom_feeds"] if item != url]
    if len(data["custom_feeds"]) == original_count:
        return False

    save_portfolio_data(data, path)
    return True


def fetch_url(url: str, timeout: int = 20) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "investment-research-agent/0.1 "
                "(local portfolio research; contact: local-user)"
            )
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def parse_rss(content: bytes, ticker: str, company: str, source: str) -> list[NewsItem]:
    root = ET.fromstring(content)
    items: list[NewsItem] = []

    for item in root.findall(".//item")[:12]:
        title = text_or_empty(item, "title")
        link = text_or_empty(item, "link")
        published = text_or_empty(item, "pubDate")

        if published:
            try:
                published = parsedate_to_datetime(published).isoformat()
            except (TypeError, ValueError):
                pass

        if title and link:
            items.append(
                NewsItem(
                    ticker=ticker,
                    company=company,
                    title=title,
                    link=link,
                    published=published,
                    source=source,
                )
            )

    return items


def text_or_empty(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def fetch_ticker_news(holding: Holding) -> list[NewsItem]:
    url = (
        "https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={quote(holding.yahoo_symbol)}&region=US&lang=en-US"
    )
    try:
        return parse_rss(fetch_url(url), holding.ticker, holding.company, "Yahoo Finance")
    except Exception as exc:
        return [
            NewsItem(
                ticker=holding.ticker,
                company=holding.company,
                title=f"Fetch failed: {exc}",
                link=url,
                published="",
                source="System",
            )
        ]


def fetch_custom_feeds(feed_urls: list[str]) -> list[NewsItem]:
    items: list[NewsItem] = []
    for url in feed_urls:
        try:
            items.extend(parse_rss(fetch_url(url), "CUSTOM", "Custom feed", url))
        except Exception as exc:
            items.append(
                NewsItem(
                    ticker="CUSTOM",
                    company="Custom feed",
                    title=f"Fetch failed for {url}: {exc}",
                    link=url,
                    published="",
                    source="System",
                )
            )
    return items


def dedupe_news(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    deduped: list[NewsItem] = []

    for item in items:
        key = item.link or f"{item.ticker}:{item.title}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    return deduped


def score_news_item(item: NewsItem, holding: Holding | None) -> int:
    title = item.title.lower()
    score = 0

    if holding:
        if holding.ticker.lower() in title:
            score += 5
        if holding.company.lower() in title:
            score += 5
        for tag in holding.tags:
            if tag.lower() in title:
                score += 2

    important_terms = [
        "earnings",
        "guidance",
        "revenue",
        "profit",
        "margin",
        "sec",
        "lawsuit",
        "regulation",
        "antitrust",
        "downgrade",
        "upgrade",
        "analyst",
        "acquisition",
        "partnership",
        "ai",
        "cloud",
        "chip",
        "data center",
    ]
    score += sum(1 for term in important_terms if term in title)

    noisy_terms = [
        "retirement",
        "millionaire",
        "prediction:",
        "buy, hold, or sell",
        "what a $1k",
    ]
    score -= sum(3 for term in noisy_terms if term in title)
    return score


def rank_and_trim_news(
    holdings: list[Holding], items: list[NewsItem], per_ticker: int = 8
) -> list[NewsItem]:
    holdings_by_ticker = {holding.ticker: holding for holding in holdings}
    grouped: dict[str, list[NewsItem]] = {}

    for item in items:
        grouped.setdefault(item.ticker, []).append(item)

    ranked: list[NewsItem] = []
    for ticker, ticker_items in grouped.items():
        holding = holdings_by_ticker.get(ticker)
        sorted_items = sorted(
            ticker_items,
            key=lambda item: score_news_item(item, holding),
            reverse=True,
        )
        ranked.extend(sorted_items[:per_ticker])

    return ranked


def build_prompt(holdings: list[Holding], news: list[NewsItem]) -> str:
    portfolio_lines = "\n".join(
        (
            f"- {h.ticker} ({h.company}, {h.bucket}): {h.thesis} "
            f"Yahoo: {h.yahoo_symbol} ISIN: {h.isin or 'n/a'} "
            f"Tags: {', '.join(h.tags)}"
        )
        for h in holdings
    )
    news_lines = "\n".join(
        f"- [{n.ticker}] {n.title} | {n.source} | {n.published} | {n.link}"
        for n in news[:80]
    )

    return f"""
You are an investment research assistant. Create a daily portfolio digest.

Rules:
- Do not give financial advice or buy/sell instructions.
- Separate sourced facts from interpretation.
- Prioritize what changed, what matters, and what deserves follow-up.
- Include adjacent public companies to research, with why they are adjacent.
- Include source links.
- Be concise but specific.

Portfolio:
{portfolio_lines}

News items:
{news_lines}

Return Markdown with these sections:
1. Executive Summary
2. Portfolio Updates
3. Risk Flags
4. Adjacent Stocks To Research
5. Questions For Follow-Up
6. Sources
""".strip()


def generate_openai_digest(holdings: list[Holding], news: list[NewsItem]) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        return None

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    response = client.responses.create(
        model=model,
        input=build_prompt(holdings, news),
    )
    return response.output_text


def generate_fallback_digest(holdings: list[Holding], news: list[NewsItem]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Daily Portfolio Digest - {now}",
        "",
        "OpenAI is not configured yet, so this is a basic headline digest.",
        "",
        "## Portfolio",
        "",
    ]

    for holding in holdings:
        lines.append(f"- **{holding.ticker} ({holding.company})**: {holding.thesis}")

    lines.extend(["", "## Headlines", ""])

    for item in news:
        lines.append(
            f"- **{item.ticker}**: [{item.title}]({item.link})"
            f" - {item.source} {item.published}".rstrip()
        )

    lines.extend(
        [
            "",
            "## Next Setup Step",
            "",
            "Add `OPENAI_API_KEY` to `.env` for analysis, risk flags, and adjacent-stock ideas.",
        ]
    )

    return "\n".join(lines)


def write_digest(markdown: str, digest_dir: Path = DEFAULT_DIGEST_DIR) -> Path:
    digest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y-%m-%d')}-daily-digest.md"
    path = digest_dir / filename
    path.write_text(markdown, encoding="utf-8")
    return path


def run_digest(
    portfolio_path: Path = DEFAULT_PORTFOLIO,
    digest_dir: Path = DEFAULT_DIGEST_DIR,
) -> Path:
    load_environment()
    holdings, custom_feeds = load_portfolio(portfolio_path)

    news: list[NewsItem] = []
    for holding in holdings:
        news.extend(fetch_ticker_news(holding))
    news.extend(fetch_custom_feeds(custom_feeds))
    news = dedupe_news(news)
    news = rank_and_trim_news(holdings, news)

    digest = generate_openai_digest(holdings, news)
    if digest is None:
        digest = generate_fallback_digest(holdings, news)

    output_path = write_digest(digest, digest_dir)

    try:
        try:
            from src.site_builder import build_static_site
        except ModuleNotFoundError:
            from site_builder import build_static_site

        build_static_site()
    except Exception:
        pass

    return output_path


def list_digest_paths(digest_dir: Path = DEFAULT_DIGEST_DIR) -> list[Path]:
    if not digest_dir.exists():
        return []
    return sorted(digest_dir.glob("*-daily-digest.md"), reverse=True)


def read_latest_digest(digest_dir: Path = DEFAULT_DIGEST_DIR) -> tuple[Path | None, str]:
    digest_paths = list_digest_paths(digest_dir)
    if not digest_paths:
        return None, ""

    latest = digest_paths[0]
    return latest, latest.read_text(encoding="utf-8")
