"""
msgraph_email.py
----------------
Microsoft Graph API email notifications for Cardinal ETLs.
Follows the A13-MedlinePBO pattern.

Secrets required in .env (encrypted via setup_credentials.py):
    TENANT_ID, CLIENT_ID, CLIENT_SECRET_HASHED

Config required in config.yaml:
    email.aad_endpoint, email.graph_endpoint, email.from_address
    notification.success_recipients, notification.failure_recipients,
    notification.success_cc_recipients, notification.failure_cc_recipients
"""
import base64
import os

import requests


# ── Internal helper ────────────────────────────────────────────────────────────
def _raise_for_status(resp, context):
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        detail = ""
        try:
            payload = resp.json()
            code = payload.get("error")
            desc = payload.get("error_description")
            if code or desc:
                detail = f" ({code}: {desc})"
        except ValueError:
            pass
        raise requests.HTTPError(f"{context}{detail}", response=resp) from exc


# ── Auth ───────────────────────────────────────────────────────────────────────
def get_access_token(secrets, config):
    """Obtain an OAuth2 Bearer token via client credentials flow."""
    aad    = config["email"]["aad_endpoint"]
    tenant = secrets["TENANT_ID"]
    url    = f"{aad}/{tenant}/oauth2/v2.0/token"
    data   = {
        "client_id":     secrets["CLIENT_ID"],
        "scope":         "https://graph.microsoft.com/.default",
        "client_secret": secrets["CLIENT_SECRET"],
        "grant_type":    "client_credentials",
    }
    resp = requests.post(url, data=data, timeout=20)
    _raise_for_status(resp, "Failed to acquire MS Graph access token")
    return resp.json()["access_token"]


# ── Core send ──────────────────────────────────────────────────────────────────
def send_email(config, secrets, recipients, subject, body_html,
               attachment_path=None, cc_recipients=None):
    """Send an HTML email via Microsoft Graph, with an optional file attachment.

    Parameters
    ----------
    recipients      : list[str]  — To: addresses
    cc_recipients   : list[str]  — CC: addresses (optional)
    attachment_path : str | None — local file to attach (optional)
    """
    token  = get_access_token(secrets, config)
    sender = config["email"]["from_address"]
    url    = f"{config['email']['graph_endpoint']}/v1.0/users/{sender}/sendMail"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }

    message = {
        "subject": subject,
        "body":    {"contentType": "HTML", "content": body_html},
        "toRecipients": [{"emailAddress": {"address": a}} for a in recipients],
    }

    if cc_recipients:
        message["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc_recipients]

    if attachment_path and os.path.isfile(attachment_path):
        with open(attachment_path, "rb") as f:
            content = base64.b64encode(f.read()).decode("utf-8")
        message["attachments"] = [{
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name":         os.path.basename(attachment_path),
            "contentBytes": content,
        }]

    resp = requests.post(url, headers=headers, json={"message": message}, timeout=30)
    _raise_for_status(resp, "Failed to send email via MS Graph")
    return True


# ── HTML body builders ─────────────────────────────────────────────────────────
_HEADER_BLUE  = "#1F5B98"
_HEADER_RED   = "#c0392b"
_ROW_LIGHT    = "#f0f4fa"
_SUCCESS_BG   = "#d4edda"
_SUCCESS_FG   = "#155724"
_FAILURE_BG   = "#f8d7da"
_FAILURE_FG   = "#721c24"

def _row(label, value, bg=_ROW_LIGHT):
    return (f'<tr><td style="background:{bg};width:200px;padding:5px 8px;">'
            f'<b>{label}</b></td>'
            f'<td style="padding:5px 8px;">{value}</td></tr>')


def _success_body(run_stats):
    rows     = run_stats.get("rows_processed", 0)
    inserted = run_stats.get("rows_inserted", 0)
    elapsed  = run_stats.get("elapsed_s", 0)
    return f"""<html><body style="font-family:Calibri,Arial,sans-serif;font-size:13px;color:#222;">
<p>The <strong>Cardinal Daily Invoice Upload</strong> completed successfully.</p>
<table border="1" cellpadding="0" cellspacing="0"
       style="border-collapse:collapse;border-color:#bbb;width:540px;">
  <tr style="background:{_HEADER_BLUE};color:white;">
    <th colspan="2" style="text-align:left;padding:8px;">Run Summary</th>
  </tr>
  {_row("Run Date",      run_stats.get("run_date", ""))}
  {_row("Host",          run_stats.get("host", ""))}
  {_row("Source File",   run_stats.get("source_file", "N/A"))}
  {_row("Rows Processed", f"{rows:,}")}
  {_row("Rows Inserted",  f"{inserted:,}")}
  {_row("Target Table",   run_stats.get("final_table", ""))}
  {_row("Total Time",     f"{elapsed:.1f}s")}
  <tr style="background:{_SUCCESS_BG};">
    <td colspan="2" style="text-align:center;color:{_SUCCESS_FG};
        font-weight:bold;padding:7px;">&#10003; SUCCESS</td>
  </tr>
</table>
<p style="color:#888;font-size:11px;margin-top:16px;">
  Automated notification &mdash; Cardinal ETL Pipeline
</p>
</body></html>"""


def _failure_body(error_msg, run_date, host):
    return f"""<html><body style="font-family:Calibri,Arial,sans-serif;font-size:13px;color:#222;">
<p>The <strong>Cardinal Daily Invoice Upload</strong> encountered an error and did not complete.</p>
<table border="1" cellpadding="0" cellspacing="0"
       style="border-collapse:collapse;border-color:#bbb;width:540px;">
  <tr style="background:{_HEADER_RED};color:white;">
    <th colspan="2" style="text-align:left;padding:8px;">Error Details</th>
  </tr>
  {_row("Run Date", run_date)}
  {_row("Host",     host)}
  <tr>
    <td style="background:#f9e1e1;padding:5px 8px;width:200px;"><b>Error</b></td>
    <td style="padding:5px 8px;font-family:monospace;
        white-space:pre-wrap;font-size:12px;">{error_msg}</td>
  </tr>
  <tr style="background:{_FAILURE_BG};">
    <td colspan="2" style="text-align:center;color:{_FAILURE_FG};
        font-weight:bold;padding:7px;">
      &#10007; FAILED &mdash; See attached log for details.
    </td>
  </tr>
</table>
<p style="color:#888;font-size:11px;margin-top:16px;">
  Automated notification &mdash; Cardinal ETL Pipeline
</p>
</body></html>"""


# ── Convenience wrappers (called from Cardinal_Inv_Upload.py) ──────────────────
def send_success_notification(config, secrets, run_stats, log_path=None):
    """Send success email with optional log attachment."""
    notif   = config["notification"]
    subject = f"Cardinal Invoice Upload - SUCCESS [{run_stats.get('run_date', '')}]"
    send_email(
        config, secrets,
        recipients=notif["success_recipients"],
        subject=subject,
        body_html=_success_body(run_stats),
        attachment_path=log_path,
        cc_recipients=notif.get("success_cc_recipients") or [],
    )


def send_failure_notification(config, secrets, error_msg, run_date, host, log_path=None):
    """Send failure/alert email with optional log attachment."""
    notif   = config["notification"]
    subject = f"Cardinal Invoice Upload - FAILED [{run_date}]"
    send_email(
        config, secrets,
        recipients=notif["failure_recipients"],
        subject=subject,
        body_html=_failure_body(error_msg or "Unknown error", run_date, host),
        attachment_path=log_path,
        cc_recipients=notif.get("failure_cc_recipients") or [],
    )
