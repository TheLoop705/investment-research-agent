# Investment Research Agent

Local-first portfolio research assistant for daily investment digests.

This project is designed to run on your Windows 11 computer now and move to an always-on Mac mini later. It fetches portfolio-related news, stores daily digest files, and can use OpenAI to turn raw headlines into a higher-signal research brief.

## What It Does

- Reads your portfolio/watchlist from `portfolio.json`
- Fetches ticker news from Yahoo Finance RSS
- Adds custom RSS feeds if you configure them
- Produces a Markdown daily digest in `digests/`
- Uses OpenAI for richer analysis when `OPENAI_API_KEY` is configured
- Falls back to a basic local digest if no API key is set

## Quick Start On Windows

```powershell
cd C:\Users\sulta\Documents\Codex\2026-06-03\i-want-to-create-a-project\outputs\investment-research-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python .\src\run_daily.py
```

Your digest will appear in:

```text
digests/
```

## Add OpenAI

Edit `.env` and set:

```text
OPENAI_API_KEY=your_api_key_here
OPENAI_MODEL=gpt-4.1-mini
```

Then run:

```powershell
python .\src\run_daily.py
```

## Edit Your Portfolio

Update `portfolio.json`:

```json
{
  "portfolio": [
    {
      "ticker": "MSFT",
      "company": "Microsoft",
      "thesis": "AI platform, cloud growth, enterprise software durability",
      "tags": ["cloud", "ai", "software"]
    }
  ],
  "watchlist": [
    {
      "ticker": "NVDA",
      "company": "NVIDIA",
      "thesis": "AI accelerator demand and data center growth",
      "tags": ["semiconductors", "ai"]
    }
  ],
  "custom_feeds": []
}
```

## Schedule On Windows

After the quick start works, register a daily 7:00 AM task:

```powershell
.\scripts\register_windows_task.ps1
```

You can change the time inside that script.

## Move To Mac Mini Later

Copy this folder to the Mac mini, then:

```bash
cd investment-research-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python src/run_daily.py
```

For scheduling, adapt `scripts/com.investment-research-agent.plist`.

## Suggested Next Upgrades

- Add SEC filing fetches
- Add price movement data
- Add email delivery
- Add persistent database storage
- Add broker/CSV import
- Add source quality scoring

## Local Dashboard

The repo now includes a local web dashboard for viewing digests and managing portfolio items.

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn src.webapp:app --reload
```

Then open:

```text
http://127.0.0.1:8000
```

From the dashboard you can:

- View the latest generated digest rendered from Markdown
- Review portfolio and watchlist items
- Add or remove holdings
- Add or remove custom RSS feeds
- Trigger a fresh digest run from the browser

## GitHub Pages Static Dashboard

The repo also supports a read-only static dashboard for GitHub Pages.

- `python src/run_daily.py` now refreshes `docs/` after each digest run
- `python src/site_builder.py` rebuilds the static site without generating a new digest
- `.github/workflows/digest-refresh.yml` can generate a new digest on GitHub and commit the updated `digests/` and `docs/`
- `.github/workflows/pages.yml` deploys `docs/` to GitHub Pages using GitHub Actions

To let GitHub generate AI-enhanced digests, add this repository secret after the repo exists:

- `OPENAI_API_KEY`

You can also optionally add a repository variable:

- `OPENAI_MODEL` with a value like `gpt-4.1-mini`

## Disclaimer

This is a research assistant, not financial advice. It should help you find facts, risks, and questions to investigate. It should not make buy/sell decisions for you.
