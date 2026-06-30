"""
main.py — OTC Derivatives Lifecycle Simulation
================================================
This is the ENTRY POINT — run this file to simulate the full lifecycle:

    python main.py

What happens when you run this:
  Step 1: Initialize the SQLite database
  Step 2: Capture (book) 50 simulated OTC trades
  Step 3: Run 30 days of daily MTM valuation
  Step 4: Generate margin calls each day
  Step 5: Process collateral for each margin call
  Step 6: Handle trade lifecycle events (expiry, settlement)
  Step 7: Run final reconciliation against counterparty records
  Step 8: Generate Excel report

The simulation covers both:
  🇮🇳 Indian regulations: RBI, SEBI, CCIL (Clearing Corp of India)
  🌍 International:        ISDA, Basel III, Dodd-Frank, EMIR
"""

import os
import sys
import logging
from datetime import datetime, timedelta

# ── Setup paths so Python finds our modules ──────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Import our modules ───────────────────────────────────────
from config import (
    SIMULATION_DAYS, NUM_TRADES, RANDOM_SEED, DATABASE_PATH, EXCEL_OUTPUT_PATH
)
from database.db_manager import DatabaseManager
from modules.trade_capture  import TradeCapture
from modules.mtm_valuation  import MTMValuationEngine
from modules.margin_engine  import MarginEngine
from modules.collateral     import CollateralManager
from modules.lifecycle      import LifecycleProcessor
from modules.reconciliation import ReconciliationEngine
from reports.excel_reporter import ExcelReporter


# ── Logging setup ────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("simulation.log", mode="w"),
    ]
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
def print_banner():
    """Print a startup banner."""
    print("\n" + "=" * 70)
    print("   OTC DERIVATIVES LIFECYCLE & MARGIN SIMULATION")
    print("   Covers: Indian (RBI/SEBI/CCIL) + International (ISDA/Basel III)")
    print("=" * 70 + "\n")

def fmt_cr(amount_inr: float) -> str:
    """Format an INR amount in crores for display."""
    return f"₹{amount_inr/1e7:,.1f} Cr"

def fmt_num(n: float) -> str:
    """Format a large number."""
    return f"{n:,.0f}"


# ─────────────────────────────────────────────────────────────
def main():
    print_banner()
    simulation_start = datetime(2024, 4, 1)   # Start of Indian FY 2024-25

    # ── STEP 0: Initialize Database ──────────────────────────
    logger.info("STEP 0 ▶ Initializing database...")
    db = DatabaseManager(DATABASE_PATH)
    logger.info(f"         Database ready at: {DATABASE_PATH}\n")

    # ── STEP 1: Trade Capture ─────────────────────────────────
    logger.info("STEP 1 ▶ Capturing OTC trades...")
    capturer    = TradeCapture(db)
    all_trades  = capturer.generate_trades(NUM_TRADES, simulation_start)
    summary     = capturer.get_trade_summary(all_trades)

    logger.info(f"         ✔ {summary['total_trades']} trades booked")
    logger.info(f"         By instrument: {summary['by_instrument']}")
    logger.info(f"         Indian CP: {summary['by_jurisdiction']['INDIA']} | "
                f"International: {summary['by_jurisdiction']['INTERNATIONAL']}")
    logger.info(f"         Total Notional: {fmt_cr(summary['total_notional_inr'])}\n")

    # ── STEP 2-6: Daily Processing Loop ──────────────────────
    logger.info("STEP 2-6 ▶ Running daily processing loop...")
    logger.info(f"           Period: {simulation_start.date()} to "
                f"{(simulation_start + timedelta(days=SIMULATION_DAYS)).date()}\n")

    valuation_engine  = MTMValuationEngine(db)
    margin_engine     = MarginEngine(db)
    collateral_mgr    = CollateralManager(db)
    lifecycle_proc    = LifecycleProcessor(db)
    recon_engine      = ReconciliationEngine(db)

    # Aggregate stats across all days
    total_valuations  = 0
    total_margin_calls = 0
    total_settled     = 0
    total_im_inr      = 0
    total_vm_inr      = 0
    all_recon_results = []

    for day_num in range(SIMULATION_DAYS):
        current_date = simulation_start + timedelta(days=day_num)

        # Skip weekends (banks don't process on Sat/Sun)
        if current_date.weekday() >= 5:
            continue

        date_str = current_date.strftime("%Y-%m-%d")

        # Get active trades for today
        active_trades = db.get_active_trades()

        # ── MTM Valuation ──────────────────────────────────
        valuations = valuation_engine.run_daily_valuation(current_date, active_trades)
        total_valuations += len(valuations)

        # Build MTM lookup {trade_id → mtm_record}
        mtm_lookup = {v["trade_id"]: v for v in valuations}

        # ── Margin Calls ───────────────────────────────────
        margin_result = margin_engine.run_daily_margin_cycle(
            current_date, active_trades, valuations
        )
        total_margin_calls += margin_result["total_calls"]
        total_im_inr += margin_result["total_im_inr"]
        total_vm_inr += margin_result["total_vm_inr"]

        # ── Collateral ─────────────────────────────────────
        # Get today's margin calls and process collateral for those that were MET
        today_calls = [
            m for m in db.get_margin_calls()
            if m["call_date"] == date_str and m["status"] == "MET"
        ]
        collateral_mgr.process_margin_calls(today_calls)

        # ── Lifecycle ──────────────────────────────────────
        lc_result = lifecycle_proc.run_daily_lifecycle(
            current_date, active_trades, mtm_lookup
        )
        total_settled += lc_result["settled"]

        # ── Reconciliation ─────────────────────────────────
        recon_result = recon_engine.run_reconciliation(current_date, valuations)
        all_recon_results.append(recon_result)

    # ── Print Daily Loop Summary ──────────────────────────────
    logger.info(f"\n         ✔ MTM Valuations:   {total_valuations:,} records")
    logger.info(f"         ✔ Margin Calls:     {total_margin_calls} total | "
                f"IM: {fmt_cr(total_im_inr)} | VM: {fmt_cr(total_vm_inr)}")
    logger.info(f"         ✔ Trades Settled:   {total_settled}\n")

    # ── STEP 7: Final Reconciliation Report ──────────────────
    logger.info("STEP 7 ▶ Generating reconciliation accuracy report...")
    final_recon = recon_engine.get_final_accuracy_report()
    lc_summary  = lifecycle_proc.get_lifecycle_summary(db.get_all_trades())
    col_summary = collateral_mgr.get_collateral_summary()

    logger.info(f"         Total records:    {final_recon['total_records']:,}")
    logger.info(f"         Matched:          {final_recon['matched']:,}")
    logger.info(f"         Auto-resolved:    {final_recon['auto_resolved']:,}")
    logger.info(f"         Open breaks:      {final_recon['open_breaks']}")
    logger.info(f"         Accuracy:         {final_recon['accuracy_pct']:.2f}%  "
                f"{'✅ TARGET MET' if final_recon['target_met'] else '❌ Below Target'}")
    logger.info(f"         EMIR Compliant:   {'✅ YES' if final_recon['regulatory_compliant'] else '❌ NO'}\n")

    # ── STEP 8: Excel Report ──────────────────────────────────
    logger.info("STEP 8 ▶ Generating Excel report...")
    reporter = ExcelReporter(db)
    excel_path = reporter.generate_report(EXCEL_OUTPUT_PATH, SIMULATION_DAYS)
    logger.info(f"         ✔ Report saved: {excel_path}\n")

    # ── Final Summary ─────────────────────────────────────────
    print("\n" + "=" * 70)
    print("   SIMULATION COMPLETE — SUMMARY")
    print("=" * 70)
    print(f"   Trades booked:          {NUM_TRADES}")
    print(f"   Simulation days:        {SIMULATION_DAYS}")
    print(f"   MTM valuations:         {total_valuations:,}")
    print(f"   Margin calls:           {total_margin_calls}")
    print(f"   Total IM required:      {fmt_cr(total_im_inr)}")
    print(f"   Total VM required:      {fmt_cr(total_vm_inr)}")
    print(f"   Collateral Posted:      {fmt_cr(col_summary['total_posted_inr'])}")
    print(f"   Collateral Received:    {fmt_cr(col_summary['total_received_inr'])}")
    print(f"   Trades Settled:         {lc_summary['total_settlements']}")
    print(f"   Recon Accuracy:         {final_recon['accuracy_pct']:.2f}%")
    print(f"   Open Breaks:            {final_recon['open_breaks']}")
    print(f"   Excel Report:           {EXCEL_OUTPUT_PATH}")
    print(f"   Database:               {DATABASE_PATH}")
    print("=" * 70 + "\n")

    db.close()
    return 0


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    sys.exit(main())
