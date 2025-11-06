#!/usr/bin/env python3
# ──────────────────────────────────────────────────────────────
#  SMART LONG SCALPER — $10 @ 33x
#  TP +33% | SL -10%
#  Regime + Dip→Bounce + ATR + Trailing + Circuit Breakers
# ──────────────────────────────────────────────────────────────

import os
import time
import json
import math
import requests
import traceback
import collections
from decimal import Decimal, ROUND_DOWN
from dotenv import load_dotenv
from eth_abi import encode as abi_encode
from web3 import Web3
from web3.main import to_checksum_address
from eth_account import Account
from eth_account.messages import encode_defunct

# ───────── CONFIG ─────────
SYMBOL        = "ASTERUSDT"
LEVERAGE      = 33
MARGIN_USD    = 10.0
TP_PNL        = 33.0      # close at +33% on margin (~+1.0% price @ 33x)
SL_PNL        = 10.0      # hard stop -10% on margin (~-0.30% price @ 33x)
POLL_SEC      = 3
BASE_COOLDOWN = 10        # seconds after close (increases on loss streak)

# Entry guards
EMA_FAST      = 9
EMA_MID       = 50
EMA_SLOW      = 200
PULLBACK_MIN  = 0.25      # last closed 1m change ≤ -0.25% (dip)
SLOPE_LEN     = 5         # short-term slope check (1m closes)
MIN_ATR_PCT   = 0.15      # require ATR(14) ≥ 0.15% to avoid dead chop

# Trailing
TRAIL_ARM_PNL = 20.0      # arm trailing when PnL ≥ +20%
TRAIL_GIVEUP  = 12.0      # close if PnL falls TRAIL_GIVEUP from peak

# Risk brakes
MAX_TRADES_PER_HOUR  = 8
MAX_CONSEC_LOSSES    = 5
SESSION_DRAWDOWN_USD = 4.0  # stop bot if down ≥ $4 for the session

RECV_WINDOW = 5000
TIMEOUT_S   = 15
MAX_RETRY   = 3
BACKOFF_S   = 1.5

# ───────── AUTH / BASE ─────────
load_dotenv()

ASTER_USER   = os.getenv("ASTER_USER", "").strip()
ASTER_SIGNER = os.getenv("ASTER_SIGNER", "").strip()
ASTER_PRIV   = os.getenv("ASTER_SIGNER_PRIVKEY", "").strip()
ASTER_KEY    = os.getenv("ASTER_API_KEY", "").strip()

if not (ASTER_USER and ASTER_SIGNER and ASTER_PRIV and ASTER_KEY):
    raise SystemExit("Missing one or more: ASTER_USER, ASTER_SIGNER, ASTER_SIGNER_PRIVKEY, ASTER_API_KEY")

BASE       = "https://fapi.asterdex.com"
BASE_HTTP  = f"{BASE}/fapi/v3"
HEADERS    = {"X-MBX-APIKEY": ASTER_KEY, "Content-Type": "application/x-www-form-urlencoded"}
w3         = Web3()

# ───────── UTIL ─────────
def now_ms(): return int(time.time() * 1000)
def now_us(): return int(time.time() * 1_000_000)

def _trim(d):
    o = {}
    for k, v in d.items():
        if v is None:
            continue
        if isinstance(v, dict):
            o[k] = json.dumps(_trim(v), separators=(",", ":"))
        elif isinstance(v, list):
            o[k] = json.dumps(v, separators=(",", ":"))
        else:
            o[k] = str(v)
    return o

def make_sorted_json_str(p):
    return json.dumps(_trim(p), sort_keys=True, separators=(",", ":"))

def sign(js, user, signer, nonce):
    enc = abi_encode(
        ['string', 'address', 'address', 'uint256'],
        [js, to_checksum_address(user), to_checksum_address(signer), int(nonce)]
    )
    keccak = w3.keccak(enc).hex()
    msg = encode_defunct(hexstr=keccak)
    sig = Account.sign_message(signable_message=msg, private_key=ASTER_PRIV)
    return '0x' + sig.signature.hex()

def _req(method, url, params=None, data=None, headers=None):
    for attempt in range(1, MAX_RETRY + 1):
        r = requests.request(method, url, params=params, data=data, headers=headers, timeout=TIMEOUT_S)
        if r.status_code in (429,) or r.status_code >= 500:
            wait = BACKOFF_S * attempt
            print(f"⏳ {r.status_code} backoff {wait:.1f}s")
            time.sleep(wait)
            continue
        return r
    r.raise_for_status()
    return r

def call(meth, path, p=None):
    p = p or {}
    p.update({'recvWindow': RECV_WINDOW, 'timestamp': now_ms()})
    js = make_sorted_json_str(p)
    nonce = now_us()
    sig = sign(js, ASTER_USER, ASTER_SIGNER, nonce)
    p.update({'nonce': nonce, 'user': ASTER_USER, 'signer': ASTER_SIGNER, 'signature': sig})

    url = BASE_HTTP + path
    if meth == "GET":
        r = _req("GET", url, params=p, headers=HEADERS)
    elif meth == "DELETE":
        r = _req("DELETE", url, data=p, headers=HEADERS)
    else:
        r = _req("POST", url, data=p, headers=HEADERS)

    if r.status_code >= 400:
        raise RuntimeError(f"{meth} {path} {r.status_code} {r.text}")
    return r.json()

# ───────── API HELPERS ─────────
def get_price():
    j = _req("GET", f"{BASE_HTTP}/ticker/price", params={"symbol": SYMBOL}, headers=HEADERS).json()
    return float(j["price"])

def get_mark_price():
    j = _req("GET", f"{BASE_HTTP}/premiumIndex", params={"symbol": SYMBOL}, headers=HEADERS).json()
    if isinstance(j, list):
        j = j[0]
    return float(j["markPrice"])

def get_klines(interval="1m", limit=240):
    r = _req("GET", f"{BASE_HTTP}/klines",
             params={"symbol": SYMBOL, "interval": interval, "limit": limit},
             headers=HEADERS)
    r.raise_for_status()
    return r.json()

def get_filters():
    info = _req("GET", f"{BASE_HTTP}/exchangeInfo", headers=HEADERS).json()
    for s in info.get("symbols", []):
        if s.get("symbol") == SYMBOL:
            f = {f["filterType"]: f for f in s["filters"]}
            pf = f.get("PRICE_FILTER", {})
            lot = f.get("MARKET_LOT_SIZE") or f.get("LOT_SIZE") or {}
            mn = f.get("MIN_NOTIONAL", {})
            return {
                "tickSize":    Decimal(pf.get("tickSize", "0.000001")),
                "minQty":      Decimal(lot.get("minQty", "0.0")),
                "maxQty":      Decimal(lot.get("maxQty", "999999999")),
                "stepSize":    Decimal(lot.get("stepSize", "0.001")),
                "minNotional": Decimal(mn.get("notional", "0")),
            }
    raise RuntimeError(f"{SYMBOL} not in exchangeInfo")

def set_leverage():
    return call("POST", "/leverage", {"symbol": SYMBOL, "leverage": LEVERAGE})

def place_market(side, qty, reduce=False):
    return call("POST", "/order", {
        "symbol": SYMBOL,
        "side": side,
        "type": "MARKET",
        "quantity": str(qty),
        "reduceOnly": str(reduce).lower(),
        "positionSide": "BOTH"
    })

def read_position():
    try:
        data = call("GET", "/positionRisk", {})
        if isinstance(data, dict):
            data = [data]
        for p in data:
            sym = p.get("symbol") or p.get("instrumentId")
            if sym != SYMBOL:
                continue
            amt = float(p.get("positionAmt", p.get("size", 0)) or 0)
            entry = float(p.get("entryPrice", p.get("entry", 0)) or 0)
            if abs(amt) < 1e-12:
                continue
            return ("LONG" if amt > 0 else "SHORT"), abs(amt), entry
    except Exception:
        print("⚠️ read_position failed:")
        traceback.print_exc()
    return None, 0.0, 0.0

def close_position():
    side, qty, _ = read_position()
    if not qty:
        print("↔ No position to close")
        return
    if side == "LONG":
        print(f"↔ Closing LONG {qty}")
        place_market("SELL", qty, reduce=True)
    else:
        print(f"↔ Reducing unexpected SHORT {qty}")
        place_market("BUY", qty, reduce=True)

# ───────── INDICATORS ─────────
def ema(vals, length):
    k = 2 / (length + 1)
    e = vals[0]
    for x in vals[1:]:
        e = x * k + e * (1 - k)
    return e

def ema_series(closes, length):
    out = []
    k = 2 / (length + 1)
    e = closes[0]
    for x in closes:
        e = x * k + e * (1 - k)
        out.append(e)
    return out

def atr(closes, highs, lows, length=14):
    trs = [max(h - l, abs(h - cp), abs(l - cp)) for (h, l, cp) in zip(highs[1:], lows[1:], closes[:-1])]
    if len(trs) < length:
        return None
    a = trs[0]
    for tr in trs[1:]:
        a = (a * (length - 1) + tr) / length
    return a

# ───────── QTY / PNL ─────────
def floor_to_step(x: Decimal, step: Decimal) -> Decimal:
    return (x // step) * step

def calc_qty(price_f, fil):
    price = Decimal(str(price_f))
    targetN = Decimal(str(MARGIN_USD)) * Decimal(str(LEVERAGE))
    mark_p = Decimal(str(get_mark_price()))
    target_qty = targetN / price
    qty = min(target_qty, fil["maxQty"])
    qty = floor_to_step(qty, fil["stepSize"])

    if qty < fil["minQty"]:
        raise RuntimeError(f"qty {qty} < minQty {fil['minQty']}")

    if (qty * mark_p) < fil["minNotional"]:
        need = (fil["minNotional"] / mark_p)
        qty = max(qty, floor_to_step(need + fil["stepSize"], fil["stepSize"]))

    return float(qty)

def pnl_pct_on_margin_long(entry, last):
    return (last - entry) / entry * LEVERAGE * 100.0

# ───────── MAIN ─────────
def main():
    print(f"\nSMART LONG :: {SYMBOL} | {LEVERAGE}x | ${MARGIN_USD} | TP +{TP_PNL}% | SL -{SL_PNL}% | poll {POLL_SEC}s\n")

    try:
        print("Setting leverage...", set_leverage())
    except Exception:
        print("⚠️ leverage set failed:")
        traceback.print_exc()

    fil = get_filters()
    last_exit_ts = 0
    in_trail = False
    peak_pnl = 0.0
    trade_times = collections.deque(maxlen=MAX_TRADES_PER_HOUR * 2)
    consec_losses = 0
    session_pnl_usd = 0.0

    while True:
        try:
            # Throttle trades per hour
            now = time.time()
            while trade_times and now - trade_times[0] > 3600:
                trade_times.popleft()

            side, qty, entry = read_position()
            px = get_price()
            ts = time.strftime("%H:%M:%S")

            # Pull 1m data for context
            kl = get_klines("1m", 240)
            closes = [float(k[4]) for k in kl]
            highs  = [float(k[2]) for k in kl]
            lows   = [float(k[3]) for k in kl]
            c1, c2 = closes[-1], closes[-2]
            chg_last = (c1 - c2) / c2 * 100.0

            e50  = ema(closes[-(EMA_MID * 3):], EMA_MID)
            e200 = ema(closes[-(EMA_SLOW * 3):], EMA_SLOW)
            e9   = ema(closes[-(EMA_FAST * 3):], EMA_FAST)

            # ATR % of price
            a = atr(closes, highs, lows, 14)
            atr_pct = (a / c1 * 100.0) if a else 0.0

            # Short slope
            slope = (closes[-1] - closes[-SLOPE_LEN]) / closes[-SLOPE_LEN] * 100.0

            # ───── ACTIVE POSITION ─────
            if side == "LONG" and qty > 0:
                pnl = pnl_pct_on_margin_long(entry, px)
                peak_pnl = max(peak_pnl, pnl)
                print(f"[{ts}] Px {px:.6f} | LONG {qty:.6f} @ {entry:.6f} | PnL {pnl:+.2f}% | peak {peak_pnl:+.2f}%")

                if not in_trail and pnl >= TRAIL_ARM_PNL:
                    in_trail = True
                    print(f"🧷 Trailing armed at {pnl:.2f}% (peak reset)")

                if in_trail and (peak_pnl - pnl) >= TRAIL_GIVEUP:
                    print(f"🔧 Trail exit (drop {TRAIL_GIVEUP:.1f}%) → close")
                    close_position()
                    session_pnl_usd += (pnl / 100.0) * MARGIN_USD
                    last_exit_ts = time.time()
                    in_trail = False
                    peak_pnl = 0.0
                    consec_losses = 0 if pnl > 0 else (consec_losses + 1)
                    trade_times.append(now)
                    time.sleep(2)
                    continue

                if pnl >= TP_PNL:
                    print("🎯 TP hit → close")
                    close_position()
                    session_pnl_usd += (pnl / 100.0) * MARGIN_USD
                    last_exit_ts = time.time()
                    in_trail = False
                    peak_pnl = 0.0
                    consec_losses = 0
                    trade_times.append(now)
                    time.sleep(2)
                    continue

                if pnl <= -SL_PNL:
                    print("🛑 SL hit → close")
                    close_position()
                    session_pnl_usd += (pnl / 100.0) * MARGIN_USD
                    last_exit_ts = time.time()
                    in_trail = False
                    peak_pnl = 0.0
                    consec_losses += 1
                    trade_times.append(now)
                    time.sleep(2)
                    continue

            # ───── FLAT STATE ─────
            else:
                if len(trade_times) >= MAX_TRADES_PER_HOUR:
                    print(f"[{ts}] throttle: max {MAX_TRADES_PER_HOUR}/h reached → waiting 60s")
                    time.sleep(60)
                    continue
                if consec_losses >= MAX_CONSEC_LOSSES:
                    print(f"[{ts}] 🔒 max consecutive losses reached ({consec_losses}) → pausing 10m")
                    time.sleep(600)
                    consec_losses = 0
                    continue
                if -session_pnl_usd >= SESSION_DRAWDOWN_USD:
                    print(f"[{ts}] 🧯 session drawdown −${SESSION_DRAWDOWN_USD:.2f} hit → stopping session")
                    break

                dyn_cd = BASE_COOLDOWN * (
                    3 if consec_losses == 1 else
                    6 if consec_losses == 2 else
                    12 if consec_losses >= 3 else 1
                )
                since_exit = time.time() - last_exit_ts

                regime_ok = (e50 > e200)
                atr_ok = (atr_pct >= MIN_ATR_PCT)
                dip = (chg_last <= -PULLBACK_MIN)
                bounce = (c1 > e9) and (slope > 0)

                if since_exit < dyn_cd and not bounce:
                    print(f"[{ts}] flat | cooldown {dyn_cd - since_exit:.1f}s (loss_streak {consec_losses})")
                    time.sleep(POLL_SEC)
                    continue

                print(f"[{ts}] flat | regime {'OK' if regime_ok else 'NO'} | ATR {atr_pct:.2f}% | dip {dip} | bounce {bounce} | slope {slope:+.2f}%")

                if regime_ok and atr_ok and dip and bounce:
                    try:
                        q = calc_qty(px, fil)
                        print(f"🟢 BUY {q} (EMA50>{EMA_SLOW}, ATR {atr_pct:.2f}%, slope {slope:+.2f}%)")
                        res = place_market("BUY", q, reduce=False)
                        print(f"→ BUY ok | Qty {res.get('origQty', q)}")
                        peak_pnl = 0.0
                        in_trail = False
                        time.sleep(2)
                    except Exception:
                        print("❌ entry error:")
                        traceback.print_exc()

        except KeyboardInterrupt:
            print("\nManual stop → flattening.")
            close_position()
            break
        except Exception:
            print("⚠️ loop error:")
            traceback.print_exc()

        time.sleep(POLL_SEC)

# ───────── ENTRYPOINT ─────────
if __name__ == "__main__":
    try:
        print("Setting leverage/filters…")
        set_leverage()
        fil = get_filters()
        main()
    except Exception:
        traceback.print_exc()
