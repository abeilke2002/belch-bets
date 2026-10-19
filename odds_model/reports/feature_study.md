# Feature study (walk-forward, test seasons 2023-24 + 2024-25)

A feature group is kept only if removing it raises out-of-sample squared error with a 95% CI (clustered by game date) entirely above zero. Removed one group per round, weakest first.

## Minutes model

Kept groups: **minutes averages, starter role, games played, rest, scoring level, return from absence, usage freed up**

| | RMSE minutes |
|---|---|
| Last-5 average | 6.663 |
| Minutes model | 6.127 |

MSE reduction vs last-5: 6.86 (95% CI [5.84, 8.28])

| round | group | features | loss increase if removed | CI low | CI high | significant |
|---|---|---|---|---|---|---|
| 1 | minutes averages | min_season, min_5, min_3 | 7.357 | 7.0041 | 7.712 | True |
| 1 | starter role | start_rate, started_last, starts_5 | 0.4836 | 0.3828 | 0.5825 | True |
| 1 | teammates out | out_min, out_ppg, n_out | -0.0556 | -0.1328 | 0.0219 | False |
| 1 | games played | gp | 0.078 | 0.0154 | 0.1456 | True |
| 1 | rest | rest_days | 0.2895 | 0.198 | 0.3848 | True |
| 1 | home | is_home | -0.0016 | -0.0431 | 0.0372 | False |
| 1 | scoring level | pts_season | 0.0463 | -0.0124 | 0.103 | False |
| 1 | opponent | opp_total_ratio | -0.0011 | -0.0589 | 0.0539 | False |
| 1 | return from absence | games_missed_before, games_since_return, last_absence_len | 0.0388 | -0.0182 | 0.0961 | False |
| 1 | usage freed up | out_fga, out_fga_share | -0.0549 | -0.1056 | -0.0075 | False |
| 11 | minutes averages | min_season, min_5, min_3 | 7.3244 | 6.9745 | 7.6725 | True |
| 11 | starter role | start_rate, started_last, starts_5 | 0.4964 | 0.4002 | 0.5935 | True |
| 11 | games played | gp | 0.0942 | 0.0284 | 0.169 | True |
| 11 | rest | rest_days | 0.3472 | 0.2656 | 0.4299 | True |
| 11 | home | is_home | 0.0251 | -0.0079 | 0.0556 | False |
| 11 | scoring level | pts_season | 0.0752 | 0.0214 | 0.1322 | True |
| 11 | opponent | opp_total_ratio | 0.0215 | -0.0301 | 0.0723 | False |
| 11 | return from absence | games_missed_before, games_since_return, last_absence_len | 0.0574 | 0.0034 | 0.107 | True |
| 11 | usage freed up | out_fga, out_fga_share | 2.6967 | 1.9977 | 3.6769 | True |
| 20 | minutes averages | min_season, min_5, min_3 | 7.457 | 7.1068 | 7.8101 | True |
| 20 | starter role | start_rate, started_last, starts_5 | 0.5075 | 0.4142 | 0.607 | True |
| 20 | games played | gp | 0.0661 | -0.0051 | 0.1393 | False |
| 20 | rest | rest_days | 0.3374 | 0.2481 | 0.428 | True |
| 20 | home | is_home | -0.0174 | -0.0506 | 0.0145 | False |
| 20 | scoring level | pts_season | 0.0403 | -0.0132 | 0.0929 | False |
| 20 | return from absence | games_missed_before, games_since_return, last_absence_len | 0.0726 | 0.0174 | 0.1285 | True |
| 20 | usage freed up | out_fga, out_fga_share | 2.6622 | 1.9681 | 3.6505 | True |
| 28 | minutes averages | min_season, min_5, min_3 | 7.4716 | 7.1168 | 7.8256 | True |
| 28 | starter role | start_rate, started_last, starts_5 | 0.5102 | 0.4152 | 0.6069 | True |
| 28 | games played | gp | 0.112 | 0.0416 | 0.1863 | True |
| 28 | rest | rest_days | 0.3711 | 0.2887 | 0.4557 | True |
| 28 | scoring level | pts_season | 0.0821 | 0.0284 | 0.1399 | True |
| 28 | return from absence | games_missed_before, games_since_return, last_absence_len | 0.0761 | 0.0217 | 0.1336 | True |
| 28 | usage freed up | out_fga, out_fga_share | 2.6931 | 1.9943 | 3.6529 | True |

## Points model

Kept groups: **season averages, recent form, predicted minutes, starter role, rest, previous season, teammates out, opponent defense, shot redistribution (new absences)**

| feature set | n features | RMSE points | MSE reduction vs original |
|---|---|---|---|
| original 18 features | 18 | 5.9261 | +0.000 [+0.000, +0.000] |
| all candidates | 34 | 5.8462 | +0.941 [+0.826, +1.052] |
| selected | 23 | 5.8481 | +0.918 [+0.793, +1.041] |
| season average (no model) | 1 | 6.148 |  |

### Elimination rounds

| round | group | features | loss increase if removed | CI low | CI high | significant |
|---|---|---|---|---|---|---|
| 1 | season averages | pts_season, fga_season, fta_season | 0.1195 | 0.0513 | 0.1851 | True |
| 1 | recent form | pts_5, pts_3, fga_5, fga_3, fta_5 | 0.1083 | 0.039 | 0.178 | True |
| 1 | raw minutes averages | min_season, min_5, min_3 | 0.016 | -0.0283 | 0.0618 | False |
| 1 | predicted minutes | pred_minutes | 0.013 | -0.0325 | 0.06 | False |
| 1 | starter role | start_rate, started_last, starts_5 | 0.0822 | 0.0402 | 0.1236 | True |
| 1 | volatility | pts_std | -0.0167 | -0.0562 | 0.0233 | False |
| 1 | games played | gp | 0.0095 | -0.0349 | 0.0549 | False |
| 1 | rest | rest_days | -0.0095 | -0.051 | 0.0302 | False |
| 1 | previous season | prev_season_ppg | 0.1947 | 0.0909 | 0.3102 | True |
| 1 | teammates out | out_ppg, out_min, n_out | 0.098 | 0.0497 | 0.1439 | True |
| 1 | home | is_home | 0.0186 | -0.0256 | 0.0639 | False |
| 1 | opponent defense | opp_pos_ratio, opp_total_ratio | 0.1694 | 0.1027 | 0.2345 | True |
| 1 | return from absence | games_missed_before, games_since_return, last_absence_len | 0.0074 | -0.0334 | 0.0484 | False |
| 1 | usage freed up | out_fga, out_fga_share | 0.0028 | -0.038 | 0.04 | False |
| 1 | shot redistribution (new absences) | usage_share, exp_extra_fga_new, exp_extra_pts_new, exp_extra_pts_recent | 0.6577 | 0.563 | 0.75 | True |
| 16 | season averages | pts_season, fga_season, fta_season | 0.115 | 0.0421 | 0.1815 | True |
| 16 | recent form | pts_5, pts_3, fga_5, fga_3, fta_5 | 0.089 | 0.0194 | 0.1564 | True |
| 16 | raw minutes averages | min_season, min_5, min_3 | 0.0149 | -0.03 | 0.06 | False |
| 16 | predicted minutes | pred_minutes | -0.004 | -0.046 | 0.0382 | False |
| 16 | starter role | start_rate, started_last, starts_5 | 0.0949 | 0.0514 | 0.1381 | True |
| 16 | games played | gp | 0.0658 | 0.017 | 0.1102 | True |
| 16 | rest | rest_days | 0.0072 | -0.0329 | 0.0466 | False |
| 16 | previous season | prev_season_ppg | 0.1952 | 0.0858 | 0.3094 | True |
| 16 | teammates out | out_ppg, out_min, n_out | 0.0938 | 0.0432 | 0.1416 | True |
| 16 | home | is_home | 0.0471 | 0.0071 | 0.0872 | True |
| 16 | opponent defense | opp_pos_ratio, opp_total_ratio | 0.1635 | 0.0958 | 0.2266 | True |
| 16 | return from absence | games_missed_before, games_since_return, last_absence_len | 0.0079 | -0.0347 | 0.0503 | False |
| 16 | usage freed up | out_fga, out_fga_share | -0.0146 | -0.0553 | 0.0231 | False |
| 16 | shot redistribution (new absences) | usage_share, exp_extra_fga_new, exp_extra_pts_new, exp_extra_pts_recent | 0.6376 | 0.5423 | 0.7377 | True |
| 30 | season averages | pts_season, fga_season, fta_season | 0.1304 | 0.0581 | 0.1998 | True |
| 30 | recent form | pts_5, pts_3, fga_5, fga_3, fta_5 | 0.1334 | 0.0554 | 0.2058 | True |
| 30 | raw minutes averages | min_season, min_5, min_3 | 0.0469 | 0.0031 | 0.0904 | True |
| 30 | predicted minutes | pred_minutes | 0.0284 | -0.0146 | 0.0748 | False |
| 30 | starter role | start_rate, started_last, starts_5 | 0.04 | -0.0022 | 0.0846 | False |
| 30 | games played | gp | 0.0286 | -0.0173 | 0.0741 | False |
| 30 | rest | rest_days | 0.0376 | 0.0007 | 0.0766 | True |
| 30 | previous season | prev_season_ppg | 0.1997 | 0.0909 | 0.3122 | True |
| 30 | teammates out | out_ppg, out_min, n_out | 0.0721 | 0.0261 | 0.1195 | True |
| 30 | home | is_home | 0.0345 | -0.0043 | 0.0782 | False |
| 30 | opponent defense | opp_pos_ratio, opp_total_ratio | 0.145 | 0.0804 | 0.2078 | True |
| 30 | return from absence | games_missed_before, games_since_return, last_absence_len | 0.0206 | -0.0197 | 0.0626 | False |
| 30 | shot redistribution (new absences) | usage_share, exp_extra_fga_new, exp_extra_pts_new, exp_extra_pts_recent | 0.6592 | 0.5686 | 0.7506 | True |
| 43 | season averages | pts_season, fga_season, fta_season | 0.1002 | 0.0317 | 0.1682 | True |
| 43 | recent form | pts_5, pts_3, fga_5, fga_3, fta_5 | 0.1029 | 0.0277 | 0.1719 | True |
| 43 | raw minutes averages | min_season, min_5, min_3 | -0.0036 | -0.0527 | 0.0425 | False |
| 43 | predicted minutes | pred_minutes | 0.0345 | -0.0076 | 0.0765 | False |
| 43 | starter role | start_rate, started_last, starts_5 | 0.0604 | 0.0193 | 0.1042 | True |
| 43 | games played | gp | 0.0724 | 0.0285 | 0.1179 | True |
| 43 | rest | rest_days | 0.038 | -0.0018 | 0.0725 | False |
| 43 | previous season | prev_season_ppg | 0.1816 | 0.0808 | 0.2919 | True |
| 43 | teammates out | out_ppg, out_min, n_out | 0.1021 | 0.0522 | 0.1518 | True |
| 43 | home | is_home | 0.0242 | -0.0145 | 0.0624 | False |
| 43 | opponent defense | opp_pos_ratio, opp_total_ratio | 0.1185 | 0.0537 | 0.1794 | True |
| 43 | shot redistribution (new absences) | usage_share, exp_extra_fga_new, exp_extra_pts_new, exp_extra_pts_recent | 0.643 | 0.5487 | 0.7376 | True |
| 55 | season averages | pts_season, fga_season, fta_season | 0.1339 | 0.0643 | 0.2035 | True |
| 55 | recent form | pts_5, pts_3, fga_5, fga_3, fta_5 | 0.3707 | 0.287 | 0.4513 | True |
| 55 | predicted minutes | pred_minutes | 0.063 | 0.0153 | 0.1135 | True |
| 55 | starter role | start_rate, started_last, starts_5 | 0.1457 | 0.0991 | 0.1957 | True |
| 55 | games played | gp | 0.0599 | 0.0129 | 0.1049 | True |
| 55 | rest | rest_days | 0.0535 | 0.0138 | 0.0954 | True |
| 55 | previous season | prev_season_ppg | 0.2226 | 0.1135 | 0.3375 | True |
| 55 | teammates out | out_ppg, out_min, n_out | 0.0777 | 0.0242 | 0.1289 | True |
| 55 | home | is_home | 0.0196 | -0.0215 | 0.0618 | False |
| 55 | opponent defense | opp_pos_ratio, opp_total_ratio | 0.1501 | 0.0827 | 0.2149 | True |
| 55 | shot redistribution (new absences) | usage_share, exp_extra_fga_new, exp_extra_pts_new, exp_extra_pts_recent | 0.6637 | 0.5705 | 0.7574 | True |
| 66 | season averages | pts_season, fga_season, fta_season | 0.1623 | 0.0906 | 0.2325 | True |
| 66 | recent form | pts_5, pts_3, fga_5, fga_3, fta_5 | 0.3962 | 0.3087 | 0.4807 | True |
| 66 | predicted minutes | pred_minutes | 0.0672 | 0.0203 | 0.1148 | True |
| 66 | starter role | start_rate, started_last, starts_5 | 0.1467 | 0.1011 | 0.1936 | True |
| 66 | games played | gp | 0.0177 | -0.0303 | 0.0682 | False |
| 66 | rest | rest_days | 0.0314 | -0.0075 | 0.0703 | False |
| 66 | previous season | prev_season_ppg | 0.2309 | 0.1255 | 0.3408 | True |
| 66 | teammates out | out_ppg, out_min, n_out | 0.0613 | 0.0098 | 0.1134 | True |
| 66 | opponent defense | opp_pos_ratio, opp_total_ratio | 0.1335 | 0.0613 | 0.1974 | True |
| 66 | shot redistribution (new absences) | usage_share, exp_extra_fga_new, exp_extra_pts_new, exp_extra_pts_recent | 0.6627 | 0.5696 | 0.7565 | True |
| 76 | season averages | pts_season, fga_season, fta_season | 0.1399 | 0.0665 | 0.21 | True |
| 76 | recent form | pts_5, pts_3, fga_5, fga_3, fta_5 | 0.4187 | 0.3325 | 0.5021 | True |
| 76 | predicted minutes | pred_minutes | 0.0674 | 0.0239 | 0.1103 | True |
| 76 | starter role | start_rate, started_last, starts_5 | 0.1596 | 0.1138 | 0.2064 | True |
| 76 | rest | rest_days | 0.1066 | 0.0683 | 0.1435 | True |
| 76 | previous season | prev_season_ppg | 0.2344 | 0.1269 | 0.3464 | True |
| 76 | teammates out | out_ppg, out_min, n_out | 0.0568 | 0.0036 | 0.1061 | True |
| 76 | opponent defense | opp_pos_ratio, opp_total_ratio | 0.1583 | 0.0894 | 0.226 | True |
| 76 | shot redistribution (new absences) | usage_share, exp_extra_fga_new, exp_extra_pts_new, exp_extra_pts_recent | 0.6829 | 0.5884 | 0.7776 | True |
