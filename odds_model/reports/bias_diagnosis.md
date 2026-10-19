# Star-out bias diagnosis (walk-forward, 2023-24 + 2024-25)

bias = prediction - actual (positive = over-predicting). CI clustered by game date.

## 1. Where is the bias?

| slice | n | bias | mean injury adjustment |
|---|---|---|---|
| all games | 51554 | +0.11 [+0.05, +0.16] | +0.39 |
| no star out | 47500 | +0.08 [+0.02, +0.13] | +0.22 |
| star out | 4054 | +0.45 [+0.27, +0.63] | +2.39 |
| star out, 2023-24 | 1577 | +0.41 [+0.10, +0.73] | +2.34 |
| star out, 2024-25 | 2477 | +0.48 [+0.26, +0.68] | +2.42 |
| no star out, 2023-24 | 24244 | +0.17 [+0.11, +0.24] | +0.18 |
| no star out, 2024-25 | 23256 | -0.02 [-0.11, +0.07] | +0.26 |

## 2. By size of the injury adjustment (star-out games)

| slice | n | bias | mean injury adjustment |
|---|---|---|---|
| adjustment (-inf, 0.0] | 30 | +0.80 [-2.11, +4.11] | -0.39 |
| adjustment (0.0, 1.0] | 367 | -0.25 [-0.84, +0.34] | +0.67 |
| adjustment (1.0, 2.0] | 1298 | +0.21 [-0.15, +0.53] | +1.55 |
| adjustment (2.0, 4.0] | 1936 | +0.53 [+0.26, +0.80] | +2.79 |
| adjustment (4.0, inf] | 423 | +1.41 [+0.74, +2.07] | +4.80 |

## 3. Fresh vs long-running absences

| slice | n | bias | mean injury adjustment |
|---|---|---|---|
| fresh (mostly new) | 2532 | +0.40 [+0.16, +0.66] | +2.44 |
| long-running (mostly baked in) | 107 | +0.49 [-0.32, +1.34] | +1.42 |
| mixed | 1415 | +0.53 [+0.26, +0.82] | +2.37 |

## 4. Damping the injury adjustment (alpha fit on training seasons only: 2023-24: alpha 0.89, concave a=1.16, c=0.118, 2024-25: alpha 0.89, concave a=1.04, c=0.062)

| slice | version | RMSE | bias | MSE reduction vs current |
|---|---|---|---|---|
| all games | current | 5.931 | 0.108 |  |
| all games | flat damping | 5.9285 | 0.065 | +0.030 [+0.015, +0.044] |
| all games | concave damping | 5.9282 | 0.075 | +0.033 [+0.013, +0.053] |
| star out | current | 6.3158 | 0.451 |  |
| star out | flat damping | 6.2959 | 0.189 | +0.252 [+0.143, +0.357] |
| star out | concave damping | 6.2892 | 0.164 | +0.336 [+0.166, +0.501] |
| no star out | current | 5.897 | 0.078 |  |
| no star out | flat damping | 5.8961 | 0.055 | +0.011 [-0.001, +0.021] |
| no star out | concave damping | 5.8963 | 0.067 | +0.007 [-0.006, +0.020] |

### Bias by adjustment size after each fix (star-out games)

| adj bucket | n | current | flat damping | concave damping |
|---|---|---|---|---|
| (-inf, 0.0] | 30.0 | 0.8 | 0.84 | 0.79 |
| (0.0, 1.0] | 367.0 | -0.25 | -0.33 | -0.24 |
| (1.0, 2.0] | 1298.0 | 0.21 | 0.04 | 0.15 |
| (2.0, 4.0] | 1936.0 | 0.53 | 0.23 | 0.2 |
| (4.0, inf] | 423.0 | 1.41 | 0.88 | 0.37 |
