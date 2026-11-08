# Rebounds and assists backtest

Walk-forward 2023-26; noon injury report (Questionable at half); market log-odds kept at weight 1.

## Assists

Projection error (all games): RMSE 1.80, bias +0.01. Props matched: 36,111; over rate 50.2%.

Projection vs line: projection closer to the actual than the line on 52.7% of props.

| version | beats market 2023-24 (x1e-4) | beats market 2024-25 (x1e-4) | beats market 2025-26 (x1e-4) | weights by fold |
|---|---|---|---|---|
| projection gap | +8.9 | +9.7 | +1.6 | 2024-25: [-0.002, 0.335]; 2025-26: [-0.211, 0.731]; 2023-24: [-0.166, 0.576] |
| count-model probability | +16.9 | +14.9 | +4.9 | 2024-25: [0.31]; 2025-26: [0.293]; 2023-24: [0.24] |

| version | rule | bets | pred / won | units | ROI | 23-24 / 24-25 / 25-26 | unders |
|---|---|---|---|---|---|---|---|
| projection gap | every edge >= 2%, 1u | 1393 | 59.4% / 58.3% | +58.5 | +4.2% | +7.6 / +50.6 / +0.3 | 25% |
| projection gap | top 1 a day, >= 2% | 348 | 59.1% / 58.0% | +20.9 | +6.0% | +1.0 / +18.5 / +1.5 | 41% |
| count-model probability | every edge >= 2%, 1u | 3028 | 53.6% / 51.9% | +116.2 | +3.8% | +46.4 / +51.9 / +18.0 | 31% |
| count-model probability | top 1 a day, >= 2% | 450 | 55.0% / 53.3% | +31.1 | +6.9% | +18.8 / +6.6 / +5.7 | 40% |
