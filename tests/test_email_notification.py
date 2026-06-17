#!/usr/bin/env python3
"""
test_email_notification.py
--------------------------
Email notification test without built-in impersonation.
To be used with run_with_impersonation.py wrapper.

Usage:
    python run_with_impersonation.py tests/test_email_notification.py
"""

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
from msgraph_email import send_email
import yaml

def main():
    # Load environment
    load_dotenv(ROOT_DIR / '.env')
    
    # Load config
    config_path = ROOT_DIR / 'config.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # Prepare secrets
    secrets = {
        'TENANT_ID': os.getenv('TENANT_ID'),
        'CLIENT_ID': os.getenv('CLIENT_ID'),
        'CLIENT_SECRET': os.getenv('CLIENT_SECRET')
    }
    
    print("Testing email notification system...")
    
    try:
        send_email(
            config=config,
            secrets=secrets,
            recipients=['atong@montefiore.org'],
            subject='Cardinal ETLs - Setup Test Email',
            body_html='<p><strong>Cardinal ETLs Setup Test</strong></p><p>Email notification system is working correctly! ✅</p><p>This email was sent during the setup process to verify email functionality.</p>'
        )
        
        print("[SUCCESS] Email sent successfully!")
        print("Email notification system is working properly.")
        return 0
        
    except Exception as e:
        print(f"[FAILED] Email test failed: {e}")
        print(f"Error type: {type(e).__name__}")
        return 1

if __name__ == '__main__':
    sys.exit(main())
