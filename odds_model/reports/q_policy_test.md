# How to count Questionable teammates at noon

Same models, three ways of building tonight's absence list. Bets: noon classifier, skip players on the report and back-to-backs, best price among your four books, flat 1u. 2023-24 uses a classifier fit on 2024-26 (fresh season); the other two are walk-forward.

| policy | RMSE points (2023-26, noon inputs) |
|---|---|
| active | 5.9309 |
| listed players resolved (crystal ball) | 5.8838 |
| prev game | 5.932 |
| half | 5.9066 |

| strategy | max bets/day | min score | bets | win % | ROI | units 2023-24 | units 2024-25 | units 2025-26 | units total | max drawdown (u) | line moved our way / against |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q = active | 1 | 0.02 | 386 | 54.9% | +6.4% [-3.0%, +16.0%] | +7.8 | +0.5 | +16.5 | +24.9 | -10.2 | 35% / 16% |
| Q = active | 3 | 0.02 | 819 | 53.2% | +3.0% [-3.5%, +9.5%] | +9.7 | +22.8 | -8.2 | +24.3 | -28.1 | 34% / 16% |
| Q = listed players resolved (crystal ball) | 1 | 0.02 | 453 | 55.2% | +6.3% [-2.5%, +15.3%] | -0.5 | +12.6 | +16.5 | +28.6 | -12.5 | 37% / 12% |
| Q = listed players resolved (crystal ball) | 3 | 0.02 | 1120 | 53.3% | +2.8% [-3.0%, +8.5%] | +12.8 | +16.0 | +2.1 | +30.9 | -19.2 | 38% / 12% |
| Q = prev game | 1 | 0.02 | 388 | 52.6% | +1.9% [-7.5%, +10.9%] | +7.0 | +4.5 | -4.0 | +7.4 | -17.1 | 32% / 16% |
| Q = prev game | 3 | 0.02 | 821 | 51.9% | +0.3% [-6.5%, +6.6%] | +10.4 | +7.4 | -15.0 | +2.7 | -30.3 | 33% / 15% |
| Q = half | 1 | 0.02 | 398 | 54.8% | +6.2% [-3.7%, +15.5%] | +8.0 | +7.3 | +9.3 | +24.6 | -12.3 | 30% / 16% |
| Q = half | 3 | 0.02 | 870 | 51.7% | +0.2% [-6.5%, +6.4%] | +10.9 | +7.6 | -16.9 | +1.6 | -29.8 | 31% / 15% |
