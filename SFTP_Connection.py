import fnmatch
import os
import posixpath
import stat
from datetime import datetime, timedelta
from pathlib import Path

import paramiko
import yaml
from dotenv import load_dotenv

from windows_impersonation import impersonate_user, whoami_network


ROOT_DIR = Path(__file__).parent
CONFIG_PATH = ROOT_DIR / "config.yaml"
ENV_PATH = ROOT_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH, override=True)

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

sftp_config = config["sftp"]
paths_config = config["paths"]
sequence_config = config.get("sequence", {})

SFTP_HOST = sftp_config["host"]
SFTP_PORT = sftp_config["port"]
SFTP_USERNAME = sftp_config["username"]
SFTP_PASSWORD = sftp_config["password"]
REMOTE_SOURCE_FOLDER = sftp_config["remote_source_folder"]
LOCAL_DESTINATION_FOLDER = sftp_config["local_destination_folder"]
ARCHIVE_FOLDER = paths_config["archive_dir"]
FILE_PATTERN = sftp_config.get("file_pattern", "*")
WINDOW_END_HOUR = int(sequence_config.get("window_end_hour", 11))

SERVICE_USER = os.environ.get("SERVICE_USER", r"DM_MONTYNT\svc_procure_data")
SERVICE_PASS = os.environ.get("SERVICE_PASS", "")
SERVICE_DOMAIN = os.environ.get("SERVICE_DOMAIN", "DM_MONTYNT")

_svc_parts = SERVICE_USER.split("\\")
_SVC_DOMAIN = _svc_parts[0] if len(_svc_parts) == 2 else SERVICE_DOMAIN
_SVC_USERNAME = _svc_parts[-1]


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def get_default_window(now=None):
    """Return [previous day 11am, current day 11am) in local server time."""
    now = now or datetime.now()
    window_end = now.replace(
        hour=WINDOW_END_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )
    window_start = window_end - timedelta(days=1)
    return window_start, window_end


def is_remote_file(remote_attr):
    if remote_attr.st_mode is not None:
        return stat.S_ISREG(remote_attr.st_mode)

    return str(remote_attr.longname).startswith("-")


def is_in_window(remote_attr, window_start, window_end):
    if remote_attr.st_mtime is None:
        return False

    remote_modified = datetime.fromtimestamp(remote_attr.st_mtime)
    return window_start <= remote_modified < window_end


def get_matching_remote_files(sftp, window_start, window_end):
    matching_files = []

    for remote_attr in sftp.listdir_attr(REMOTE_SOURCE_FOLDER):
        file_name = remote_attr.filename

        if not fnmatch.fnmatch(file_name, FILE_PATTERN):
            continue

        if not is_remote_file(remote_attr):
            log(f"Skipping folder/non-file: {file_name}")
            continue

        if not is_in_window(remote_attr, window_start, window_end):
            continue

        matching_files.append(remote_attr)

    return sorted(matching_files, key=lambda attr: attr.st_mtime or 0)


def local_or_archive_exists(file_name):
    local_path = os.path.join(LOCAL_DESTINATION_FOLDER, file_name)
    archive_path = os.path.join(ARCHIVE_FOLDER, file_name)
    return os.path.exists(local_path) or os.path.exists(archive_path)


def preserve_download_timestamp(sftp, remote_path, local_path, remote_attr):
    original_atime = remote_attr.st_atime
    original_mtime = remote_attr.st_mtime

    sftp.get(remote_path, local_path)

    if original_atime is not None and original_mtime is not None:
        os.utime(local_path, (original_atime, original_mtime))
        log(f"Timestamp preserved: {datetime.fromtimestamp(original_mtime)}")


def download_sftp_files(window_start=None, window_end=None):
    if window_start is None or window_end is None:
        default_start, default_end = get_default_window()
        window_start = window_start or default_start
        window_end = window_end or default_end

    os.makedirs(LOCAL_DESTINATION_FOLDER, exist_ok=True)
    os.makedirs(ARCHIVE_FOLDER, exist_ok=True)

    log(
        "SFTP window: "
        f"{window_start:%Y-%m-%d %H:%M:%S} <= modified < "
        f"{window_end:%Y-%m-%d %H:%M:%S}"
    )

    transport = None
    sftp = None
    downloaded_files = []

    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USERNAME, password=SFTP_PASSWORD)
        sftp = paramiko.SFTPClient.from_transport(transport)

        matching_files = get_matching_remote_files(sftp, window_start, window_end)
        if not matching_files:
            log(f"No SFTP files found in window matching {FILE_PATTERN!r}.")
            return downloaded_files

        log(f"Matched SFTP files in window: {len(matching_files)}")

        for remote_attr in matching_files:
            file_name = remote_attr.filename

            if local_or_archive_exists(file_name):
                log(f"Skipping already downloaded/archived file: {file_name}")
                continue

            remote_path = posixpath.join(REMOTE_SOURCE_FOLDER, file_name)
            local_path = os.path.join(LOCAL_DESTINATION_FOLDER, file_name)

            log(f"Copying: {remote_path} -> {local_path}")
            preserve_download_timestamp(
                sftp=sftp,
                remote_path=remote_path,
                local_path=local_path,
                remote_attr=remote_attr,
            )
            downloaded_files.append(local_path)
            log(f"Copied SFTP file: {file_name}")

    finally:
        if sftp is not None:
            sftp.close()
        if transport is not None:
            transport.close()
        log("SFTP connection closed.")

    return downloaded_files


def run_sftp_download(window_start=None, window_end=None):
    if not SERVICE_PASS:
        raise EnvironmentError("Missing required .env value: SERVICE_PASS")

    target_identity = f"{_SVC_DOMAIN}\\{_SVC_USERNAME}"
    log(f"Starting Windows impersonation for network drive access: {target_identity}")

    with impersonate_user(_SVC_DOMAIN, _SVC_USERNAME, SERVICE_PASS):
        try:
            active_identity = whoami_network()
        except Exception:
            active_identity = target_identity

        log(f"Impersonation active as: {active_identity}")
        return download_sftp_files(window_start=window_start, window_end=window_end)


def main():
    downloaded_files = run_sftp_download()
    log(f"SFTP download complete. Files downloaded: {len(downloaded_files)}")


if __name__ == "__main__":
    main()
