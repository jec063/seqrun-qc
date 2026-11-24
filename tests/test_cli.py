import csv
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from seqrun_qc.cli import inspect_step, main, read_samples


class SampleSheetTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.sheet = self.root / "samples.csv"
        (self.root / "R1.fq").touch()
        (self.root / "R2.fq").touch()

    def test_checks_both_duplicates_blank_id_and_missing_mates(self):
        self.sheet.write_text(
            "sample_id,read1,read2\n"
            " good ,R1.fq,R2.fq\n"
            "dup,R1.fq,R2.fq\n"
            "dup,R1.fq,absent.fq\n"
            ",,R2.fq\n"
            "../escape,R1.fq,R2.fq\n",
            encoding="utf-8",
        )
        samples = read_samples(self.sheet)
        self.assertEqual([sample["row"] for sample in samples], [2, 3, 4, 5, 6])
        self.assertEqual(samples[0]["sample_id"], "good")
        self.assertEqual(samples[0]["issues"], [])
        self.assertEqual(samples[1]["issues"], ["duplicate sample_id"])
        self.assertEqual(samples[2]["issues"], ["duplicate sample_id", "missing read2 file: absent.fq"])
        self.assertEqual(samples[3]["issues"], ["blank sample_id", "missing read1 path"])
        self.assertIn("safe directory name", samples[4]["issues"][0])

    def test_rejects_missing_header(self):
        self.sheet.write_text("sample_id,read1\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "CSV header"):
            read_samples(self.sheet)

    def test_reports_physical_line_for_multiline_records(self):
        self.sheet.write_text(
            'sample_id,read1,read2,note\ngood,R1.fq,R2.fq,"first\nsecond"\nshort,R1.fq\n',
            encoding="utf-8",
        )
        good, short = read_samples(self.sheet)
        self.assertEqual(good["row"], 2)
        self.assertEqual(short["row"], 4)
        self.assertEqual(short["issues"], ["column count differs from header", "missing read2 path"])

    def test_check_leaves_step_columns_empty_for_invalid_rows(self):
        self.sheet.write_text(
            "sample_id,read1,read2\nvalid,R1.fq,R2.fq\ninvalid,R1.fq,\n", encoding="utf-8"
        )
        report = self.root / "report.csv"
        with redirect_stdout(io.StringIO()) as terminal:
            result = main(["check", str(self.sheet), str(self.root), "--report", str(report)])
        self.assertEqual(result, 1)
        self.assertIn("2 rows checked, 1 need correction.", terminal.getvalue())
        with report.open(newline="", encoding="utf-8") as handle:
            valid, invalid = csv.DictReader(handle)
        self.assertEqual(valid["trim_status"], "pending")
        self.assertEqual(invalid["trim_status"], "")
        self.assertEqual(invalid["issues"], "missing read2 path")


class StepTests(unittest.TestCase):
    def test_status_and_evidence(self):
        cases = [
            ((), "pending"),
            (("one",), "incomplete"),
            (("one", "two"), "incomplete"),
            (("done.marker",), "incomplete"),
            (("done.marker", "one", "two"), "complete"),
            (("failed.txt", "one"), "failed"),
            (("failed.txt", "done.marker", "one", "two"), "incomplete"),
        ]
        for files, expected in cases:
            with self.subTest(files=files), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                for name in files:
                    (directory / name).touch()
                status, evidence = inspect_step(directory, ("one", "two"))
                self.assertEqual(status, expected)
                known = ("done.marker", "failed.txt", "one", "two")
                present = ", ".join(name for name in known if name in files) or "none"
                absent = ", ".join(name for name in known if name not in files) or "none"
                self.assertEqual(evidence, f"{directory}: present [{present}]; absent [{absent}]")
