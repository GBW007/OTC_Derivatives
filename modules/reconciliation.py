"""
reconciliation.py — Position Reconciliation Engine
====================================================
In the real world, both you AND your counterparty keep records of each trade.
Every day, you compare your records with theirs. Any differences are called "BREAKS".

Why does this matter?
  - A large unexplained difference could mean a booking error
  - Breaks can lead to wrong margin calls (which causes disputes)
  - Regulators require daily reconciliation (EMIR Article 11, SEBI OTC circular)
  - CCIL requires all trades be reconciled before noon each day (Indian market)

Types of breaks:
  1. MTM_MISMATCH      — Our valuation differs from theirs
  2. NOTIONAL_MISMATCH — We disagree on the trade size
  3. DATE_MISMATCH     — Different maturity or start dates
  4. MISSING_TRADE     — We see the trade; they don't (or vice versa)
  5. STATUS_MISMATCH   — We say ACTIVE; they say TERMINATED

Our target: 99.8% accuracy (2 breaks per 1,000 records)
"""

import random
import logging
from datetime import datetime

from config import RECONCILIATION, FX_RATES_TO_INR, RANDOM_SEED

logger = logging.getLogger(__name__)
random.seed(RANDOM_SEED + 500)


class ReconciliationEngine:
    """
    Simulates daily position reconciliation between our books
    and counterparty records.

    Process:
    1. Get our MTM values from the database
    2. Simulate what the counterparty would report (with small differences)
    3. Compare record by record
    4. Classify each as MATCHED, BREAK, or AUTO_RESOLVED
    5. Achieve 99.8% accuracy overall

    The 0.2% breaks represent:
      - Timing differences (different end-of-day cut-off times)
      - Model differences (we use different pricing models)
      - Holiday calendar differences (different country holidays)
      - Data entry errors
    """

    def __init__(self, db_manager):
        self.db = db_manager
        self.target_accuracy = RECONCILIATION["target_accuracy"]   # 0.998
        self.tolerance_pct = RECONCILIATION["tolerance_pct"]       # 0.001 = 0.1%
        self.auto_resolve_threshold = RECONCILIATION["auto_resolve_threshold"]

    def run_reconciliation(self, recon_date: datetime, valuations: list) -> dict:
        """
        Run daily reconciliation for all valuations on a given date.

        Args:
            recon_date:   Date being reconciled
            valuations:   List of our MTM valuations

        Returns:
            Reconciliation result summary
        """
        date_str = recon_date.strftime("%Y-%m-%d")

        if not valuations:
            return {"date": date_str, "total": 0, "matched": 0, "breaks": 0, "accuracy": 100.0}

        total = len(valuations)
        records = []

        # Determine how many breaks to simulate (to hit 99.8% accuracy)
        # 0.2% of records = 2 breaks per 1,000 records.
        # Per day with ~40 records: expected breaks = 40 * 0.002 = 0.08
        # So a break should only occur on ~8% of days.
        expected_breaks = total * (1 - self.target_accuracy) * 0.7
        # Poisson-style: only generate a break if a random draw says so
        num_breaks = 1 if random.random() < expected_breaks else 0
        break_indices = set(random.sample(range(total), num_breaks) if num_breaks > 0 else [])

        matched = 0
        breaks = 0
        auto_resolved = 0

        for i, val in enumerate(valuations):
            our_mtm = val.get("mtm_value_inr", 0)
            trade_id = val.get("trade_id")

            if i in break_indices:
                # ── Simulate a BREAK ──────────────────────────────
                break_type = random.choice(RECONCILIATION["break_categories"])
                cp_mtm, diff, diff_pct, desc = self._simulate_break(our_mtm, break_type)

                # Check if auto-resolvable (small difference)
                if abs(diff) <= self.auto_resolve_threshold:
                    status = "AUTO_RESOLVED"
                    resolved = 1
                    resolution = f"Auto-resolved: difference ₹{abs(diff):,.0f} below threshold ₹{self.auto_resolve_threshold:,}"
                    auto_resolved += 1
                else:
                    status = "BREAK"
                    resolved = 0
                    resolution = None
                    breaks += 1

                record = {
                    "recon_date":         date_str,
                    "trade_id":           trade_id,
                    "counterparty_id":    self._get_cp_for_trade(trade_id),
                    "our_mtm":            round(our_mtm, 2),
                    "counterparty_mtm":   round(cp_mtm, 2),
                    "difference":         round(diff, 2),
                    "difference_pct":     round(diff_pct, 4),
                    "status":             status,
                    "break_category":     break_type,
                    "break_description":  desc,
                    "resolved":           resolved,
                    "resolution_notes":   resolution,
                }
            else:
                # ── Perfect MATCH ─────────────────────────────────
                # Counterparty agrees (within a tiny rounding tolerance)
                noise = our_mtm * random.uniform(-0.00005, 0.00005)   # 0.005% noise
                cp_mtm = our_mtm + noise
                diff = cp_mtm - our_mtm
                diff_pct = (diff / our_mtm * 100) if our_mtm != 0 else 0

                record = {
                    "recon_date":         date_str,
                    "trade_id":           trade_id,
                    "counterparty_id":    self._get_cp_for_trade(trade_id),
                    "our_mtm":            round(our_mtm, 2),
                    "counterparty_mtm":   round(cp_mtm, 2),
                    "difference":         round(diff, 2),
                    "difference_pct":     round(diff_pct, 6),
                    "status":             "MATCHED",
                    "break_category":     None,
                    "break_description":  None,
                    "resolved":           1,
                    "resolution_notes":   "Positions agree within tolerance",
                }
                matched += 1

            records.append(record)

        # Bulk-save all records
        self.db.insert_reconciliation_batch(records)

        # Final accuracy (matched + auto-resolved)
        effective_matched = matched + auto_resolved
        accuracy = (effective_matched / total) * 100

        result = {
            "date":          date_str,
            "total":         total,
            "matched":       matched,
            "auto_resolved": auto_resolved,
            "breaks":        breaks,
            "accuracy_pct":  round(accuracy, 2),
        }

        logger.debug(
            f"[RECON] {date_str}: {total} records | {matched} matched | "
            f"{auto_resolved} auto-resolved | {breaks} breaks | {accuracy:.2f}% accuracy"
        )
        return result

    def _simulate_break(self, our_mtm: float, break_type: str) -> tuple:
        """
        Simulate a counterparty's differing MTM value for a break scenario.

        Returns: (counterparty_mtm, difference, difference_pct, description)
        """
        if break_type == "MTM_MISMATCH":
            # Counterparty's model gives different value (2-5% difference)
            diff_pct = random.uniform(0.02, 0.05) * random.choice([-1, 1])
            cp_mtm = our_mtm * (1 + diff_pct)
            diff = cp_mtm - our_mtm
            desc = (
                f"MTM mismatch: Our model ₹{our_mtm:,.0f} vs CP model ₹{cp_mtm:,.0f}. "
                f"Likely cause: different discount curve or fixing date."
            )

        elif break_type == "NOTIONAL_MISMATCH":
            # Counterparty has different notional (booking error)
            notional_diff = random.uniform(0.01, 0.03) * random.choice([-1, 1])
            cp_mtm = our_mtm * (1 + notional_diff)
            diff = cp_mtm - our_mtm
            diff_pct = notional_diff
            desc = "Notional mismatch: suspected booking error. Pending ops team review."

        elif break_type == "DATE_MISMATCH":
            # Different maturity date causes slightly different MTM
            date_diff_days = random.randint(1, 5) * random.choice([-1, 1])
            diff = our_mtm * 0.001 * date_diff_days   # ~0.1% per day difference
            cp_mtm = our_mtm + diff
            diff_pct = (diff / our_mtm * 100) if our_mtm != 0 else 0
            desc = f"Date mismatch: CP maturity differs by {abs(date_diff_days)} business day(s)."

        elif break_type == "MISSING_TRADE":
            # Trade not on counterparty's books
            cp_mtm = 0.0
            diff = -our_mtm
            diff_pct = -100.0
            desc = "Trade missing from counterparty's system. Confirmation pending."

        elif break_type == "STATUS_MISMATCH":
            # Counterparty shows trade as terminated
            cp_mtm = 0.0
            diff = -our_mtm
            diff_pct = -100.0
            desc = "Status mismatch: Our books show ACTIVE; CP shows TERMINATED/SETTLED."

        else:
            cp_mtm = our_mtm
            diff = 0.0
            diff_pct = 0.0
            desc = "Unknown break type"

        diff_pct = (diff / our_mtm * 100) if our_mtm != 0 else 0
        return cp_mtm, diff, diff_pct, desc

    def _get_cp_for_trade(self, trade_id: str) -> str:
        """Look up the counterparty for a trade from the database."""
        trades = self.db.get_all_trades()
        for t in trades:
            if t["trade_id"] == trade_id:
                return t["counterparty_id"]
        return "UNKNOWN"

    def get_final_accuracy_report(self) -> dict:
        """
        Generate the final reconciliation accuracy report.
        This is what you'd present to risk management / regulators.
        """
        summary = self.db.get_reconciliation_summary()
        total = summary.get("total", 0)
        matched = summary.get("MATCHED", 0)
        auto_resolved = summary.get("AUTO_RESOLVED", 0)
        breaks = summary.get("BREAK", 0)

        effective_matched = matched + auto_resolved
        accuracy = (effective_matched / total * 100) if total > 0 else 0

        return {
            "total_records":          total,
            "matched":                matched,
            "auto_resolved":          auto_resolved,
            "open_breaks":            breaks,
            "accuracy_pct":           round(accuracy, 2),
            "target_pct":             self.target_accuracy * 100,
            "target_met":             accuracy >= self.target_accuracy * 100,
            "regulatory_compliant":   accuracy >= 99.0,  # EMIR requires 99%+
        }
