import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from Cardinal_Inv_Upload import main as run_invoice_upload
from Cardinal_Monthly_Process import main as run_monthly_process
from SFTP_Connection import run_sftp_download


ROOT_DIR = Path(__file__).parent
CONFIG_PATH = ROOT_DIR / "config.yaml"


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def load_config(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_run_datetime(value):
    if not value:
        return datetime.now()

    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def get_sftp_window(run_datetime, window_end_hour):
    window_end = run_datetime.replace(
        hour=window_end_hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    window_start = window_end - timedelta(days=1)
    return window_start, window_end


def get_sequence_settings(config_path):
    config = load_config(config_path)
    sequence_config = config.get("sequence", {})
    window_end_hour = int(sequence_config.get("window_end_hour", 11))
    monthly_run_day = int(sequence_config.get("monthly_run_day", 8))
    return window_end_hour, monthly_run_day


def run_sftp_part(config_path=CONFIG_PATH, run_datetime=None):
    window_end_hour, _ = get_sequence_settings(config_path)

    run_datetime = run_datetime or datetime.now()
    window_start, window_end = get_sftp_window(run_datetime, window_end_hour)

    log(
        "SFTP window: "
        f"{window_start:%Y-%m-%d %H:%M:%S} <= modified < "
        f"{window_end:%Y-%m-%d %H:%M:%S}"
    )

    log("[STEP 1] Downloading SFTP files...")
    downloaded_files = run_sftp_download(
        window_start=window_start,
        window_end=window_end,
    )
    log(f"Downloaded files: {len(downloaded_files)}")
    return downloaded_files


def run_daily_invoice_part():
    log("Running daily invoice upload.")
    return run_invoice_upload()


def run_monthly_catalog_part():
    log("Running monthly catalog upload.")
    return run_monthly_process()


def run_sequence(config_path=CONFIG_PATH, run_datetime=None):
    _, monthly_run_day = get_sequence_settings(config_path)

    run_datetime = run_datetime or datetime.now()

    log("Starting Cardinal ETL sequence.")
    log(f"Run date: {run_datetime:%Y-%m-%d}")

    run_sftp_part(config_path=config_path, run_datetime=run_datetime)

    log("[STEP 2] Running daily invoice upload.")
    run_daily_invoice_part()

    if run_datetime.day == monthly_run_day:
        log(f"[STEP 3] Day {monthly_run_day}: running monthly catalog upload.")
        run_monthly_catalog_part()

    log("Cardinal ETL sequence completed successfully.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Run the Cardinal SFTP-to-ETL sequence.")
    parser.add_argument(
        "action",
        nargs="?",
        choices=[
            "sftp_download",
            "daily_inv_upload",
            "monthly_catalog_upload",
        ],
        help=(
            "Optional single step to run. Omit to run the default sequence: "
            "SFTP download, daily invoice upload, then monthly catalog upload on the 8th."
        ),
    )
    parser.add_argument(
        "--config",
        default=str(CONFIG_PATH),
        help="Path to config.yaml. Kept for run.bat compatibility.",
    )
    parser.add_argument(
        "--run-date",
        help="Optional run date for testing, as YYYY-MM-DD or YYYY-MM-DD HH:MM:SS.",
    )
    args = parser.parse_args()

    try:
        run_datetime = parse_run_datetime(args.run_date)
        config_path = Path(args.config)

        if args.action == "sftp_download":
            run_sftp_part(config_path=config_path, run_datetime=run_datetime)
            return 0

        if args.action == "daily_inv_upload":
            return run_daily_invoice_part() or 0

        if args.action == "monthly_catalog_upload":
            return run_monthly_catalog_part() or 0

        return run_sequence(config_path=config_path, run_datetime=run_datetime)
    except Exception as exc:
        log(f"Sequence failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
