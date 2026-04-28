#!/usr/bin/env python3
"""
Fetch Bybit trading data for Raven Dashboard (GitHub Actions)
Updates data.json with live balances, positions, and market data.
"""
import requests, json, os, hmac, hashlib, time
from datetime import datetime, timedelta

BASE = 'https://api.bybit.com/v5'
WILD_KEY = 'E3G3MbtVngOhRpHS6D'
WILD_SECRET = 'skjTaRenp1Vlf4xF8vftEJ5DTwzYCQteKF7y'
JOAKO_KEY = 'r0H7bCbFNwR7jQQc6x'
JOAKO_SECRET = 'sJWEt8HjpyXhQf6iROn3DkV80HrYvmMclF8y'

def bybit_get(api_key, api_secret, endpoint, params=None):
    if params is None: params = {}
    ts = str(int(time.time() * 1000))
    recv = '5000'
    qs = '&'.join([f'{k}={v}' for k,v in sorted(params.items())])
    sig_str = ts + api_key + recv + qs
    sig = hmac.new(api_secret.encode(), sig_str.encode(), hashlib.sha256).hexdigest()
    
    r = requests.get(f'{BASE}{endpoint}', 
        headers={
            'X-BAPI-API-KEY': api_key,
            'X-BAPI-TIMESTAMP': ts,
            'X-BAPI-SIGN': sig,
            'X-BAPI-RECV-WINDOW': recv
        }, params=params, timeout=15)
    return r.json()

def get_balance(api_key, api_secret, name):
    data = bybit_get(api_key, api_secret, '/account/wallet-balance', {'accountType': 'UNIFIED'})
    equity = 0.0
    coins = []
    if data.get('retCode') == 0:
        result = data['result']
        equity = float(result.get('totalEquity', 0))
        coins = result.get('list', [{}])[0].get('coin', [])
    return equity, coins

def get_positions(api_key, api_secret):
    data = bybit_get(api_key, api_secret, '/position/list', {'category': 'linear', 'settleCoin': 'USDT'})
    positions = []
    if data.get('retCode') == 0:
        for p in data['result'].get('list', []):
            size = float(p.get('size', 0))
            if size > 0:
                positions.append({
                    'symbol': p['symbol'],
                    'size': size,
                    'entryPrice': float(p.get('avgPrice', 0)),
                    'unrealisedPnl': float(p.get('unrealisedPnl', 0)),
                    'leverage': p.get('leverage', '1x'),
                    'liquidationPrice': float(p.get('liquidationPrice', 0)),
                    'side': p.get('side', 'Buy')
                })
    return positions

def get_btc_info():
    try:
        r = requests.get(f'{BASE}/market/tickers', params={'category': 'spot', 'symbol': 'BTCUSDT'}, timeout=10)
        if r.json().get('retCode') == 0:
            d = r.json()['result']['list'][0]
            return {'price': float(d['lastPrice']), 'change': float(d.get('change24h', 0))}
    except: pass
    return {'price': 0, 'change': 0}

def get_top_movers():
    try:
        r = requests.get(f'{BASE}/market/tickers', params={'category': 'linear', 'limit': 200}, timeout=10)
        movers = []
        if r.json().get('retCode') == 0:
            coins = r.json()['result']['list']
            filtered = [c for c in coins if float(c.get('turnover24h', 0)) > 500000]
            sorted_coins = sorted(filtered, key=lambda c: abs(float(c.get('change24h', 0))), reverse=True)[:10]
            for c in sorted_coins:
                movers.append({
                    'symbol': c['symbol'],
                    'price': float(c['lastPrice']),
                    'change': float(c.get('change24h', 0)),
                    'signal': 'OBSERVANDO' if abs(float(c.get('change24h', 0))) > 5 else '—'
                })
        return movers
    except: return []

# ====== MAIN ======
print('Fetching trading data...')

# WILD balance
wild_eq, wild_coins = get_balance(WILD_KEY, WILD_SECRET, 'WILD')
wild_usdt = 0.0
for c in wild_coins:
    if c['coin'] == 'USDT':
        wild_usdt = float(c.get('walletBalance', 0))
        break
wild_equity = wild_eq

# JOAKO balance
joako_eq, joako_coins = get_balance(JOAKO_KEY, JOAKO_SECRET, 'JOAKO')
joako_usdt = 0.0
for c in joako_coins:
    if c['coin'] == 'USDT':
        joako_usdt = float(c.get('walletBalance', 0))
        break
joako_equity = joako_eq

total = wild_eq + joako_eq

# Positions
positions = get_positions(WILD_KEY, WILD_SECRET) + get_positions(JOAKO_KEY, JOAKO_SECRET)

# BTC
btc = get_btc_info()

# Movers
movers = get_top_movers()

# Last trades from file (persistent across runs)
last_trades = []
trades_file = 'trades.json'
if os.path.exists(trades_file):
    try:
        with open(trades_file) as f: last_trades = json.load(f)
    except: pass

# Capital history
capital_history = []
history_file = 'capital_history.json'
if os.path.exists(history_file):
    try:
        with open(history_file) as f: capital_history = json.load(f)
    except: pass

# Add today's data point
today = datetime.now().strftime('%d/%m')
if not capital_history or capital_history[-1]['date'] != today:
    capital_history.append({'date': today, 'capital': round(total, 2)})
else:
    capital_history[-1]['capital'] = round(total, 2)
# Keep max 30 days
capital_history = capital_history[-30:]

# Save history
with open(history_file, 'w') as f:
    json.dump(capital_history, f)

# PnL calculation from history
initial = capital_history[0]['capital'] if capital_history else 0
pnl = total - initial
pnl_pct = (pnl / initial * 100) if initial > 0 else 0

# Build output
output = {
    'totalCapital': round(total, 2),
    'wildCapital': round(wild_equity, 2),
    'joakoCapital': round(joako_equity, 2),
    'wildEquity': round(wild_equity, 2),
    'joakoEquity': round(joako_equity, 2),
    'pnlCycle': round(pnl, 2),
    'pnlPercent': round(pnl_pct, 2),
    'openPositions': len(positions),
    'timestamp': datetime.now().isoformat(),
    'btc': btc,
    'positions': positions,
    'lastTrades': last_trades[:20],
    'watchCoins': movers[:15],
    'capitalHistory': capital_history
}

# Write data.json
with open('data.json', 'w') as f:
    json.dump(output, f, indent=2)

print(f'✅ Data updated: Total=${total:.2f} | WILD=${wild_equity:.2f} | JOAKO=${joako_equity:.2f} | Pos={len(positions)}')
