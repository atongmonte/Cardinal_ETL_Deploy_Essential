import os
import fnmatch
import paramiko
from datetime import datetime


SFTP_HOST = "sftp.example.com"
SFTP_PORT = 22
SFTP_USERNAME = "your_username"
SFTP_PASSWORD = "your_password"

REMOTE_SOURCE_FOLDER = "/incoming"
LOCAL_DESTINATION_FOLDER = r"\\montefiore.org\centralfiles\data\YourFolder"

FILE_PATTERN = "*"


def log(msg):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")


def preserve_download_timestamp(sftp, remote_path, local_path):
    remote_attr = sftp.stat(remote_path)

    original_atime = remote_attr.st_atime
    original_mtime = remote_attr.st_mtime

    sftp.get(remote_path, local_path)

    # Restore local file timestamp to match SFTP file
    os.utime(local_path, (original_atime, original_mtime))

    log(f"Timestamp preserved: {datetime.fromtimestamp(original_mtime)}")


def main():
    os.makedirs(LOCAL_DESTINATION_FOLDER, exist_ok=True)

    transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    transport.connect(
        username=SFTP_USERNAME,
        password=SFTP_PASSWORD
    )

    sftp = paramiko.SFTPClient.from_transport(transport)

    try:
        files = sftp.listdir(REMOTE_SOURCE_FOLDER)

        for file_name in files:
            if not fnmatch.fnmatch(file_name, FILE_PATTERN):
                continue

            remote_path = f"{REMOTE_SOURCE_FOLDER}/{file_name}"
            local_path = os.path.join(LOCAL_DESTINATION_FOLDER, file_name)

            remote_attr = sftp.stat(remote_path)

            # Skip folders
            if not str(remote_attr.longname).startswith("-"):
                log(f"Skipping folder/non-file: {file_name}")
                continue

            log(f"Copying: {remote_path} -> {local_path}")

            preserve_download_timestamp(
                sftp=sftp,
                remote_path=remote_path,
                local_path=local_path
            )

            log(f"Copied with original modified date: {file_name}")

    finally:
        sftp.close()
        transport.close()
        log("SFTP connection closed.")


if __name__ == "__main__":
    main()