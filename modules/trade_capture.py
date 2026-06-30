"""
trade_capture.py — Trade Capture Module
=========================================
This module handles booking (capturing) new OTC derivative trades.

In a real bank, the front office (traders) book trades into a system
called the "trade capture system". This module simulates that process.

It generates realistic sample trades across 4 instrument types,
with both Indian and international counterparties.
"""

import random
import logging
from datetime import datetime, timedelta

from config import (
    INSTRUMENTS, INSTRUMENT_TENORS, NOTIONAL_RANGE_INR, NOTIONAL_RANGE_USD,
    TRADE_CURRENCIES, FX_RATES_TO_INR, ALL_COUNTERPARTIES, INDIA_REGULATIONS,
    RANDOM_SEED, YIELD_CURVES
)

logger = logging.getLogger(__name__)
random.seed(RANDOM_SEED)


class TradeCapture:
    """
    Simulates the booking of OTC derivative trades.

    How it works:
    1. Randomly select an instrument type (IRS, FX_FWD, CDS, XCCY)
    2. Pick a counterparty (Indian or foreign)
    3. Generate realistic trade parameters
    4. Create a structured trade record

    In real life, this is a heavily automated but human-supervised process.
    """

    def __init__(self, db_manager):
        self.db = db_manager
        self.trade_counter = 0     # Used to generate unique trade IDs

    def generate_trade_id(self) -> str:
        """Generate a unique trade ID like TRD-00001."""
        self.trade_counter += 1
        return f"TRD-{self.trade_counter:05d}"

    def generate_trades(self, num_trades: int, start_date: datetime) -> list:
        """
        Generate a batch of simulated OTC trades.

        Args:
            num_trades: How many trades to create
            start_date: The simulation start date

        Returns:
            List of trade dictionaries
        """
        trades = []
        instrument_types = list(INSTRUMENTS.keys())
        weights = [0.35, 0.30, 0.20, 0.15]   # IRS most common, then FX, CDS, XCCY

        for i in range(num_trades):
            # Pick instrument type (weighted — IRS is most common in practice)
            instrument = random.choices(instrument_types, weights=weights, k=1)[0]

            # Pick currency
            currency = random.choices(
                list(TRADE_CURRENCIES.keys()),
                weights=list(TRADE_CURRENCIES.values()),
                k=1
            )[0]

            # Pick a counterparty
            cp = random.choice(ALL_COUNTERPARTIES)

            # Determine jurisdiction based on counterparty country
            jurisdiction = "INDIA" if cp["country"] == "IN" else "INTERNATIONAL"

            # Determine clearing venue
            if jurisdiction == "INDIA" and instrument in ("IRS", "OIS"):
                clearing_venue = "CCIL"       # Mandatory clearing in India
            elif jurisdiction == "INTERNATIONAL":
                clearing_venue = random.choice(["LCH", "CME", "BILATERAL"])
            else:
                clearing_venue = "BILATERAL"   # Most OTC is bilateral

            # Generate notional amount
            if currency == "INR":
                notional = round(random.uniform(*NOTIONAL_RANGE_INR), -4)  # Round to ₹10k
            else:
                notional = round(random.uniform(*NOTIONAL_RANGE_USD), -3)  # Round to $1k

            fx_rate = FX_RATES_TO_INR.get(currency, 1.0)
            notional_inr = notional * fx_rate

            # Trade dates
            trade_date = start_date + timedelta(days=random.randint(0, 5))
            start_dt = trade_date + timedelta(days=2)   # T+2 standard settlement

            # Tenor (how long the trade runs)
            tenor_days = random.choice(INSTRUMENT_TENORS[instrument])
            maturity_date = start_dt + timedelta(days=tenor_days)

            # Rates — based on instrument type
            fixed_rate, floating_rate = self._generate_rates(instrument, currency)

            # Direction — do we pay fixed or receive fixed?
            direction = random.choice(["PAY_FIXED", "RECEIVE_FIXED"])

            # Regulatory regime
            if jurisdiction == "INDIA":
                reg_regime = "RBI/SEBI"
            else:
                reg_regime = "ISDA/Dodd-Frank" if cp["country"] == "US" else "ISDA/EMIR"

            trade = {
                "trade_id":           self.generate_trade_id(),
                "instrument_type":    instrument,
                "instrument_name":    INSTRUMENTS[instrument],
                "trade_date":         trade_date.strftime("%Y-%m-%d"),
                "start_date":         start_dt.strftime("%Y-%m-%d"),
                "maturity_date":      maturity_date.strftime("%Y-%m-%d"),
                "notional":           notional,
                "currency":           currency,
                "notional_inr":       notional_inr,
                "fixed_rate":         fixed_rate,
                "floating_rate":      floating_rate,
                "fx_rate":            fx_rate,
                "direction":          direction,
                "counterparty_id":    cp["id"],
                "counterparty_name":  cp["name"],
                "counterparty_country": cp["country"],
                "jurisdiction":       jurisdiction,
                "clearing_venue":     clearing_venue,
                "status":             "ACTIVE",
                "regulatory_regime":  reg_regime,
            }

            trades.append(trade)
            self.db.insert_trade(trade)

            # Log a lifecycle "BOOKED" event
            self.db.insert_lifecycle_event({
                "trade_id":          trade["trade_id"],
                "event_date":        trade["trade_date"],
                "event_type":        "BOOKED",
                "from_status":       None,
                "to_status":         "ACTIVE",
                "event_description": (
                    f"Trade booked: {instrument} {currency} "
                    f"Notional={notional:,.0f} with {cp['name']}"
                ),
                "triggered_by": "SYSTEM",
            })

        logger.info(
            f"[TRADE CAPTURE] Booked {len(trades)} trades | "
            f"Indian CP: {sum(1 for t in trades if t['jurisdiction']=='INDIA')} | "
            f"International: {sum(1 for t in trades if t['jurisdiction']=='INTERNATIONAL')}"
        )
        return trades

    def _generate_rates(self, instrument: str, currency: str) -> tuple:
        """
        Generate realistic fixed and floating rates for a trade.

        For IRS: fixed rate is swap rate, floating is LIBOR/SOFR/MIBOR
        For FX_FWD: rates represent forward points
        For CDS: rates represent credit spread (in basis points)
        """
        curve = YIELD_CURVES.get(currency, YIELD_CURVES["USD"])

        if instrument == "IRS":
            # Fixed rate ~ 5Y swap rate + small adjustment
            base = curve.get("5Y", 0.06)
            fixed_rate = round(base + random.uniform(-0.005, 0.015), 4)
            floating_rate = round(curve.get("overnight", 0.05) + random.uniform(0, 0.002), 4)

        elif instrument == "FX_FWD":
            # Forward points (interest rate differential)
            fixed_rate = round(random.uniform(0.005, 0.025), 4)   # Forward premium/discount
            floating_rate = round(curve.get("1Y", 0.05), 4)        # Reference rate

        elif instrument == "CDS":
            # Credit spread in decimal (e.g., 0.015 = 150 bps)
            fixed_rate = round(random.uniform(0.005, 0.04), 4)     # CDS spread (protection fee)
            floating_rate = 0.0                                     # CDS has no floating leg

        elif instrument == "XCCY":
            # Cross-currency swap rates
            fixed_rate = round(curve.get("5Y", 0.06) + random.uniform(-0.003, 0.003), 4)
            floating_rate = round(YIELD_CURVES["USD"].get("5Y", 0.045) + random.uniform(-0.002, 0.002), 4)

        else:
            fixed_rate = 0.05
            floating_rate = 0.045

        return fixed_rate, floating_rate

    def get_trade_summary(self, trades: list) -> dict:
        """Print and return a summary of booked trades."""
        by_instrument = {}
        by_jurisdiction = {"INDIA": 0, "INTERNATIONAL": 0}
        total_notional_inr = 0

        for t in trades:
            inst = t["instrument_type"]
            by_instrument[inst] = by_instrument.get(inst, 0) + 1
            by_jurisdiction[t["jurisdiction"]] += 1
            total_notional_inr += t["notional_inr"]

        summary = {
            "total_trades":        len(trades),
            "by_instrument":       by_instrument,
            "by_jurisdiction":     by_jurisdiction,
            "total_notional_inr":  total_notional_inr,
        }
        return summary
