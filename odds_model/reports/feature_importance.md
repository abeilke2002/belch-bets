# Feature importance (out-of-sample, test seasons 2023-24 and 2024-25)

**RMSE increase if shuffled** is the main ranking: how much worse the predictions get when that feature's values are scrambled. Features with a highly correlated twin (right column) share credit, so each can look less important alone than its group does together.

## Points model (RMSE in points)

### By feature

| feature | rank | RMSE increase if shuffled | SHAP share | gain share | by season (23-24 / 24-25) | most correlated with |
|---|---|---|---|---|---|---|
| pts_season | 1 | +1.076 | 32.2% | 63.5% | 1.198 / 0.953 | fga_season (0.98) |
| pred_minutes | 2 | +0.798 | 19.9% | 9.4% | 0.747 / 0.849 | min_5 (0.96) |
| fga_season | 3 | +0.197 | 10.9% | 11.0% | 0.212 / 0.182 | pts_season (0.98) |
| min_season | 4 | +0.135 | 5.7% | 0.7% | 0.144 / 0.126 | pred_minutes (0.93) |
| prev_season_ppg | 5 | +0.091 | 4.4% | 0.7% | 0.099 / 0.084 | pts_season (0.90) |
| fga_3 | 6 | +0.053 | 4.9% | 3.5% | 0.053 / 0.053 | fga_5 (0.97) |
| min_5 | 7 | +0.028 | 2.5% | 0.5% | 0.029 / 0.028 | min_3 (0.97) |
| opp_total_ratio | 8 | +0.021 | 3.0% | 0.8% | 0.018 / 0.023 | opp_pos_ratio (0.41) |
| fga_5 | 9 | +0.019 | 3.5% | 3.1% | 0.021 / 0.016 | fga_3 (0.97) |
| pts_3 | 10 | +0.017 | 2.0% | 1.0% | 0.019 / 0.014 | pts_5 (0.96) |
| fta_season | 11 | +0.012 | 2.7% | 1.1% | 0.017 / 0.006 | fta_5 (0.89) |
| pts_5 | 12 | +0.011 | 2.7% | 2.0% | 0.012 / 0.009 | fga_5 (0.96) |
| gp | 13 | +0.009 | 1.5% | 0.6% | 0.008 / 0.009 | pred_minutes (0.30) |
| fta_5 | 14 | +0.003 | 1.8% | 0.7% | 0.002 / 0.004 | fta_season (0.89) |
| opp_pos_ratio | 15 | +0.002 | 1.0% | 0.7% | 0.002 / 0.003 | opp_total_ratio (0.41) |
| min_3 | 16 | -0.001 | 1.3% | 0.5% | -0.004 / 0.001 | min_5 (0.97) |

### By group (all features in the group shuffled together)

| group | features | RMSE increase if shuffled |
|---|---|---|
| season averages | pts_season, fga_season, fta_season | +2.267 |
| predicted minutes | pred_minutes | +0.809 |
| recent form | pts_5, pts_3, fga_5, fga_3, fta_5 | +0.419 |
| raw minutes averages | min_season, min_5, min_3 | +0.359 |
| previous season | prev_season_ppg | +0.093 |
| opponent defense | opp_pos_ratio, opp_total_ratio | +0.021 |
| games played | gp | +0.009 |

## Minutes model (RMSE in minutes)

### By feature

| feature | rank | RMSE increase if shuffled | SHAP share | gain share | by season (23-24 / 24-25) | most correlated with |
|---|---|---|---|---|---|---|
| min_3 | 1 | +1.631 | 30.6% | 51.1% | 1.62 / 1.641 | min_5 (0.97) |
| min_season | 2 | +1.464 | 27.5% | 33.3% | 1.528 / 1.4 | min_5 (0.92) |
| started_last | 3 | +0.369 | 11.7% | 2.8% | 0.399 / 0.339 | starts_5 (0.91) |
| min_5 | 4 | +0.249 | 7.9% | 6.5% | 0.266 / 0.231 | min_3 (0.97) |
| rest_days | 5 | +0.114 | 4.4% | 1.1% | 0.113 / 0.115 | min_3 (0.25) |
| pts_season | 6 | +0.111 | 4.3% | 1.4% | 0.114 / 0.107 | min_season (0.86) |
| out_min | 7 | +0.058 | 3.8% | 1.2% | 0.054 / 0.062 | out_ppg (0.97) |
| gp | 8 | +0.021 | 1.2% | 0.5% | 0.023 / 0.019 | min_season (0.29) |
| start_rate | 9 | +0.018 | 2.1% | 0.8% | 0.017 / 0.019 | starts_5 (0.89) |
| n_out | 10 | +0.016 | 2.1% | 0.3% | 0.023 / 0.009 | out_min (0.94) |
| out_ppg | 11 | +0.009 | 2.3% | 0.9% | 0.012 / 0.007 | out_min (0.97) |
| starts_5 | 12 | +0.007 | 2.2% | 0.2% | 0.01 / 0.005 | started_last (0.91) |

### By group (all features in the group shuffled together)

| group | features | RMSE increase if shuffled |
|---|---|---|
| minutes averages | min_season, min_5, min_3 | +6.016 |
| teammates out | out_min, out_ppg, n_out | +0.283 |
| starter role | start_rate, started_last, starts_5 | +0.129 |
| scoring level | pts_season | +0.116 |
| rest | rest_days | +0.115 |
| games played | gp | +0.020 |
