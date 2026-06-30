"""
config.py — Central Configuration File
========================================
All settings for the OTC Derivatives simulation are stored here.
This includes regulatory parameters for both Indian (RBI/SEBI) and
international (ISDA/Basel III) frameworks.

Think of this as the "rulebook" that all other modules refer to.
"""

# ─────────────────────────────────────────────
# SIMULATION SETTINGS
# ─────────────────────────────────────────────

SIMULATION_DAYS       = 30        # How many business days to simulate
NUM_TRADES            = 50        # Number of OTC trades to generate
RANDOM_SEED           = 42        # Makes random numbers reproducible
BASE_CURRENCY_INDIA   = "INR"     # Indian Rupee
BASE_CURRENCY_GLOBAL  = "USD"     # US Dollar (global benchmark)
DATABASE_PATH         = "data/otc_simulation.db"
EXCEL_OUTPUT_PATH     = "OTC_Derivatives_Report.xlsx"


# ─────────────────────────────────────────────
# INSTRUMENT TYPES
# ─────────────────────────────────────────────

INSTRUMENTS = {
    "IRS":   "Interest Rate Swap",         # Fixed vs floating interest payments
    "FX_FWD": "FX Forward",               # Lock in a future exchange rate
    "CDS":   "Credit Default Swap",        # Insurance against a bond defaulting
    "XCCY":  "Cross-Currency Swap",        # Swap cash flows in two currencies
}

# How many days each instrument type typically runs
INSTRUMENT_TENORS = {
    "IRS":    [180, 365, 730, 1825],       # 6mo, 1yr, 2yr, 5yr
    "FX_FWD": [10,  20,  30,  60,  90,  180],  # short tenors included so some settle within simulation window
    "CDS":    [365, 730, 1825, 3650],      # 1yr, 2yr, 5yr, 10yr
    "XCCY":   [365, 730, 1825],            # 1yr, 2yr, 5yr
}

# Typical notional ranges in INR (crores) and USD (millions)
NOTIONAL_RANGE_INR = (10_00_00_000, 500_00_00_000)   # ₹10 Cr to ₹500 Cr
NOTIONAL_RANGE_USD = (1_000_000,    50_000_000)        # $1M to $50M

# Currency distribution for trades
TRADE_CURRENCIES = {
    "INR": 0.45,   # 45% — domestic Indian trades
    "USD": 0.30,   # 30% — USD denominated
    "EUR": 0.15,   # 15% — Euro
    "GBP": 0.10,   # 10% — British Pound
}

# FX rates vs INR (approximate)
FX_RATES_TO_INR = {
    "INR": 1.0,
    "USD": 83.5,
    "EUR": 90.2,
    "GBP": 105.8,
}


# ─────────────────────────────────────────────
# COUNTERPARTIES
# ─────────────────────────────────────────────

# Indian counterparties — banks and financial institutions
INDIAN_COUNTERPARTIES = [
    {"id": "CP_HDFC",   "name": "HDFC Bank",                "type": "PSB",  "country": "IN", "rating": "AA"},
    {"id": "CP_SBI",    "name": "State Bank of India",       "type": "PSB",  "country": "IN", "rating": "AA"},
    {"id": "CP_ICICI",  "name": "ICICI Bank",                "type": "PVB",  "country": "IN", "rating": "AA"},
    {"id": "CP_AXIS",   "name": "Axis Bank",                 "type": "PVB",  "country": "IN", "rating": "A+"},
    {"id": "CP_KOTAK",  "name": "Kotak Mahindra Bank",       "type": "PVB",  "country": "IN", "rating": "A+"},
    {"id": "CP_CCIL",   "name": "CCIL (Central CCP)",        "type": "CCP",  "country": "IN", "rating": "AAA"},
]

# International / foreign counterparties
FOREIGN_COUNTERPARTIES = [
    {"id": "CP_JPM",    "name": "JPMorgan Chase",            "type": "G-SIB","country": "US", "rating": "A+"},
    {"id": "CP_CITI",   "name": "Citibank N.A.",             "type": "G-SIB","country": "US", "rating": "A"},
    {"id": "CP_DEUT",   "name": "Deutsche Bank AG",          "type": "G-SIB","country": "DE", "rating": "BBB+"},
    {"id": "CP_BARC",   "name": "Barclays Bank PLC",         "type": "G-SIB","country": "GB", "rating": "A"},
    {"id": "CP_HSBC",   "name": "HSBC Holdings",             "type": "G-SIB","country": "GB", "rating": "A+"},
    {"id": "CP_BNPP",   "name": "BNP Paribas",               "type": "G-SIB","country": "FR", "rating": "A+"},
]

ALL_COUNTERPARTIES = INDIAN_COUNTERPARTIES + FOREIGN_COUNTERPARTIES


# ─────────────────────────────────────────────
# TRADE STATES (Lifecycle States)
# ─────────────────────────────────────────────

# A trade moves through these states over its life
TRADE_STATES = {
    "PENDING":    "Trade submitted, awaiting confirmation",
    "CONFIRMED":  "Both parties confirmed",
    "ACTIVE":     "Trade is live, being valued daily",
    "EXPIRING":   "Trade is within 5 days of maturity",
    "MATURED":    "Trade has reached maturity date",
    "SETTLED":    "Final cash settlement completed",
    "CANCELLED":  "Trade cancelled before maturity",
    "DEFAULTED":  "Counterparty has defaulted",
}


# ─────────────────────────────────────────────
# 🇮🇳 INDIAN REGULATIONS — RBI / SEBI / CCIL
# ─────────────────────────────────────────────

INDIA_REGULATIONS = {
    "regulator":         "Reserve Bank of India (RBI) / SEBI",
    "framework":         "RBI Master Direction on Risk Management",
    "mandatory_clearing": ["IRS_INR", "OIS"],   # Products mandated for CCIL clearing
    "reporting_deadline": 30,                    # Minutes to report to CCIL trade repository

    # Minimum Transfer Amount before a margin call is issued
    "mta_inr": 50_00_000,       # ₹50 lakhs (₹0.5 Cr)

    # Eligible collateral types per RBI guidelines
    "eligible_collateral": {
        "INR_CASH":         {"haircut": 0.00, "description": "Indian Rupee cash"},
        "GOI_BONDS":        {"haircut": 0.02, "description": "Government of India bonds (haircut 2%)"},
        "T_BILLS":          {"haircut": 0.005,"description": "Treasury bills (haircut 0.5%)"},
        "SDL":              {"haircut": 0.03, "description": "State Development Loans (haircut 3%)"},
        "AAA_CORP_BONDS":   {"haircut": 0.05, "description": "AAA-rated corporate bonds (haircut 5%)"},
        "FX_USD":           {"haircut": 0.08, "description": "USD cash (FX risk haircut 8%)"},
    },

    # Margin thresholds
    "initial_margin_method":    "ISDA SIMM (RBI accepted)",
    "variation_margin_freq":    "Daily",
    "im_threshold_inr":         0,             # Zero threshold for IM (post full IM)

    # Capital requirements
    "credit_risk_weight":       1.0,           # 100% risk weight for unrated counterparties
    "ccil_risk_weight":         0.02,          # 2% risk weight for CCIL cleared trades

    # Reporting
    "trade_repository":         "CCIL Trade Repository",
    "reporting_currency":       "INR",
}

# ─────────────────────────────────────────────
# 🌍 INTERNATIONAL REGULATIONS — ISDA / Basel III
# ─────────────────────────────────────────────

INTERNATIONAL_REGULATIONS = {
    "framework":         "ISDA 2016 Credit Support Annex (VM) + ISDA 2018 (IM)",
    "us_framework":      "Dodd-Frank Act (CFTC/SEC regulated)",
    "eu_framework":      "EMIR (European Market Infrastructure Regulation)",

    # Minimum Transfer Amount (international standard)
    "mta_usd": 500_000,      # $500,000
    "mta_eur": 500_000,      # €500,000

    # ISDA SIMM (Standard Initial Margin Model) — simplified parameters
    "isda_simm": {
        "IRS":    {"delta_risk_weight": 0.0055, "vega_risk_weight": 0.16},
        "FX_FWD": {"delta_risk_weight": 0.011,  "vega_risk_weight": 0.21},
        "CDS":    {"delta_risk_weight": 0.0096, "vega_risk_weight": 0.27},
        "XCCY":   {"delta_risk_weight": 0.0055, "vega_risk_weight": 0.16},
    },

    # Eligible collateral types (Basel III / BCBS-IOSCO)
    "eligible_collateral": {
        "USD_CASH":        {"haircut": 0.00, "description": "US Dollar cash"},
        "EUR_CASH":        {"haircut": 0.00, "description": "Euro cash"},
        "US_TREASURIES":   {"haircut": 0.02, "description": "US Treasury bonds (haircut 2%)"},
        "EUR_GOVIES":      {"haircut": 0.04, "description": "European Govt bonds (haircut 4%)"},
        "UK_GILTS":        {"haircut": 0.03, "description": "UK Gilts (haircut 3%)"},
        "IG_CORP_BONDS":   {"haircut": 0.06, "description": "Investment-grade corporate bonds"},
        "EQUITIES":        {"haircut": 0.15, "description": "Listed equities (haircut 15%)"},
    },

    # Threshold amounts (below threshold, no IM needed)
    "im_threshold_usd":         50_000_000,    # $50M threshold for phase-in entities
    "im_threshold_eur":         50_000_000,    # €50M

    # Basel III capital requirements
    "sa_ccr_alpha":             1.4,           # Standardised Approach for CCR alpha factor
    "mpor_bilateral":           10,            # Margin Period of Risk (days) — bilateral trades
    "mpor_cleared":             5,             # MPOR for cleared trades
    "confidence_level":         0.99,          # 99% confidence for margin calculations
}


# ─────────────────────────────────────────────
# MTM VALUATION PARAMETERS
# ─────────────────────────────────────────────

# Base interest rates for valuation (simplified yield curves)
YIELD_CURVES = {
    "INR": {
        "overnight": 0.065,   # 6.5% RBI Repo rate
        "1Y":        0.068,
        "2Y":        0.071,
        "5Y":        0.073,
        "10Y":       0.075,
    },
    "USD": {
        "overnight": 0.053,   # 5.3% Fed Funds rate
        "1Y":        0.052,
        "2Y":        0.049,
        "5Y":        0.046,
        "10Y":       0.045,
    },
    "EUR": {
        "overnight": 0.04,    # 4.0% ECB rate
        "1Y":        0.039,
        "2Y":        0.036,
        "5Y":        0.033,
        "10Y":       0.032,
    },
}

# Daily volatility for MTM simulation (how much price moves each day)
DAILY_VOLATILITY = {
    "IRS":    0.0008,    # 0.08% daily vol — interest rates move slowly
    "FX_FWD": 0.006,     # 0.60% daily vol — FX moves more
    "CDS":    0.003,     # 0.30% daily vol — credit spreads
    "XCCY":   0.005,     # 0.50% daily vol — cross-currency
}


# ─────────────────────────────────────────────
# MARGIN CALL SETTINGS
# ─────────────────────────────────────────────

MARGIN_SETTINGS = {
    "vm_frequency":         "DAILY",        # Variation margin called every day
    "im_frequency":         "DAILY",        # Initial margin recalculated daily
    "settlement_currency":  "INR",          # Default settlement in INR for Indian trades
    "dispute_window_days":  1,              # Days to resolve a margin dispute
    "grace_period_hours":   2,              # Hours to meet a margin call
}


# ─────────────────────────────────────────────
# RECONCILIATION SETTINGS
# ─────────────────────────────────────────────

RECONCILIATION = {
    "target_accuracy":      0.998,       # 99.8% match target
    "tolerance_pct":        0.001,       # 0.1% tolerance on MTM differences
    "break_categories": [
        "MTM_MISMATCH",           # MTM value differs between parties
        "NOTIONAL_MISMATCH",      # Notional doesn't agree
        "DATE_MISMATCH",          # Maturity/start date differs
        "MISSING_TRADE",          # Trade on one side, not the other
        "STATUS_MISMATCH",        # Trade status disagrees
    ],
    "auto_resolve_threshold": 10_000,    # Auto-resolve breaks under ₹10,000
}
