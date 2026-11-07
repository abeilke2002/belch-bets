"""Historical noon lines for more player-prop markets, at the exact moments of the points pull (resumable).

For every game in data/odds_raw (the player-points pull), ask for the other markets at that game's early
snapshot time, so each new line lines up with the points line from the same moment and no credits go on
re-listing games. Cost: 10 credits per market per game.

    python pull_extra_markets.py                                    # rebounds + assists -> data/odds_raw_rebast/
    python pull_extra_markets.py --markets player_threes --out odds_raw_threes --test 3
    python pull_extra_markets.py --floor 20000                       # stop before credits fall below this

Same file format as data/odds_raw ({event_id}_early.json), so parse_odds.read_raw reads it.
"""
import argparse
import json
import shutil

from config import DATA, RAW, REGIONS, SPORT
from odds_api import CreditLimit, OddsAPI


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--markets', default='player_rebounds,player_assists')
    ap.add_argument('--out', default='odds_raw_rebast', help='folder under data/')
    ap.add_argument('--floor', type=int, default=20_000, help='stop when remaining credits would fall below this')
    ap.add_argument('--test', type=int, help='only this many games')
    args = ap.parse_args()
    out = DATA / args.out
    out.mkdir(exist_ok=True)
    cost = 10 * len(args.markets.split(',')) * len(REGIONS.split(','))
    test_dir = DATA / 'odds_raw_rebast_test'                 # games already pulled in the coverage check

    sources = sorted(RAW.glob('*_early.json'))
    todo = [f for f in sources if not (out / f.name).exists()]
    if args.test:
        todo = todo[:args.test]
    print(f'{len(sources)} games in the points pull, {len(todo)} still to pull at {cost} credits each '
          f'(~{len(todo) * cost:,} credits)', flush=True)

    api = OddsAPI(floor=args.floor)
    done = reused = 0
    try:
        for i, f in enumerate(todo, 1):
            snap = json.loads(f.read_text())
            event = snap.get('_meta', {}).get('event') or snap.get('data') or {}
            eid, ts = event.get('id') or f.stem.split('_')[0], snap.get('timestamp')
            if not ts:
                continue
            if args.markets == 'player_rebounds,player_assists' and (test_dir / f.name).exists():
                shutil.copy(test_dir / f.name, out / f.name)     # same markets, pulled at noon that day
                reused += 1
                continue
            data = api.get(f'/historical/sports/{SPORT}/events/{eid}/odds', expected_cost=cost, regions=REGIONS,
                           markets=args.markets, oddsFormat='american', date=ts)
            meta = {**snap.get('_meta', {}), 'snapshot': 'early', 'markets': args.markets}
            (out / f.name).write_text(json.dumps({'timestamp': (data or {}).get('timestamp', ts),
                                                  'data': (data or {}).get('data'), '_meta': meta}))
            done += 1
            if i % 100 == 0:
                print(f'  {i}/{len(todo)} | credits left {api.remaining}', flush=True)
    except CreditLimit as e:
        print(f'stopped: {e}', flush=True)
    print(f'done: {done} pulled, {reused} reused from the coverage check | credits left {api.remaining}', flush=True)


if __name__ == '__main__':
    main()
