"""Check paired-end input paths and inspect local pipeline artifacts."""

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

STEPS = {
    "trim": ("read1.trimmed.fastq", "read2.trimmed.fastq"),
    "qc": ("metrics.tsv",),
}
STATUSES = ("complete", "failed", "incomplete", "pending")
REQUIRED_COLUMNS = ("sample_id", "read1", "read2")


def read_samples(sheet):
    with sheet.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, strict=True)
        header = next(reader, [])
        if len(header) != len(set(header)) or not set(REQUIRED_COLUMNS) <= set(header):
            raise ValueError("CSV header must contain unique sample_id, read1 and read2 columns")
        samples = []
        while True:
            line = reader.line_num + 1
            values = next(reader, None)
            if values is None:
                break
            sample = {
                key: value.strip()
                for key, value in zip(header, values)
                if key in REQUIRED_COLUMNS
            }
            sample["row"] = line
            sample["issues"] = []
            if len(values) != len(header):
                sample["issues"].append("column count differs from header")
            samples.append(sample)

    counts = Counter(sample.get("sample_id", "") for sample in samples)
    for sample in samples:
        sample_id = sample.get("sample_id", "")
        issues = sample["issues"]
        if not sample_id:
            issues.append("blank sample_id")
        elif not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", sample_id):
            issues.append("sample_id must be a safe directory name (letters, digits, _, -, .)")
        if sample_id and counts[sample_id] > 1:
            issues.append("duplicate sample_id")
        for mate in ("read1", "read2"):
            value = sample.get(mate, "")
            if not value:
                issues.append(f"missing {mate} path")
            elif not (sheet.parent / value).is_file():
                issues.append(f"missing {mate} file: {value}")
    return samples


def inspect_step(directory, outputs):
    names = ("done.marker", "failed.txt", *outputs)
    present = [name for name in names if (directory / name).is_file()]
    missing = [name for name in names if name not in present]
    done = "done.marker" in present
    failed = "failed.txt" in present
    if done and failed:
        status = "incomplete"
    elif failed:
        status = "failed"
    elif done and all(name in present for name in outputs):
        status = "complete"
    elif present:
        status = "incomplete"
    else:
        status = "pending"
    evidence = (
        f"{directory}: present [{', '.join(present) or 'none'}]; "
        f"absent [{', '.join(missing) or 'none'}]"
    )
    return status, evidence


def check(sheet, output_dir, report):
    if not output_dir.is_dir():
        raise ValueError(f"pipeline output directory does not exist: {output_dir}")
    samples = read_samples(sheet)
    fields = ["row", *REQUIRED_COLUMNS, "issues"]
    for step in STEPS:
        fields.extend((f"{step}_status", f"{step}_evidence"))
    totals = Counter()
    invalid = []
    rows = []
    for sample in samples:
        row = {field: sample.get(field, "") for field in fields}
        row["issues"] = "; ".join(sample["issues"])
        if sample["issues"]:
            invalid.append(row)
        else:
            for step, outputs in STEPS.items():
                status, evidence = inspect_step(output_dir / row["sample_id"] / step, outputs)
                row[f"{step}_status"] = status
                row[f"{step}_evidence"] = evidence
                totals[status] += 1
        rows.append(row)

    if report.resolve() == sheet.resolve() or (
        report.exists() and report.samefile(sheet)
    ):
        raise ValueError("report path must differ from the sample sheet")
    with report.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(samples)} rows checked, {len(invalid)} need correction.")
    for row in invalid:
        print(f"  Row {row['row']} ({row['sample_id'] or 'blank ID'}): {row['issues']}")
    print("Steps: " + ", ".join(f"{totals[status]} {status}" for status in STATUSES) + ".")
    print(f"CSV report: {report}")
    return int(bool(invalid) or any(totals[status] for status in STATUSES[1:]))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="seqrun-qc")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("check", help="check sample inputs and pipeline artifacts")
    command.add_argument("sample_sheet", type=Path)
    command.add_argument("output_dir", type=Path, help="existing pipeline output directory")
    command.add_argument("--report", type=Path, default=Path("seqrun-qc-status.csv"))
    args = parser.parse_args(argv)
    try:
        return check(args.sample_sheet, args.output_dir, args.report)
    except (OSError, ValueError, csv.Error) as exc:
        print(f"seqrun-qc: {exc}", file=sys.stderr)
        return 2
