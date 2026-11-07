# Rebounds and assists backtest

Walk-forward 2023-26; noon injury report (Questionable at half); market log-odds kept at weight 1.

## Rebounds

Projection error (all games): RMSE 2.47, bias +0.03. Props matched: 37,907; over rate 48.2%.

Projection vs line: projection closer to the actual than the line on 51.9% of props.

| version | beats market 2023-24 (x1e-4) | beats market 2024-25 (x1e-4) | beats market 2025-26 (x1e-4) | weights by fold |
|---|---|---|---|---|
| projection gap | +25.8 | +19.9 | +5.9 | 2024-25: [-0.033, 0.621]; 2025-26: [0.008, 0.465]; 2023-24: [0.005, 0.317] |
| count-model probability | +25.4 | +16.5 | +9.5 | 2024-25: [0.35]; 2025-26: [0.309]; 2023-24: [0.237] |

| version | rule | bets | pred / won | units | ROI | 23-24 / 24-25 / 25-26 | unders |
|---|---|---|---|---|---|---|---|
| projection gap | every edge >= 2%, 1u | 4609 | 58.4% / 56.6% | +179.1 | +3.9% | +68.1 / +110.3 / +0.7 | 89% |
| projection gap | top 1 a day, >= 2% | 465 | 60.8% / 59.4% | +44.1 | +9.5% | +21.7 / +13.7 / +8.7 | 96% |
| count-model probability | every edge >= 2%, 1u | 4541 | 55.0% / 53.8% | +233.8 | +5.1% | +77.4 / +102.5 / +53.9 | 87% |
| count-model probability | top 1 a day, >= 2% | 471 | 57.9% / 57.1% | +52.5 | +11.1% | +18.9 / +21.8 / +11.8 | 93% |

## Assists

Projection error (all games): RMSE 1.81, bias +0.01. Props matched: 36,111; over rate 50.2%.

Projection vs line: projection closer to the actual than the line on 52.4% of props.

| version | beats market 2023-24 (x1e-4) | beats market 2024-25 (x1e-4) | beats market 2025-26 (x1e-4) | weights by fold |
|---|---|---|---|---|
| projection gap | +7.0 | +9.7 | +3.4 | 2024-25: [-0.018, 0.319]; 2025-26: [-0.183, 0.66]; 2023-24: [-0.187, 0.621] |
| count-model probability | +13.1 | +14.2 | +6.0 | 2024-25: [0.256]; 2025-26: [0.27]; 2023-24: [0.241] |

| version | rule | bets | pred / won | units | ROI | 23-24 / 24-25 / 25-26 | unders |
|---|---|---|---|---|---|---|---|
| projection gap | every edge >= 2%, 1u | 1015 | 58.5% / 58.2% | +55.0 | +5.4% | +15.0 / +28.9 / +11.2 | 27% |
| projection gap | top 1 a day, >= 2% | 327 | 57.8% / 58.1% | +27.2 | +8.3% | +2.4 / +22.1 / +2.7 | 36% |
| count-model probability | every edge >= 2%, 1u | 2498 | 53.4% / 51.4% | +81.2 | +3.3% | +31.4 / +30.5 / +19.4 | 30% |
| count-model probability | top 1 a day, >= 2% | 446 | 54.2% / 53.1% | +32.1 | +7.2% | +18.0 / +15.5 / -1.4 | 35% |
