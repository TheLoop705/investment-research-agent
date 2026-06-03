from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
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

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "into",
    "is",
    "its",
    "it",
    "new",
    "of",
    "on",
    "or",
    "the",
    "their",
    "this",
    "to",
    "today",
    "up",
    "with",
}

EVENT_KEYWORDS: dict[str, list[str]] = {
    "earnings": ["earnings", "q1", "q2", "q3", "q4", "results", "revenue", "profit", "margin"],
    "guidance": ["guidance", "outlook", "forecast", "raises price target", "revises"],
    "partnership": ["partnership", "collaborate", "collaboration", "agreement", "ecosystem", "alliance"],
    "product": ["launch", "platform", "solution", "product", "chip", "rack", "factory", "technology"],
    "regulation": ["sec", "regulation", "regulatory", "antitrust", "tariff", "export", "certified"],
    "litigation": ["lawsuit", "sues", "legal", "probe", "investigation", "scrutiny", "short seller"],
    "financing": ["financing", "notes", "loan", "share issuance", "offering", "dilution", "debt"],
    "analyst": ["analyst", "upgrade", "downgrade", "price target", "coverage", "strong buy", "neutral stance"],
    "management": ["cfo", "ceo", "board", "director", "appoint", "transition", "shareholders"],
    "customer": ["order", "win", "customer", "supplier", "recognized", "award"],
    "macro": ["market", "economy", "labor", "record highs", "rotational", "valuation", "stock rises"],
}

EVENT_LABELS = {
    "earnings": "Earnings",
    "guidance": "Guidance",
    "partnership": "Partnership",
    "product": "Product",
    "regulation": "Regulation",
    "litigation": "Litigation",
    "financing": "Financing",
    "analyst": "Analyst",
    "management": "Management",
    "customer": "Customer",
    "macro": "Macro",
    "general": "General",
}

EVENT_SCORE_BONUS = {
    "earnings": 6,
    "guidance": 5,
    "regulation": 5,
    "litigation": 5,
    "financing": 4,
    "partnership": 4,
    "product": 3,
    "analyst": 2,
    "customer": 3,
    "management": 2,
    "macro": 1,
    "general": 0,
}

THEME_KEYWORDS = {
    "AI infrastructure": ["ai", "data center", "server", "factory", "hpc", "compute", "mgx"],
    "Power and grid": ["power", "grid", "energy", "gan", "sic", "battery"],
    "Optical and photonics": ["optical", "photonics", "laser", "co-packaged optics", "broadband"],
    "Semiconductor supply chain": ["foundry", "packaging", "assembly", "test", "chip", "semiconductor"],
    "Enterprise software": ["enterprise", "workflow", "software", "automation", "cloud"],
}

POSITIVE_HINTS = [
    "beats",
    "beat",
    "surges",
    "soars",
    "gains",
    "strengthens",
    "raises",
    "record",
    "secures",
    "recognized",
    "upgraded",
    "strong buy",
    "expansion",
    "boost",
    "higher",
    "growth",
]

NEGATIVE_HINTS = [
    "miss",
    "drops",
    "slip",
    "sinks",
    "downgrade",
    "downgraded",
    "red flags",
    "cautious",
    "decline",
    "falls",
    "neutral stance",
    "loss",
    "probe",
    "scrutiny",
    "lawsuit",
    "dilution",
    "debt",
]

SOURCE_QUALITY = {
    "reuters.com": (5.0, "Institutional"),
    "sec.gov": (5.0, "Primary"),
    "finance.yahoo.com": (3.5, "Core"),
    "www.fool.com": (2.5, "Secondary"),
    "marketbeat.com": (2.5, "Secondary"),
    "www.marketbeat.com": (2.5, "Secondary"),
    "247wallst.com": (1.5, "Speculative"),
    "stocktwits.com": (1.0, "Speculative"),
    "www.proactiveinvestors.com": (2.0, "Secondary"),
    "barchart.com": (2.5, "Secondary"),
    "www.barchart.com": (2.5, "Secondary"),
    "qz.com": (2.0, "Secondary"),
    "www.trefis.com": (2.0, "Secondary"),
    "app.moby.co": (1.5, "Speculative"),
}


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


@dataclass
class AnalyzedNewsItem:
    item: NewsItem
    event_type: str
    event_label: str
    impact: str
    source_domain: str
    source_quality_score: float
    source_quality_label: str
    title_key: str
    token_set: set[str]
    theme_tags: list[str]
    published_dt: datetime | None
    materiality_score: int


@dataclass
class NewsCluster:
    ticker: str
    company: str
    event_type: str
    event_label: str
    impact: str
    representative_title: str
    representative_link: str
    source_domain: str
    source_quality_label: str
    cluster_size: int
    latest_published: str
    materiality_score: int
    catalyst: str
    risk: str
    theme_tags: list[str]
    sources: list[dict[str, str]]


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


def normalize_title(title: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", title.lower())
    tokens = [token for token in cleaned.split() if token not in STOPWORDS]
    return " ".join(tokens)


def tokenize_title(title: str) -> set[str]:
    return set(normalize_title(title).split())


def parse_published_datetime(value: str) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        try:
            return parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None


def extract_source_domain(link: str) -> str:
    domain = urlparse(link).netloc.lower()
    return domain[4:] if domain.startswith("www.") else domain


def source_quality_for(link: str) -> tuple[float, str]:
    domain = extract_source_domain(link)
    if domain in SOURCE_QUALITY:
        return SOURCE_QUALITY[domain]

    if "finance.yahoo.com" in domain:
        return 3.5, "Core"

    return 2.5, "Secondary"


def classify_event_type(title: str) -> str:
    lowered = title.lower()
    best_match = "general"
    best_score = 0

    for event_type, keywords in EVENT_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in lowered)
        if score > best_score:
            best_match = event_type
            best_score = score

    return best_match


def infer_impact(title: str, event_type: str) -> str:
    lowered = title.lower()
    positive = sum(1 for term in POSITIVE_HINTS if term in lowered)
    negative = sum(1 for term in NEGATIVE_HINTS if term in lowered)

    if event_type in {"litigation", "regulation", "financing"}:
        negative += 1
    if event_type in {"partnership", "product", "customer"}:
        positive += 1

    if positive > negative:
        return "positive"
    if negative > positive:
        return "negative"
    return "neutral"


def infer_theme_tags(title: str, holding: Holding | None) -> list[str]:
    lowered = title.lower()
    themes: list[str] = []

    for theme, keywords in THEME_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            themes.append(theme)

    if holding:
        for tag in holding.tags:
            tag_text = tag.replace("-", " ").lower()
            if tag_text in lowered:
                if "ai" in tag_text and "AI infrastructure" not in themes:
                    themes.append("AI infrastructure")
                if "optical" in tag_text or "photonics" in tag_text:
                    if "Optical and photonics" not in themes:
                        themes.append("Optical and photonics")

    return themes


def recency_bonus(published_dt: datetime | None) -> int:
    if published_dt is None:
        return 0

    age = datetime.now(published_dt.tzinfo) - published_dt
    if age.days <= 1:
        return 3
    if age.days <= 3:
        return 2
    if age.days <= 7:
        return 1
    return 0


def analyze_news_item(item: NewsItem, holding: Holding | None) -> AnalyzedNewsItem:
    event_type = classify_event_type(item.title)
    event_label = EVENT_LABELS[event_type]
    source_quality_score, source_quality_label = source_quality_for(item.link)
    published_dt = parse_published_datetime(item.published)
    impact = infer_impact(item.title, event_type)
    materiality_score = (
        score_news_item(item, holding)
        + EVENT_SCORE_BONUS[event_type]
        + int(source_quality_score * 2)
        + recency_bonus(published_dt)
    )

    return AnalyzedNewsItem(
        item=item,
        event_type=event_type,
        event_label=event_label,
        impact=impact,
        source_domain=extract_source_domain(item.link),
        source_quality_score=source_quality_score,
        source_quality_label=source_quality_label,
        title_key=normalize_title(item.title),
        token_set=tokenize_title(item.title),
        theme_tags=infer_theme_tags(item.title, holding),
        published_dt=published_dt,
        materiality_score=materiality_score,
    )


def similarity_score(left: AnalyzedNewsItem, right: AnalyzedNewsItem) -> float:
    if left.title_key == right.title_key:
        return 1.0

    sequence = SequenceMatcher(None, left.title_key, right.title_key).ratio()
    overlap = 0.0
    if left.token_set and right.token_set:
        overlap = len(left.token_set & right.token_set) / len(left.token_set | right.token_set)
    return max(sequence, overlap)


def choose_representative_item(items: list[AnalyzedNewsItem]) -> AnalyzedNewsItem:
    return sorted(
        items,
        key=lambda item: (
            item.source_quality_score,
            item.materiality_score,
            item.published_dt.timestamp() if item.published_dt else 0,
        ),
        reverse=True,
    )[0]


def build_cluster(items: list[AnalyzedNewsItem]) -> NewsCluster:
    representative = choose_representative_item(items)
    latest_dt = max(
        (item.published_dt for item in items if item.published_dt is not None),
        default=None,
    )
    latest_published = latest_dt.isoformat() if latest_dt else representative.item.published
    materiality = max(item.materiality_score for item in items) + max(0, len(items) - 1)
    theme_tags = sorted({theme for item in items for theme in item.theme_tags})

    catalyst = ""
    risk = ""
    if representative.impact == "positive":
        catalyst = representative.item.title
    elif representative.impact == "negative":
        risk = representative.item.title
    elif representative.event_type in {"earnings", "guidance", "partnership", "product", "customer"}:
        catalyst = representative.item.title
    elif representative.event_type in {"regulation", "litigation", "financing"}:
        risk = representative.item.title

    return NewsCluster(
        ticker=representative.item.ticker,
        company=representative.item.company,
        event_type=representative.event_type,
        event_label=representative.event_label,
        impact=representative.impact,
        representative_title=representative.item.title,
        representative_link=representative.item.link,
        source_domain=representative.source_domain,
        source_quality_label=representative.source_quality_label,
        cluster_size=len(items),
        latest_published=latest_published,
        materiality_score=materiality,
        catalyst=catalyst,
        risk=risk,
        theme_tags=theme_tags,
        sources=[
            {
                "title": item.item.title,
                "link": item.item.link,
                "source": item.item.source,
                "domain": item.source_domain,
            }
            for item in sorted(items, key=lambda item: item.materiality_score, reverse=True)[:4]
        ],
    )


def cluster_news_items(analyzed_items: list[AnalyzedNewsItem]) -> list[NewsCluster]:
    clusters: list[list[AnalyzedNewsItem]] = []

    for analyzed in sorted(analyzed_items, key=lambda item: item.materiality_score, reverse=True):
        matched_cluster: list[AnalyzedNewsItem] | None = None

        for cluster in clusters:
            representative = choose_representative_item(cluster)
            if representative.event_type != analyzed.event_type:
                continue
            if similarity_score(representative, analyzed) >= 0.58:
                matched_cluster = cluster
                break

        if matched_cluster is None:
            clusters.append([analyzed])
        else:
            matched_cluster.append(analyzed)

    return sorted((build_cluster(cluster) for cluster in clusters), key=lambda item: item.materiality_score, reverse=True)


def event_counts_list(clusters: list[NewsCluster]) -> list[dict[str, Any]]:
    counts = Counter(cluster.event_label for cluster in clusters)
    return [
        {"label": label, "count": count}
        for label, count in counts.most_common()
    ]


def decision_relevance_for(clusters: list[NewsCluster]) -> str:
    if not clusters:
        return "Low"

    top_score = clusters[0].materiality_score
    if top_score >= 20:
        return "High"
    if top_score >= 14:
        return "Medium"
    return "Low"


def ticker_overview_for(holding: Holding | None, clusters: list[NewsCluster]) -> str:
    if not clusters:
        return f"{holding.ticker if holding else 'Ticker'} has no high-signal headlines in the latest pull."

    lead = clusters[0]
    direction = {
        "positive": "leans constructive",
        "negative": "leans cautious",
        "neutral": "is mixed",
    }[lead.impact]
    return (
        f"{lead.event_label} coverage {direction}; "
        f"top signal is '{lead.representative_title}'"
        f"{' with corroborating variants' if lead.cluster_size > 1 else ''}."
    )


def cluster_follow_up_question(cluster: NewsCluster) -> str:
    if cluster.event_type == "earnings":
        return f"What did management say on the latest {cluster.ticker} call about durability beyond this quarter?"
    if cluster.event_type == "guidance":
        return f"Does the updated {cluster.ticker} outlook change the thesis time horizon or only near-term expectations?"
    if cluster.event_type == "partnership":
        return f"Is the {cluster.ticker} partnership likely to affect revenue timing or mostly narrative?"
    if cluster.event_type == "regulation":
        return f"What is the real exposure of {cluster.ticker} to the cited regulatory issue?"
    if cluster.event_type == "financing":
        return f"How material is the financing or dilution path for {cluster.ticker} from here?"
    if cluster.event_type == "litigation":
        return f"Is the legal or scrutiny headline for {cluster.ticker} operationally meaningful or mostly noise?"
    return f"What changed for {cluster.ticker} that deserves primary-source follow-up?"


def build_news_intelligence(holdings: list[Holding], news: list[NewsItem]) -> dict[str, Any]:
    holdings_by_ticker = {holding.ticker: holding for holding in holdings}
    analyzed_by_ticker: dict[str, list[AnalyzedNewsItem]] = defaultdict(list)

    for item in news:
        analyzed_by_ticker[item.ticker].append(analyze_news_item(item, holdings_by_ticker.get(item.ticker)))

    ticker_signals: list[dict[str, Any]] = []
    all_clusters: list[NewsCluster] = []

    for ticker, analyzed_items in analyzed_by_ticker.items():
        holding = holdings_by_ticker.get(ticker)
        clusters = cluster_news_items(analyzed_items)
        all_clusters.extend(clusters)

        catalysts = [cluster.catalyst for cluster in clusters if cluster.catalyst][:3]
        risks = [cluster.risk for cluster in clusters if cluster.risk][:3]
        signal = {
            "ticker": ticker,
            "company": holding.company if holding else analyzed_items[0].item.company,
            "overview": ticker_overview_for(holding, clusters[:3]),
            "dominant_event": clusters[0].event_label if clusters else "General",
            "decision_relevance": decision_relevance_for(clusters),
            "event_counts": event_counts_list(clusters),
            "catalysts": catalysts,
            "risks": risks,
            "top_clusters": [asdict(cluster) for cluster in clusters[:3]],
            "score": clusters[0].materiality_score if clusters else 0,
        }
        ticker_signals.append(signal)

    ticker_signals.sort(key=lambda item: item["score"], reverse=True)
    all_clusters.sort(key=lambda item: item.materiality_score, reverse=True)

    theme_map: dict[str, dict[str, Any]] = {}
    for signal in ticker_signals:
        seen_for_ticker: set[str] = set()
        for cluster in signal["top_clusters"]:
            for theme in cluster["theme_tags"]:
                if theme in seen_for_ticker:
                    continue
                seen_for_ticker.add(theme)
                bucket = theme_map.setdefault(theme, {"theme": theme, "tickers": [], "count": 0})
                bucket["tickers"].append(signal["ticker"])
                bucket["count"] += 1

    cross_themes = sorted(
        [theme for theme in theme_map.values() if theme["count"] >= 2],
        key=lambda theme: theme["count"],
        reverse=True,
    )[:6]

    top_risks = []
    for signal in ticker_signals:
        for risk in signal["risks"][:2]:
            top_risks.append({"ticker": signal["ticker"], "company": signal["company"], "risk": risk})
    top_risks = top_risks[:10]

    follow_up_questions = []
    for cluster in all_clusters[:8]:
        follow_up_questions.append(cluster_follow_up_question(cluster))

    sources = []
    for cluster in all_clusters[:16]:
        sources.append(
            {
                "ticker": cluster.ticker,
                "title": cluster.representative_title,
                "link": cluster.representative_link,
                "quality": cluster.source_quality_label,
                "domain": cluster.source_domain,
            }
        )

    return {
        "generated_at": datetime.now().isoformat(),
        "signal_board": ticker_signals[:8],
        "cross_themes": cross_themes,
        "top_risks": top_risks,
        "follow_up_questions": follow_up_questions[:8],
        "sources": sources,
    }


def build_prompt(holdings: list[Holding], intelligence: dict[str, Any]) -> str:
    portfolio_lines = "\n".join(
        (
            f"- {holding.ticker} ({holding.company}, {holding.bucket}): {holding.thesis} "
            f"Yahoo: {holding.yahoo_symbol} ISIN: {holding.isin or 'n/a'} "
            f"Tags: {', '.join(holding.tags)}"
        )
        for holding in holdings
    )

    signal_lines = "\n".join(
        (
            f"- {signal['ticker']} ({signal['company']}) | relevance: {signal['decision_relevance']} | "
            f"dominant event: {signal['dominant_event']} | overview: {signal['overview']} | "
            f"catalysts: {', '.join(signal['catalysts']) or 'none'} | "
            f"risks: {', '.join(signal['risks']) or 'none'}"
        )
        for signal in intelligence["signal_board"]
    )

    source_lines = "\n".join(
        f"- [{item['ticker']}] {item['title']} | {item['quality']} | {item['domain']} | {item['link']}"
        for item in intelligence["sources"][:24]
    )

    return f"""
You are an investment research assistant. Create a daily portfolio digest.

Rules:
- Do not give financial advice or buy/sell instructions.
- Separate sourced facts from interpretation.
- Prioritize what changed, what matters, and what deserves follow-up.
- Focus on decision-relevant developments, not generic stock chatter.
- Include source links in the Sources section.
- Be concise but specific.

Portfolio:
{portfolio_lines}

Structured signal board:
{signal_lines}

Representative sources:
{source_lines}

Return Markdown with these sections:
1. Executive Summary
2. Highest-Signal Portfolio Updates
3. Risk Flags
4. Cross-Holding Themes
5. Questions For Follow-Up
6. Sources
""".strip()


def generate_openai_digest(holdings: list[Holding], intelligence: dict[str, Any]) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        return None

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    response = client.responses.create(
        model=model,
        input=build_prompt(holdings, intelligence),
    )
    return response.output_text


def generate_fallback_digest(holdings: list[Holding], intelligence: dict[str, Any]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Daily Portfolio Digest - {now}",
        "",
        "Generated with local news-intelligence scoring, clustering, and signal extraction.",
        "",
        "## Executive Summary",
        "",
    ]

    for signal in intelligence["signal_board"][:5]:
        lines.append(f"- **{signal['ticker']}**: {signal['overview']}")

    lines.extend(["", "## Highest-Signal Portfolio Updates", ""])

    for signal in intelligence["signal_board"][:8]:
        lines.append(f"### {signal['ticker']} ({signal['company']})")
        lines.append("")
        lines.append(
            f"- **Relevance:** {signal['decision_relevance']} | "
            f"**Dominant event:** {signal['dominant_event']}"
        )
        if signal["catalysts"]:
            lines.append("- **Catalysts:**")
            for catalyst in signal["catalysts"][:2]:
                lines.append(f"  - {catalyst}")
        if signal["risks"]:
            lines.append("- **Risks:**")
            for risk in signal["risks"][:2]:
                lines.append(f"  - {risk}")
        for cluster in signal["top_clusters"][:2]:
            cluster_suffix = f" ({cluster['cluster_size']} related headlines)" if cluster["cluster_size"] > 1 else ""
            lines.append(
                f"- **{cluster['event_label']} / {cluster['source_quality_label']}**: "
                f"[{cluster['representative_title']}]({cluster['representative_link']}){cluster_suffix}"
            )
        lines.append("")

    lines.extend(["## Risk Flags", ""])
    if intelligence["top_risks"]:
        for risk in intelligence["top_risks"][:10]:
            lines.append(f"- **{risk['ticker']}**: {risk['risk']}")
    else:
        lines.append("- No material risk flags surfaced in the latest pull.")

    lines.extend(["", "## Cross-Holding Themes", ""])
    if intelligence["cross_themes"]:
        for theme in intelligence["cross_themes"]:
            lines.append(
                f"- **{theme['theme']}** across {theme['count']} names: {', '.join(theme['tickers'])}"
            )
    else:
        lines.append("- No cross-holding theme showed up across multiple tracked names.")

    lines.extend(["", "## Questions For Follow-Up", ""])
    for question in intelligence["follow_up_questions"][:8]:
        lines.append(f"- {question}")

    lines.extend(["", "## Sources", ""])
    for source in intelligence["sources"][:18]:
        lines.append(
            f"- **{source['ticker']}**: [{source['title']}]({source['link']}) "
            f"- {source['quality']} / {source['domain']}"
        )

    lines.extend(
        [
            "",
            "## Next Setup Step",
            "",
            "Add `OPENAI_API_KEY` to `.env` for deeper synthesis on top of the structured local signal extraction.",
        ]
    )

    return "\n".join(lines)


def write_digest(markdown: str, digest_dir: Path = DEFAULT_DIGEST_DIR) -> Path:
    digest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y-%m-%d')}-daily-digest.md"
    path = digest_dir / filename
    path.write_text(markdown, encoding="utf-8")
    return path


def write_intelligence_snapshot(
    intelligence: dict[str, Any],
    digest_path: Path,
) -> Path:
    snapshot_path = digest_path.with_suffix(".json")
    snapshot_path.write_text(json.dumps(intelligence, indent=2), encoding="utf-8")
    return snapshot_path


def read_latest_intelligence_snapshot(
    digest_dir: Path = DEFAULT_DIGEST_DIR,
) -> tuple[Path | None, dict[str, Any]]:
    digest_paths = list_digest_paths(digest_dir)
    if not digest_paths:
        return None, {}

    snapshot_path = digest_paths[0].with_suffix(".json")
    if not snapshot_path.exists():
        return None, {}

    return snapshot_path, json.loads(snapshot_path.read_text(encoding="utf-8"))


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

    intelligence = build_news_intelligence(holdings, news)
    digest = generate_openai_digest(holdings, intelligence)
    if digest is None:
        digest = generate_fallback_digest(holdings, intelligence)

    output_path = write_digest(digest, digest_dir)
    write_intelligence_snapshot(intelligence, output_path)

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
