# OTC Derivatives Lifecycle & Margin Simulation

A Python-based simulation of an **end-to-end OTC (Over-The-Counter) Derivative Trade Lifecycle**, modelled after real-world clearing bank workflows. Covers both **Indian regulations (SEBI/RBI/CCIL)** and **international standards (ISDA/Basel III/Dodd-Frank/EMIR)**.

---

## What Is This Project?

When banks trade financial contracts (like interest rate swaps, currency forwards, or credit default swaps) **directly with each other** — without going through a stock exchange — that's called an OTC derivative trade. This project simulates what happens to such a trade from the moment it's created until it's settled or expires.

---

## Key Features

| Feature | Description |
|---|---|
| **Trade Capture** | Book IRS, FX Forward, CDS, and Currency Swap trades |
| **MTM Valuation** | Daily Mark-to-Market pricing (how much is the trade worth today?) |
| **Margin Engine** | Calculates Initial Margin (IM) and Variation Margin (VM) per ISDA SIMM |
| **Collateral Management** | Tracks collateral posted/received with Basel III haircuts |
| **Lifecycle Processing** | Manages trade states: ACTIVE → EXPIRING → SETTLED |
| **Reconciliation Engine** | Matches our records with counterparty records — **99.8% accuracy** |
| **Excel Reports** | Auto-generates a multi-sheet Excel workbook with charts |
| **SQL Database** | SQLite database stores all trade, margin, and collateral data |
| **Dual Regulation** | Supports both Indian (RBI/SEBI/CCIL) and global (ISDA/Basel/EMIR) rules |

---

## Regulatory Coverage

### 🇮🇳 Indian Regulations
- **SEBI**: Securities and Exchange Board of India — OTC derivative reporting requirements
- **RBI**: Reserve Bank of India — Eligible collateral types, haircut norms, FX derivative guidelines
- **CCIL**: Clearing Corporation of India Ltd — Central counterparty clearing for eligible trades
- **FEMA**: Foreign Exchange Management Act — Cross-border trade constraints

### 🌍 International Regulations
- **ISDA**: International Swaps and Derivatives Association — Master Agreement, SIMM model for margin
- **Basel III/IV**: Capital and margin requirements for non-cleared derivatives
- **Dodd-Frank (US)**: Mandatory clearing thresholds and reporting requirements
- **EMIR (EU)**: European Market Infrastructure Regulation — bilateral margin rules

---

## Project Structure

```
otc_derivatives/
│
├── main.py                  # 🚀 Run this — orchestrates the whole simulation
├── config.py                # ⚙️  All settings: regulatory params, haircuts, thresholds
├── requirements.txt         # 📦 Python packages needed
│
├── database/
│   ├── schema.sql           # 📊 SQL table definitions (what data we store)
│   └── db_manager.py        # 🗄️  Database create/read/write operations
│
├── modules/
│   ├── trade_capture.py     # 📝 Book new OTC trades
│   ├── mtm_valuation.py     # 💹 Daily Mark-to-Market valuation
│   ├── margin_engine.py     # 📉 Margin call calculations
│   ├── collateral.py        # 🏦 Collateral tracking and haircuts
│   ├── lifecycle.py         # ⏱️  Trade state management and settlement
│   └── reconciliation.py   # ✅ Position matching and break detection
│
├── reports/
│   └── excel_reporter.py    # 📋 Excel workbook generation
│
└── data/
    └── otc_simulation.db    # 🗃️  Auto-generated SQLite database (after running)
```

---

## How to Run

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Full Simulation
```bash
python main.py
```

### 3. View the Output
- **Console**: Step-by-step logs of the simulation
- **Excel file**: `OTC_Derivatives_Report.xlsx` — generated in the project root (a sample is already included in this repo so you can preview it immediately)
- **SQLite DB**: `data/otc_simulation.db` — browse with [DB Browser for SQLite](https://sqlitebrowser.org/) (free) or run the queries in `database/sample_queries.sql`

---

## Instruments Simulated

| Instrument | Full Name | Use Case |
|---|---|---|
| **IRS** | Interest Rate Swap | Hedge floating rate exposure |
| **FX Fwd** | FX Forward | Lock in future exchange rate |
| **CDS** | Credit Default Swap | Insure against credit default |
| **XCCY** | Cross-Currency Swap | Swap principal + interest in two currencies |

---

## Sample Output

```
[TRADE CAPTURE]    Booked 50 OTC trades across 4 instrument types
[MTM VALUATION]    Processed 30 days × 50 trades = 1,500 valuations
[MARGIN ENGINE]    Generated 87 margin calls (IM + VM)
[COLLATERAL MGR]   Allocated ₹ 4.2 Cr / $ 5.1M in collateral
[LIFECYCLE]        12 trades expired, 8 cash-settled
[RECONCILIATION]   Matched 998/1000 positions — Accuracy: 99.80%
[EXCEL REPORT]     Saved → OTC_Derivatives_Report.xlsx
```

---

## Tech Stack

- **Python 3.8+** — Core simulation logic
- **SQLite + SQL** — Trade and margin data storage
- **Pandas + NumPy** — Data processing and calculations
- **OpenPyXL** — Excel report generation
- **Logging** — Audit trail for all events

---

## Glossary (for Beginners)

| Term | Meaning |
|---|---|
| **OTC** | Over-The-Counter — trades done directly between two parties, not on an exchange |
| **MTM** | Mark-to-Market — the current market value of a trade (changes daily) |
| **Margin** | Money deposited as security in case a trade loses value |
| **Initial Margin (IM)** | Upfront margin posted when a trade is opened |
| **Variation Margin (VM)** | Daily margin adjustments based on MTM changes |
| **Collateral** | Assets (cash, bonds) pledged to cover potential losses |
| **Haircut** | A percentage reduction applied to collateral value (e.g., a bond worth ₹100 might only count as ₹95) |
| **Reconciliation** | Comparing your records with your counterparty's records to find mismatches |
| **Break** | A mismatch found during reconciliation |
| **ISDA SIMM** | A standard model for calculating margin on derivatives |
| **Notional** | The face value of a derivative contract (not actual money exchanged) |
| **Settlement** | Final payment when a trade ends |
| **Counterparty** | The other party in a trade |

---

## Author Notes

This project is built for portfolio and learning purposes. Pricing models are simplified (not production-grade) but the **workflow, terminology, data structures, and regulatory references** accurately reflect industry practice.

---
