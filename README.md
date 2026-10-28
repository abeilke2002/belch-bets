# The Noon Line

NBA player-points betting pipeline and site. Bets every eligible prop with a 2%+ edge, 1u each.

- `odds_model/` — models, daily pipeline (`daily_pipeline.py`), site (`site/`), Cloudflare Worker (`worker.js`)
- `csvs/` — box scores (2018–26 from stats.nba.com; 2026-27 on from ESPN via `pull_box_scores_espn.py`)
- `.github/workflows/daily.yml` — the cloud run: picks (~12:15 PM ET), close (evenings), results (~9 AM ET),
  plus the site's "Update now" button

Secrets (repo settings): `ODDS_API_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`.
Worker secret: `GITHUB_TOKEN` (fine-grained, Actions read/write on this repo only).
