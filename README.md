# SMART TRADER AI v0.2 — research only

Research laboratory with paper trades. Only public Bybit linear USDT data; NO private API calls, Demo orders, or real execution.

- Screens all public USDT linear tickers every 6h, deep-scans top 12 liquid/spread-qualified pairs (MAX_RESEARCH_SYMBOLS up to 16, MIN_TURNOVER_USDT default 20M).
- Pulls up to 3000 closed 15m bars per pair. Tests six rule families (24 configurations), 24 threshold trials, CatBoost, and LightGBM with chronological validation and holdout, modeled trading costs, and a conservative test gate.
- Runs market monitoring and daily model review in separate workers; stores research history, model results, and virtual balance in existing PostgreSQL schema smart_trader_ai when DATABASE_URL is set.
- Paper-only risk: $1000 starting account, no leverage, <=25% notional per position, max 3% day loss and 15% drawdown. A rejection means no trade; no guarantees.
- Public GET /api/status and dashboard. Logs and errors visible in Render.
- Original research guide: TRADING_PLAYBOOK_RU.md. The guide is for humans; models only train on explicit numeric features and implemented hypotheses.

## Run
pip install -r requirements.txt
python -m unittest discover -p 'test_*.py'
python app.py

## Caution
This is NOT self-improving general AI or all Bybit instruments. Rolling reuse of validation/holdout can overfit; paper fills on 15m bars are approximations, and a paid Render plan does not guarantee zero downtime. CFD/gold, spot-funding arbitrage, tick/order-book data, Bybit Demo order execution and autonomous invention of code are future work and NOT implemented. Never put credentials in GitHub.
