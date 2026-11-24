import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
        self.assertIn("Steps: 0 complete, 0 failed, 0 incomplete, 2 pending.", terminal.getvalue())
        with report.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, [
                "row", "sample_id", "read1", "read2", "issues",
                "trim_status", "trim_evidence", "qc_status", "qc_evidence",
            ])
            valid, invalid = reader
        self.assertEqual(valid["trim_status"], "pending")
        self.assertEqual(invalid["trim_status"], "")
        self.assertEqual(invalid["issues"], "missing read2 path")


class ConfigTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.config = self.root / "steps.json"
        self.report = self.root / "report.csv"
        sheet = self.root / "samples.csv"
        sheet.write_text("sample_id,read1,read2\nsample,R1.fq,R2.fq\n", encoding="utf-8")
        (self.root / "R1.fq").touch()
        (self.root / "R2.fq").touch()
        self.args = [
            "check", str(sheet), str(self.root), "--report", str(self.report),
            "--config", str(self.config),
        ]

    def test_custom_steps_replace_defaults_in_config_order(self):
        self.config.write_text(json.dumps({"steps": [
            {"name": "qc", "outputs": ["custom.tsv"]},
            {"name": "align", "outputs": ["aligned.bam", "aligned.bam.bai"]},
        ]}), encoding="utf-8")
        qc = self.root / "sample" / "qc"
        align = self.root / "sample" / "align"
        for step in (qc, align):
            step.mkdir(parents=True)
            (step / "done.marker").touch()
        (qc / "metrics.tsv").touch()
        (align / "aligned.bam").touch()
        (align / "aligned.bam.bai").touch()

        with redirect_stdout(io.StringIO()) as terminal:
            self.assertEqual(main(self.args), 1)
        self.assertIn("Steps: 1 complete, 0 failed, 1 incomplete, 0 pending.", terminal.getvalue())
        with self.report.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, [
                "row", "sample_id", "read1", "read2", "issues",
                "qc_status", "qc_evidence", "align_status", "align_evidence",
            ])
            row, = reader
        self.assertEqual(row["qc_status"], "incomplete")
        self.assertIn("absent [failed.txt, custom.tsv]", row["qc_evidence"])
        self.assertEqual(row["align_status"], "complete")
        self.assertIn("present [done.marker, aligned.bam, aligned.bam.bai]", row["align_evidence"])

    def test_invalid_config_leaves_existing_report_untouched(self):
        cases = [
            ("{", "Expecting"),
            ('{"steps": [], "extra": NaN}', "invalid JSON constant"),
            ("[]", "expected a JSON object"),
            ('{"steps": []}', "steps must be a nonempty list"),
            ('{"steps": [42]}', "step 1 must be an object"),
            ('{"steps": [{"name": "qc", "outputs": []}]}', "outputs must be a nonempty list"),
            ('{"steps": [{"name": "qc", "outputs": "out"}]}', "outputs must be a nonempty list"),
        ]
        repeated_steps = [{"name": name, "outputs": ["out"]} for name in ("qc", "QC")]
        cases.append((json.dumps({"steps": repeated_steps}), "duplicate step name"))
        for name in ("", ".", "..", "stage/child", r"stage\child", "/outside", "C:stage"):
            cases.append((
                json.dumps({"steps": [{"name": name, "outputs": ["out"]}]}),
                "step 1 name must be a nonempty, safe single path component",
            ))
        for filename in ("", ".", "..", "sub/file", r"sub\file", "/tmp/file", "C:file", "\x00"):
            cases.append((
                json.dumps({"steps": [{"name": "qc", "outputs": [filename]}]}),
                "step 1 output 1 must be a nonempty, safe single path component",
            ))
        cases.append(('{"steps": [{"name": "qc", "outputs": [42]}]}', "output 1 must be a string"))
        for filename in ("done.marker", "failed.txt", "DONE.MARKER"):
            cases.append((
                json.dumps({"steps": [{"name": "qc", "outputs": [filename]}]}),
                "collides with a reserved marker",
            ))

        original_report = b"keep,original\r\n"
        self.report.write_bytes(original_report)
        for contents, message in cases:
            with self.subTest(contents=contents), redirect_stderr(io.StringIO()) as errors:
                self.config.write_text(contents, encoding="utf-8")
                self.assertEqual(main(self.args), 2)
                self.assertIn(f"invalid config {self.config}", errors.getvalue())
                self.assertIn(message, errors.getvalue())
                self.assertEqual(self.report.read_bytes(), original_report)

    def test_unreadable_config_does_not_create_report(self):
        with redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(main(self.args), 2)
        self.assertIn(f"invalid config {self.config}", errors.getvalue())
        self.assertFalse(self.report.exists())

    def test_flat_and_nested_layouts_use_expanded_markers(self):
        output = self.root / "sample.align.bam"
        output.touch()
        (self.root / "sample.done").touch()
        nested = self.root / "work" / "sample" / "qc"
        nested.mkdir(parents=True)
        (nested / "qc.failed").touch()
        self.config.write_text(json.dumps({"steps": [
            {"name": "align", "directory": ".", "outputs": ["{sample_id}.{step}.bam"],
             "done_marker": "{sample_id}.done", "failed_marker": "{sample_id}.failed"},
            {"name": "qc", "directory": "work/{sample_id}/{step}", "outputs": ["metrics.tsv"],
             "failed_marker": "{step}.failed"},
        ]}), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(self.args), 1)
        with self.report.open(newline="", encoding="utf-8") as handle:
            row, = csv.DictReader(handle)
        self.assertEqual(row["align_status"], "complete")
        self.assertIn("present [sample.done, sample.align.bam]", row["align_evidence"])
        self.assertEqual(row["qc_status"], "failed")
        self.assertIn(f"{nested}: present [qc.failed]", row["qc_evidence"])

    def test_invalid_layouts_leave_report_untouched(self):
        cases = [
            ({"directory": "{other}/qc"}, "unknown or malformed placeholder"),
            ({"outputs": ["{sample_id!r}.txt"]}, "unknown or malformed placeholder"),
            ({"failed_marker": "{step"}, "unknown or malformed placeholder"),
            ({"directory": "/tmp"}, "relative to OUTPUT_DIR"),
            ({"directory": "{step}/../../extra"}, "relative to OUTPUT_DIR"),
            ({"directory": r"C:\outside"}, "safe single path component"),
            ({"done_marker": "{sample_id}/done"}, "safe single path component"),
            ({"done_marker": "{sample_id}", "failed_marker": "SAMPLE"}, "colliding"),
            ({"outputs": ["{step}.txt", "QC.txt"]}, "duplicate output filename"),
            ({"outputs": ["{sample_id}.txt"], "failed_marker": "sample.txt"}, "reserved marker"),
            ({"outputs": ["{step}1.txt"], "name": "com"}, "safe single path component"),
        ]
        self.report.write_bytes(b"original")
        for overrides, message in cases:
            config = {"steps": [{"name": "qc", "outputs": ["file"], **overrides}]}
            with self.subTest(config=config), redirect_stderr(io.StringIO()) as errors:
                self.config.write_text(json.dumps(config), encoding="utf-8")
                self.assertEqual(main(self.args), 2)
                self.assertIn(message, errors.getvalue())
                self.assertEqual(self.report.read_bytes(), b"original")

    def test_symlinks_cannot_escape_output_directory(self):
        output = self.root / "output"
        output.mkdir()
        self.args[2] = str(output)
        (output / "linked").symlink_to(self.root, target_is_directory=True)
        (output / "artifact").symlink_to(self.root / "R1.fq")
        for directory in ("linked", "."):
            config = {"steps": [{"name": "qc", "directory": directory, "outputs": ["artifact"]}]}
            with self.subTest(directory=directory), redirect_stderr(io.StringIO()) as errors:
                self.config.write_text(json.dumps(config), encoding="utf-8")
                self.assertEqual(main(self.args), 2)
                self.assertIn("path escapes OUTPUT_DIR", errors.getvalue())
                self.assertFalse(self.report.exists())


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
