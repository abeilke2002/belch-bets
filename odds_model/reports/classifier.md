# Classifier (market fixed, recency-weighted)

| test season | trained on | projection weight | log loss: market / model | daily picks |
|---|---|---|---|---|
| 2024-25 | 2023-24 | 0.519 | 0.6921 / 0.6921 | 154 |
| 2025-26 | 2023-24 + 2024-25 | 0.724 | 0.6921 / 0.6916 | 142 |
| 2023-24 | 2024-25 + 2025-26 | 0.375 | 0.6924 / 0.6912 | 130 |

Daily picks: 426 bets, predicted 56.3%, won 53.1%, +12.9 units with edge-sized stakes

Live model: z = market log-odds -0.0431 -0.0161 x gap +0.3891 x gap/sigma; stake scale 1u = 3.66% edge; a bet on 81% of days
