import stat
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import Cardinal_ETL_Sequence
import SFTP_Connection


def remote_attr(filename, modified, mode=None):
    return SimpleNamespace(
        filename=filename,
        st_mtime=modified.timestamp(),
        st_atime=modified.timestamp(),
        st_mode=mode if mode is not None else stat.S_IFREG | 0o644,
        longname="-rw-r--r--",
    )


class FakeSFTP:
    def __init__(self, attrs):
        self.attrs = attrs

    def listdir_attr(self, _path):
        return self.attrs


class SequenceLogicTests(unittest.TestCase):
    def test_sftp_window_includes_start_and_excludes_end(self):
        window_start = datetime(2026, 6, 16, 11)
        window_end = datetime(2026, 6, 17, 11)
        attrs = [
            remote_attr("before.txt", datetime(2026, 6, 16, 10, 59, 59)),
            remote_attr("start.txt", datetime(2026, 6, 16, 11)),
            remote_attr("inside.txt", datetime(2026, 6, 17, 10, 59, 59)),
            remote_attr("end.txt", datetime(2026, 6, 17, 11)),
        ]

        matches = SFTP_Connection.get_matching_remote_files(
            FakeSFTP(attrs),
            window_start,
            window_end,
        )

        self.assertEqual([attr.filename for attr in matches], ["start.txt", "inside.txt"])

    def test_sftp_filter_skips_directories(self):
        window_start = datetime(2026, 6, 16, 11)
        window_end = datetime(2026, 6, 17, 11)
        attrs = [
            remote_attr(
                "folder",
                datetime(2026, 6, 16, 12),
                mode=stat.S_IFDIR | 0o755,
            ),
            remote_attr("file.txt", datetime(2026, 6, 16, 12)),
        ]

        matches = SFTP_Connection.get_matching_remote_files(
            FakeSFTP(attrs),
            window_start,
            window_end,
        )

        self.assertEqual([attr.filename for attr in matches], ["file.txt"])

    def test_non_monthly_run_downloads_then_runs_invoice_upload(self):
        calls = []

        with patch.object(Cardinal_ETL_Sequence, "load_config", return_value=self.sequence_config(monthly_run_day=8)), \
             patch.object(Cardinal_ETL_Sequence, "run_sftp_download", side_effect=lambda **_: calls.append("sftp") or []), \
             patch.object(Cardinal_ETL_Sequence, "run_invoice_upload", side_effect=lambda: calls.append("daily")), \
             patch.object(Cardinal_ETL_Sequence, "run_monthly_process", side_effect=lambda: calls.append("monthly")):
            Cardinal_ETL_Sequence.run_sequence(
                run_datetime=datetime(2026, 6, 7, 12),
            )

        self.assertEqual(calls, ["sftp", "daily"])

    def test_monthly_run_downloads_daily_then_monthly_upload(self):
        calls = []

        with patch.object(Cardinal_ETL_Sequence, "load_config", return_value=self.sequence_config(monthly_run_day=8)), \
             patch.object(Cardinal_ETL_Sequence, "run_sftp_download", side_effect=lambda **_: calls.append("sftp") or []), \
             patch.object(Cardinal_ETL_Sequence, "run_invoice_upload", side_effect=lambda: calls.append("daily")), \
             patch.object(Cardinal_ETL_Sequence, "run_monthly_process", side_effect=lambda: calls.append("monthly")):
            Cardinal_ETL_Sequence.run_sequence(
                run_datetime=datetime(2026, 6, 8, 12),
            )

        self.assertEqual(calls, ["sftp", "daily", "monthly"])

    def test_manual_sftp_action_runs_only_sftp_download(self):
        calls = []

        with patch.object(Cardinal_ETL_Sequence, "load_config", return_value=self.sequence_config(monthly_run_day=8)), \
             patch.object(Cardinal_ETL_Sequence, "run_sftp_download", side_effect=lambda **_: calls.append("sftp") or []), \
             patch.object(Cardinal_ETL_Sequence, "run_invoice_upload", side_effect=lambda: calls.append("daily")), \
             patch.object(Cardinal_ETL_Sequence, "run_monthly_process", side_effect=lambda: calls.append("monthly")), \
             patch.object(Cardinal_ETL_Sequence.sys, "argv", ["Cardinal_ETL_Sequence.py", "sftp_download", "--run-date", "2026-06-08"]):
            exit_code = Cardinal_ETL_Sequence.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["sftp"])

    def test_manual_daily_action_runs_only_daily_upload(self):
        calls = []

        with patch.object(Cardinal_ETL_Sequence, "run_sftp_download", side_effect=lambda **_: calls.append("sftp") or []), \
             patch.object(Cardinal_ETL_Sequence, "run_invoice_upload", side_effect=lambda: calls.append("daily")), \
             patch.object(Cardinal_ETL_Sequence, "run_monthly_process", side_effect=lambda: calls.append("monthly")), \
             patch.object(Cardinal_ETL_Sequence.sys, "argv", ["Cardinal_ETL_Sequence.py", "daily_inv_upload"]):
            exit_code = Cardinal_ETL_Sequence.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["daily"])

    def test_manual_monthly_action_runs_only_monthly_upload(self):
        calls = []

        with patch.object(Cardinal_ETL_Sequence, "run_sftp_download", side_effect=lambda **_: calls.append("sftp") or []), \
             patch.object(Cardinal_ETL_Sequence, "run_invoice_upload", side_effect=lambda: calls.append("daily")), \
             patch.object(Cardinal_ETL_Sequence, "run_monthly_process", side_effect=lambda: calls.append("monthly")), \
             patch.object(Cardinal_ETL_Sequence.sys, "argv", ["Cardinal_ETL_Sequence.py", "monthly_catalog_upload"]):
            exit_code = Cardinal_ETL_Sequence.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(calls, ["monthly"])

    def sequence_config(self, monthly_run_day):
        return {
            "sequence": {
                "window_end_hour": 11,
                "monthly_run_day": monthly_run_day,
            }
        }


if __name__ == "__main__":
    unittest.main()
