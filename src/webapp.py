from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import markdown
from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

try:
    from src.research_core import (
        DEFAULT_DIGEST_DIR,
        DEFAULT_PORTFOLIO,
        add_custom_feed,
        add_holding,
        list_digest_paths,
        load_environment,
        load_portfolio,
        load_portfolio_data,
        read_latest_digest,
        read_latest_intelligence_snapshot,
        remove_custom_feed,
        remove_holding,
        run_digest,
    )
except ModuleNotFoundError:
    from research_core import (
        DEFAULT_DIGEST_DIR,
        DEFAULT_PORTFOLIO,
        add_custom_feed,
        add_holding,
        list_digest_paths,
        load_environment,
        load_portfolio,
        load_portfolio_data,
        read_latest_digest,
        read_latest_intelligence_snapshot,
        remove_custom_feed,
        remove_holding,
        run_digest,
    )


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"

app = FastAPI(title="Investment Research Dashboard")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES))


def home_redirect(message: str, tone: str = "success") -> RedirectResponse:
    query = urlencode({"message": message, "tone": tone})
    return RedirectResponse(url=f"/?{query}", status_code=303)


def render_digest(markdown_text: str) -> str:
    if not markdown_text:
        return "<p class='empty-state'>No digest has been generated yet.</p>"

    return markdown.markdown(
        markdown_text,
        extensions=["extra", "sane_lists", "tables"],
    )


def build_dashboard_context(message: str = "", tone: str = "success") -> dict[str, object]:
    load_environment()
    portfolio_data = load_portfolio_data(DEFAULT_PORTFOLIO)
    holdings, custom_feeds = load_portfolio(DEFAULT_PORTFOLIO)
    latest_digest_path, latest_digest_markdown = read_latest_digest(DEFAULT_DIGEST_DIR)
    _, intelligence_snapshot = read_latest_intelligence_snapshot(DEFAULT_DIGEST_DIR)
    digest_paths = list_digest_paths(DEFAULT_DIGEST_DIR)

    holdings_by_bucket = {
        "portfolio": [holding for holding in holdings if holding.bucket == "portfolio"],
        "watchlist": [holding for holding in holdings if holding.bucket == "watchlist"],
    }

    return {
        "message": message,
        "tone": tone,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "portfolio_items": holdings_by_bucket["portfolio"],
        "watchlist_items": holdings_by_bucket["watchlist"],
        "custom_feeds": custom_feeds,
        "portfolio_path": str(DEFAULT_PORTFOLIO),
        "digest_count": len(digest_paths),
        "latest_digest_name": latest_digest_path.name if latest_digest_path else "No digest yet",
        "latest_digest_html": render_digest(latest_digest_markdown),
        "signal_board": intelligence_snapshot.get("signal_board", []),
        "cross_themes": intelligence_snapshot.get("cross_themes", []),
        "top_risks": intelligence_snapshot.get("top_risks", []),
        "recent_digests": digest_paths[:8],
        "portfolio_count": len(portfolio_data["portfolio"]),
        "watchlist_count": len(portfolio_data["watchlist"]),
    }


@app.get("/")
def index(
    request: Request,
    message: str = "",
    tone: str = "success",
):
    context = build_dashboard_context(message=message, tone=tone)
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=context,
    )


@app.post("/holdings/add")
def create_holding(
    bucket: str = Form(...),
    ticker: str = Form(...),
    company: str = Form(""),
    yahoo_symbol: str = Form(""),
    isin: str = Form(""),
    thesis: str = Form(""),
    tags: str = Form(""),
):
    try:
        add_holding(
            bucket=bucket,
            ticker=ticker,
            company=company,
            yahoo_symbol=yahoo_symbol,
            isin=isin,
            thesis=thesis,
            tags=tags,
        )
    except ValueError as exc:
        return home_redirect(str(exc), tone="error")

    return home_redirect(f"Added {ticker.strip().upper()} to {bucket}.")


@app.post("/holdings/{bucket}/{ticker}/delete")
def delete_holding(bucket: str, ticker: str):
    removed = remove_holding(bucket, ticker)
    if not removed:
        return home_redirect(f"Could not find {ticker.upper()} in {bucket}.", tone="error")

    return home_redirect(f"Removed {ticker.upper()} from {bucket}.")


@app.post("/feeds/add")
def create_feed(url: str = Form(...)):
    try:
        add_custom_feed(url)
    except ValueError as exc:
        return home_redirect(str(exc), tone="error")

    return home_redirect("Added custom feed.")


@app.post("/feeds/delete")
def delete_feed(url: str = Form(...)):
    removed = remove_custom_feed(url)
    if not removed:
        return home_redirect("Feed was not found.", tone="error")

    return home_redirect("Removed custom feed.")


@app.post("/digests/run")
def create_digest():
    output_path = run_digest(DEFAULT_PORTFOLIO, DEFAULT_DIGEST_DIR)
    return home_redirect(f"Digest generated: {output_path.name}")


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
