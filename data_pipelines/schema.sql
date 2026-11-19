-- GlobalBLOCS financial data warehouse: PostgreSQL 16 + TimescaleDB + pgvector
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS mkt; CREATE SCHEMA IF NOT EXISTS ref; CREATE SCHEMA IF NOT EXISTS research;
CREATE SCHEMA IF NOT EXISTS trading; CREATE SCHEMA IF NOT EXISTS ai;

-- Reference: point-in-time security master (keeps delisted names -> avoids survivorship bias)
CREATE TABLE ref.security (
  security_id   BIGSERIAL PRIMARY KEY,
  symbol        TEXT NOT NULL, cik INT, figi TEXT, name TEXT, exchange TEXT,
  asset_class   TEXT NOT NULL CHECK (asset_class IN ('equity','etf','option','index','fx','commodity')),
  sector TEXT, industry TEXT,
  listed_on DATE, delisted_on DATE,
  valid_from TIMESTAMPTZ NOT NULL DEFAULT now(), valid_to TIMESTAMPTZ
);
CREATE INDEX ON ref.security (symbol, valid_from);

-- Market data (hypertables). Every row records source and latency label.
CREATE TABLE mkt.bar (
  security_id BIGINT REFERENCES ref.security, ts TIMESTAMPTZ NOT NULL, interval TEXT NOT NULL,
  open NUMERIC(18,6), high NUMERIC(18,6), low NUMERIC(18,6), close NUMERIC(18,6), volume BIGINT, vwap NUMERIC(18,6),
  adj_factor NUMERIC(18,10) DEFAULT 1, source TEXT NOT NULL, latency TEXT NOT NULL CHECK (latency IN ('real-time','delayed-15m','end-of-day','simulated')),
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY (security_id, interval, ts)
);
SELECT create_hypertable('mkt.bar', 'ts', chunk_time_interval => INTERVAL '30 days');
ALTER TABLE mkt.bar SET (timescaledb.compress, timescaledb.compress_segmentby = 'security_id,interval');
SELECT add_compression_policy('mkt.bar', INTERVAL '60 days');

CREATE TABLE mkt.quote (security_id BIGINT, ts TIMESTAMPTZ NOT NULL, bid NUMERIC(18,6), ask NUMERIC(18,6),
  bid_size INT, ask_size INT, source TEXT NOT NULL, latency TEXT NOT NULL);
SELECT create_hypertable('mkt.quote', 'ts', chunk_time_interval => INTERVAL '1 day');

CREATE TABLE mkt.option_quote (underlying_id BIGINT, ts TIMESTAMPTZ NOT NULL, expiry DATE, strike NUMERIC(18,4), put_call CHAR(1),
  bid NUMERIC(18,6), ask NUMERIC(18,6), iv NUMERIC(10,6), delta NUMERIC(10,6), gamma NUMERIC(10,6), theta NUMERIC(10,6),
  vega NUMERIC(10,6), open_interest INT, source TEXT NOT NULL);
SELECT create_hypertable('mkt.option_quote', 'ts');

CREATE TABLE mkt.macro_series (series_id TEXT, obs_date DATE, value NUMERIC, vintage_date DATE NOT NULL, source TEXT NOT NULL,
  PRIMARY KEY (series_id, obs_date, vintage_date));   -- vintages => no look-ahead from revisions

-- Fundamentals as first reported (filing date = availability date)
CREATE TABLE ref.fundamental (security_id BIGINT REFERENCES ref.security, period_end DATE, fiscal_period TEXT,
  filed_at TIMESTAMPTZ NOT NULL, form TEXT, metric TEXT, value NUMERIC, unit TEXT, accession TEXT, source TEXT DEFAULT 'SEC EDGAR XBRL',
  PRIMARY KEY (security_id, period_end, metric, filed_at));
CREATE TABLE ref.corporate_action (security_id BIGINT, ex_date DATE, kind TEXT, ratio NUMERIC, cash_amount NUMERIC, source TEXT);
CREATE TABLE ref.insider_txn (security_id BIGINT, filed_at TIMESTAMPTZ, insider TEXT, role TEXT, code TEXT, shares NUMERIC, price NUMERIC, accession TEXT);
CREATE TABLE ref.institutional_holding (security_id BIGINT, report_date DATE, filer TEXT, shares NUMERIC, value NUMERIC, accession TEXT);
CREATE TABLE ref.short_interest (security_id BIGINT, settle_date DATE, short_shares NUMERIC, days_to_cover NUMERIC, borrow_fee NUMERIC, source TEXT);

-- Research
CREATE TABLE research.factor_score (security_id BIGINT, as_of DATE, factor TEXT, score NUMERIC, model_version TEXT,
  PRIMARY KEY (security_id, as_of, factor, model_version));
CREATE TABLE research.signal (signal_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), security_id BIGINT, strategy TEXT, classification TEXT,
  price NUMERIC, price_ts TIMESTAMPTZ, entry_low NUMERIC, entry_high NUMERIC, stop_loss NUMERIC, targets NUMERIC[], confidence NUMERIC,
  payload JSONB, data_source TEXT, data_latency TEXT, generated_at TIMESTAMPTZ DEFAULT now(), expires_at TIMESTAMPTZ);
CREATE TABLE research.model_registry (model_id TEXT, version TEXT, algo TEXT, params JSONB, train_start DATE, train_end DATE,
  metrics JSONB, artifact_uri TEXT, sha256 TEXT, created_at TIMESTAMPTZ DEFAULT now(), PRIMARY KEY (model_id, version));
CREATE TABLE research.backtest_run (run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), strategy JSONB, costs JSONB, universe TEXT[],
  start_date DATE, end_date DATE, metrics JSONB, code_commit TEXT, data_snapshot TEXT, created_by TEXT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE research.index_methodology (index_id TEXT, version INT, rules JSONB, rebalance TEXT, effective_from DATE, doc_uri TEXT,
  PRIMARY KEY (index_id, version));
CREATE TABLE research.index_level (index_id TEXT, version INT, ts DATE, level NUMERIC, total_return NUMERIC, PRIMARY KEY (index_id, version, ts));

-- Trading (brokerage data is read-only mirror + order lifecycle)
CREATE TABLE trading.broker_connection (conn_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), user_id TEXT, broker TEXT,
  token_ciphertext TEXT NOT NULL, scopes TEXT[] DEFAULT ARRAY['read'], trading_permission BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT now(), expires_at TIMESTAMPTZ);
CREATE TABLE trading.position_snapshot (conn_id UUID, account_id TEXT, as_of TIMESTAMPTZ, symbol TEXT, quantity NUMERIC,
  cost_basis NUMERIC, market_value NUMERIC, unrealized_pl NUMERIC, PRIMARY KEY (conn_id, account_id, as_of, symbol));
CREATE TABLE trading.order_proposal (proposal_id TEXT PRIMARY KEY, broker TEXT, payload JSONB, status TEXT,
  proposed_by TEXT, proposed_by_role TEXT, approved_by TEXT, approved_at TIMESTAMPTZ, submitted_at TIMESTAMPTZ, broker_response JSONB,
  risk_failures TEXT[], created_at TIMESTAMPTZ DEFAULT now(),
  CHECK (approved_by IS NULL OR proposed_by_role IS NOT NULL));
CREATE TABLE trading.audit_log (seq BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT now(), actor TEXT, action TEXT, detail JSONB,
  prev_hash TEXT, hash TEXT NOT NULL);
REVOKE UPDATE, DELETE ON trading.audit_log FROM PUBLIC;   -- append-only

-- AI / RAG
CREATE TABLE ai.document (doc_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), kind TEXT, source_uri TEXT, security_id BIGINT,
  published_at TIMESTAMPTZ, title TEXT);
CREATE TABLE ai.chunk (chunk_id BIGSERIAL PRIMARY KEY, doc_id UUID REFERENCES ai.document, text TEXT, embedding vector(1024));
CREATE INDEX ON ai.chunk USING hnsw (embedding vector_cosine_ops);
CREATE TABLE ai.agent_run (run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), agent TEXT, inputs JSONB, findings JSONB,
  evidence JSONB, sources TEXT[], started_at TIMESTAMPTZ DEFAULT now());

-- Roles (RBAC at the database layer)
CREATE ROLE gb_readonly; CREATE ROLE gb_research; CREATE ROLE gb_trader; CREATE ROLE gb_agent;
GRANT USAGE ON SCHEMA mkt, ref, research TO gb_readonly, gb_research, gb_trader, gb_agent;
GRANT SELECT ON ALL TABLES IN SCHEMA mkt, ref, research TO gb_readonly, gb_research, gb_trader, gb_agent;
GRANT INSERT ON research.signal, research.factor_score, research.backtest_run, ai.agent_run TO gb_research, gb_agent;
GRANT USAGE ON SCHEMA trading TO gb_trader, gb_agent;
GRANT INSERT ON trading.order_proposal TO gb_agent;                      -- agents may only propose
GRANT SELECT, INSERT, UPDATE ON trading.order_proposal TO gb_trader;
GRANT INSERT, SELECT ON trading.audit_log TO gb_trader, gb_agent;
