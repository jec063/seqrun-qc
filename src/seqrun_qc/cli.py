"""Check paired-end input paths and inspect local pipeline artifacts."""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath

from .reports import format_evidence, validate_destinations, write_json

DONE_MARKER = "done.marker"
FAILURE_RECORD = "failed.txt"
SCHEMA_VERSION = 1
STATUSES = ("complete", "failed", "incomplete", "pending")
REQUIRED_COLUMNS = ("sample_id", "read1", "read2")
PLACEHOLDER = re.compile(r"\{(sample_id|step)\}")


@dataclass(frozen=True)
class Step:
    outputs: tuple[str, ...]
    directory: str | None = None
    done_marker: str = DONE_MARKER
    failed_marker: str = FAILURE_RECORD


DEFAULT_STEPS = {
    "trim": Step(("read1.trimmed.fastq", "read2.trimmed.fastq")),
    "qc": Step(("metrics.tsv",)),
}


def validate_component(value, field):
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.endswith((".", " "))
        or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f\ud800-\udfff]', value)
        or PureWindowsPath(value).is_reserved()
    ):
        raise ValueError(f"{field} must be a nonempty, safe single path component")


def validate_directory(value, field):
    if value.startswith("/") or ".." in value.split("/"):
        raise ValueError(f"{field} must be relative to OUTPUT_DIR without parent traversal")
    for component in value.split("/"):
        if component != ".":
            validate_component(component, field)


def validate_template(value, field, validate=validate_component):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    remainder = PLACEHOLDER.sub("", value)
    if "{" in remainder or "}" in remainder:
        raise ValueError(f"{field} has an unknown or malformed placeholder")
    validate(value, field)
    return value


def validate_filenames(done, failed, outputs, label):
    markers = {done.casefold(), failed.casefold()}
    if len(markers) != 2:
        raise ValueError(f"{label} has colliding done and failed marker filenames")
    seen = set()
    for index, output in enumerate(outputs, start=1):
        key = output.casefold()
        if key in markers:
            raise ValueError(f"{label} output {index} collides with a reserved marker: {output!r}")
        if key in seen:
            raise ValueError(f"{label} has duplicate output filename {output!r}")
        seen.add(key)


def reject_json_constant(value):
    raise ValueError(f"invalid JSON constant {value}")


def load_steps(config):
    try:
        with config.open(encoding="utf-8") as handle:
            document = json.load(handle, parse_constant=reject_json_constant)
        if not isinstance(document, dict):
            raise ValueError("expected a JSON object with a steps list")
        entries = document.get("steps")
        if not isinstance(entries, list) or not entries:
            raise ValueError("steps must be a nonempty list")

        steps = {}
        names = set()
        for index, entry in enumerate(entries, start=1):
            label = f"step {index}"
            if not isinstance(entry, dict):
                raise ValueError(f"{label} must be an object")
            name = entry.get("name")
            validate_component(name, f"{label} name")
            if name.casefold() in names:
                raise ValueError(f"{label} has duplicate step name {name!r}")
            names.add(name.casefold())

            outputs = entry.get("outputs")
            if not isinstance(outputs, list) or not outputs:
                raise ValueError(f"{label} outputs must be a nonempty list")
            directory = None
            if "directory" in entry:
                directory = validate_template(
                    entry["directory"], f"{label} directory", validate_directory
                )
            done = validate_template(entry.get("done_marker", DONE_MARKER), f"{label} done_marker")
            failed = validate_template(
                entry.get("failed_marker", FAILURE_RECORD), f"{label} failed_marker"
            )
            filenames = tuple(
                validate_template(filename, f"{label} output {index}")
                for index, filename in enumerate(outputs, start=1)
            )
            validate_filenames(done, failed, filenames, label)
            steps[name] = Step(filenames, directory, done, failed)
        return steps
    except (OSError, ValueError, RecursionError) as exc:
        raise ValueError(f"invalid config {config}: {exc}") from exc


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


def locate_step(output_dir, root, sample_id, name, step):
    values = {"sample_id": sample_id, "step": name}
    label = f"sample {sample_id!r}, step {name!r}"

    def expand(template):
        return PLACEHOLDER.sub(lambda match: values[match[1]], template)

    if step.directory is None:
        directory = output_dir / sample_id / name
    else:
        relative = expand(step.directory)
        validate_directory(relative, f"{label} directory")
        directory = output_dir / relative

    done, failed, *outputs = (
        expand(template) for template in (step.done_marker, step.failed_marker, *step.outputs)
    )
    for filename in (done, failed, *outputs):
        validate_component(filename, f"{label} filename {filename!r}")
    validate_filenames(done, failed, outputs, label)

    for path in (directory, *(directory / filename for filename in (done, failed, *outputs))):
        try:
            resolved = path.resolve()
        except RuntimeError as exc:
            raise ValueError(f"{label}: cannot resolve path {path}") from exc
        if not resolved.is_relative_to(root):
            raise ValueError(f"{label}: path escapes OUTPUT_DIR: {path}")
    return directory, outputs, done, failed


def inspect_step(directory, outputs, done_marker=DONE_MARKER, failed_marker=FAILURE_RECORD):
    names = (done_marker, failed_marker, *outputs)
    present = [name for name in names if (directory / name).is_file()]
    missing = [name for name in names if name not in present]
    done = done_marker in present
    failed = failed_marker in present
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
    return {
        "status": status,
        "evidence": {"directory": str(directory), "present": present, "absent": missing},
    }


def collect_snapshot(sheet, output_dir, steps):
    if not output_dir.is_dir():
        raise ValueError(f"pipeline output directory does not exist: {output_dir}")
    root = output_dir.resolve()
    rows = read_samples(sheet)
    totals = dict.fromkeys(STATUSES, 0)
    inputs = {sheet, output_dir}
    for row in rows:
        for key in REQUIRED_COLUMNS:
            row.setdefault(key, "")
        for key in ("read1", "read2"):
            if row[key] and "\x00" not in row[key]:
                inputs.add(sheet.parent / row[key])
        row["steps"] = {}
        if row["issues"]:
            continue
        for name, step in steps.items():
            directory, outputs, done, failed = locate_step(
                output_dir, root, row["sample_id"], name, step
            )
            result = inspect_step(directory, outputs, done, failed)
            row["steps"][name] = result
            totals[result["status"]] += 1
            inputs.update(directory / filename for filename in (done, failed, *outputs))

    definitions = []
    for name, step in steps.items():
        definition = asdict(step)
        if definition["directory"] is None:
            definition["directory"] = "{sample_id}/{step}"
        definitions.append({"name": name, **definition})
    return {
        "schema_version": SCHEMA_VERSION,
        "steps": definitions,
        "status_totals": totals,
        "rows": rows,
    }, inputs


def write_csv(report, snapshot):
    fields = ["row", *REQUIRED_COLUMNS, "issues"]
    for step in snapshot["steps"]:
        name = step["name"]
        fields.extend((f"{name}_status", f"{name}_evidence"))
    with report.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in snapshot["rows"]:
            record = {key: row[key] for key in ("row", *REQUIRED_COLUMNS)}
            record["issues"] = "; ".join(row["issues"])
            for name, result in row["steps"].items():
                record[f"{name}_status"] = result["status"]
                record[f"{name}_evidence"] = format_evidence(result["evidence"])
            writer.writerow(record)


def check(sheet, output_dir, report, steps=DEFAULT_STEPS, *, json_report=None, config=None):
    snapshot, inputs = collect_snapshot(sheet, output_dir, steps)
    if config is not None:
        inputs.add(config)
    destinations = [report] if json_report is None else [report, json_report]
    validate_destinations(destinations, inputs)
    write_csv(report, snapshot)
    if json_report is not None:
        write_json(json_report, snapshot)

    rows = snapshot["rows"]
    invalid = [row for row in rows if row["issues"]]
    totals = snapshot["status_totals"]
    print(f"{len(rows)} rows checked, {len(invalid)} need correction.")
    for row in invalid:
        print(f"  Row {row['row']} ({row['sample_id'] or 'blank ID'}): {'; '.join(row['issues'])}")
    print("Steps: " + ", ".join(f"{totals[status]} {status}" for status in STATUSES) + ".")
    print(f"CSV report: {report}")
    if json_report is not None:
        print(f"JSON report: {json_report}")
    return int(bool(invalid) or any(totals[status] for status in STATUSES[1:]))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="seqrun-qc")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("check", help="check sample inputs and pipeline artifacts")
    command.add_argument("sample_sheet", type=Path)
    command.add_argument("output_dir", type=Path, help="existing pipeline output directory")
    command.add_argument("--report", type=Path, default=Path("seqrun-qc-status.csv"))
    command.add_argument("--json-report", type=Path, help="write a JSON run snapshot")
    command.add_argument("--config", type=Path, help="JSON file defining pipeline steps")
    args = parser.parse_args(argv)
    try:
        steps = DEFAULT_STEPS
        if args.config is not None:
            steps = load_steps(args.config)
        return check(
            args.sample_sheet, args.output_dir, args.report, steps,
            json_report=args.json_report, config=args.config,
        )
    except (OSError, ValueError, RuntimeError, csv.Error) as exc:
        print(f"seqrun-qc: {exc}", file=sys.stderr)
        return 2
