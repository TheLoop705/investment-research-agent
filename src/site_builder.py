from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    from src.research_core import (
        DEFAULT_DIGEST_DIR,
        DEFAULT_PORTFOLIO,
        enrich_intelligence_snapshot,
        load_portfolio,
        read_latest_intelligence_snapshot,
    )
except ModuleNotFoundError:
    from research_core import (
        DEFAULT_DIGEST_DIR,
        DEFAULT_PORTFOLIO,
        enrich_intelligence_snapshot,
        load_portfolio,
        read_latest_intelligence_snapshot,
    )


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
DEFAULT_SITE_DIR = ROOT / "docs"


def slugify_digest_path(path: Path) -> str:
    return path.with_suffix(".html").name


def slugify_ticker(ticker: str) -> str:
    return f"{ticker.upper()}.html"


def markdown_to_html(markdown_text: str) -> str:
    if not markdown_text:
        return "<p class='empty-state'>No digest has been generated yet.</p>"

    return markdown.markdown(
        markdown_text,
        extensions=["extra", "sane_lists", "tables"],
    )


def render_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "xml"]),
    )


def build_ticker_maps(holdings: list[object], intelligence_snapshot: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    holdings_by_ticker = {holding.ticker: holding for holding in holdings}
    signals_by_ticker = {
        signal["ticker"]: signal for signal in intelligence_snapshot.get("ticker_signals", [])
    }
    return holdings_by_ticker, signals_by_ticker


def build_ticker_detail_context(
    ticker: str,
    *,
    holdings_by_ticker: dict[str, object],
    signals_by_ticker: dict[str, object],
    latest_digest_name: str,
    generated_at: str,
    digest_href: str | None = None,
    home_href: str = "../index.html",
) -> dict[str, object] | None:
    normalized_ticker = ticker.upper()
    holding = holdings_by_ticker.get(normalized_ticker)
    signal = signals_by_ticker.get(normalized_ticker)

    if holding is None and signal is None:
        return None

    company = holding.company if holding else signal["company"]
    themes = []
    if signal:
        seen_themes: set[str] = set()
        for cluster in signal.get("top_clusters", []):
            for theme in cluster.get("theme_tags", []):
                if theme not in seen_themes:
                    seen_themes.add(theme)
                    themes.append(theme)

    return {
        "ticker": normalized_ticker,
        "company": company,
        "holding": holding,
        "signal": signal,
        "ticker_themes": themes,
        "latest_digest_name": latest_digest_name,
        "digest_href": digest_href,
        "generated_at": generated_at,
        "home_href": home_href,
    }


def build_static_site(
    site_dir: Path = DEFAULT_SITE_DIR,
    portfolio_path: Path = DEFAULT_PORTFOLIO,
    digest_dir: Path = DEFAULT_DIGEST_DIR,
) -> Path:
    env = render_environment()
    site_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = site_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    digest_output_dir = site_dir / "digests"
    digest_output_dir.mkdir(parents=True, exist_ok=True)
    ticker_output_dir = site_dir / "tickers"
    ticker_output_dir.mkdir(parents=True, exist_ok=True)
    for stale_page in digest_output_dir.glob("*.html"):
        stale_page.unlink()
    for stale_page in ticker_output_dir.glob("*.html"):
        stale_page.unlink()

    shutil.copy2(STATIC / "app.css", assets_dir / "app.css")
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")

    holdings, custom_feeds = load_portfolio(portfolio_path)
    portfolio_items = [holding for holding in holdings if holding.bucket == "portfolio"]
    watchlist_items = [holding for holding in holdings if holding.bucket == "watchlist"]
    digest_paths = sorted(digest_dir.glob("*-daily-digest.md"), reverse=True) if digest_dir.exists() else []
    _, intelligence_snapshot = read_latest_intelligence_snapshot(digest_dir)
    intelligence_snapshot = enrich_intelligence_snapshot(holdings, intelligence_snapshot)
    holdings_by_ticker, signals_by_ticker = build_ticker_maps(holdings, intelligence_snapshot)
    overview = intelligence_snapshot.get("overview", {})

    latest_digest_html = ""
    latest_digest_name = "No digest yet"
    recent_digests: list[dict[str, str]] = []

    digest_template = env.get_template("static_digest.html")
    ticker_template = env.get_template("static_ticker_detail.html")
    for digest_path in digest_paths:
        digest_markdown = digest_path.read_text(encoding="utf-8")
        digest_html = markdown_to_html(digest_markdown)
        digest_output_path = digest_output_dir / slugify_digest_path(digest_path)
        digest_output_path.write_text(
            digest_template.render(
                title=digest_path.stem,
                asset_prefix="../assets",
                home_href="../index.html",
                digest_name=digest_path.name,
                digest_html=digest_html,
                generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            ),
            encoding="utf-8",
        )
        recent_digests.append(
            {
                "name": digest_path.name,
                "href": f"digests/{digest_output_path.name}",
            }
        )
        if not latest_digest_html:
            latest_digest_html = digest_html
            latest_digest_name = digest_path.name

    for ticker in sorted(set(holdings_by_ticker) | set(signals_by_ticker)):
        ticker_context = build_ticker_detail_context(
            ticker,
            holdings_by_ticker=holdings_by_ticker,
            signals_by_ticker=signals_by_ticker,
            latest_digest_name=latest_digest_name,
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            digest_href=f"../digests/{slugify_digest_path(digest_paths[0])}" if digest_paths else None,
            home_href="../index.html",
        )
        if ticker_context is None:
            continue
        (ticker_output_dir / slugify_ticker(ticker)).write_text(
            ticker_template.render(
                title=f"{ticker_context['ticker']} detail",
                asset_prefix="../assets",
                **ticker_context,
            ),
            encoding="utf-8",
        )

    index_template = env.get_template("static_index.html")
    (site_dir / "index.html").write_text(
        index_template.render(
            title="Investment Research Dashboard",
            asset_prefix="assets",
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            portfolio_items=portfolio_items,
            watchlist_items=watchlist_items,
            custom_feeds=custom_feeds,
            digest_count=len(digest_paths),
            portfolio_count=len(portfolio_items),
            watchlist_count=len(watchlist_items),
            latest_digest_name=latest_digest_name,
            latest_digest_html=latest_digest_html,
            ticker_signals=intelligence_snapshot.get("ticker_signals", []),
            signal_board=intelligence_snapshot.get("signal_board", []),
            cross_themes=intelligence_snapshot.get("cross_themes", []),
            top_risks=intelligence_snapshot.get("top_risks", []),
            fed_monitor=intelligence_snapshot.get("fed_monitor", {}),
            earnings_calendar=intelligence_snapshot.get("earnings_calendar", []),
            overview_cards=overview.get("summary_cards", []),
            relevance_mix=overview.get("relevance_mix", []),
            event_mix=overview.get("event_mix", []),
            theme_count=overview.get("theme_count", 0),
            cluster_count=overview.get("cluster_count", 0),
            recent_digests=recent_digests[:12],
        ),
        encoding="utf-8",
    )
    return site_dir


def main() -> int:
    build_static_site()
    print(f"Built static site: {DEFAULT_SITE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
