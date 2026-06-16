#!/usr/bin/env python3
"""
PRIME_Connection.py
-------------------
PRIME database connection test without built-in impersonation.
To be used with run_with_impersonation.py wrapper.

Usage:
    python run_with_impersonation.py PRIME_Connection.py
"""

import pyodbc
import pandas as pd
import warnings
from pathlib import Path
import yaml

# Load config
config_path = Path(__file__).parent / 'config.yaml'
with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

DB_SERVER = config['database']['server']
DB_DATABASE = config['database']['name']
DRIVER = config['database']['driver']
HEALTH_TABLE = '[PRIME].[dbo].[ETL_Health_Status]'

def get_prime_connection() -> pyodbc.Connection:
    """Open and return a pyodbc connection to PRIME database using Windows Authentication."""
    connection_string = (
        f"DRIVER={DRIVER};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_DATABASE};"
        "Trusted_Connection=yes;"
    )
    return pyodbc.connect(connection_string)

def main():
    print(f"Connecting to: {DB_SERVER} / {DB_DATABASE} ...")
    
    try:
        with get_prime_connection() as cnxn:
            # Test basic connection
            cursor = cnxn.cursor()
            cursor.execute("SELECT DB_NAME(), SUSER_SNAME(), GETDATE()")
            db, login, ts = cursor.fetchone()
            
            print(f"\nConnected successfully!")
            print(f"Database       : {db}")
            print(f"Logged in as   : {login}")
            print(f"Server time    : {ts}")
            
            # Test ETL health table
            print(f"\n{'='*70}")
            print(f"Table: {HEALTH_TABLE}")
            print(f"{'='*70}")
            
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                df = pd.read_sql_query(f"SELECT TOP 20 * FROM {HEALTH_TABLE} ORDER BY LastRunTime DESC", cnxn)
            
            if df.empty:
                print("(no rows returned)")
            else:
                print(f"Rows returned  : {len(df)}")
                print(f"Columns        : {list(df.columns)}")
                print()
                pd.set_option('display.max_columns', None)
                pd.set_option('display.width', 200)
                pd.set_option('display.max_colwidth', 40)
                print(df.to_string(index=False))
                
    except Exception as e:
        print(f"\nConnection FAILED: {e}")
        return 1
    
    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main())
