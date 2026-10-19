"""Walk-forward backward elimination of feature groups, with game-date-clustered bootstrap CIs.

A group stays only if removing it makes the out-of-sample loss significantly worse
(95% CI of the loss increase is entirely above 0). Groups are tested as blocks because
correlated features (e.g. season avg and last-5 avg) hide each other when tested one at a time.
"""
import numpy as np
import pandas as pd


def clustered_ci(diff, clusters, n_boot=2000, seed=0):
    """Mean of diff with a 95% CI that resamples whole game dates (rows on a date are correlated)."""
    d = pd.DataFrame({'d': diff, 'c': clusters}).groupby('c')['d'].agg(['sum', 'count'])
    idx = np.random.default_rng(seed).integers(0, len(d), (n_boot, len(d)))
    boot = d['sum'].values[idx].sum(1) / d['count'].values[idx].sum(1)
    return float(np.mean(diff)), float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def backward_eliminate(groups, evaluate, protected=(), log=print):
    """groups: {name: [features]}. evaluate(features) -> (per-row loss array, cluster labels).
    Returns (kept groups, table of every test run)."""
    cache = {}

    def run(feats):
        key = frozenset(feats)
        if key not in cache:
            cache[key] = evaluate(sorted(feats, key=feats.index))
        return cache[key]

    current, rounds = dict(groups), []
    while True:
        feats = [f for fs in current.values() for f in fs]
        base, clusters = run(feats)
        rows = []
        for name, fs in current.items():
            if name in protected:
                continue
            loss, _ = run([f for f in feats if f not in fs])
            m, lo, hi = clustered_ci(loss - base, clusters)
            rows.append({'round': len(rounds) + 1, 'group': name, 'features': ', '.join(fs),
                         'loss increase if removed': m, 'CI low': lo, 'CI high': hi,
                         'significant': lo > 0})
        rounds += rows
        removable = [r for r in rows if not r['significant']]
        log(f"round {len(set(r['round'] for r in rounds))}: base loss {base.mean():.4f} | "
            + ', '.join(f"{r['group']} {r['loss increase if removed']:+.4f}" for r in rows))
        if not removable:
            break
        drop = min(removable, key=lambda r: r['loss increase if removed'])
        log(f"  -> dropping '{drop['group']}' (removing it changes loss by "
            f"{drop['loss increase if removed']:+.4f}, CI [{drop['CI low']:+.4f}, {drop['CI high']:+.4f}])")
        del current[drop['group']]
    return current, pd.DataFrame(rounds)
