# Rebounds and assists backtest

Walk-forward 2023-26; noon injury report (Questionable at half); market log-odds kept at weight 1.

## Rebounds

Projection error (all games): RMSE 2.47, bias +0.03. Props matched: 37,907; over rate 48.2%.

Projection vs line: projection closer to the actual than the line on 51.9% of props.

| version | beats market 2023-24 (x1e-4) | beats market 2024-25 (x1e-4) | beats market 2025-26 (x1e-4) | weights by fold |
|---|---|---|---|---|
| projection gap | +25.4 | +20.2 | +6.2 | 2024-25: [-0.011, 0.55]; 2025-26: [0.008, 0.463]; 2023-24: [-0.003, 0.34] |
| count-model probability | +25.1 | +16.9 | +9.7 | 2024-25: [0.345]; 2025-26: [0.31]; 2023-24: [0.238] |

| version | rule | bets | pred / won | units | ROI | 23-24 / 24-25 / 25-26 | unders |
|---|---|---|---|---|---|---|---|
| projection gap | every edge >= 2%, 1u | 4599 | 58.3% / 56.7% | +188.8 | +4.1% | +98.0 / +108.0 / -17.2 | 90% |
| projection gap | top 1 a day, >= 2% | 465 | 60.7% / 58.3% | +35.5 | +7.6% | +14.9 / +16.3 / +4.4 | 96% |
| count-model probability | every edge >= 2%, 1u | 4536 | 55.1% / 54.4% | +286.9 | +6.3% | +84.6 / +141.9 / +60.4 | 87% |
| count-model probability | top 1 a day, >= 2% | 469 | 57.9% / 56.1% | +45.1 | +9.6% | +18.0 / +16.9 / +10.2 | 92% |

## Assists

Projection error (all games): RMSE 1.81, bias +0.01. Props matched: 36,111; over rate 50.2%.

Projection vs line: projection closer to the actual than the line on 52.4% of props.

| version | beats market 2023-24 (x1e-4) | beats market 2024-25 (x1e-4) | beats market 2025-26 (x1e-4) | weights by fold |
|---|---|---|---|---|
| projection gap | +6.3 | +8.9 | +2.9 | 2024-25: [-0.003, 0.283]; 2025-26: [-0.195, 0.674]; 2023-24: [-0.205, 0.643] |
| count-model probability | +12.7 | +13.4 | +4.9 | 2024-25: [0.251]; 2025-26: [0.262]; 2023-24: [0.228] |

| version | rule | bets | pred / won | units | ROI | 23-24 / 24-25 / 25-26 | unders |
|---|---|---|---|---|---|---|---|
| projection gap | every edge >= 2%, 1u | 1007 | 58.5% / 58.5% | +59.6 | +5.9% | +15.9 / +38.6 / +5.1 | 27% |
| projection gap | top 1 a day, >= 2% | 324 | 58.0% / 58.6% | +28.7 | +8.8% | +5.9 / +15.8 / +7.0 | 37% |
| count-model probability | every edge >= 2%, 1u | 2335 | 53.2% / 51.3% | +80.7 | +3.5% | +26.5 / +36.7 / +17.6 | 30% |
| count-model probability | top 1 a day, >= 2% | 434 | 54.0% / 54.6% | +47.0 | +10.8% | +15.9 / +24.7 / +6.4 | 35% |
