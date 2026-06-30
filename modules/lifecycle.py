"""
lifecycle.py — Trade Lifecycle Processor
==========================================
An OTC trade doesn't just sit still — it moves through several states:

  ACTIVE → EXPIRING (when < 5 days to maturity) → MATURED → SETTLED

This module handles:
  1. Detecting trades approaching expiry
  2. Processing expired trades
  3. Calculating final cash settlement amounts
  4. Recording settlement events

Settlement in OTC derivatives:
  - For most OTC trades, at expiry one party pays the other the net amount
  - This is called CASH SETTLEMENT (the alternative is physical delivery)
  - Close-out netting: if multiple trades exist with same counterparty,
    all MTMs are netted and a single payment is made (reduces credit risk)

Indian context (RBI Guidelines):
  - IRS in INR: Cash settled in INR
  - FX Forwards: Can be cash or physical settled
  - CCIL cleared: CCIL guarantees settlement

International (ISDA Master Agreement):
  - Section 6(e): Close-out netting on default/termination
  - Fallback provisions for market disruption
"""

import logging
import random
from datetime import datetime, timedelta

from config import FX_RATES_TO_INR, RANDOM_SEED

logger = logging.getLogger(__name__)
random.seed(RANDOM_SEED + 400)


class LifecycleProcessor:
    """
    Processes trade lifecycle events: expiry, maturity, settlement.

    The processor runs daily to:
    1. Flag trades within 5 days of maturity as "EXPIRING"
    2. Process trades that have hit their maturity date
    3. Calculate and record final settlement
    """

    def __init__(self, db_manager):
        self.db = db_manager
        self.settlement_counter = 0

    def generate_settlement_id(self) -> str:
        self.settlement_counter += 1
        return f"SETL-{self.settlement_counter:06d}"

    def run_daily_lifecycle(self, process_date: datetime, trades: list,
                            mtm_lookup: dict) -> dict:
        """
        Process lifecycle events for all trades on a given date.

        Args:
            process_date: Date being processed
            trades:       All active trades
            mtm_lookup:   Dict of {trade_id: latest_mtm_record}

        Returns:
            Summary of lifecycle events processed
        """
        date_str = process_date.strftime("%Y-%m-%d")
        expiring_count = 0
        settled_count = 0
        events = []

        for trade in trades:
            trade_id = trade["trade_id"]
            current_status = trade["status"]
            maturity = datetime.strptime(trade["maturity_date"], "%Y-%m-%d")
            days_to_maturity = (maturity - process_date).days

            # ── Check if trade is approaching maturity ────────────
            if current_status == "ACTIVE" and 0 < days_to_maturity <= 5:
                # Flag as EXPIRING
                self.db.update_trade_status(trade_id, "EXPIRING")
                self.db.insert_lifecycle_event({
                    "trade_id":          trade_id,
                    "event_date":        date_str,
                    "event_type":        "EXPIRY_WARNING",
                    "from_status":       "ACTIVE",
                    "to_status":         "EXPIRING",
                    "event_description": f"Trade maturing in {days_to_maturity} day(s). Settlement preparations initiated.",
                    "triggered_by":      "SYSTEM",
                })
                expiring_count += 1
                events.append({"type": "EXPIRY_WARNING", "trade_id": trade_id})

            # ── Process matured trades ────────────────────────────
            elif current_status in ("ACTIVE", "EXPIRING") and days_to_maturity <= 0:
                # Trade has matured — calculate settlement
                settlement = self._process_settlement(trade, process_date, mtm_lookup)

                if settlement:
                    # Update trade status to SETTLED
                    self.db.update_trade_status(trade_id, "SETTLED")
                    self.db.insert_lifecycle_event({
                        "trade_id":          trade_id,
                        "event_date":        date_str,
                        "event_type":        "SETTLED",
                        "from_status":       current_status,
                        "to_status":         "SETTLED",
                        "event_description": (
                            f"Trade settled. Settlement amount: "
                            f"{trade['currency']} {settlement['settlement_amount']:,.0f} "
                            f"(₹{settlement['settlement_amount_inr']:,.0f}). "
                            f"Payer: {settlement['payer']}"
                        ),
                        "triggered_by": "SYSTEM",
                    })
                    settled_count += 1
                    events.append({"type": "SETTLED", "trade_id": trade_id})

        if expiring_count > 0 or settled_count > 0:
            logger.debug(
                f"[LIFECYCLE] {date_str}: {expiring_count} trades expiring, "
                f"{settled_count} trades settled"
            )

        return {
            "date":            date_str,
            "expiring":        expiring_count,
            "settled":         settled_count,
            "events":          events,
        }

    def _process_settlement(self, trade: dict, settlement_date: datetime,
                            mtm_lookup: dict) -> dict:
        """
        Calculate and record the final cash settlement for a matured trade.

        For most OTC trades:
        - If final MTM > 0 (we're in-the-money) → counterparty pays us
        - If final MTM < 0 (we're out-of-the-money) → we pay counterparty
        - Close-out netting is applied across all trades with same counterparty

        Legal basis:
        - Indian trades: RBI Guidelines on Risk Management, FEMA
        - International: ISDA Master Agreement Section 6(e)
        """
        date_str = settlement_date.strftime("%Y-%m-%d")
        trade_id = trade["trade_id"]

        # Get the final MTM value
        mtm_record = mtm_lookup.get(trade_id, {})
        if not mtm_record:
            mtm_record = self.db.get_latest_mtm(trade_id)

        final_mtm_inr = mtm_record.get("mtm_value_inr", 0) if mtm_record else 0
        final_mtm_ccy = mtm_record.get("mtm_value", 0) if mtm_record else 0

        fx_rate = FX_RATES_TO_INR.get(trade["currency"], 1.0)

        # Settlement amount = absolute value of final MTM
        settlement_amount_ccy = abs(final_mtm_ccy)
        settlement_amount_inr = abs(final_mtm_inr)

        # Determine who pays whom
        # If MTM is positive → counterparty owes us → they pay
        # If MTM is negative → we owe counterparty → we pay
        our_entity = "OUR_BANK"
        cp_name = trade.get("counterparty_id", "COUNTERPARTY")

        if final_mtm_inr >= 0:
            payer = cp_name
            receiver = our_entity
        else:
            payer = our_entity
            receiver = cp_name

        # Determine legal basis
        if trade.get("jurisdiction") == "INDIA":
            legal_basis = "RBI Guidelines / FEMA 1999"
        else:
            legal_basis = "ISDA Master Agreement 2002 — Section 6(e)"

        # Check if netting was applied (applicable when multiple trades with same CP)
        netting_applied = 1 if trade.get("clearing_venue") in ("CCIL", "LCH", "CME") else 0

        settlement_record = {
            "settlement_id":          self.generate_settlement_id(),
            "trade_id":               trade_id,
            "settlement_date":        date_str,
            "settlement_type":        "CASH",
            "final_mtm":              round(final_mtm_inr, 2),
            "settlement_amount":      round(settlement_amount_ccy, 2),
            "settlement_currency":    trade["currency"],
            "settlement_amount_inr":  round(settlement_amount_inr, 2),
            "payer":                  payer,
            "receiver":               receiver,
            "payment_status":         "COMPLETED",
            "netting_applied":        netting_applied,
            "legal_basis":            legal_basis,
        }

        self.db.insert_settlement(settlement_record)
        return settlement_record

    def get_lifecycle_summary(self, trades: list) -> dict:
        """Return breakdown of trades by lifecycle status."""
        status_counts = {}
        for trade in trades:
            s = trade.get("status", "UNKNOWN")
            status_counts[s] = status_counts.get(s, 0) + 1

        settlements = self.db.get_settlements()
        total_settled_inr = sum(s["settlement_amount_inr"] for s in settlements)

        return {
            "status_breakdown":     status_counts,
            "total_settlements":    len(settlements),
            "total_settled_inr":    total_settled_inr,
        }
