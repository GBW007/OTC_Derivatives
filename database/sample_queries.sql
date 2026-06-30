-- ============================================================
-- sample_queries.sql — Useful Analytical Queries
-- ============================================================
-- Run these against data/otc_simulation.db (after running main.py)
-- using any SQLite client, e.g.:
--   sqlite3 data/otc_simulation.db < database/sample_queries.sql
--
-- Or open the .db file in "DB Browser for SQLite" (free GUI tool)
-- and paste these queries into the "Execute SQL" tab.
-- ============================================================


-- 1. Portfolio overview: trades by instrument and status
SELECT instrument_type, status, COUNT(*) AS trade_count,
       ROUND(SUM(notional_inr)/1e7, 2) AS total_notional_cr
FROM trades
GROUP BY instrument_type, status
ORDER BY total_notional_cr DESC;


-- 2. Top 10 trades by absolute MTM exposure (latest valuation date)
SELECT t.trade_id, t.instrument_type, t.counterparty_name,
       m.mtm_value_inr, t.currency
FROM mtm_valuations m
JOIN trades t ON m.trade_id = t.trade_id
WHERE m.valuation_date = (SELECT MAX(valuation_date) FROM mtm_valuations)
ORDER BY ABS(m.mtm_value_inr) DESC
LIMIT 10;


-- 3. Margin calls summary by type and status
SELECT margin_type, status, COUNT(*) AS num_calls,
       ROUND(SUM(call_amount_inr)/1e7, 2) AS total_amount_cr
FROM margin_calls
GROUP BY margin_type, status
ORDER BY margin_type, total_amount_cr DESC;


-- 4. Counterparty exposure ranking (net MTM by counterparty)
SELECT t.counterparty_id, t.counterparty_name, t.jurisdiction,
       COUNT(DISTINCT t.trade_id) AS num_trades,
       ROUND(SUM(m.mtm_value_inr)/1e7, 2) AS net_mtm_exposure_cr
FROM trades t
JOIN mtm_valuations m ON t.trade_id = m.trade_id
WHERE m.valuation_date = (SELECT MAX(valuation_date) FROM mtm_valuations)
GROUP BY t.counterparty_id
ORDER BY ABS(net_mtm_exposure_cr) DESC;


-- 5. Collateral haircut analysis — which collateral types are used most
SELECT collateral_type, direction, COUNT(*) AS postings,
       ROUND(AVG(haircut_pct), 2) AS avg_haircut_pct,
       ROUND(SUM(net_value_inr)/1e7, 2) AS total_net_value_cr
FROM collateral
GROUP BY collateral_type, direction
ORDER BY total_net_value_cr DESC;


-- 6. Reconciliation breaks by category
SELECT break_category, COUNT(*) AS num_breaks,
       SUM(resolved) AS resolved_count,
       ROUND(AVG(ABS(difference_pct)), 4) AS avg_diff_pct
FROM reconciliation
WHERE status IN ('BREAK', 'AUTO_RESOLVED')
GROUP BY break_category
ORDER BY num_breaks DESC;


-- 7. Daily reconciliation accuracy trend
SELECT recon_date,
       COUNT(*) AS total_records,
       SUM(CASE WHEN status = 'MATCHED' THEN 1 ELSE 0 END) AS matched,
       SUM(CASE WHEN status = 'AUTO_RESOLVED' THEN 1 ELSE 0 END) AS auto_resolved,
       SUM(CASE WHEN status = 'BREAK' THEN 1 ELSE 0 END) AS breaks,
       ROUND(100.0 * SUM(CASE WHEN status IN ('MATCHED','AUTO_RESOLVED') THEN 1 ELSE 0 END)
             / COUNT(*), 2) AS accuracy_pct
FROM reconciliation
GROUP BY recon_date
ORDER BY recon_date;


-- 8. Lifecycle event timeline for a specific trade (change TRD-00001 as needed)
SELECT event_date, event_type, from_status, to_status, event_description
FROM lifecycle_events
WHERE trade_id = 'TRD-00001'
ORDER BY event_date;


-- 9. Settlement summary — who paid whom
SELECT payer, receiver, COUNT(*) AS num_settlements,
       ROUND(SUM(settlement_amount_inr)/1e7, 2) AS total_settled_cr,
       legal_basis
FROM settlements
GROUP BY payer, receiver, legal_basis
ORDER BY total_settled_cr DESC;


-- 10. Regulatory comparison: India vs International margin requirements
SELECT
    CASE WHEN regulatory_basis LIKE '%RBI%' THEN 'India (RBI/SEBI)'
         ELSE 'International (ISDA/Basel)' END AS regime,
    margin_type,
    COUNT(*) AS num_calls,
    ROUND(SUM(call_amount_inr)/1e7, 2) AS total_margin_cr,
    ROUND(AVG(call_amount_inr)/1e5, 2) AS avg_margin_lakh
FROM margin_calls
GROUP BY regime, margin_type
ORDER BY regime, total_margin_cr DESC;
