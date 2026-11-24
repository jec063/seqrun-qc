import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from seqrun_qc.cli import main
from seqrun_qc.reports import format_evidence


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.sheet = self.root / "samples.csv"
        self.report = self.root / "report.csv"
        self.snapshot = self.root / "snapshot.json"
        self.read = self.root / "reads.fq"
        self.read.touch()
        self.output = self.root / "output"
        self.output.mkdir()
        self.sheet.write_text(
            "sample_id,read1,read2\nvalid,reads.fq,reads.fq\n"
            "dup,reads.fq,reads.fq\ndup,reads.fq,absent.fq\n,,reads.fq\n",
            encoding="utf-8",
        )
        self.args = ["check", str(self.sheet), str(self.output), "--report", str(self.report)]

    def test_snapshot_matches_legacy_csv_and_preserves_invalid_rows(self):
        with redirect_stdout(io.StringIO()) as legacy:
            self.assertEqual(main(self.args), 1)
        original = self.report.read_bytes()
        with redirect_stdout(io.StringIO()) as current:
            self.assertEqual(main([*self.args, "--json-report", str(self.snapshot)]), 1)
        self.assertEqual(current.getvalue(), legacy.getvalue() + f"JSON report: {self.snapshot}\n")
        self.assertEqual(self.report.read_bytes(), original)

        snapshot = json.loads(self.snapshot.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual([step["name"] for step in snapshot["steps"]], ["trim", "qc"])
        self.assertEqual(snapshot["status_totals"], dict(complete=0, failed=0, incomplete=0, pending=2))
        rows = snapshot["rows"]
        self.assertEqual([row["sample_id"] for row in rows], ["valid", "dup", "dup", ""])
        self.assertEqual(rows[2]["issues"], ["duplicate sample_id", "missing read2 file: absent.fq"])
        self.assertTrue(all(row["issues"] and not row["steps"] for row in rows[1:]))
        with self.report.open(newline="", encoding="utf-8") as handle:
            record = next(csv.DictReader(handle))
        trim = rows[0]["steps"]["trim"]
        self.assertEqual(record["trim_status"], trim["status"])
        self.assertEqual(record["trim_evidence"], format_evidence(trim["evidence"]))

    def test_invalid_destination_leaves_first_report_untouched(self):
        self.report.write_text("original", encoding="utf-8")
        alias = self.root / "alias.json"
        alias.hardlink_to(self.report)
        expected_artifact = self.output / "valid" / "trim" / "done.marker"
        expected_artifact.parent.mkdir(parents=True)
        config = self.root / "steps.json"
        config.write_text('{"steps":[{"name":"trim","outputs":["out"]}]}', encoding="utf-8")
        self.args.extend(("--config", str(config)))
        for destination in (
            self.report, alias, self.sheet, self.read, config, expected_artifact,
            self.output, self.root / "missing" / "report.json",
        ):
            with self.subTest(destination=destination), redirect_stderr(io.StringIO()):
                self.assertEqual(main([*self.args, "--json-report", str(destination)]), 2)
                self.assertEqual(self.report.read_text(encoding="utf-8"), "original")
        self.assertFalse(expected_artifact.exists())
