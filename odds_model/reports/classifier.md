# Classifier (market fixed, recency-weighted)

| test season | trained on | projection weight | log loss: market / model | daily picks |
|---|---|---|---|---|
| 2024-25 | 2023-24 | 1.036 | 0.6921 / 0.6924 | 152 |
| 2025-26 | 2023-24 + 2024-25 | 0.713 | 0.6921 / 0.6918 | 137 |
| 2023-24 | 2024-25 + 2025-26 | 0.292 | 0.6924 / 0.6915 | 107 |

Daily picks: 396 bets, predicted 56.1%, won 56.1%, +39.1 units with edge-sized stakes

Live model: z = market log-odds -0.0362 -0.0183 x gap +0.3466 x gap/sigma; stake scale 1u = 3.23% edge; a bet on 61% of days
