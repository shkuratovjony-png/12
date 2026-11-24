# SMART TRADER AI — paper research v0.1

Isolated branch and service, no private exchange API, no real orders. Target 10% daily is a research aspiration, not a profit claim or optimization mandate. Risk takes precedence.

## Implemented
- Bybit public linear 15m candles: BTC, ETH, SOL, initially up to 3,000 bars per symbol, capped at 6,000. Incremental refresh.
- Optuna 24 rule trials per symbol, LightGBM and CatBoost classification; chronological train/validation/holdout with one-label gap; promotion only on positive validation and holdout with minimum trade counts.
- Backtest with modeled 0.14% round-trip costs, stop approximation, no leverage, 25% of portfolio notional. Bar-level tests are approximate.
- Prospective paper entries only after fresh closed bars and approved models, at observed bid/ask. One position at a time, stop observed on polling, daily loss 3%, drawdown 15%. Sleep/outages can cause worse losses or missed opportunities.
- Daily per-symbol retraining while awake; bounded memory; public read-only dashboard.
- Postgres: supply internal DATABASE_URL in Render Environment, startup creates only schema smart_trader_ai and its state table. Never commit secrets. Otherwise uses temporary SQLite, which is lost on instance replacement or free-service spin-down. No durable persistence promised without Postgres.
- Research history and trades stored; no access to other schemas needed by code. Shared DB user should ideally be replaced by a dedicated restricted role.

## Start
pip install -r requirements.txt
python -m unittest test_risk
python app.py

## Not yet implemented
Year-scale archives, gold/spot/funding/order-book historical feeds, additional strategy families, 100 simultaneous forward paper portfolios, full opportunity attribution, continuous monitoring on free Render, real trading, independent forward performance qualification. Model selection is not a guarantee of positive returns. Repeated rolling tests can overfit; forward evidence is essential. Do not enable real execution based on this prototype.
