# Teammates of a 15+ ppg player who is out (walk-forward, 2023-24 + 2024-25)

"Model adjustment" = prediction with the injury minus the same model with nobody out. "Actual uplift" = actual points minus that no-injury prediction. If the model captured injuries well, the two would match.

## Did the model move the right amount?

| segment | n | actual pts | model pred | model adjustment | actual uplift | best boost on model |
|---|---|---|---|---|---|---|
| ALL teammates | 4054 | 11.27 | 10.4 | +0.51 (+5.1%) | +1.38 (+13.9%) [+1.18, +1.59] | +6.4% [+4.7%, +8.3%] |
| top remaining scorer | 414 | 22.63 | 21.32 | +0.08 (+0.4%) | +1.39 (+6.6%) [+0.62, +2.19] | +4.8% [+1.0%, +8.5%] |
| other 15+ ppg scorers | 283 | 19.47 | 18.37 | +0.05 (+0.3%) | +1.15 (+6.3%) [+0.34, +2.00] | +4.7% [+0.3%, +9.5%] |
| 8-15 ppg | 1253 | 12.47 | 11.57 | +0.29 (+2.6%) | +1.18 (+10.5%) [+0.82, +1.54] | +7.0% [+3.8%, +10.1%] |
| <8 ppg | 2104 | 7.22 | 6.48 | +0.79 (+13.8%) | +1.52 (+26.8%) [+1.21, +1.83] | +10.1% [+5.9%, +14.1%] |

Control, games with no 15+ scorer out (n=47,500): mean residual -0.14, best boost -1.4% [-1.9%, -0.9%].

## All teammates (n=4,054), best RMSE: model +5%

| method | RMSE | MAE | bias (pred - actual) |
|---|---|---|---|
| current model | 6.367 | 4.852 | -0.87 |
| model, injury ignored | 6.475 | 4.865 | -1.38 |
| model +5% | 6.324 | 4.856 | -0.35 |
| model +10% | 6.336 | 4.902 | 0.17 |
| model +15% | 6.403 | 4.984 | 0.69 |
| model +20% | 6.524 | 5.103 | 1.21 |
| season avg | 6.844 | 5.123 | -2.231 |
| season avg +5% | 6.74 | 5.06 | -1.779 |
| season avg +10% | 6.679 | 5.031 | -1.327 |
| season avg +15% | 6.662 | 5.032 | -0.875 |
| season avg +20% | 6.689 | 5.07 | -0.423 |
| last-5 avg | 6.772 | 5.098 | -1.39 |

## Top remaining scorer (the Maxey case) (n=414), best RMSE: model +5%

| method | RMSE | MAE | bias (pred - actual) |
|---|---|---|---|
| current model | 8.423 | 6.626 | -1.31 |
| model, injury ignored | 8.446 | 6.656 | -1.395 |
| model +5% | 8.358 | 6.581 | -0.243 |
| model +10% | 8.434 | 6.65 | 0.823 |
| model +15% | 8.648 | 6.818 | 1.889 |
| model +20% | 8.991 | 7.078 | 2.955 |
| season avg | 8.739 | 6.864 | -1.892 |
| season avg +5% | 8.629 | 6.759 | -0.855 |
| season avg +10% | 8.65 | 6.768 | 0.182 |
| season avg +15% | 8.801 | 6.871 | 1.219 |
| season avg +20% | 9.076 | 7.097 | 2.256 |
| last-5 avg | 8.884 | 7.06 | -0.614 |

## Other 15+ ppg scorers (n=283), best RMSE: season avg +10%

| method | RMSE | MAE | bias (pred - actual) |
|---|---|---|---|
| current model | 7.473 | 5.976 | -1.099 |
| model, injury ignored | 7.505 | 5.985 | -1.153 |
| model +5% | 7.421 | 5.967 | -0.181 |
| model +10% | 7.485 | 6.073 | 0.738 |
| model +15% | 7.662 | 6.257 | 1.656 |
| model +20% | 7.945 | 6.521 | 2.575 |
| season avg | 7.511 | 5.937 | -1.689 |
| season avg +5% | 7.376 | 5.863 | -0.8 |
| season avg +10% | 7.35 | 5.88 | 0.089 |
| season avg +15% | 7.433 | 6.001 | 0.979 |
| season avg +20% | 7.621 | 6.215 | 1.868 |
| last-5 avg | 7.637 | 5.997 | -1.167 |

## 8-15 ppg (n=1,253), best RMSE: model +5%

| method | RMSE | MAE | bias (pred - actual) |
|---|---|---|---|
| current model | 6.672 | 5.196 | -0.893 |
| model, injury ignored | 6.71 | 5.203 | -1.182 |
| model +5% | 6.624 | 5.186 | -0.314 |
| model +10% | 6.63 | 5.225 | 0.264 |
| model +15% | 6.688 | 5.306 | 0.843 |
| model +20% | 6.797 | 5.427 | 1.422 |
| season avg | 7.016 | 5.436 | -1.833 |
| season avg +5% | 6.9 | 5.369 | -1.302 |
| season avg +10% | 6.825 | 5.339 | -0.77 |
| season avg +15% | 6.793 | 5.34 | -0.238 |
| season avg +20% | 6.803 | 5.38 | 0.293 |
| last-5 avg | 7.033 | 5.489 | -0.976 |

## <8 ppg (n=2,104), best RMSE: model +10%

| method | RMSE | MAE | bias (pred - actual) |
|---|---|---|---|
| current model | 5.49 | 4.147 | -0.74 |
| model, injury ignored | 5.688 | 4.161 | -1.525 |
| model +5% | 5.456 | 4.17 | -0.416 |
| model +10% | 5.445 | 4.208 | -0.092 |
| model +15% | 5.455 | 4.26 | 0.233 |
| model +20% | 5.487 | 4.33 | 0.557 |
| season avg | 6.191 | 4.485 | -2.607 |
| season avg +5% | 6.1 | 4.434 | -2.377 |
| season avg +10% | 6.019 | 4.392 | -2.146 |
| season avg +15% | 5.947 | 4.357 | -1.916 |
| season avg +20% | 5.885 | 4.332 | -1.685 |
| last-5 avg | 5.96 | 4.359 | -1.82 |

## By how big the absent player is

| player out | teammate | n | model adjustment | actual uplift | best boost |
|---|---|---|---|---|---|
| 15-20 ppg out | top remaining scorer | 206 | +0.10 | +1.65 | +5.7% |
| 15-20 ppg out | other 15+ ppg scorers | 140 | +0.03 | +0.90 | +3.3% |
| 15-20 ppg out | 8-15 ppg | 649 | +0.31 | +0.94 | +4.8% |
| 20-25 ppg out | top remaining scorer | 139 | +0.08 | +0.34 | +0.1% |
| 20-25 ppg out | other 15+ ppg scorers | 84 | +0.07 | +0.33 | +0.8% |
| 20-25 ppg out | 8-15 ppg | 445 | +0.30 | +1.61 | +9.8% |
| 25+ ppg out | top remaining scorer | 69 | +0.05 | +2.77 | +10.8% |
| 25+ ppg out | other 15+ ppg scorers | 59 | +0.08 | +2.92 | +15.8% |
| 25+ ppg out | 8-15 ppg | 159 | +0.18 | +0.96 | +7.8% |
