import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from seqrun_qc.cli import main
from seqrun_qc.comparison import compare_snapshots
from seqrun_qc.snapshots import STATUSES


def definition(name, output="out.bam"):
    return {
        "name": name, "directory": "{sample_id}/{step}", "done_marker": "done.marker",
        "failed_marker": "failed.txt", "outputs": [output],
    }


def snapshot(steps, samples, invalid=()):
    rows = []
    totals = dict.fromkeys(STATUSES, 0)
    for sample_id, statuses in samples.items():
        results = {}
        for step, status in zip(steps, statuses):
            totals[status] += 1
            results[step["name"]] = {
                "status": status,
                "evidence": {
                    "directory": f"no-longer-on-disk/{sample_id}",
                    "present": [],
                    "absent": step["outputs"],
                },
            }
        rows.append((sample_id, [], results))
    rows.extend((sample_id, issues, {}) for sample_id, issues in invalid)
    return {
        "schema_version": 1,
        "steps": steps,
        "status_totals": totals,
        "rows": [
            {"row": line, "sample_id": sample_id, "read1": "r1.fq", "read2": "r2.fq",
             "issues": issues, "steps": results}
            for line, (sample_id, issues, results) in enumerate(rows, start=2)
        ],
    }


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.before = self.root / "before.json"
        self.after = self.root / "after.json"
        self.report = self.root / "report.json"
        self.html = self.root / "report.html"
        self.args = ["compare", str(self.before), str(self.after)]

    def write_snapshots(self, before, after):
        self.before.write_text(json.dumps(before), encoding="utf-8")
        self.after.write_text(json.dumps(after), encoding="utf-8")

    def test_reordered_rows_and_invalid_samples(self):
        old = snapshot(
            [definition("qc"), definition("removed")],
            {"z": ("complete", "complete"), "a": ("incomplete", "pending"),
             "gone": ("complete", "complete")},
            [("dup", ["duplicate sample_id"]), ("dup", ["duplicate sample_id", "missing read"])],
        )
        new = snapshot(
            [definition("added"), definition("qc")],
            {"new": ("pending", "pending"), "z": ("complete", "failed"),
             "a": ("complete", "complete")},
            [("gone", ["missing read"])],
        )
        result = compare_snapshots(old, new)
        self.assertEqual(result["added_samples"], ["new"])
        self.assertEqual(result["removed_samples"], ["gone"])
        self.assertEqual(result["added_steps"], ["added"])
        self.assertEqual(result["removed_steps"], ["removed"])
        self.assertEqual(result["validation"], {
            "before": {"rows": 5, "rows_with_issues": 2, "issues": 3},
            "after": {"rows": 4, "rows_with_issues": 1, "issues": 1},
        })
        self.assertEqual(
            [(item["sample_id"], item["change"]) for item in result["transitions"]],
            [("a", "recovery"), ("z", "regression")],
        )
        self.write_snapshots(old, new)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([*self.args, "--json-report", str(self.report)]), 0)
        original = self.report.read_bytes()
        for document in (old, new):
            document["rows"].reverse()
            for line, row in enumerate(document["rows"], start=2):
                row["row"] = line
        self.write_snapshots(old, new)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([*self.args, "--json-report", str(self.report)]), 0)
        self.assertEqual(self.report.read_bytes(), original)

    def test_definition_changes_are_separate_from_regressions(self):
        old = snapshot([definition("align")], {"sample": ("complete",)})
        new = snapshot([definition("align", "new.bam")], {"sample": ("failed",)})
        self.write_snapshots(old, new)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main([*self.args, "--fail-on-regression",
                                   "--json-report", str(self.report)]), 0)
        self.assertIn("Changed step definitions: 'align'", output.getvalue())
        result = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(result["transitions"], [])
        self.assertEqual(result["changed_definitions"][0]["before"]["outputs"], ["out.bam"])
        self.assertEqual(result["samples"][0]["steps"][0]["change"], "definition_changed")

    def test_fail_on_regression_writes_both_reports(self):
        old = snapshot([definition("align")], {"sample": ("complete",)})
        new = snapshot([definition("align")], {"sample": ("pending",)})
        self.write_snapshots(old, new)
        args = [*self.args, "--json-report", str(self.report), "--html-report", str(self.html)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
            self.assertEqual(main([*args, "--fail-on-regression"]), 1)
        self.assertEqual(json.loads(self.report.read_text(encoding="utf-8"))["counts"]["regressions"], 1)
        self.assertIn("Regression", self.html.read_text(encoding="utf-8"))

    def test_rejects_invalid_snapshots_without_writing_a_report(self):
        valid = snapshot([definition("align")], {"sample": ("pending",)})
        unsupported = {**valid, "schema_version": 2}
        invalid_status = copy.deepcopy(valid)
        invalid_status["rows"][0]["steps"]["align"]["status"] = "unknown"
        duplicate = copy.deepcopy(valid)
        duplicate["rows"].append({**duplicate["rows"][0], "row": 3})
        bad_totals = {**valid, "status_totals": dict.fromkeys(STATUSES, 0)}
        self.after.write_text(json.dumps(valid), encoding="utf-8")
        self.report.write_text("original", encoding="utf-8")
        cases = (
            ("{", "invalid snapshot"),
            (json.dumps(unsupported), "unsupported schema version"),
            (json.dumps(invalid_status), "invalid status"),
            (json.dumps(duplicate), "duplicate valid sample ID"),
            (json.dumps(bad_totals), "status totals do not match"),
        )
        for contents, message in cases:
            with self.subTest(message=message), redirect_stderr(io.StringIO()) as error:
                self.before.write_text(contents, encoding="utf-8")
                self.assertEqual(main([*self.args, "--json-report", str(self.report)]), 2)
                self.assertIn(message, error.getvalue())
                self.assertEqual(self.report.read_text(encoding="utf-8"), "original")

    def test_reports_cannot_overwrite_snapshots_or_each_other(self):
        data = snapshot([definition("align")], {"sample": ("complete",)})
        self.write_snapshots(data, data)
        original = self.before.read_bytes()
        alias = self.root / "alias.json"
        alias.symlink_to(self.before)
        for target in (self.report, alias):
            with self.subTest(target=target), redirect_stderr(io.StringIO()):
                self.assertEqual(main([*self.args, "--json-report", str(self.report),
                                       "--html-report", str(target)]), 2)
                self.assertFalse(self.report.exists())
                self.assertEqual(self.before.read_bytes(), original)

    def test_html_escapes_untrusted_snapshot_values(self):
        sample = '<script>alert("sample")</script>'
        step = "<mark>step</mark>"
        raw_evidence = '<img src=x onerror="alert(1)"> & evidence'
        before = snapshot([definition(step)], {sample: ("complete",)})
        after = snapshot([definition(step)], {sample: ("failed",)})
        after["rows"][0]["steps"][step]["evidence"]["directory"] = raw_evidence
        self.write_snapshots(before, after)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([*self.args, "--html-report", str(self.html)]), 0)
        html = self.html.read_text(encoding="utf-8")
        self.assertNotIn(sample, html)
        self.assertNotIn(step, html)
        self.assertNotIn(raw_evidence, html)
        self.assertIn("&lt;script&gt;alert(&quot;sample&quot;)&lt;/script&gt;", html)
        self.assertIn("&lt;mark&gt;step&lt;/mark&gt;", html)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; evidence", html)
