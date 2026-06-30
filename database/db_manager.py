"""
db_manager.py — Database Manager
==================================
Handles all database operations: creating tables, inserting records,
and running queries. Uses SQLite — a simple file-based database.

This is the "data layer" of the application — all other modules
call these functions to save and retrieve data.
"""

import sqlite3
import os
import logging
from config import DATABASE_PATH

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages the SQLite database for the OTC simulation.

    Usage:
        db = DatabaseManager()
        db.insert_trade(trade_dict)
        trades = db.get_all_trades()
        db.close()
    """

    def __init__(self, db_path: str = DATABASE_PATH):
        """Connect to (or create) the SQLite database and set up tables."""
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row   # Rows behave like dicts
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")  # Better performance
        self._create_tables()
        logger.info(f"Database connected: {db_path}")

    def _create_tables(self):
        """Read schema.sql and create all tables."""
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, "r") as f:
            schema_sql = f.read()
        self.conn.executescript(schema_sql)
        self.conn.commit()

    # ── TRADES ─────────────────────────────────────────────────

    def insert_trade(self, trade: dict) -> bool:
        """Insert a new trade record into the database."""
        sql = """
        INSERT OR IGNORE INTO trades (
            trade_id, instrument_type, instrument_name, trade_date, start_date,
            maturity_date, notional, currency, notional_inr, fixed_rate,
            floating_rate, fx_rate, direction, counterparty_id, counterparty_name,
            counterparty_country, jurisdiction, clearing_venue, status,
            regulatory_regime
        ) VALUES (
            :trade_id, :instrument_type, :instrument_name, :trade_date, :start_date,
            :maturity_date, :notional, :currency, :notional_inr, :fixed_rate,
            :floating_rate, :fx_rate, :direction, :counterparty_id, :counterparty_name,
            :counterparty_country, :jurisdiction, :clearing_venue, :status,
            :regulatory_regime
        )
        """
        self.conn.execute(sql, trade)
        self.conn.commit()
        return True

    def get_all_trades(self) -> list:
        """Return all trades as a list of dicts."""
        cursor = self.conn.execute("SELECT * FROM trades")
        return [dict(row) for row in cursor.fetchall()]

    def get_active_trades(self) -> list:
        """Return only trades that are currently active."""
        cursor = self.conn.execute(
            "SELECT * FROM trades WHERE status IN ('ACTIVE', 'EXPIRING', 'CONFIRMED')"
        )
        return [dict(row) for row in cursor.fetchall()]

    def update_trade_status(self, trade_id: str, new_status: str):
        """Change the lifecycle status of a trade."""
        self.conn.execute(
            "UPDATE trades SET status = ? WHERE trade_id = ?",
            (new_status, trade_id)
        )
        self.conn.commit()

    # ── MTM VALUATIONS ─────────────────────────────────────────

    def insert_mtm(self, records: list):
        """Bulk-insert MTM valuation records (faster than one at a time)."""
        sql = """
        INSERT INTO mtm_valuations (
            trade_id, valuation_date, mtm_value, mtm_value_inr,
            delta, pnl_daily, fx_rate_today, discount_factor, valuation_method
        ) VALUES (
            :trade_id, :valuation_date, :mtm_value, :mtm_value_inr,
            :delta, :pnl_daily, :fx_rate_today, :discount_factor, :valuation_method
        )
        """
        self.conn.executemany(sql, records)
        self.conn.commit()

    def get_mtm_by_date(self, valuation_date: str) -> list:
        """Get all MTM valuations for a specific date."""
        cursor = self.conn.execute(
            "SELECT * FROM mtm_valuations WHERE valuation_date = ?",
            (valuation_date,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_latest_mtm(self, trade_id: str) -> dict:
        """Get the most recent MTM for a specific trade."""
        cursor = self.conn.execute(
            """SELECT * FROM mtm_valuations
               WHERE trade_id = ?
               ORDER BY valuation_date DESC LIMIT 1""",
            (trade_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else {}

    # ── MARGIN CALLS ───────────────────────────────────────────

    def insert_margin_call(self, call: dict):
        """Insert a new margin call record."""
        sql = """
        INSERT OR IGNORE INTO margin_calls (
            call_id, trade_id, counterparty_id, call_date, margin_type,
            call_amount, call_currency, call_amount_inr, direction,
            status, due_date, regulatory_basis
        ) VALUES (
            :call_id, :trade_id, :counterparty_id, :call_date, :margin_type,
            :call_amount, :call_currency, :call_amount_inr, :direction,
            :status, :due_date, :regulatory_basis
        )
        """
        self.conn.execute(sql, call)
        self.conn.commit()

    def get_margin_calls(self) -> list:
        """Return all margin calls."""
        cursor = self.conn.execute("SELECT * FROM margin_calls ORDER BY call_date")
        return [dict(row) for row in cursor.fetchall()]

    def update_margin_call_status(self, call_id: str, status: str, settled_amount: float = None):
        """Mark a margin call as MET or FAILED."""
        if settled_amount is not None:
            self.conn.execute(
                "UPDATE margin_calls SET status=?, settled_amount=? WHERE call_id=?",
                (status, settled_amount, call_id)
            )
        else:
            self.conn.execute(
                "UPDATE margin_calls SET status=? WHERE call_id=?",
                (status, call_id)
            )
        self.conn.commit()

    # ── COLLATERAL ─────────────────────────────────────────────

    def insert_collateral(self, record: dict):
        """Insert a new collateral posting."""
        sql = """
        INSERT OR IGNORE INTO collateral (
            collateral_id, trade_id, counterparty_id, posting_date,
            collateral_type, collateral_desc, gross_value, haircut_pct,
            net_value, currency, net_value_inr, direction, status, eligible_under
        ) VALUES (
            :collateral_id, :trade_id, :counterparty_id, :posting_date,
            :collateral_type, :collateral_desc, :gross_value, :haircut_pct,
            :net_value, :currency, :net_value_inr, :direction, :status, :eligible_under
        )
        """
        self.conn.execute(sql, record)
        self.conn.commit()

    def get_collateral_summary(self) -> list:
        """Summarise collateral by direction and type."""
        cursor = self.conn.execute("""
            SELECT direction, collateral_type, COUNT(*) as count,
                   SUM(gross_value) as total_gross, SUM(net_value_inr) as total_net_inr
            FROM collateral
            GROUP BY direction, collateral_type
            ORDER BY direction, total_net_inr DESC
        """)
        return [dict(row) for row in cursor.fetchall()]

    # ── LIFECYCLE EVENTS ───────────────────────────────────────

    def insert_lifecycle_event(self, event: dict):
        """Log a lifecycle state change."""
        sql = """
        INSERT INTO lifecycle_events (
            trade_id, event_date, event_type, from_status,
            to_status, event_description, triggered_by
        ) VALUES (
            :trade_id, :event_date, :event_type, :from_status,
            :to_status, :event_description, :triggered_by
        )
        """
        self.conn.execute(sql, event)
        self.conn.commit()

    # ── SETTLEMENTS ────────────────────────────────────────────

    def insert_settlement(self, record: dict):
        """Record a final cash settlement."""
        sql = """
        INSERT OR IGNORE INTO settlements (
            settlement_id, trade_id, settlement_date, settlement_type,
            final_mtm, settlement_amount, settlement_currency,
            settlement_amount_inr, payer, receiver, payment_status,
            netting_applied, legal_basis
        ) VALUES (
            :settlement_id, :trade_id, :settlement_date, :settlement_type,
            :final_mtm, :settlement_amount, :settlement_currency,
            :settlement_amount_inr, :payer, :receiver, :payment_status,
            :netting_applied, :legal_basis
        )
        """
        self.conn.execute(sql, record)
        self.conn.commit()

    def get_settlements(self) -> list:
        cursor = self.conn.execute("SELECT * FROM settlements ORDER BY settlement_date")
        return [dict(row) for row in cursor.fetchall()]

    # ── RECONCILIATION ─────────────────────────────────────────

    def insert_reconciliation_batch(self, records: list):
        """Bulk-insert reconciliation results."""
        sql = """
        INSERT INTO reconciliation (
            recon_date, trade_id, counterparty_id, our_mtm, counterparty_mtm,
            difference, difference_pct, status, break_category,
            break_description, resolved, resolution_notes
        ) VALUES (
            :recon_date, :trade_id, :counterparty_id, :our_mtm, :counterparty_mtm,
            :difference, :difference_pct, :status, :break_category,
            :break_description, :resolved, :resolution_notes
        )
        """
        self.conn.executemany(sql, records)
        self.conn.commit()

    def get_reconciliation_summary(self) -> dict:
        """Return high-level stats on reconciliation results."""
        cursor = self.conn.execute("""
            SELECT status, COUNT(*) as count
            FROM reconciliation
            GROUP BY status
        """)
        rows = cursor.fetchall()
        summary = {row["status"]: row["count"] for row in rows}
        total = sum(summary.values())
        matched = summary.get("MATCHED", 0) + summary.get("AUTO_RESOLVED", 0)
        accuracy = (matched / total * 100) if total > 0 else 0
        summary["total"] = total
        summary["accuracy_pct"] = round(accuracy, 2)
        return summary

    # ── UTILITY ────────────────────────────────────────────────

    def get_portfolio_summary(self) -> dict:
        """Return a high-level summary of the whole portfolio."""
        trades_cursor = self.conn.execute("""
            SELECT status, instrument_type, COUNT(*) as count,
                   SUM(notional_inr) as total_notional_inr
            FROM trades
            GROUP BY status, instrument_type
        """)
        mtm_cursor = self.conn.execute("""
            SELECT SUM(mtm_value_inr) as total_mtm,
                   SUM(pnl_daily)     as total_pnl
            FROM mtm_valuations
            WHERE valuation_date = (SELECT MAX(valuation_date) FROM mtm_valuations)
        """)
        margin_cursor = self.conn.execute("""
            SELECT margin_type, SUM(call_amount_inr) as total_inr
            FROM margin_calls
            GROUP BY margin_type
        """)
        return {
            "trades":  [dict(r) for r in trades_cursor.fetchall()],
            "mtm":     dict(mtm_cursor.fetchone() or {}),
            "margins": [dict(r) for r in margin_cursor.fetchall()],
        }

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed.")
