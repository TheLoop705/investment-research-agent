Use the existing Python-first architecture in this repo to improve the investment research engine materially.

Focus on:
- headline de-duplication and clustering
- source quality scoring
- event-type classification
- catalyst extraction
- risk flag generation
- more structured digest sections

Constraints:
- keep `portfolio.json` as the source of truth unless there is a strong reason not to
- preserve compatibility with both the live FastAPI dashboard and the static `docs/` site
- avoid adding a database unless it is clearly necessary

Deliver:
- implemented code changes
- any schema changes needed
- UI updates if the new analysis should be visible
- verification steps and results
