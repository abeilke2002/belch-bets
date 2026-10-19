# Points distribution model (no odds in the number)

Negative binomial around the noon projection; dispersion fit on earlier seasons only.

## Log loss on the test seasons (market = 0.6921)

| season | model | log loss | mean P(over) |
|---|---|---|---|
| 2024-25 | market (no-vig) | 0.6921 | 0.501 |
| 2024-25 | distribution, raw | 0.7115 | 0.443 |
| 2024-25 | distribution, calibrated | 0.6945 | 0.48 |
| 2024-25 | blend: market + distribution | 0.6935 | 0.48 |
| 2025-26 | market (no-vig) | 0.6921 | 0.501 |
| 2025-26 | distribution, raw | 0.7129 | 0.437 |
| 2025-26 | distribution, calibrated | 0.6935 | 0.49 |
| 2025-26 | blend: market + distribution | 0.6925 | 0.49 |

Blend coefficients [market, distribution]: [0.79 0.88], [0.92 0.85]

## Calibration of the distribution alone (test seasons)

| p_bucket | n | predicted | market | actual |
|---|---|---|---|---|
| (0.0, 0.44] | 2101 | 0.422 | 0.495 | 0.486 |
| (0.44, 0.47] | 1638 | 0.455 | 0.495 | 0.468 |
| (0.47, 0.49] | 12569 | 0.48 | 0.499 | 0.483 |
| (0.49, 0.51] | 6220 | 0.499 | 0.505 | 0.519 |
| (0.51, 0.53] | 5845 | 0.513 | 0.505 | 0.507 |
| (0.56, 1.0] | 45 | 0.573 | 0.509 | 0.556 |

## Betting (flat 1u, best noon price among your four books)

| strategy | max bets/day | min score | bets | win % | ROI | units 2024-25 | units 2025-26 | units total | max drawdown (u) | line moved our way / against |
|---|---|---|---|---|---|---|---|---|---|---|
| origination (distribution vs price) | 1 | 0.0 | 322 | 52.5% | +3.3% [-7.9%, +13.8%] | -6.0 | +16.5 | +10.6 | -16.7 | 29% / 25% |
| origination (distribution vs price) | 1 | 0.02 | 321 | 53.3% | +4.9% [-6.4%, +15.8%] | -1.0 | +16.5 | +15.6 | -15.2 | 29% / 26% |
| origination (distribution vs price) | 1 | 0.04 | 297 | 53.2% | +4.6% [-7.0%, +15.3%] | -2.7 | +16.3 | +13.6 | -15.2 | 29% / 26% |
| origination (distribution vs price) | 1 | 0.06 | 215 | 51.6% | +1.5% [-12.0%, +14.8%] | -11.9 | +15.0 | +3.1 | -14.7 | 31% / 26% |
| origination (distribution vs price) | 3 | 0.0 | 945 | 48.9% | -3.9% [-10.1%, +2.3%] | -9.2 | -27.2 | -36.4 | -45.4 | 24% / 27% |
| origination (distribution vs price) | 3 | 0.02 | 919 | 49.2% | -3.3% [-9.7%, +3.2%] | -11.0 | -19.0 | -30.0 | -42.0 | 25% / 27% |
| origination (distribution vs price) | 3 | 0.04 | 697 | 50.8% | -0.2% [-7.4%, +6.7%] | +3.1 | -4.7 | -1.6 | -28.3 | 26% / 27% |
| origination (distribution vs price) | 3 | 0.06 | 381 | 49.1% | -3.6% [-13.1%, +6.2%] | -3.5 | -10.3 | -13.8 | -21.0 | 27% / 28% |
| origination (distribution vs price) | 5 | 0.0 | 1506 | 49.3% | -3.1% [-8.3%, +2.1%] | -15.0 | -31.8 | -46.8 | -58.6 | 23% / 26% |
| origination (distribution vs price) | 5 | 0.02 | 1388 | 49.1% | -3.4% [-8.5%, +2.2%] | -18.0 | -28.7 | -46.8 | -59.6 | 24% / 27% |
| origination (distribution vs price) | 5 | 0.04 | 875 | 50.6% | -0.6% [-6.8%, +5.4%] | +5.0 | -10.6 | -5.6 | -29.9 | 25% / 26% |
| origination (distribution vs price) | 5 | 0.06 | 405 | 49.1% | -3.5% [-13.2%, +6.3%] | -3.6 | -10.7 | -14.3 | -23.1 | 26% / 29% |
| origination (distribution vs price) | all | 0.0 | 2390 | 50.3% | -1.1% [-5.1%, +3.1%] | -4.0 | -22.9 | -26.9 | -63.3 | 22% / 26% |
| origination (distribution vs price) | all | 0.02 | 1807 | 49.7% | -2.4% [-6.8%, +2.3%] | -16.5 | -26.5 | -43.0 | -56.5 | 24% / 26% |
| origination (distribution vs price) | all | 0.04 | 937 | 50.4% | -1.2% [-7.5%, +5.1%] | +0.6 | -12.0 | -11.5 | -31.1 | 25% / 26% |
| origination (distribution vs price) | all | 0.06 | 412 | 49.3% | -3.2% [-12.8%, +6.6%] | -2.6 | -10.7 | -13.3 | -23.1 | 26% / 29% |
| blend (market + distribution) | 1 | 0.0 | 322 | 51.2% | -1.7% [-12.8%, +8.5%] | -8.7 | +3.1 | -5.6 | -18.5 | 37% / 15% |
| blend (market + distribution) | 1 | 0.02 | 314 | 51.6% | -1.1% [-11.8%, +9.4%] | -7.7 | +4.3 | -3.4 | -17.5 | 37% / 16% |
| blend (market + distribution) | 1 | 0.04 | 263 | 51.7% | -0.7% [-11.9%, +11.4%] | -10.9 | +9.1 | -1.7 | -17.5 | 38% / 16% |
| blend (market + distribution) | 1 | 0.06 | 145 | 54.5% | +4.3% [-11.5%, +19.0%] | +3.9 | +2.3 | +6.2 | -10.6 | 42% / 16% |
| blend (market + distribution) | 3 | 0.0 | 944 | 49.4% | -5.2% [-11.2%, +0.6%] | -9.8 | -39.2 | -49.0 | -62.0 | 34% / 18% |
| blend (market + distribution) | 3 | 0.02 | 806 | 50.1% | -3.8% [-10.6%, +2.7%] | -9.1 | -21.7 | -30.7 | -44.0 | 35% / 19% |
| blend (market + distribution) | 3 | 0.04 | 548 | 52.0% | -0.1% [-8.0%, +8.2%] | +7.1 | -7.4 | -0.4 | -20.4 | 35% / 19% |
| blend (market + distribution) | 3 | 0.06 | 214 | 52.8% | +1.0% [-13.0%, +13.3%] | +9.0 | -6.9 | +2.1 | -18.9 | 39% / 21% |
| blend (market + distribution) | 5 | 0.0 | 1490 | 49.9% | -4.2% [-9.4%, +0.6%] | -15.6 | -46.4 | -62.0 | -84.2 | 33% / 18% |
| blend (market + distribution) | 5 | 0.02 | 1123 | 50.5% | -3.4% [-8.9%, +2.1%] | -7.7 | -30.1 | -37.8 | -66.4 | 35% / 18% |
| blend (market + distribution) | 5 | 0.04 | 620 | 51.5% | -1.2% [-9.2%, +6.6%] | -1.9 | -5.6 | -7.5 | -24.9 | 34% / 19% |
| blend (market + distribution) | 5 | 0.06 | 217 | 53.5% | +2.1% [-12.1%, +14.8%] | +10.6 | -6.1 | +4.6 | -18.1 | 39% / 21% |
| blend (market + distribution) | all | 0.0 | 2286 | 50.7% | -2.8% [-6.8%, +1.2%] | -30.4 | -34.1 | -64.5 | -88.7 | 31% / 18% |
| blend (market + distribution) | all | 0.02 | 1356 | 50.7% | -3.1% [-8.1%, +2.0%] | -10.5 | -31.1 | -41.6 | -71.4 | 34% / 17% |
| blend (market + distribution) | all | 0.04 | 636 | 51.6% | -0.9% [-8.7%, +6.9%] | +1.9 | -7.7 | -5.8 | -26.1 | 34% / 20% |
| blend (market + distribution) | all | 0.06 | 218 | 53.7% | +2.5% [-11.9%, +15.1%] | +11.6 | -6.1 | +5.5 | -18.1 | 39% / 21% |

## Fitted dispersion r (larger = tighter)

| fit for | projection | starter | r |
|---|---|---|---|
| 2024-25 | (0, 6] | 0 | 1.75 |
| 2024-25 | (0, 6] | 1 | 3.06 |
| 2024-25 | (6, 10] | 0 | 3.41 |
| 2024-25 | (6, 10] | 1 | 3.55 |
| 2024-25 | (10, 14] | 0 | 6.14 |
| 2024-25 | (10, 14] | 1 | 5.53 |
| 2024-25 | (14, 18] | 0 | 6.35 |
| 2024-25 | (14, 18] | 1 | 8.07 |
| 2024-25 | (18, 23] | 0 | 6.19 |
| 2024-25 | (18, 23] | 1 | 9.67 |
| 2024-25 | (23, 60] | 1 | 13.38 |
| 2025-26 | (0, 6] | 0 | 1.99 |
| 2025-26 | (0, 6] | 1 | 2.5 |
| 2025-26 | (6, 10] | 0 | 3.15 |
| 2025-26 | (6, 10] | 1 | 3.64 |
| 2025-26 | (10, 14] | 0 | 4.89 |
| 2025-26 | (10, 14] | 1 | 5.48 |
| 2025-26 | (14, 18] | 0 | 5.59 |
| 2025-26 | (14, 18] | 1 | 7.46 |
| 2025-26 | (18, 23] | 0 | 5.21 |
| 2025-26 | (18, 23] | 1 | 9.7 |
| 2025-26 | (23, 60] | 1 | 13.51 |
