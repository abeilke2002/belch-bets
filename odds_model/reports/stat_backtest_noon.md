# Rebounds and assists backtest

Walk-forward 2023-26; noon injury report (Questionable at half); market log-odds kept at weight 1.

## Rebounds

Projection error (all games): RMSE 2.47, bias +0.03. Props matched: 37,907; over rate 48.2%.

Projection vs line: projection closer to the actual than the line on 51.9% of props.

| version | beats market 2023-24 (x1e-4) | beats market 2024-25 (x1e-4) | beats market 2025-26 (x1e-4) | weights by fold |
|---|---|---|---|---|
| projection gap | +24.8 | +19.8 | +5.4 | 2024-25: [-0.026, 0.584]; 2025-26: [0.013, 0.441]; 2023-24: [-0.004, 0.333] |
| count-model probability | +24.4 | +16.5 | +8.9 | 2024-25: [0.337]; 2025-26: [0.303]; 2023-24: [0.229] |

| version | rule | bets | pred / won | units | ROI | 23-24 / 24-25 / 25-26 | unders |
|---|---|---|---|---|---|---|---|
| projection gap | every edge >= 2%, 1u | 4454 | 58.2% / 56.5% | +168.7 | +3.8% | +62.4 / +96.4 / +9.9 | 90% |
| projection gap | top 1 a day, >= 2% | 464 | 60.6% / 56.9% | +21.7 | +4.7% | +9.8 / +13.5 / -1.5 | 96% |
| count-model probability | every edge >= 2%, 1u | 4339 | 55.0% / 53.9% | +235.4 | +5.4% | +74.1 / +100.7 / +60.6 | 88% |
| count-model probability | top 1 a day, >= 2% | 470 | 57.7% / 56.4% | +48.8 | +10.4% | +18.2 / +21.4 / +9.2 | 93% |

## Assists

Projection error (all games): RMSE 1.81, bias +0.01. Props matched: 36,111; over rate 50.2%.

Projection vs line: projection closer to the actual than the line on 52.6% of props.

| version | beats market 2023-24 (x1e-4) | beats market 2024-25 (x1e-4) | beats market 2025-26 (x1e-4) | weights by fold |
|---|---|---|---|---|
| projection gap | +7.5 | +9.4 | +3.2 | 2024-25: [-0.013, 0.319]; 2025-26: [-0.19, 0.671]; 2023-24: [-0.191, 0.623] |
| count-model probability | +14.3 | +14.2 | +5.7 | 2024-25: [0.265]; 2025-26: [0.271]; 2023-24: [0.238] |

| version | rule | bets | pred / won | units | ROI | 23-24 / 24-25 / 25-26 | unders |
|---|---|---|---|---|---|---|---|
| projection gap | every edge >= 2%, 1u | 1060 | 58.5% / 59.3% | +80.2 | +7.6% | +21.2 / +36.3 / +22.7 | 28% |
| projection gap | top 1 a day, >= 2% | 332 | 58.0% / 58.4% | +28.1 | +8.5% | +5.5 / +19.5 / +3.1 | 39% |
| count-model probability | every edge >= 2%, 1u | 2493 | 53.3% / 51.7% | +103.1 | +4.1% | +40.5 / +52.0 / +10.6 | 30% |
| count-model probability | top 1 a day, >= 2% | 441 | 54.0% / 54.0% | +44.8 | +10.2% | +28.0 / +10.5 / +6.2 | 37% |
