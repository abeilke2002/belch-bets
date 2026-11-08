# Rebounds and assists backtest

Walk-forward 2023-26; noon injury report (Questionable at half); market log-odds kept at weight 1.

## Rebounds

Projection error (all games): RMSE 2.47, bias +0.03. Props matched: 37,907; over rate 48.2%.

Projection vs line: projection closer to the actual than the line on 52.2% of props.

| version | beats market 2023-24 (x1e-4) | beats market 2024-25 (x1e-4) | beats market 2025-26 (x1e-4) | weights by fold |
|---|---|---|---|---|
| projection gap | +25.3 | +18.6 | +7.6 | 2024-25: [-0.039, 0.642]; 2025-26: [0.009, 0.449]; 2023-24: [0.024, 0.278] |
| count-model probability | +25.3 | +15.4 | +10.8 | 2024-25: [0.364]; 2025-26: [0.305]; 2023-24: [0.246] |

| version | rule | bets | pred / won | units | ROI | 23-24 / 24-25 / 25-26 | unders |
|---|---|---|---|---|---|---|---|
| projection gap | every edge >= 2%, 1u | 4562 | 58.4% / 56.9% | +198.2 | +4.3% | +87.9 / +96.2 / +14.1 | 91% |
| projection gap | top 1 a day, >= 2% | 467 | 60.6% / 55.7% | +12.3 | +2.6% | +2.9 / +13.5 / -4.1 | 96% |
| count-model probability | every edge >= 2%, 1u | 4568 | 55.1% / 54.4% | +290.3 | +6.4% | +89.2 / +128.0 / +73.1 | 88% |
| count-model probability | top 1 a day, >= 2% | 470 | 57.9% / 54.3% | +30.4 | +6.5% | +13.9 / +10.2 / +6.3 | 93% |
