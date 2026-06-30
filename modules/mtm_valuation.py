"""
mtm_valuation.py — Daily Mark-to-Market Valuation Engine
==========================================================
MTM (Mark-to-Market) means: "what is this trade worth RIGHT NOW
at today's market prices?"

Every day, the bank revalues all its trades. If a trade that was
initially worth ₹0 is now worth +₹10 Cr, that's a gain. If it's
worth -₹5 Cr, that's a loss. These daily changes drive margin calls.

Simplified pricing:
  - IRS:    Based on interest rate changes vs trade inception rate
  - FX_FWD: Based on FX rate movement since trade date
  - CDS:    Based on credit spread widening/tightening
  - XCCY:   Combination of interest rate and FX moves
"""

import random
import math
import logging
from datetime import datetime, timedelta

from config import (
    DAILY_VOLATILITY, FX_RATES_TO_INR, YIELD_CURVES, RANDOM_SEED
)

logger = logging.getLogger(__name__)
random.seed(RANDOM_SEED + 100)   # Different seed from trade capture


class MTMValuationEngine:
    """
    Calculates daily MTM values for all active trades.

    The core idea:
        MTM = Present Value of future cash flows we expect to receive
              MINUS Present value of future cash flows we expect to pay

    A positive MTM means the trade is "in the money" — the counterparty
    effectively owes us money. A negative MTM means we owe them.
    """

    def __init__(self, db_manager):
        self.db = db_manager
        # Store simulated market rates for each day
        self._market_rates = {}
        self._fx_rates = {}

    def run_daily_valuation(self, valuation_date: datetime, trades: list) -> list:
        """
        Value all active trades for a given date.

        Args:
            valuation_date: The date to value trades on
            trades:         List of trade dictionaries

        Returns:
            List of MTM valuation records
        """
        date_str = valuation_date.strftime("%Y-%m-%d")

        # Simulate today's market data (rates and FX)
        market_data = self._generate_market_data(valuation_date)

        valuations = []
        for trade in trades:
            # Skip settled or cancelled trades
            if trade["status"] in ("SETTLED", "CANCELLED", "DEFAULTED"):
                continue

            # Check if trade is still live on this date
            maturity = datetime.strptime(trade["maturity_date"], "%Y-%m-%d")
            start = datetime.strptime(trade["start_date"], "%Y-%m-%d")
            if valuation_date > maturity or valuation_date < start:
                continue

            # Calculate MTM
            mtm_value = self._calculate_mtm(trade, valuation_date, market_data)
            fx_today = market_data["fx_rates"].get(trade["currency"], 1.0)
            mtm_inr = mtm_value * fx_today

            # Get yesterday's MTM to calculate daily P&L
            prev_mtm = self.db.get_latest_mtm(trade["trade_id"])
            prev_value = prev_mtm.get("mtm_value", 0) if prev_mtm else 0
            delta = mtm_value - prev_value
            pnl_daily = delta * fx_today

            # Time remaining (used for discount factor)
            days_remaining = (maturity - valuation_date).days
            discount_factor = self._discount_factor(
                days_remaining, trade["currency"], market_data
            )

            record = {
                "trade_id":         trade["trade_id"],
                "valuation_date":   date_str,
                "mtm_value":        round(mtm_value, 2),
                "mtm_value_inr":    round(mtm_inr, 2),
                "delta":            round(delta, 2),
                "pnl_daily":        round(pnl_daily, 2),
                "fx_rate_today":    round(fx_today, 4),
                "discount_factor":  round(discount_factor, 6),
                "valuation_method": "MARK_TO_MARKET",
            }
            valuations.append(record)

        # Save to database
        if valuations:
            self.db.insert_mtm(valuations)

        logger.debug(f"[MTM] {date_str}: Valued {len(valuations)} trades")
        return valuations

    def _calculate_mtm(self, trade: dict, today: datetime, market_data: dict) -> float:
        """
        Calculate the MTM value for a single trade.

        Returns MTM in the trade's currency (not INR).
        Positive = we are owed money; Negative = we owe money.
        """
        instrument = trade["instrument_type"]
        notional = trade["notional"]
        currency = trade["currency"]

        maturity = datetime.strptime(trade["maturity_date"], "%Y-%m-%d")
        start = datetime.strptime(trade["start_date"], "%Y-%m-%d")
        total_days = max((maturity - start).days, 1)
        elapsed_days = (today - start).days
        time_fraction = elapsed_days / total_days  # How far through the trade are we

        # Today's market rate for this currency
        market_rate = market_data["rates"].get(currency, 0.05)

        if instrument == "IRS":
            mtm = self._mtm_irs(trade, market_rate, total_days, elapsed_days, notional)

        elif instrument == "FX_FWD":
            spot_rate = market_data["fx_rates"].get(currency, FX_RATES_TO_INR.get(currency, 1.0))
            mtm = self._mtm_fx_forward(trade, spot_rate, total_days, elapsed_days, notional)

        elif instrument == "CDS":
            credit_spread = market_data["credit_spreads"].get(currency, 0.015)
            mtm = self._mtm_cds(trade, credit_spread, total_days, elapsed_days, notional)

        elif instrument == "XCCY":
            usd_rate = market_data["rates"].get("USD", 0.045)
            mtm = self._mtm_xccy(trade, market_rate, usd_rate, total_days, elapsed_days, notional)

        else:
            mtm = 0.0

        # Flip sign based on direction (PAY_FIXED means rates rising is bad for us)
        if trade.get("direction") == "PAY_FIXED" and instrument == "IRS":
            mtm = -mtm

        return mtm

    def _mtm_irs(self, trade, market_rate, total_days, elapsed_days, notional) -> float:
        """
        IRS MTM Simplified:
        If market rate > our fixed rate → receiving fixed is valuable (positive MTM)
        If market rate < our fixed rate → paying fixed is cheaper (positive if pay-fixed)

        Formula: MTM ≈ Notional × (market_rate - fixed_rate) × remaining_years
        """
        fixed_rate = trade.get("fixed_rate", 0.06)
        years_remaining = (total_days - elapsed_days) / 365
        rate_diff = market_rate - fixed_rate
        mtm = notional * rate_diff * years_remaining
        return round(mtm, 2)

    def _mtm_fx_forward(self, trade, spot_rate_today, total_days, elapsed_days, notional) -> float:
        """
        FX Forward MTM:
        We locked in an exchange rate. If the spot moved in our favour, positive MTM.

        formula: MTM = Notional × (InceptionFxRate - TodayFxRate) / InceptionFxRate
        Adjusted for time elapsed.
        """
        inception_fx = trade.get("fx_rate", spot_rate_today)
        if inception_fx == 0:
            return 0.0
        rate_move = (inception_fx - spot_rate_today) / inception_fx
        # Scale by time elapsed (more time elapsed = more crystallised P&L)
        time_factor = elapsed_days / max(total_days, 1)
        mtm = notional * rate_move * time_factor
        return round(mtm, 2)

    def _mtm_cds(self, trade, current_spread, total_days, elapsed_days, notional) -> float:
        """
        CDS MTM:
        If credit spreads widened → protection seller loses (negative MTM for seller)
        If spreads tightened → protection buyer's hedge is worth less

        MTM ≈ Notional × (current_spread - original_spread) × years_remaining
        """
        original_spread = trade.get("fixed_rate", 0.015)
        years_remaining = (total_days - elapsed_days) / 365
        spread_change = current_spread - original_spread
        mtm = notional * spread_change * years_remaining
        return round(mtm, 2)

    def _mtm_xccy(self, trade, local_rate, usd_rate, total_days, elapsed_days, notional) -> float:
        """
        Cross-Currency Swap MTM:
        Combination of interest rate differentials and FX moves.
        """
        fixed_rate = trade.get("fixed_rate", 0.06)
        floating_rate = trade.get("floating_rate", 0.045)
        years_remaining = (total_days - elapsed_days) / 365
        # Spread between current differential and locked-in rates
        current_diff = local_rate - usd_rate
        locked_diff = fixed_rate - floating_rate
        mtm = notional * (current_diff - locked_diff) * years_remaining
        return round(mtm, 2)

    def _discount_factor(self, days_remaining: int, currency: str, market_data: dict) -> float:
        """
        Discount Factor = how much is ₹1 received in the future worth today?
        DF = 1 / (1 + rate × time)
        """
        rate = market_data["rates"].get(currency, 0.05)
        years = days_remaining / 365
        if years <= 0:
            return 1.0
        return 1.0 / (1.0 + rate * years)

    def _generate_market_data(self, date: datetime) -> dict:
        """
        Simulate daily market data: interest rates, FX rates, credit spreads.
        In real life this comes from Bloomberg/Reuters market data feeds.

        We simulate random daily moves around base levels.
        """
        date_str = date.strftime("%Y-%m-%d")
        if date_str in self._market_rates:
            return self._market_rates[date_str]

        # Simulate interest rate moves (small daily changes)
        rates = {}
        for currency, curve in YIELD_CURVES.items():
            base = curve.get("5Y", 0.05)
            # Random walk: add small noise each day
            shock = random.gauss(0, DAILY_VOLATILITY.get("IRS", 0.0008))
            rates[currency] = max(0.001, base + shock)

        # Simulate FX rates (slightly different from inception rates)
        fx_rates = {}
        for currency, base_rate in FX_RATES_TO_INR.items():
            if currency == "INR":
                fx_rates[currency] = 1.0
                continue
            shock = random.gauss(0, DAILY_VOLATILITY.get("FX_FWD", 0.006) * base_rate)
            fx_rates[currency] = max(0.01, base_rate + shock)

        # Simulate credit spreads
        credit_spreads = {
            "INR": round(random.gauss(0.015, 0.002), 4),
            "USD": round(random.gauss(0.012, 0.002), 4),
            "EUR": round(random.gauss(0.018, 0.003), 4),
            "GBP": round(random.gauss(0.020, 0.003), 4),
        }

        data = {
            "rates": rates,
            "fx_rates": fx_rates,
            "credit_spreads": credit_spreads,
            "date": date_str,
        }
        self._market_rates[date_str] = data
        return data

    def get_portfolio_mtm(self, valuation_date: str) -> dict:
        """Get total portfolio MTM for a given date."""
        valuations = self.db.get_mtm_by_date(valuation_date)
        total_mtm_inr = sum(v["mtm_value_inr"] for v in valuations)
        total_pnl = sum(v["pnl_daily"] for v in valuations)
        return {
            "date":              valuation_date,
            "num_trades":        len(valuations),
            "total_mtm_inr":     total_mtm_inr,
            "total_pnl_inr":     total_pnl,
            "positive_mtm":      sum(1 for v in valuations if v["mtm_value_inr"] > 0),
            "negative_mtm":      sum(1 for v in valuations if v["mtm_value_inr"] < 0),
        }
