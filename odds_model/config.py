import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSV_DIR = ROOT.parent / 'csvs'
DATA = ROOT / 'data'
RAW = DATA / 'odds_raw'          # historical snapshots: {event_id}_{early|close}.json
RAW_EVENTS = RAW / 'events'      # cached daily event lists: {YYYY-MM-DD}.json
LIVE = DATA / 'odds_live'        # daily logger snapshots, same file format as RAW
REPORTS = ROOT / 'reports'
for d in (DATA, RAW, RAW_EVENTS, LIVE, REPORTS):
    d.mkdir(parents=True, exist_ok=True)

# Odds API
_KEY_FILE = ROOT / '.odds_api_key'          # local file, chmod 600; keeps the key out of scripts
API_KEY = os.environ.get('ODDS_API_KEY') or (_KEY_FILE.read_text().strip() if _KEY_FILE.exists() else None)
SPORT = 'basketball_nba'
REGIONS = 'us'
MARKET = 'player_points'
# Live snapshots (noon and close) ask for all of these in one request: 1 credit per market per game
LIVE_MARKETS = ['player_points', 'player_rebounds', 'player_assists']
# Books used for training, the consensus and bets (Caesars = williamhill_us). Raw pulls keep every book.
BOOKS = ['draftkings', 'fanduel', 'betmgm', 'williamhill_us']
CLOSE_LINES = False              # evening closing-line pulls off (free plan); the Worker has the same switch
CREDIT_FLOOR = 0                 # no floor: the plan ends soon, so the daily runs may use every remaining credit
COST_EVENT_ODDS = 10             # historical event odds: 10 x markets x regions
COST_EVENTS = 1                  # historical events list

# Regular-season date ranges with player props available (props start May 2023)
SEASONS = {
    '2023-24': ('2023-10-24', '2024-04-14'),
    '2024-25': ('2024-10-22', '2025-04-13'),
    '2025-26': ('2025-10-21', '2026-04-12'),
}
# NBA GAME_ID prefix (after stripping leading zeros) -> season label
SEASON_CODE = {f'2{y % 100:02d}': f'{y}-{(y + 1) % 100:02d}' for y in range(2018, 2031)}

# Snapshot timing
EARLY_ET_HOUR = 12               # noon Eastern on game day (daylight-saving aware)
EARLY_MIN_LEAD_HOURS = 3         # early-game fallback (e.g. noon tips): commence - 3h
CLOSE_LEAD_MINUTES = 1           # close: last snapshot before tip (5-min snapshots; probe showed lines complete at tip)
EVENTS_UTC_HOUR = 15             # when to list each day's games (before any tip)

# Box score / game info files: the original files + every season pulled by pull_box_scores.py
BOX_FILES = ['all_box.csv'] + sorted(p.name for p in CSV_DIR.glob('20*_all_box.csv'))
GAME_INFO_FILES = ['game_info_new.csv'] + sorted(p.name for p in CSV_DIR.glob('game_info_20*.csv'))

# Intel (x86_64) Java for nbainjuries/tabula: the anaconda Python is an Intel build under Rosetta
import glob as _glob
JAVA_X64_HOME = (sorted(_glob.glob(os.path.expanduser('~/Library/Java-x64/jdk-17*/Contents/Home'))) or [''])[-1]
