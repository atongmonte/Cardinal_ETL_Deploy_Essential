
import pandas as pd
import os
import sys
import subprocess
from glob import glob
from datetime import datetime
from pathlib import Path
import pyodbc
import socket
import logging
import yaml
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from msgraph_email import send_success_notification, send_failure_notification
from windows_impersonation import impersonate_user, whoami_network

# Load credentials and config from .env (same directory as this script)
_ENV_PATH = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=_ENV_PATH, override=True)

# Load structural config from YAML
_CFG = yaml.safe_load((Path(__file__).parent / 'config.yaml').read_text(encoding='utf-8'))

# Force UTF-8 output on Windows console
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# Configure logging
_LOG_DIR = Path(__file__).parent / 'log_python'
_LOG_DIR.mkdir(exist_ok=True)
log_file = str(_LOG_DIR / f"cardinal_invoice_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

formatter = logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S')

handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8')
handler.setFormatter(formatter)
logger.addHandler(handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# ============================================================================
# CONFIGURATION  (values loaded from .env)
# ============================================================================
BASE_DIR       = _CFG['paths']['base_dir']
DB_SERVER      = _CFG['database']['server']
DB_NAME        = _CFG['database']['name']
NET_USE_SERVER = _CFG['paths']['net_use_server']
SERVICE_USER   = os.environ.get('SERVICE_USER')
SERVICE_PASS   = os.environ.get('SERVICE_PASS', '')

# --- MS Graph API (email notifications) --------------------------------------
_GRAPH_TENANT   = os.environ.get('TENANT_ID', '')
_GRAPH_CLIENT   = os.environ.get('CLIENT_ID', '')
_GRAPH_SECRET   = os.environ.get('CLIENT_SECRET', '')
_GRAPH_SECRETS  = {'TENANT_ID': _GRAPH_TENANT, 'CLIENT_ID': _GRAPH_CLIENT, 'CLIENT_SECRET': _GRAPH_SECRET}
_EMAIL_ENABLED  = all(_GRAPH_SECRETS.values())

# Validate required credentials are present in .env
_missing = [k for k, v in {'SERVICE_USER': SERVICE_USER, 'SERVICE_PASS': SERVICE_PASS}.items() if not v]
if _missing:
    raise EnvironmentError(f"Missing required .env values: {', '.join(_missing)}")

# Parse domain and username for Windows impersonation
_default_domain = os.environ.get('SERVICE_DOMAIN', 'DM_MONTYNT')
_svc_parts      = SERVICE_USER.split('\\')
_SVC_DOMAIN     = _svc_parts[0] if len(_svc_parts) == 2 else _default_domain
_SVC_USERNAME   = _svc_parts[-1]

_USER_PART     = SERVICE_USER.split('\\')[-1] if '\\' in SERVICE_USER else SERVICE_USER
_tbl           = _CFG['tables']
STAGING_TABLE  = _tbl['staging']
FINAL_TABLE    = _tbl['final']
HEALTH_TABLE   = _tbl['health']

# ============================================================================
# NETWORK DRIVE AUTHENTICATION
# ============================================================================
def net_use_connect(server: str, user: str, password: str) -> bool:
    """
    Authenticate to a UNC server with explicit credentials via 'net use'.
    Required for non-interactive Task Scheduler sessions that have no cached
    SMB/Kerberos token for the share.
    """
    # Disconnect stale session first (ignore errors)
    subprocess.run(['net', 'use', server, '/delete', '/y'], capture_output=True)
    result = subprocess.run(
        ['net', 'use', server, password, f'/user:{user}', '/persistent:no'],
        capture_output=True, text=True
    )
    return result.returncode == 0


def net_use_disconnect(server: str) -> None:
    """Disconnect the UNC session created by net_use_connect."""
    subprocess.run(['net', 'use', server, '/delete', '/y'], capture_output=True)


# ============================================================================
# EXPECTED COLUMNS  (loaded from config.yaml; year_month is derived by this script)
# ============================================================================
EXPECTED_COLUMNS = _CFG['expected_columns']

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
def find_invoice_file(base_dir):
    """Find invoice file matching today's date."""
    today = datetime.now().strftime('%Y-%m-%d')
    pattern = _CFG['file_patterns']['invoice_glob'].format(date=today)
    files = glob(os.path.join(base_dir, pattern))
    if files:
        return os.path.basename(files[0])
    raise FileNotFoundError(f"No invoice file found for {today}")

def get_file_path(base_dir, file_name):
    """Get the full file path."""
    return os.path.join(base_dir, file_name)

def extract_create_date(file_path):
    """Extract creation date from file and format as YYYYMMDD."""
    modified_time = os.path.getmtime(file_path)
    return datetime.fromtimestamp(modified_time).strftime('%Y%m%d')

def archive_and_rename_file(file_path, create_date_str):
    """Move file to Daily Archive subdirectory with date in filename."""
    base_dir = os.path.dirname(file_path)
    archived_dir = os.path.join(base_dir, _CFG['file_patterns']['archive_subdir'])
    os.makedirs(archived_dir, exist_ok=True)

    new_filename = _CFG['file_patterns']['archive_filename'].format(date=create_date_str)
    new_file_path = os.path.join(archived_dir, new_filename)
    
    os.replace(file_path, new_file_path)
    logger.info(f"         File archived to: {new_file_path}")
    return new_file_path

def to_yearmonth(val):
    """Convert 'MON YYYY' format to 'YYYY-MM' format."""
    month_map = {
        'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
        'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
        'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'
    }
    try:
        parts = str(val).split()
        month = month_map.get(parts[0].upper())
        year = parts[1]
        return f'{year}-{month}' if month else None
    except:
        return None

def validate_columns(df, file_path):
    """
    Validate that the loaded DataFrame contains all expected columns.
    Logs a warning for any extra (unexpected) columns and raises a
    ValueError listing any missing columns so the run fails fast.
    """
    actual   = set(df.columns.tolist())
    expected = set(EXPECTED_COLUMNS)

    missing = expected - actual
    extra   = actual - expected

    if extra:
        logger.warning(f"         Column check — unexpected columns in file ({len(extra)}): {sorted(extra)}")

    if missing:
        logger.error(f"         Column check — MISSING columns ({len(missing)}): {sorted(missing)}")
        raise ValueError(
            f"Column validation FAILED for '{os.path.basename(file_path)}'. "
            f"Missing {len(missing)} column(s): {sorted(missing)}"
        )

    logger.info(f"         Column check — OK ({len(actual)} columns present, {len(extra)} extra)")


def load_and_prepare_data(file_path):
    """Load Excel file and prepare data."""
    df = pd.read_excel(file_path, dtype=str)

    # ── Column validation (before any transformations) ────────────────────
    validate_columns(df, file_path)

    # Exclude last row (Summary)
    df = df.iloc[:-1]
    
    # Fill NaN values
    df.fillna('', inplace=True)
    
    # Create year_month column
    df['year_month'] = df['Month Year Display Text'].apply(to_yearmonth)
    
    # Drop unnecessary columns
    if 'Billing Item' in df.columns:
        df = df.drop(columns=['Billing Item'])
        logger.info("         Dropped 'Billing Item' column")
    
    return df

def insert_to_staging_table(df, cnxn):
    """Insert data into staging table."""
    cursor = cnxn.cursor()
    cursor.fast_executemany = True
    
    logger.info(f"         Truncating staging table...")
    cursor.execute(f"TRUNCATE TABLE {STAGING_TABLE}")
    cursor.commit()
    
    # Get column headers from table
    prime_header = pd.read_sql_query(f"SELECT TOP 3 * FROM {STAGING_TABLE}", cnxn)
    header = prime_header.columns.tolist()
    
    # Build INSERT statement
    value_qstring = ','.join(['?' for _ in range(len(header))])
    cols = ','.join([f'[{col}]' for col in header])
    sql_insert = f'INSERT INTO {STAGING_TABLE} ({cols}) VALUES ({value_qstring})'
    
    logger.info(f"         Bulk inserting {len(df):,} rows...")
    cursor.executemany(sql_insert, df.values.tolist())
    cursor.commit()
    
    logger.info(f"         Staging count verified: {len(df):,}")
    cursor.close()

def insert_to_final_table(cnxn):
    """Insert data from staging table to final table with transformations."""
    cursor = cnxn.cursor()
    
    sql_insert = f"""
    INSERT INTO {FINAL_TABLE}
        ([MONTH_YEAR_SOURCE], [ACCOUNT_NUM], [ACCOUNT_TYPE], [ACCOUNT_NAME], [SITE],
         [ACCOUNT_CLASSIFICATION_DESC], [CIN_NUM], [PRODUCT_DESCRIPTION], [TRADE_NAME],
         [GENERIC_NAME], [STRENGTH], [SIZE_DIMENSION], [FORM], [PACK_QTY], [PACK],
         [VENDOR_NAME], [NDC_NUM], [UPC_NUM], [CARDINAL_KEY], [CARDINAL_SUBSTITUTION_KEY],
         [GCN_SEQ_NUM], [GENRIC_PRODUCT_ID], [MFR_PART_NUM], [UOI], [BASE_UOM], [MDSP_UOM],
         [PACKAGING_INDICATOR], [OE_CAT_CODE2], [SHAPE], [COLOR], [REFRIG_FLAG],
         [TEMP_CONDT_INDICATOR], [TEMP_CONDT_INDICATOR_DESC], [AHFS_CODE], [AHFS_CODE_DESC],
         [FINE_CLASS], [FINE_CLASS_DESC], [FINER_CLASS], [FINER_CLASS_DESC], [FINEST_CLASS],
         [FINEST_CLASS_DESC], [DEA_SCHEDULE1], [RX_PROD_FLAG], [MATERIAL_GROUP], [SPD_FLAG],
         [BUYING_GROUP], [BUYING_GROUP_NAME], [CUST_PO_TYPE_DESC], [BILLING_TYPE_DESC],
         [SALES_DOCUMENT], [PO_NUM], [ORDER_DATE], [INVOICE_DATE], [INVOICE_NUMBER],
         [ORDER_QTY], [ACTUAL_INVOICE_QTY], [UNIT_PRICE], [UOI_PRICE],
         [PRICING_SUBTOTAL_2_NET_PRICE_AFTER_PROMOTIONS], [TAX_AMT_IN_DOC_CURRENCY],
         [TOTAL_DOLLARS], [YEAR_MONTH], [UPDATE_TIME])
    SELECT
        [Month Year Display Text], [Ship To Customer Number], [Acct Type],
        [Ship To Customer Name], [Site], [Customer classification Description],
        [Material Number (Numeric)], [Material Description],
        [Misc Product Attributes.Trade Name], [Generic Name Type], [Strength],
        [Size/dimensions], [Form], TRY_CONVERT(numeric(18,2),[Pack Qty]),
        TRY_CONVERT(numeric(18,2),[Pack Size]), [Vendor Name], [NDC 11], [UPC Number],
        [Cardinal Key], [Cardinal Substitution Key], [GCN Sequence Number],
        [Genric Product Id], [Manufacturer Part Number], [UOI], [Base Unit Of Measure],
        [MDSP UOM], [Packaging Indicator], [OE Cat Code2], [Shape], [Color],
        [Refrig Flag], [Temperature conditions indicator],
        [Temperature conditions indicator descriptions], [AHFS Code],
        [AHFS Code Description], [Fine Class], [Fine Class Description],
        [Finer Class], [Finer Class Description], [Finest Class],
        [Finest Class Description], [DEA Schedule1], [Rx Product Flag],
        [Material Group], [SPD Flag], [Buying Group], [Buying Group Name],
        [Cust Purchase Order Type Desc], [Billing Type Description], [Sales Document],
        [Customer Purchase Order Number], [Order Document Date], [Billing Date],
        [Invoice Number], TRY_CONVERT(numeric(18,2),[Cum. Order Qty In Sales Units]),
        TRY_CONVERT(numeric(18,2),[Actual Invoice Quantity]),
        TRY_CONVERT(numeric(18,2),[Unit Price]), TRY_CONVERT(numeric(18,2),[UOI Price]),
        TRY_CONVERT(numeric(18,2),[Pricing Subtotal 2 - Net Price after Promotions]),
        TRY_CONVERT(numeric(18,2),[Tax Amount In Document Currency]),
        TRY_CONVERT(numeric(18,2),[Total Dollars]), [year_month], GETDATE()
    FROM {STAGING_TABLE}
    """
    
    logger.info(f"         Executing INSERT into {FINAL_TABLE}...")
    cursor.execute(sql_insert)
    cursor.commit()
    
    rowcount = cursor.rowcount
    logger.info(f"         Rows inserted: {rowcount:,}")
    cursor.close()
    return rowcount

def get_db_connection():
    """Establish database connection using Windows Integrated Security (Trusted Connection).
    MISCPRDADHOCDB uses Kerberos/Windows auth only — UID/PWD is not accepted.
    When called inside ``impersonate_user()``, SQL Server sees the service account's network token.
    """
    cnxn = pyodbc.connect(
        f'DRIVER={{ODBC Driver 17 for SQL Server}};'
        f'SERVER={DB_SERVER};'
        f'DATABASE={DB_NAME};'
        'Trusted_Connection=yes;'
    )
    return cnxn

def insert_health_status(cnxn, source_file_path, run_time, task_status, row_count,
                         log_file_path, error_msg):
    """Insert ETL run metadata into ETL_Health_Status table."""
    script_path = os.path.abspath(__file__)
    package_path = f"{socket.gethostname()}: {script_path}"
    owner = SERVICE_USER or os.getenv('USERNAME', os.getenv('USER', 'unknown'))

    sql = f"""
    INSERT INTO {HEALTH_TABLE}
        (PackageName, DataFlowTaskName, SourceFilePath, LastRunTime, TargetTableName,
         TaskStatus, Row_Count, PackagePath, LogFilePath, STGTableName,
         ProcessFrequency, Error, Owner)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
    """
    _etl = _CFG['etl_metadata']
    values = (
        _etl['package_name'],
        _etl['data_flow_task'],
        source_file_path,
        run_time,
        FINAL_TABLE,
        task_status,
        row_count,
        package_path,
        log_file_path,
        STAGING_TABLE,
        error_msg,
        owner,
    )
    cursor = cnxn.cursor()
    try:
        cursor.execute(sql, values)
        cnxn.commit()
        logger.info(f"         ETL health status recorded: {task_status}")
    finally:
        cursor.close()


# ============================================================================
# MAIN EXECUTION
# ============================================================================
def run_etl():
    run_start = datetime.now()
    task_status = 'FAILED'
    error_msg = None
    rows_inserted = 0
    rows_processed = 0
    source_file_path = None
    cnxn = None

    logger.info("\u2554" + "\u2550" * 64 + "\u2557")
    logger.info("\u2551  Cardinal Invoice Detail Upload Process                        \u2551")
    logger.info("\u255a" + "\u2550" * 64 + "\u255d")
    logger.info(f"Staging Table: {STAGING_TABLE}")
    logger.info(f"Final Table:   {FINAL_TABLE}")
    logger.info(f"Source Dir:    {BASE_DIR}")
    logger.info(f"Timestamp:     {run_start.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Auth User:     {SERVICE_USER}")
    logger.info("")

    # Run ETL process
    try:
        # ── Step 0: Authenticate network share ───────────────────────────
        logger.info("[STEP 0] Authenticating network share...")
        ok = net_use_connect(NET_USE_SERVER, SERVICE_USER, SERVICE_PASS)
        if ok:
            logger.info(f"         net use OK  — authenticated as {SERVICE_USER}")
        else:
            logger.warning("         net use returned non-zero — may already be connected, continuing...")

        # ── Step 1: File Discovery ────────────────────────────────────────
        logger.info("--- File Discovery ---")
        file_name = find_invoice_file(BASE_DIR)
        file_path = get_file_path(BASE_DIR, file_name)
        source_file_path = file_path
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        logger.info(f"[STEP 1] Source file identified: {file_name}")
        logger.info(f"         Full path:  {file_path}")
        logger.info(f"         File size:  {file_size_mb:.2f} MB")

        # ── Step 2: Archive File ──────────────────────────────────────────
        logger.info("[STEP 2] Archiving file...")
        create_date_str = extract_create_date(file_path)
        archived_file_path = archive_and_rename_file(file_path, create_date_str)

        # ── Step 3: Load & Prepare Data ──────────────────────────────────
        step3_start = datetime.now()
        logger.info("[STEP 3] Reading Excel file...")
        df = load_and_prepare_data(archived_file_path)
        rows_processed = len(df)
        step3_elapsed = (datetime.now() - step3_start).total_seconds()
        logger.info(f"         Rows read from Excel:   {len(df):,}")
        logger.info(f"         Columns:                {df.shape[1]}")
        logger.info(f"         Unique days:            {sorted(df['Billing Date'].unique())}")
        logger.info(f"         Read time:              {step3_elapsed:.1f}s")

        # ── Step 4: Database Connection ───────────────────────────────────
        logger.info("[STEP 4] Database connection: {}.{}".format(DB_SERVER, DB_NAME))
        cnxn = get_db_connection()
        cursor = cnxn.cursor()
        cursor.execute("SELECT DB_NAME(), SUSER_SNAME()")
        db_name, login_name = cursor.fetchone()
        cursor.close()
        logger.info(f"         Connected to:  {db_name}")
        logger.info(f"         SQL login:     {login_name}")

        # ── Step 5: Load to Staging ───────────────────────────────────────
        step5_start = datetime.now()
        logger.info("[STEP 5] Loading to staging table...")
        insert_to_staging_table(df, cnxn)
        step5_elapsed = (datetime.now() - step5_start).total_seconds()
        logger.info(f"         Staging load time: {step5_elapsed:.1f}s")

        # ── Step 6: Insert to Final Table ─────────────────────────────────
        step6_start = datetime.now()
        logger.info("[STEP 6] Inserting transformed data into final table...")
        rows_inserted = insert_to_final_table(cnxn)
        step6_elapsed = (datetime.now() - step6_start).total_seconds()
        logger.info(f"         Insert time: {step6_elapsed:.1f}s")

        task_status = 'SUCCESS'

        # ── Step 7: Summary ───────────────────────────────────────────────
        total_elapsed = (datetime.now() - run_start).total_seconds()
        throughput = len(df) / total_elapsed if total_elapsed > 0 else 0
        logger.info("")
        logger.info("╔" + "═" * 64 + "╗")
        logger.info("║  Process Completed Successfully!                               ║")
        logger.info("╚" + "═" * 64 + "╝")
        logger.info("")
        logger.info("=" * 47)
        logger.info(f"  Total Rows Processed: {len(df):,}")
        logger.info(f"  Rows Inserted:        {rows_inserted:,}")
        logger.info(f"  Staging Table:        {STAGING_TABLE}")
        logger.info(f"  Final Table:          {FINAL_TABLE}")
        logger.info(f"  Total Time:           {total_elapsed:.1f}s")
        logger.info(f"  Throughput:           {throughput:,.0f} rows/sec")
        logger.info("=" * 47)

    except FileNotFoundError as e:
        error_msg = str(e)
        task_status = 'FILE_NOT_FOUND'
        logger.warning(f"File not found: {error_msg}")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error during insertion: {error_msg}")
        raise

    finally:
        # ── Step 8: Write ETL Health Status ──────────────────────────────
        logger.info("[STEP 8] Writing ETL health status...")
        # Store log path relative to script folder (portable across machines)
        log_file_path = str(Path(log_file).relative_to(Path(__file__).parent))
        try:
            if cnxn is None:
                cnxn = get_db_connection()
            insert_health_status(
                cnxn,
                source_file_path=source_file_path,
                run_time=run_start,
                task_status=task_status,
                row_count=rows_inserted,
                log_file_path=log_file_path,
                error_msg=error_msg,
            )
        except Exception as health_err:
            logger.warning(f"         Could not write health status: {health_err}")
        finally:
            if cnxn:
                cnxn.close()
                logger.info("Database connection closed.")
            net_use_disconnect(NET_USE_SERVER)
            logger.info(f"Network share disconnected: {NET_USE_SERVER}")

        # ── Step 9: Email notification ────────────────────────────────────
        logger.info("[STEP 9] Sending email notification...")
        if _EMAIL_ENABLED:
            try:
                run_date = run_start.strftime('%Y-%m-%d')
                total_elapsed = (datetime.now() - run_start).total_seconds()
                if task_status == 'SUCCESS':
                    send_success_notification(
                        _CFG, _GRAPH_SECRETS,
                        run_stats={
                            'run_date':       run_date,
                            'host':           socket.gethostname(),
                            'source_file':    os.path.basename(source_file_path) if source_file_path else 'N/A',
                            'rows_processed': rows_processed,
                            'rows_inserted':  rows_inserted,
                            'final_table':    FINAL_TABLE,
                            'elapsed_s':      total_elapsed,
                        },
                        log_path=log_file,
                    )
                else:
                    send_failure_notification(
                        _CFG, _GRAPH_SECRETS,
                        error_msg=error_msg,
                        run_date=run_date,
                        host=socket.gethostname(),
                        log_path=log_file,
                    )
                logger.info("         Email notification sent.")
            except Exception as email_err:
                logger.warning(f"         Email notification failed (non-fatal): {email_err}")
        else:
            logger.warning("         Email disabled — MS Graph credentials not configured in .env.")


def main():
    """Direct-entry wrapper that impersonates the service account before running the ETL."""
    target_identity = f"{_SVC_DOMAIN}\\{_SVC_USERNAME}" if _SVC_DOMAIN else _SVC_USERNAME
    logger.info("[AUTH] Starting Windows impersonation for outbound network access...")
    logger.info(f"         Target service account: {target_identity}")

    etl_started = False
    try:
        with impersonate_user(_SVC_DOMAIN, _SVC_USERNAME, SERVICE_PASS):
            try:
                active_identity = whoami_network()
            except Exception:
                active_identity = target_identity
            logger.info(f"         Impersonation active as: {active_identity}")
            etl_started = True
            run_etl()
    except Exception as exc:
        if not etl_started:
            logger.exception(f"Impersonation startup failed: {exc}")
            if _EMAIL_ENABLED:
                try:
                    send_failure_notification(
                        _CFG,
                        _GRAPH_SECRETS,
                        error_msg=str(exc),
                        run_date=datetime.now().strftime('%Y-%m-%d'),
                        host=socket.gethostname(),
                        log_path=log_file,
                    )
                    logger.info("         Failure email sent for impersonation error.")
                except Exception as email_err:
                    logger.warning(f"         Email notification failed (non-fatal): {email_err}")
        raise


if __name__ == "__main__":
    main()
