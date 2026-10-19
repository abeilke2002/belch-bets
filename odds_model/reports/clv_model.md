# Line-movement (CLV) model: noon -> close

Walk-forward: each season predicted from earlier seasons only. Bets placed at the best noon price among your four books, on the side the line is predicted to move toward.

## How well it predicts the move

| test season | k (prob per point) | n | corr(predicted, actual move) | direction right when line moved | actual |move| (mean) |
|---|---|---|---|---|---|
| 2024-25 | 0.071 | 12945 | 0.201 | 56.3% | 0.54 |
| 2025-26 | 0.067 | 15311 | 0.167 | 55.1% | 0.6 |

## Betting the biggest predicted moves

| bet when |predicted move| >= | bets | win % | ROI | ROI 24-25 / 25-26 | realized CLV (pts) | market moved our way |
|---|---|---|---|---|---|---|
| 0.25 | 5579 | 53.2% | -0.5% [-2.9%, +2.0%] | -1.7% / +0.9% | +0.28 | 61% |
| 0.5 | 247 | 51.0% | -5.4% [-17.2%, +6.7%] | -18.0% / +9.1% | +0.41 | 63% |

## What drives the prediction (gain share, last model)

| feature | share |
|---|---|
| gapz | 0.176 |
| q_ppg | 0.104 |
| gap | 0.102 |
| form_season | 0.099 |
| min_trend | 0.071 |
| hours_to_tip | 0.061 |
| book_down | 0.061 |
| form5 | 0.058 |
| price_tilt | 0.054 |
| skew | 0.053 |
| line | 0.052 |
| hold | 0.039 |
| n_books | 0.029 |
| own_questionable | 0.022 |
| book_up | 0.019 |
| own_probable | 0.001 |
