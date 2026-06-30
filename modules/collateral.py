"""
collateral.py — Collateral Management Module
=============================================
Collateral is assets (cash, bonds) that parties pledge to each other
to protect against default risk. When you have a losing trade, you post
collateral to your counterparty. When you win, you receive collateral.

Key concepts:
  - HAIRCUT: A reduction in the collateral value to account for price risk.
    e.g., A GOI bond worth ₹100 might only count as ₹98 (2% haircut).
  - ELIGIBLE COLLATERAL: Only certain asset types are accepted
    (RBI has its own list; ISDA/Basel has another).
  - REHYPOTHECATION: Reusing received collateral (complex, not simulated here)
  - SUBSTITUTION: Replacing one type of collateral with another

Indian regulations (RBI):
  - Eligible: INR cash, GOI bonds, T-bills, State Dev Loans, AAA bonds
  - Haircuts defined by RBI circular FMRD.DIRD.10/14.01.006/2019-20

International (ISDA/Basel III):
  - Eligible: Cash (USD/EUR/GBP), Sovereigns, IG corporate bonds, equities
  - BCBS-IOSCO margin framework haircuts
"""

import random
import logging
from datetime import datetime, timedelta

from config import (
    INDIA_REGULATIONS, INTERNATIONAL_REGULATIONS,
    FX_RATES_TO_INR, RANDOM_SEED
)

logger = logging.getLogger(__name__)
random.seed(RANDOM_SEED + 300)


class CollateralManager:
    """
    Manages the posting and receiving of collateral for margin calls.

    Workflow:
    1. A margin call is generated
    2. Collateral manager selects eligible collateral
    3. Applies the appropriate haircut
    4. Records the posting in the database
    5. Tracks active collateral balances
    """

    def __init__(self, db_manager):
        self.db = db_manager
        self.collateral_counter = 0
        # Track balance of collateral posted/received by counterparty
        self.collateral_balance = {}

    def generate_collateral_id(self) -> str:
        self.collateral_counter += 1
        return f"COL-{self.collateral_counter:06d}"

    def process_margin_calls(self, margin_calls: list) -> list:
        """
        For each margin call, allocate and post collateral.

        Args:
            margin_calls: List of margin call records from the DB

        Returns:
            List of collateral posting records
        """
        collateral_records = []

        for call in margin_calls:
            if call.get("status") != "MET":
                continue   # Only process calls that were met

            jurisdiction = self._infer_jurisdiction(call)
            amount_inr = call.get("call_amount_inr", 0)
            direction = call.get("direction", "CALL")

            # Select collateral type
            col_type, col_info = self._select_collateral_type(jurisdiction)

            # Calculate gross value needed (must post enough to cover after haircut)
            # If haircut is 5%, we need to post 100/95 = 1.053× the required amount
            haircut = col_info["haircut"]
            gross_value_inr = amount_inr / (1 - haircut) if haircut < 1 else amount_inr
            net_value_inr = gross_value_inr * (1 - haircut)   # What actually counts

            # Determine currency (cash collateral posted in trade currency)
            if col_type in ("INR_CASH", "GOI_BONDS", "T_BILLS", "SDL", "AAA_CORP_BONDS"):
                currency = "INR"
                gross_value = gross_value_inr
                net_value = net_value_inr
                eligible_under = "RBI"
            else:
                currency = col_type.split("_")[0]  # e.g. "USD_CASH" → "USD"
                fx = FX_RATES_TO_INR.get(currency, 83.5)
                gross_value = gross_value_inr / fx
                net_value = net_value_inr / fx
                eligible_under = "ISDA"

            # Posting direction: if call is "CALL" (we owe), we POST collateral
            # if call is "RETURN" (they owe), we RECEIVE collateral
            col_direction = "POSTED" if direction == "CALL" else "RECEIVED"

            record = {
                "collateral_id":    self.generate_collateral_id(),
                "trade_id":         call.get("trade_id"),
                "counterparty_id":  call.get("counterparty_id"),
                "posting_date":     call.get("call_date"),
                "collateral_type":  col_type,
                "collateral_desc":  col_info["description"],
                "gross_value":      round(gross_value, 2),
                "haircut_pct":      round(haircut * 100, 2),
                "net_value":        round(net_value, 2),
                "currency":         currency,
                "net_value_inr":    round(net_value_inr, 2),
                "direction":        col_direction,
                "status":           "ACTIVE",
                "return_date":      None,
                "eligible_under":   eligible_under,
            }

            collateral_records.append(record)
            self.db.insert_collateral(record)

            # Update running balance
            cp = call["counterparty_id"]
            if cp not in self.collateral_balance:
                self.collateral_balance[cp] = {"posted": 0, "received": 0}
            if col_direction == "POSTED":
                self.collateral_balance[cp]["posted"] += net_value_inr
            else:
                self.collateral_balance[cp]["received"] += net_value_inr

        logger.info(
            f"[COLLATERAL] Processed {len(collateral_records)} collateral postings | "
            f"Total Posted: ₹{sum(r['net_value_inr'] for r in collateral_records if r['direction']=='POSTED')/1e7:.1f}Cr"
        )
        return collateral_records

    def _select_collateral_type(self, jurisdiction: str) -> tuple:
        """
        Select an eligible collateral type and its haircut based on jurisdiction.

        Indian trades: prefer GOI bonds and INR cash (RBI eligible)
        International: prefer USD/EUR cash and US Treasuries (ISDA eligible)
        """
        if jurisdiction == "INDIA":
            eligible = INDIA_REGULATIONS["eligible_collateral"]
        else:
            eligible = INTERNATIONAL_REGULATIONS["eligible_collateral"]

        # Weighted selection: prefer lower-haircut (better quality) collateral
        types = list(eligible.keys())
        # Weight = 1/(haircut + 0.01) — lower haircut types preferred
        weights = [1.0 / (info["haircut"] + 0.01) for info in eligible.values()]
        total = sum(weights)
        weights = [w / total for w in weights]

        chosen_type = random.choices(types, weights=weights, k=1)[0]
        return chosen_type, eligible[chosen_type]

    def _infer_jurisdiction(self, call: dict) -> str:
        """Infer jurisdiction from regulatory_basis field of the margin call."""
        basis = call.get("regulatory_basis", "")
        if "RBI" in basis or "SEBI" in basis:
            return "INDIA"
        return "INTERNATIONAL"

    def get_collateral_summary(self) -> dict:
        """Return summary of all collateral activity."""
        records = self.db.get_collateral_summary()
        total_posted_inr = sum(
            r["total_net_inr"] for r in records if r["direction"] == "POSTED"
        )
        total_received_inr = sum(
            r["total_net_inr"] for r in records if r["direction"] == "RECEIVED"
        )
        net_exposure_inr = total_received_inr - total_posted_inr
        return {
            "total_posted_inr":   total_posted_inr,
            "total_received_inr": total_received_inr,
            "net_exposure_inr":   net_exposure_inr,
            "by_type":            records,
        }
