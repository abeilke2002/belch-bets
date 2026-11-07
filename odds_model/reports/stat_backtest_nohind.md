# Rebounds and assists backtest

Walk-forward 2023-26; noon injury report (Questionable at half); market log-odds kept at weight 1.

## Rebounds

Projection error (all games): RMSE 2.47, bias +0.03. Props matched: 37,907; over rate 48.2%.

Projection vs line: projection closer to the actual than the line on 51.9% of props.

| version | beats market 2023-24 (x1e-4) | beats market 2024-25 (x1e-4) | beats market 2025-26 (x1e-4) | weights by fold |
|---|---|---|---|---|
| projection gap | +25.2 | +19.5 | +6.3 | 2024-25: [-0.01, 0.545]; 2025-26: [-0.0, 0.477]; 2023-24: [-0.007, 0.347] |
| count-model probability | +24.9 | +16.2 | +9.8 | 2024-25: [0.343]; 2025-26: [0.303]; 2023-24: [0.235] |

| version | rule | bets | pred / won | units | ROI | 23-24 / 24-25 / 25-26 | unders |
|---|---|---|---|---|---|---|---|
| projection gap | every edge >= 2%, 1u | 4523 | 58.3% / 56.9% | +201.6 | +4.5% | +85.7 / +110.8 / +5.1 | 90% |
| projection gap | top 1 a day, >= 2% | 465 | 60.7% / 57.8% | +30.9 | +6.7% | +12.4 / +15.8 / +2.8 | 96% |
| count-model probability | every edge >= 2%, 1u | 4444 | 55.0% / 53.9% | +241.1 | +5.4% | +83.7 / +118.4 / +39.0 | 88% |
| count-model probability | top 1 a day, >= 2% | 471 | 57.8% / 56.3% | +46.0 | +9.8% | +16.5 / +20.3 / +9.2 | 93% |

## Assists

Projection error (all games): RMSE 1.81, bias +0.01. Props matched: 36,111; over rate 50.2%.

Projection vs line: projection closer to the actual than the line on 52.4% of props.

| version | beats market 2023-24 (x1e-4) | beats market 2024-25 (x1e-4) | beats market 2025-26 (x1e-4) | weights by fold |
|---|---|---|---|---|
| projection gap | +6.3 | +8.9 | +3.0 | 2024-25: [-0.004, 0.286]; 2025-26: [-0.192, 0.667]; 2023-24: [-0.206, 0.644] |
| count-model probability | +12.7 | +13.4 | +4.8 | 2024-25: [0.252]; 2025-26: [0.262]; 2023-24: [0.227] |

| version | rule | bets | pred / won | units | ROI | 23-24 / 24-25 / 25-26 | unders |
|---|---|---|---|---|---|---|---|
| projection gap | every edge >= 2%, 1u | 990 | 58.4% / 58.1% | +53.0 | +5.4% | +9.9 / +38.9 / +4.2 | 27% |
| projection gap | top 1 a day, >= 2% | 320 | 58.0% / 59.7% | +35.3 | +11.0% | +2.9 / +24.2 / +8.2 | 37% |
| count-model probability | every edge >= 2%, 1u | 2318 | 53.2% / 51.3% | +80.5 | +3.5% | +29.6 / +31.9 / +18.9 | 29% |
| count-model probability | top 1 a day, >= 2% | 433 | 54.2% / 54.7% | +44.5 | +10.3% | +15.5 / +18.8 / +10.2 | 35% |
