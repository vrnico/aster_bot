# 🪙 ASTER LONG SCALPER  
**Smart, Always-In Long-Bias Scalping Bot for ASTER Futures**  
*by vrnico*  

---

## 📖 Overview

The **Dog Bowl Smart Long Scalper** is a fully-automated Python trading bot designed for  
**ASTERUSDT perpetual futures** on [AsterDex](https://asterdex.com).

It operates on a simple but proven philosophy:  
> “Markets rise more often than they fall — especially in reflexive crypto ecosystems.”

Rather than trying to predict both sides of the market, this bot stays **long-only**,  
optimizing for compounding, position recovery, and trend alignment.  
It hunts **micro-pullbacks inside broader uptrends**, taking advantage of ASTER’s volatility  
while minimizing emotional overtrading.


## 🧠 Strategy Breakdown

The scalper combines a handful of classic trading concepts into an  
intelligent, rule-based loop:

| Component | Description |
|------------|-------------|
| **Regime Filter** | Only trades when short-term trend (EMA-50) is above long-term trend (EMA-200). |
| **Dip → Bounce Logic** | Waits for a small pullback (–0.25%) and confirmation of price reclaiming EMA-9. |
| **ATR Filter** | Requires at least 0.15% volatility to avoid dead markets. |
| **PnL Targets** | Takes profit at +33% on margin (~+1.0% price) and stops out at –10% (~–0.3% price). |
| **Trailing Exit** | Arms a trailing stop once profit exceeds +20%, exits if it gives back 12%. |
| **Circuit Breakers** | Limits trades/hour, loss streaks, and session drawdown to preserve capital. |

Every few seconds, the bot checks the market and acts only when  
conditions align. When in a trade, it automatically manages trailing,  
take-profit, and stop-loss levels with dynamic cooldowns between entries.

---

## 📈 Why Long-Only?

Because this strategy isn’t trying to fight the tide.  
On ASTER, upward trends are where liquidity and volume concentrate —  
most short moves are whipsaws, not sustained breakdowns.  

By staying **long-biased**, the bot:  
- Keeps alignment with the dominant direction of funding and flow.  
- Recovers faster after stop-outs.  
- Avoids the psychological and mathematical traps of fading a reflexive token.  

In short:  
> “We don’t fade CZ.”  
If it’s a bear day, the bot will sit flat // that’s a feature, not a bug.

---

## ⚠️ Usage Notes

- This is an **experimental system** built for **educational and research use**.  
- Do **not** deploy it with funds you can’t afford to lose.  
- Always test on **testnet** before production use.  
- The bot depends on AsterDex API stability and accurate API credentials.  

---

## 💾 Requirements

- Python ≥ 3.10  
- Libraries:  
  ```
  pip install requests python-dotenv eth-account web3 eth-abi
  ```
- A `.env` file containing:
  ```
  ASTER_USER=<your_user_address>
  ASTER_SIGNER=<signer_address>
  ASTER_SIGNER_PRIVKEY=<private_key>
  ASTER_API_KEY=<api_key>
  ```

---

## 🪞 Example Output

```
[21:16:46] flat | regime OK | ATR 0.56% | dip True | bounce False | slope -0.00%
[21:21:02] flat | regime OK | ATR 0.49% | dip False | bounce True | slope +0.81%
🟢 BUY 285.47 (EMA50>EMA200, ATR 0.49%, slope +0.81%)
→ BUY ok | Qty 285.47
[21:23:10] Px 1.149200 | LONG 285.47 @ 1.147600 | PnL +0.93%
🎯 TP hit → close
```

---

## 🧭 Philosophy

This bot isn’t a casino script.  
It’s a small, disciplined automaton that thrives in micro-trends,  
trading like a scalpel — not a sledgehammer.  

If you respect its parameters, it respects your capital.  
If you run it into a bear day, well… you’re fading CZ.  
And no one fades CZ for long.

---

## 💰 Support the Project

If this code helps your trading or inspires your own builds,  
you can send a small token of appreciation here:

```
0x57325a6ba8cc52f1e16095e53218a89e00638674
```

Every contribution keeps the lights on for the next experiment.

---

## 🧾 License

MIT License — free for modification and personal use.  
Attribution appreciated, especially if you fork or remix it.

---
