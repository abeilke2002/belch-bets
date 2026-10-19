# Redistribution feature test (walk-forward, 2023-24 + 2024-25)

MSE reduction vs A: positive = better than the current model; 95% CI clustered by game date.

## Accuracy

| subset | n | variant | RMSE | bias | MSE reduction vs A |
|---|---|---|---|---|---|
| all games | 51554 | A current | 5.9417 | 0.063 |  |
| all games | 51554 | B + redistribution | 5.9381 | 0.185 | +0.043 [-0.050, +0.139] |
| all games | 51554 | C + redistribution (monotone) | 5.9414 | 0.18 | +0.004 [-0.084, +0.099] |
| all games | 51554 | D + usage freed up | 5.9406 | 0.196 | +0.013 [-0.079, +0.106] |
| all games | 51554 | E + NEW-absence redistribution | 5.931 | 0.108 | +0.127 [+0.035, +0.224] |
| all games | 51554 | F + NEW-absence redistribution (monotone) | 5.9322 | 0.113 | +0.113 [+0.023, +0.209] |
| star out (all teammates) | 4054 | A current | 6.3672 | -0.87 |  |
| star out (all teammates) | 4054 | B + redistribution | 6.3449 | 0.639 | +0.284 [-0.448, +1.017] |
| star out (all teammates) | 4054 | C + redistribution (monotone) | 6.3376 | 0.686 | +0.375 [-0.326, +1.069] |
| star out (all teammates) | 4054 | D + usage freed up | 6.337 | 0.635 | +0.384 [-0.304, +1.079] |
| star out (all teammates) | 4054 | E + NEW-absence redistribution | 6.3158 | 0.451 | +0.651 [+0.011, +1.308] |
| star out (all teammates) | 4054 | F + NEW-absence redistribution (monotone) | 6.3144 | 0.5 | +0.669 [+0.033, +1.320] |
| star out: top remaining scorer | 414 | A current | 8.4231 | -1.31 |  |
| star out: top remaining scorer | 414 | B + redistribution | 8.4504 | 0.549 | -0.460 [-4.136, +3.501] |
| star out: top remaining scorer | 414 | C + redistribution (monotone) | 8.4641 | 0.86 | -0.693 [-4.487, +3.301] |
| star out: top remaining scorer | 414 | D + usage freed up | 8.3711 | 0.555 | +0.874 [-2.663, +4.557] |
| star out: top remaining scorer | 414 | E + NEW-absence redistribution | 8.4325 | 0.34 | -0.158 [-3.597, +3.318] |
| star out: top remaining scorer | 414 | F + NEW-absence redistribution (monotone) | 8.4343 | 0.468 | -0.189 [-3.556, +3.323] |
| star out: other 15+ scorers | 283 | A current | 7.4728 | -1.099 |  |
| star out: other 15+ scorers | 283 | B + redistribution | 7.4893 | 0.7 | -0.247 [-4.064, +3.710] |
| star out: other 15+ scorers | 283 | C + redistribution (monotone) | 7.4306 | 0.865 | +0.630 [-3.092, +4.530] |
| star out: other 15+ scorers | 283 | D + usage freed up | 7.4267 | 0.636 | +0.687 [-2.598, +4.162] |
| star out: other 15+ scorers | 283 | E + NEW-absence redistribution | 7.4066 | 0.521 | +0.985 [-2.541, +4.611] |
| star out: other 15+ scorers | 283 | F + NEW-absence redistribution (monotone) | 7.4638 | 0.605 | +0.135 [-3.484, +3.877] |
| star out: 8-15 ppg | 1253 | A current | 6.6716 | -0.893 |  |
| star out: 8-15 ppg | 1253 | B + redistribution | 6.6477 | 0.801 | +0.318 [-1.022, +1.653] |
| star out: 8-15 ppg | 1253 | C + redistribution (monotone) | 6.647 | 0.873 | +0.328 [-1.022, +1.667] |
| star out: 8-15 ppg | 1253 | D + usage freed up | 6.6422 | 0.735 | +0.392 [-0.855, +1.679] |
| star out: 8-15 ppg | 1253 | E + NEW-absence redistribution | 6.6452 | 0.579 | +0.351 [-0.840, +1.582] |
| star out: 8-15 ppg | 1253 | F + NEW-absence redistribution (monotone) | 6.6242 | 0.63 | +0.630 [-0.570, +1.891] |
| star out: <8 ppg | 2104 | A current | 5.4896 | -0.74 |  |
| star out: <8 ppg | 2104 | B + redistribution | 5.4456 | 0.552 | +0.481 [-0.428, +1.328] |
| star out: <8 ppg | 2104 | C + redistribution (monotone) | 5.4365 | 0.517 | +0.580 [-0.302, +1.414] |
| star out: <8 ppg | 2104 | D + usage freed up | 5.4675 | 0.591 | +0.242 [-0.735, +1.159] |
| star out: <8 ppg | 2104 | E + NEW-absence redistribution | 5.4029 | 0.387 | +0.944 [+0.125, +1.732] |
| star out: <8 ppg | 2104 | F + NEW-absence redistribution (monotone) | 5.404 | 0.414 | +0.933 [+0.084, +1.737] |

## Does it move the right amount when a 15+ ppg teammate is out?

| subset | variant | model adjustment | actual uplift | share of uplift captured |
|---|---|---|---|---|
| star out (all teammates) | A current | +0.51 | +1.38 | 37% |
| star out (all teammates) | B + redistribution | +2.20 | +1.56 | 141% |
| star out (all teammates) | C + redistribution (monotone) | +2.26 | +1.57 | 144% |
| star out (all teammates) | D + usage freed up | +2.19 | +1.56 | 141% |
| star out (all teammates) | E + NEW-absence redistribution | +2.39 | +1.94 | 123% |
| star out (all teammates) | F + NEW-absence redistribution (monotone) | +2.45 | +1.95 | 126% |
| star out: top remaining scorer | A current | +0.08 | +1.39 | 6% |
| star out: top remaining scorer | B + redistribution | +2.10 | +1.55 | 135% |
| star out: top remaining scorer | C + redistribution (monotone) | +2.44 | +1.58 | 154% |
| star out: top remaining scorer | D + usage freed up | +2.04 | +1.49 | 137% |
| star out: top remaining scorer | E + NEW-absence redistribution | +2.40 | +2.06 | 117% |
| star out: top remaining scorer | F + NEW-absence redistribution (monotone) | +2.51 | +2.04 | 123% |
| star out: other 15+ scorers | A current | +0.05 | +1.15 | 5% |
| star out: other 15+ scorers | B + redistribution | +2.07 | +1.37 | 151% |
| star out: other 15+ scorers | C + redistribution (monotone) | +2.19 | +1.32 | 165% |
| star out: other 15+ scorers | D + usage freed up | +1.94 | +1.30 | 149% |
| star out: other 15+ scorers | E + NEW-absence redistribution | +2.34 | +1.82 | 129% |
| star out: other 15+ scorers | F + NEW-absence redistribution (monotone) | +2.38 | +1.78 | 134% |
| star out: 8-15 ppg | A current | +0.29 | +1.18 | 24% |
| star out: 8-15 ppg | B + redistribution | +2.17 | +1.37 | 158% |
| star out: 8-15 ppg | C + redistribution (monotone) | +2.27 | +1.40 | 162% |
| star out: 8-15 ppg | D + usage freed up | +2.11 | +1.38 | 153% |
| star out: 8-15 ppg | E + NEW-absence redistribution | +2.43 | +1.85 | 131% |
| star out: 8-15 ppg | F + NEW-absence redistribution (monotone) | +2.49 | +1.86 | 134% |
| star out: <8 ppg | A current | +0.79 | +1.52 | 51% |
| star out: <8 ppg | B + redistribution | +2.26 | +1.71 | 132% |
| star out: <8 ppg | C + redistribution (monotone) | +2.23 | +1.71 | 130% |
| star out: <8 ppg | D + usage freed up | +2.31 | +1.72 | 134% |
| star out: <8 ppg | E + NEW-absence redistribution | +2.37 | +1.98 | 120% |
| star out: <8 ppg | F + NEW-absence redistribution (monotone) | +2.41 | +2.00 | 121% |
