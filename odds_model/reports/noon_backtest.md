# Noon-knowable backtest (official injury reports)

Each season predicted by models trained on earlier seasons only. Bets at the best noon price across DraftKings, FanDuel, BetMGM and Caesars; DNPs voided.

## Log loss vs the market (lower is better)

| injury info | classifier | season | market log loss | model log loss |
|---|---|---|---|---|
| hindsight injuries | gap only | 2024-25 | 0.6921 | 0.6914 |
| hindsight injuries | gap only | 2025-26 | 0.6921 | 0.6909 |
| noon injury report | gap only | 2024-25 | 0.6921 | 0.6924 |
| noon injury report | gap only | 2025-26 | 0.6921 | 0.6919 |
| noon injury report | gap + own status + questionable teammates | 2024-25 | 0.6921 | 0.6924 |
| noon injury report | gap + own status + questionable teammates | 2025-26 | 0.6921 | 0.6917 |

## Betting: each day, up to N bets with the biggest edge (model P minus break-even of the best price)

Flat 1-unit stakes. "all" = every bet over the minimum edge.

| strategy | max bets/day | min score | bets | days with a bet | win % | ROI | units 2024-25 | units 2025-26 | units total | max drawdown (u) | worst month (u) | line moved our way / against |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hindsight injuries | gap only | 1 | 0.0 | 322 | 322/323 | 55.9% | +7.4% [-3.1%, +17.6%] | +11.3 | +12.4 | +23.7 | -10.1 | -6.8 (2024-11) | 46% / 9% |
| hindsight injuries | gap only | 1 | 0.02 | 320 | 320/323 | 56.2% | +8.0% [-2.2%, +18.8%] | +12.3 | +13.4 | +25.7 | -9.8 | -6.8 (2024-11) | 46% / 9% |
| hindsight injuries | gap only | 1 | 0.04 | 277 | 277/323 | 57.0% | +9.6% [-1.5%, +20.9%] | +12.6 | +14.1 | +26.7 | -8.4 | -5.5 (2025-04) | 45% / 9% |
| hindsight injuries | gap only | 3 | 0.0 | 945 | 322/323 | 54.7% | +4.9% [-1.3%, +11.1%] | +19.5 | +27.0 | +46.5 | -15.7 | -8.7 (2025-04) | 45% / 11% |
| hindsight injuries | gap only | 3 | 0.02 | 914 | 320/323 | 55.1% | +5.8% [-0.5%, +12.1%] | +26.9 | +25.7 | +52.6 | -18.1 | -7.7 (2025-04) | 45% / 11% |
| hindsight injuries | gap only | 3 | 0.04 | 591 | 277/323 | 56.5% | +8.4% [+0.5%, +15.9%] | +28.2 | +21.2 | +49.5 | -9.2 | -2.6 (2024-10) | 47% / 9% |
| hindsight injuries | gap only | 5 | 0.0 | 1507 | 322/323 | 54.5% | +4.6% [-0.2%, +9.6%] | +46.9 | +22.3 | +69.2 | -15.7 | -5.6 (2025-04) | 41% / 11% |
| hindsight injuries | gap only | 5 | 0.02 | 1360 | 320/323 | 54.8% | +5.2% [+0.2%, +10.3%] | +55.4 | +15.1 | +70.5 | -20.3 | -5.3 (2025-04) | 42% / 11% |
| hindsight injuries | gap only | 5 | 0.04 | 661 | 277/323 | 56.4% | +8.2% [+0.9%, +15.2%] | +34.8 | +19.3 | +54.1 | -10.6 | -3.4 (2025-04) | 46% / 10% |
| hindsight injuries | gap only | all | 0.0 | 2373 | 322/323 | 54.8% | +5.2% [+1.1%, +9.0%] | +71.7 | +50.7 | +122.4 | -22.8 | -5.8 (2025-12) | 38% / 11% |
| hindsight injuries | gap only | all | 0.02 | 1727 | 320/323 | 54.9% | +5.4% [+0.8%, +10.0%] | +75.6 | +17.3 | +92.9 | -24.0 | -8.2 (2025-04) | 42% / 11% |
| hindsight injuries | gap only | all | 0.04 | 684 | 277/323 | 56.3% | +8.0% [+0.8%, +14.8%] | +31.4 | +23.0 | +54.4 | -10.1 | -6.4 (2025-04) | 46% / 10% |
| noon injury report | gap only | 1 | 0.0 | 322 | 322/323 | 53.4% | +3.0% [-6.9%, +13.2%] | +0.9 | +8.7 | +9.7 | -11.8 | -7.4 (2025-01) | 39% / 15% |
| noon injury report | gap only | 1 | 0.02 | 307 | 307/323 | 54.1% | +4.3% [-6.5%, +15.5%] | +1.1 | +12.0 | +13.1 | -10.8 | -6.4 (2025-01) | 39% / 16% |
| noon injury report | gap only | 1 | 0.04 | 149 | 149/323 | 57.7% | +11.4% [-4.1%, +26.6%] | +10.0 | +7.0 | +16.9 | -9.3 | -3.3 (2026-02) | 43% / 18% |
| noon injury report | gap only | 3 | 0.0 | 944 | 322/323 | 48.8% | -6.0% [-12.4%, +0.7%] | -12.4 | -44.3 | -56.8 | -70.8 | -20.1 (2026-03) | 34% / 17% |
| noon injury report | gap only | 3 | 0.02 | 748 | 307/323 | 50.0% | -3.8% [-10.7%, +3.5%] | +3.8 | -31.8 | -28.1 | -47.4 | -13.8 (2026-03) | 36% / 16% |
| noon injury report | gap only | 3 | 0.04 | 208 | 149/323 | 55.3% | +6.7% [-6.7%, +20.8%] | +11.1 | +2.8 | +13.9 | -12.3 | -6.2 (2026-03) | 39% / 22% |
| noon injury report | gap only | 5 | 0.0 | 1488 | 322/323 | 50.7% | -2.4% [-7.9%, +3.3%] | +7.7 | -43.0 | -35.3 | -77.0 | -18.6 (2026-01) | 32% / 17% |
| noon injury report | gap only | 5 | 0.02 | 950 | 307/323 | 51.4% | -1.2% [-8.1%, +5.4%] | +9.4 | -20.5 | -11.1 | -39.7 | -8.1 (2026-03) | 35% / 16% |
| noon injury report | gap only | 5 | 0.04 | 213 | 149/323 | 56.3% | +8.7% [-5.0%, +22.5%] | +14.0 | +4.6 | +18.6 | -12.3 | -6.2 (2026-03) | 38% / 22% |
| noon injury report | gap only | all | 0.0 | 2264 | 322/323 | 51.0% | -1.7% [-5.8%, +2.3%] | +0.7 | -40.0 | -39.3 | -66.9 | -27.4 (2026-01) | 30% / 18% |
| noon injury report | gap only | all | 0.02 | 1035 | 307/323 | 51.6% | -0.7% [-7.4%, +5.6%] | +6.8 | -14.4 | -7.6 | -34.2 | -7.6 (2025-12) | 34% / 16% |
| noon injury report | gap only | all | 0.04 | 213 | 149/323 | 56.3% | +8.7% [-5.0%, +22.5%] | +14.0 | +4.6 | +18.6 | -12.3 | -6.2 (2026-03) | 38% / 22% |
| noon injury report | gap + own status + questionable teammates | 1 | 0.0 | 322 | 322/323 | 50.3% | -3.1% [-13.5%, +7.0%] | -10.6 | +0.6 | -10.0 | -18.4 | -7.9 (2025-01) | 32% / 15% |
| noon injury report | gap + own status + questionable teammates | 1 | 0.02 | 308 | 308/323 | 50.6% | -2.4% [-14.0%, +8.3%] | -10.3 | +2.9 | -7.4 | -15.8 | -7.9 (2025-01) | 31% / 15% |
| noon injury report | gap + own status + questionable teammates | 1 | 0.04 | 186 | 186/323 | 52.2% | +0.7% [-13.7%, +15.3%] | -0.8 | +2.2 | +1.3 | -9.6 | -5.6 (2025-01) | 35% / 14% |
| noon injury report | gap + own status + questionable teammates | 3 | 0.0 | 944 | 322/323 | 50.8% | -2.1% [-8.6%, +4.1%] | -1.8 | -18.1 | -19.9 | -41.8 | -13.9 (2026-02) | 32% / 16% |
| noon injury report | gap + own status + questionable teammates | 3 | 0.02 | 801 | 308/323 | 50.1% | -3.7% [-10.6%, +3.0%] | -10.3 | -19.5 | -29.8 | -38.8 | -9.4 (2025-01) | 33% / 16% |
| noon injury report | gap + own status + questionable teammates | 3 | 0.04 | 287 | 186/323 | 49.8% | -4.0% [-16.0%, +7.1%] | +0.5 | -12.0 | -11.5 | -22.4 | -6.8 (2026-02) | 32% / 16% |
| noon injury report | gap + own status + questionable teammates | 5 | 0.0 | 1493 | 322/323 | 51.7% | -0.5% [-5.8%, +4.6%] | +16.1 | -23.3 | -7.3 | -53.2 | -13.0 (2026-02) | 30% / 16% |
| noon injury report | gap + own status + questionable teammates | 5 | 0.02 | 1063 | 308/323 | 51.5% | -1.1% [-7.2%, +4.9%] | +6.7 | -18.2 | -11.5 | -37.6 | -10.6 (2026-01) | 32% / 15% |
| noon injury report | gap + own status + questionable teammates | 5 | 0.04 | 298 | 186/323 | 50.3% | -3.1% [-15.3%, +8.5%] | +1.9 | -11.2 | -9.2 | -22.4 | -7.8 (2026-02) | 31% / 16% |
| noon injury report | gap + own status + questionable teammates | all | 0.0 | 2282 | 322/323 | 52.0% | +0.2% [-4.0%, +4.2%] | -7.2 | +11.7 | +4.5 | -49.2 | -17.4 (2025-01) | 29% / 17% |
| noon injury report | gap + own status + questionable teammates | all | 0.02 | 1201 | 308/323 | 51.2% | -1.5% [-7.5%, +4.2%] | +0.7 | -18.9 | -18.2 | -39.0 | -12.6 (2026-01) | 31% / 15% |
| noon injury report | gap + own status + questionable teammates | all | 0.04 | 301 | 186/323 | 50.5% | -2.8% [-15.0%, +9.0%] | +3.9 | -12.2 | -8.3 | -22.9 | -7.8 (2026-02) | 31% / 17% |
