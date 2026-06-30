"""
margin_engine.py — Margin Call Generation Engine
==================================================
When an OTC trade moves against you (MTM becomes negative), you may need
to post additional collateral. This is called a MARGIN CALL.

Two types of margin:
  1. INITIAL MARGIN (IM): Posted upfront when trade is booked.
     Protects against potential future losses (like a security deposit).
     Calculated using ISDA SIMM model (simplified here).

  2. VARIATION MARGIN (VM): Posted daily to cover actual MTM losses.
     If trade MTM drops by ₹1 Cr overnight → counterparty calls ₹1 Cr VM.

Indian regulations (RBI/SEBI) and international (ISDA/Basel) have
different thresholds and eligible collateral rules.
"""

import random
import logging
import math
from datetime import datetime, timedelta

from config import (
    INDIA_REGULATIONS, INTERNATIONAL_REGULATIONS,
    FX_RATES_TO_INR, RANDOM_SEED, MARGIN_SETTINGS
)

logger = logging.getLogger(__name__)
random.seed(RANDOM_SEED + 200)


class MarginEngine:
    """
    Generates Initial Margin and Variation Margin calls
    for all active OTC trades.

    Key concepts:
    - IM = forward-looking protection (calculated using ISDA SIMM)
    - VM = backward-looking coverage (based on yesterday's MTM change)
    - MTA = Minimum Transfer Amount (don't call if amount is too small)
    - Netting = offset positive and negative MTMs within a counterparty
    """

    def __init__(self, db_manager):
        self.db = db_manager
        self.call_counter = 0

    def generate_call_id(self) -> str:
        """Generate unique margin call ID."""
        self.call_counter += 1
        return f"MC-{self.call_counter:06d}"

    def run_daily_margin_cycle(self, margin_date: datetime, trades: list,
                               valuations: list) -> dict:
        """
        Run the full daily margin cycle for all counterparties.

        Steps:
        1. Group trades by counterparty (netting)
        2. Calculate IM for each counterparty portfolio
        3. Calculate VM based on MTM changes
        4. Apply MTA threshold filters
        5. Generate margin call records

        Returns dict with summary of calls generated.
        """
        date_str = margin_date.strftime("%Y-%m-%d")

        # Build lookup: trade_id → latest MTM
        mtm_lookup = {v["trade_id"]: v for v in valuations}

        # Group trades by counterparty (for netting)
        cp_portfolios = {}
        for trade in trades:
            if trade["status"] not in ("ACTIVE", "EXPIRING"):
                continue
            cp_id = trade["counterparty_id"]
            if cp_id not in cp_portfolios:
                cp_portfolios[cp_id] = {
                    "trades": [],
                    "jurisdiction": trade["jurisdiction"],
                    "currency": trade["currency"],
                }
            cp_portfolios[cp_id]["trades"].append(trade)

        all_calls = []
        im_calls = 0
        vm_calls = 0
        total_im_inr = 0
        total_vm_inr = 0

        for cp_id, portfolio in cp_portfolios.items():
            trades_in_portfolio = portfolio["trades"]
            jurisdiction = portfolio["jurisdiction"]

            # ── VARIATION MARGIN ──────────────────────────────────
            # VM = net MTM change across all trades with this counterparty
            net_mtm_today = sum(
                mtm_lookup.get(t["trade_id"], {}).get("mtm_value_inr", 0)
                for t in trades_in_portfolio
            )
            net_delta = sum(
                mtm_lookup.get(t["trade_id"], {}).get("delta", 0) *
                mtm_lookup.get(t["trade_id"], {}).get("fx_rate_today", 1)
                for t in trades_in_portfolio
            )

            # Determine MTA (Minimum Transfer Amount)
            mta = self._get_mta(jurisdiction, portfolio["currency"])

            # Only issue a VM call if the change exceeds MTA
            if abs(net_delta) > mta:
                direction = "CALL" if net_delta < 0 else "RETURN"
                vm_call = self._create_margin_call(
                    cp_id=cp_id,
                    call_type="VARIATION_MARGIN",
                    amount_inr=abs(net_delta),
                    direction=direction,
                    call_date=date_str,
                    jurisdiction=jurisdiction,
                    trade_id=None,   # Portfolio-level, not trade-level
                )
                all_calls.append(vm_call)
                vm_calls += 1
                total_vm_inr += abs(net_delta)

            # ── INITIAL MARGIN ────────────────────────────────────
            # IM = forward-looking potential loss (ISDA SIMM)
            for trade in trades_in_portfolio:
                mtm_data = mtm_lookup.get(trade["trade_id"], {})
                if not mtm_data:
                    continue

                im_required = self._calculate_isda_simm(trade, mtm_data)

                if im_required > mta:
                    # 30% chance of issuing new IM call on any given day
                    # (In reality, IM is recalculated daily but calls only when threshold exceeded)
                    if random.random() < 0.30:
                        im_call = self._create_margin_call(
                            cp_id=cp_id,
                            call_type="INITIAL_MARGIN",
                            amount_inr=im_required,
                            direction="CALL",
                            call_date=date_str,
                            jurisdiction=jurisdiction,
                            trade_id=trade["trade_id"],
                        )
                        all_calls.append(im_call)
                        im_calls += 1
                        total_im_inr += im_required

        # Save calls to database
        for call in all_calls:
            self.db.insert_margin_call(call)

        logger.debug(
            f"[MARGIN] {date_str}: {im_calls} IM calls, {vm_calls} VM calls | "
            f"IM: ₹{total_im_inr/1e7:.1f}Cr, VM: ₹{total_vm_inr/1e7:.1f}Cr"
        )

        return {
            "date":          date_str,
            "total_calls":   len(all_calls),
            "im_calls":      im_calls,
            "vm_calls":      vm_calls,
            "total_im_inr":  total_im_inr,
            "total_vm_inr":  total_vm_inr,
        }

    def _calculate_isda_simm(self, trade: dict, mtm_data: dict) -> float:
        """
        Simplified ISDA SIMM (Standard Initial Margin Model).

        The real ISDA SIMM is complex — it uses sensitivities across
        multiple risk factors. Here we use a simplified proxy:

        IM ≈ Notional × Risk Weight × √(MPOR / 10)

        Where MPOR = Margin Period of Risk (how long to close out a position)
        Risk weight = how volatile is this instrument type
        """
        instrument = trade["instrument_type"]
        notional_inr = trade.get("notional_inr", 0)
        jurisdiction = trade.get("jurisdiction", "INTERNATIONAL")

        # ISDA SIMM delta risk weights (simplified)
        risk_weights = INTERNATIONAL_REGULATIONS["isda_simm"]
        rw = risk_weights.get(instrument, {}).get("delta_risk_weight", 0.01)

        # MPOR (Margin Period of Risk)
        # Bilateral: 10 days; Cleared: 5 days
        mpor = 5 if trade.get("clearing_venue") in ("CCIL", "LCH", "CME") else 10

        # Confidence factor (99% confidence = ~2.33 sigma)
        confidence = INTERNATIONAL_REGULATIONS.get("confidence_level", 0.99)
        z_score = 2.33  # 99% confidence interval

        # Simplified SIMM formula
        im = notional_inr * rw * z_score * math.sqrt(mpor / 10)

        # Add RBI buffer for Indian regulated trades (5% add-on)
        if jurisdiction == "INDIA":
            im *= 1.05

        return round(im, 2)

    def _get_mta(self, jurisdiction: str, currency: str) -> float:
        """
        Get the Minimum Transfer Amount (MTA) in INR.
        Below MTA, no margin call is issued (to avoid operational overhead).
        """
        if jurisdiction == "INDIA":
            return INDIA_REGULATIONS["mta_inr"]
        else:
            fx_rate = FX_RATES_TO_INR.get(currency, FX_RATES_TO_INR.get("USD", 83.5))
            mta_usd = INTERNATIONAL_REGULATIONS["mta_usd"]
            return mta_usd * fx_rate

    def _create_margin_call(self, cp_id, call_type, amount_inr, direction,
                            call_date, jurisdiction, trade_id=None) -> dict:
        """Build a margin call dictionary for database insertion."""
        # Settlement currency
        if jurisdiction == "INDIA":
            currency = "INR"
            amount_ccy = amount_inr
            reg_basis = "RBI Master Direction on Risk Management"
        else:
            currency = "USD"
            amount_ccy = amount_inr / FX_RATES_TO_INR["USD"]
            reg_basis = "ISDA 2016 Credit Support Annex"

        # Due date (same day for VM in India, next business day internationally)
        call_dt = datetime.strptime(call_date, "%Y-%m-%d")
        due_dt = call_dt + timedelta(days=1)
        due_date = due_dt.strftime("%Y-%m-%d")

        return {
            "call_id":          self.generate_call_id(),
            "trade_id":         trade_id,
            "counterparty_id":  cp_id,
            "call_date":        call_date,
            "margin_type":      call_type,
            "call_amount":      round(amount_ccy, 2),
            "call_currency":    currency,
            "call_amount_inr":  round(amount_inr, 2),
            "direction":        direction,
            "status":           random.choices(
                                    ["MET", "PENDING", "DISPUTED"],
                                    weights=[0.85, 0.10, 0.05]
                                )[0],
            "due_date":         due_date,
            "regulatory_basis": reg_basis,
        }
