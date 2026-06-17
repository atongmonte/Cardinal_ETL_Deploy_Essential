#!/usr/bin/env python3
"""
test_network_drive.py
---------------------
Network drive test without built-in impersonation.
To be used with run_with_impersonation.py wrapper.

Usage:
    python run_with_impersonation.py tests/test_network_drive.py
"""

import os
import sys
import time
import socket
import subprocess
from pathlib import Path
import pandas as pd
import yaml

# Load config from the project root.
ROOT_DIR = Path(__file__).resolve().parents[1]
config_path = ROOT_DIR / 'config.yaml'
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

# Network paths
UNC_SERVER = config['paths']['net_use_server']
UNC_DIR = config['paths']['base_dir']
UNC_FILE = config['network']['test_file']

def check_host_reachable(host: str = 'montefiore.org', timeout: int = 5) -> bool:
    """Attempt a TCP connection to the host on port 445 (SMB)."""
    try:
        sock = socket.create_connection((host, 445), timeout=timeout)
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False

def net_use_connect(server: str) -> bool:
    """Authenticate to server using current credentials."""
    try:
        result = subprocess.run(['net', 'use', server], 
                              capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False

def check_path_accessible(path: str) -> bool:
    """Return True if the UNC path exists and is readable."""
    return os.path.exists(path)

def read_excel(file_path: str) -> pd.DataFrame:
    """Read an Excel file and return a DataFrame."""
    return pd.read_excel(file_path, dtype=str)

def main():
    sep = '=' * 70
    print(sep)
    print('  Network Drive Connection Test')
    print(sep)
    from dotenv import load_dotenv
    load_dotenv(ROOT_DIR / '.env')
    service_user = os.environ.get('SERVICE_USER', f'{os.environ.get("USERDOMAIN","?")}\\{os.environ.get("USERNAME","?")}')
    print(f'  Host        : montefiore.org')
    print(f'  Target dir  : {UNC_DIR}')
    print(f'  Target file : {UNC_FILE}')
    print(f'  Run user    : {service_user}')
    print()

    # Step 1: Host reachability
    print('[STEP 1] Checking SMB connectivity to montefiore.org ...')
    t0 = time.time()
    reachable = check_host_reachable()
    elapsed = time.time() - t0
    if reachable:
        print(f'         OK  - host reachable on port 445  ({elapsed:.2f}s)')
    else:
        print(f'         FAIL - cannot reach montefiore.org:445  ({elapsed:.2f}s)')
        print('         Possible causes:')
        print('           - VPN not connected')
        print('           - Firewall blocking SMB traffic')
        print('           - Host name not resolving')
        return 1

    # Step 1b: Authenticate
    print(f'\n[STEP 1b] Authenticating to {UNC_SERVER} ...')
    ok = net_use_connect(UNC_SERVER)
    if ok:
        print(f'         OK  - net use authentication succeeded')
    else:
        print(f'         WARN - net use returned non-zero (may already be connected)')

    # Step 2: Directory access
    print(f'\n[STEP 2] Checking directory access ...')
    if check_path_accessible(UNC_DIR):
        entries = list(Path(UNC_DIR).iterdir())
        print(f'         OK  - directory accessible')
        print(f'         Items in folder: {len(entries)}')
    else:
        print(f'         FAIL - directory not accessible: {UNC_DIR}')
        return 1

    # Step 3: File existence
    print(f'\n[STEP 3] Checking file existence ...')
    if check_path_accessible(UNC_FILE):
        size_kb = os.path.getsize(UNC_FILE) / 1024
        mtime = time.strftime('%Y-%m-%d %H:%M:%S',
                             time.localtime(os.path.getmtime(UNC_FILE)))
        print(f'         OK  - file found')
        print(f'         Size          : {size_kb:.1f} KB')
        print(f'         Last modified : {mtime}')
    else:
        print(f'         FAIL - file not found: {UNC_FILE}')
        return 1

    # Step 4: Read Excel
    print(f'\n[STEP 4] Reading Excel file ...')
    try:
        t0 = time.time()
        df = read_excel(UNC_FILE)
        elapsed = time.time() - t0
        print(f'         OK  - file read successfully  ({elapsed:.2f}s)')
        print(f'         Rows    : {len(df):,}')
        print(f'         Columns : {df.shape[1]}  {list(df.columns)}')
        print()
        print('  Preview (first 5 rows):')
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 200)
        pd.set_option('display.max_colwidth', 40)
        print(df.head().to_string(index=False))
    except Exception as exc:
        print(f'         FAIL - could not read file: {exc}')
        return 1

    print(f'\n{sep}')
    print('  All tests PASSED')
    print(sep)

    # Cleanup
    try:
        subprocess.run(['net', 'use', UNC_SERVER, '/delete'], 
                      capture_output=True, timeout=10)
    except:
        pass  # Ignore cleanup errors

    return 0

if __name__ == '__main__':
    sys.exit(main())
