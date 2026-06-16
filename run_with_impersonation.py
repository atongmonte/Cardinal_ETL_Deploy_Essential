#!/usr/bin/env python3
"""
run_with_impersonation.py
-------------------------
Standalone script to execute commands under Windows impersonation.

Usage:
    python run_with_impersonation.py <script_name.py> [args...]
    
This script will:
1. Load service account credentials from .env
2. Run the specified script under Windows impersonation
3. Pass through all command line arguments
4. Exit with the same exit code as the wrapped script

NOTE: The target script is executed in-process via runpy so that it runs on
the same thread that holds the impersonation token.  Using subprocess.run()
would spawn a child process that inherits the original process token, not the
thread impersonation token, meaning network calls would not use the service
account credentials.

Example:
    python run_with_impersonation.py PRIME_Connection.py
    python run_with_impersonation.py Test_NetworkDrive.py
    python run_with_impersonation.py Cardinal_Inv_Upload.py
"""

import sys
import os
import runpy
from pathlib import Path
from dotenv import load_dotenv
from windows_impersonation import impersonate_user

def main():
    if len(sys.argv) < 2:
        print("Usage: python run_with_impersonation.py <script_name.py> [args...]", file=sys.stderr)
        print("", file=sys.stderr)
        print("Available scripts:", file=sys.stderr)
        script_dir = Path(__file__).parent
        for py_file in script_dir.glob("*.py"):
            if py_file.name not in ['run_with_impersonation.py', 'windows_impersonation.py']:
                print(f"  {py_file.name}", file=sys.stderr)
        sys.exit(1)
    
    # Load environment variables
    load_dotenv()
    
    # Get service account credentials
    service_user_full = os.getenv('SERVICE_USER', r'DM_MONTYNT\svc_procure_data')
    parts = service_user_full.split('\\')
    domain = parts[0] if len(parts) == 2 else 'DM_MONTYNT'
    username = parts[-1]
    
    service_pass = os.getenv('SERVICE_PASS')
    if not service_pass:
        print("ERROR: SERVICE_PASS not found in .env file", file=sys.stderr)
        sys.exit(1)
    
    # Get script to run and its arguments
    script_name = sys.argv[1]
    script_args = sys.argv[2:]
    
    # Ensure script exists
    script_path = Path(script_name)
    if not script_path.exists():
        # Try relative to current script directory
        script_path = Path(__file__).parent / script_name
        if not script_path.exists():
            print(f"ERROR: Script not found: {script_name}", file=sys.stderr)
            sys.exit(1)

    print(f"[IMPERSONATION] Running as: {domain}\\{username}")
    print(f"[SCRIPT] {script_path}")
    print()

    # Run the target script in-process on the same thread that holds the
    # impersonation token.  sys.argv is patched so the script sees its own
    # name and any forwarded arguments as if it were launched directly.
    original_argv = sys.argv[:]
    sys.argv = [str(script_path)] + script_args

    exit_code = 0
    try:
        with impersonate_user(domain, username, service_pass):
            runpy.run_path(str(script_path), run_name='__main__')
    except SystemExit as e:
        exit_code = e.code if e.code is not None else 0
    except Exception as e:
        print(f"ERROR: Script raised an exception: {e}", file=sys.stderr)
        exit_code = 1
    finally:
        sys.argv = original_argv

    sys.exit(exit_code)

if __name__ == '__main__':
    main()
