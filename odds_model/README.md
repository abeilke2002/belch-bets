# Odds model: P(over the sportsbook line)

Run everything from this folder with the anaconda Python (the project `.venv` is too old):

```bash
PY=/Users/aidanbeilke/anaconda3/bin/python
export ODDS_API_KEY=your_key_here
```

## One-time setup (historical backtest)

| Step | Command | Notes |
|---|---|---|
| 1. 2025-26 box scores | `$PY pull_box_scores.py --season 2025-26` | ~1,230 games, about 30–40 min, resumable |
| 2. Test odds pull | `$PY pull_historical_odds.py --test 3 --probe-close 60 30 10 0` | ~180 credits; checks cost and the latest safe close time |
| 3. Full odds pull ($59 plan) | `$PY pull_historical_odds.py --max-credits 85000` | ~74k credits, resumable, stops at the credit floor |
| 4. Parse lines | `$PY parse_odds.py` | prints coverage of early/close lines |
| 5. Features | `$PY build_features.py` | runs leakage checks |
| 6. Match names | `$PY name_map.py` | fill `data/name_overrides.csv` for unmatched names, rerun |
| 7. Feature selection | `$PY feature_study.py` | ~10 min; picks minutes + points features, report in `reports/feature_study.md` |
| 8. Regression | `$PY regression.py` | two-stage (minutes → points), walk-forward predictions |
| 9. Classifier | `$PY classifier.py --select` | ~15–25 min with `--select`; picks features on log loss, market group always kept |
| 10. Backtest | `$PY backtest.py --model lgbm --margin 0.02` | report in `reports/` |

Rerun steps 5, 8, 9 (without `--select`) and 10 whenever new box scores or lines come in.
Rerun feature selection (7, and `--select`) only occasionally, e.g. once a season.

## Daily logging (this season)

```bash
$PY daily_logger.py early        # ~noon ET (same time as the historical early snapshot)
$PY daily_logger.py close        # every 15 min during game windows
$PY daily_logger.py results      # next morning
$PY parse_odds.py --raw-dir data/odds_live --out-dir data/live
```

## How to read the backtest
- **Classifier vs market log loss** is the first gate. If the model doesn't beat the no-vig market probability out of sample, there's no edge, whatever the ROI says.
- **Beat close %** should be above 50%, with **avg CLV pts** above 0. That's the most reliable sign of a real edge.
- Look at the **ROI 95% CI**: an interval that includes 0% means the result could be luck.
- The 2% margin is the pre-registered rule. Don't tune it on the test seasons.

## Daily predictions (replaces the retired predict.py)

```bash
$PY predict_today.py --out "Player Out" "Another Player"   # list tonight's ruled-out players
streamlit run "🏠_Home.py"                                  # from Basketball_Projects/, with anaconda's streamlit
```

`predict_today.py` builds features the same way as `build_features.py` (checked: replaying
2025-03-01 gives identical features), predicts points, and, once `classifier.py` has saved
`models/over_model.pkl` and today's lines are parsed into `data/live/`, adds P(over), edge and Play.
