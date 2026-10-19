# Role-jump features for the minutes model

Walk-forward 2023-26, actual absences.

| model | segment | games | minutes RMSE | minutes bias (actual - pred) | points RMSE | points bias (actual - pred) |
|---|---|---|---|---|---|---|
| + role features | all games | 77620 | 5.968 | -0.07 | 5.836 | -0.06 |
| current | all games | 77620 | 6.111 | -0.23 | 5.84 | -0.07 |
| + role features | bench (<15 mpg), 25+ new minutes out | 8637 | 7.31 | -0.1 | 4.868 | 0.14 |
| current | bench (<15 mpg), 25+ new minutes out | 8637 | 7.592 | 0.27 | 4.889 | 0.14 |
| + role features | props: bench (<15 mpg), line 2+ above avg | 399 | 7.433 | 2.35 | 6.086 | 1.39 |
| current | props: bench (<15 mpg), line 2+ above avg | 399 | 7.531 | 2.26 | 6.07 | 1.33 |
| + role features | props: line 4+ above season avg | 1956 | 6.061 | 1.32 | 7.296 | 1.08 |
| current | props: line 4+ above season avg | 1956 | 6.091 | 1.31 | 7.298 | 1.1 |
