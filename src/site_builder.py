from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    from src.research_core import DEFAULT_DIGEST_DIR, DEFAULT_PORTFOLIO, load_portfolio
except ModuleNotFoundError:
    from research_core import DEFAULT_DIGEST_DIR, DEFAULT_PORTFOLIO, load_portfolio


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"
DEFAULT_SITE_DIR = ROOT / "docs"


def markdown_to_html(markdown_text: str) -> str:
    if not markdown_text:
        return "<p class='empty-state'>No digest has been generated yet.</p>"

    return markdown.markdown(
        markdown_text,
        extensions=["extra", "sane_lists", "tables"],
    )


def slugify_digest_path(path: Path) -> str:
    return path.with_suffix(".html").name


def render_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "xml"]),
    )


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
    for stale_page in digest_output_dir.glob("*.html"):
        stale_page.unlink()

    shutil.copy2(STATIC / "app.css", assets_dir / "app.css")
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")

    holdings, custom_feeds = load_portfolio(portfolio_path)
    portfolio_items = [holding for holding in holdings if holding.bucket == "portfolio"]
    watchlist_items = [holding for holding in holdings if holding.bucket == "watchlist"]
    digest_paths = sorted(digest_dir.glob("*-daily-digest.md"), reverse=True) if digest_dir.exists() else []

    latest_digest_html = ""
    latest_digest_name = "No digest yet"
    recent_digests: list[dict[str, str]] = []

    digest_template = env.get_template("static_digest.html")
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
