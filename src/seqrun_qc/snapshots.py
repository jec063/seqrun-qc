"""Read and validate the versioned snapshot format without consulting pipeline files."""

import json

SCHEMA_VERSION = 1
STATUSES = ("complete", "failed", "incomplete", "pending")
DEFINITION_FIELDS = ("name", "directory", "done_marker", "failed_marker", "outputs")


def strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def reject_json_constant(value):
    raise ValueError(f"invalid JSON constant {value}")


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("expected a JSON object")
    version = snapshot.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema version {version!r}; expected {SCHEMA_VERSION}")

    steps = snapshot.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("steps must be a nonempty list")
    names = set()
    for step in steps:
        if not isinstance(step, dict) or any(
            not isinstance(step.get(key), str) or not step[key]
            for key in DEFINITION_FIELDS[:-1]
        ):
            raise ValueError("each step requires a name, directory, done marker, and failed marker")
        outputs = step.get("outputs")
        if not strings(outputs) or not outputs or not all(outputs):
            raise ValueError(f"step {step['name']!r} requires a nonempty list of output filenames")
        name = step["name"].casefold()
        if name in names:
            raise ValueError(f"duplicate step name {step['name']!r}")
        names.add(name)
    step_names = {step["name"] for step in steps}

    rows = snapshot.get("rows")
    if not isinstance(rows, list):
        raise ValueError("rows must be a list")
    lines = set()
    valid_ids = set()
    invalid_ids = set()
    counts = dict.fromkeys(STATUSES, 0)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each row must be an object")
        line = row.get("row")
        if type(line) is not int or line < 2 or line in lines:
            raise ValueError(f"invalid or duplicate sample-sheet row number {line!r}")
        lines.add(line)
        if any(not isinstance(row.get(key), str) for key in ("sample_id", "read1", "read2")):
            raise ValueError(f"row {line} requires string sample_id, read1, and read2 fields")
        issues = row.get("issues")
        results = row.get("steps")
        if not strings(issues) or not isinstance(results, dict):
            raise ValueError(f"row {line} requires an issues list and step results object")
        sample_id = row["sample_id"]
        if issues:
            if results:
                raise ValueError(f"row {line} has validation issues and step results")
            invalid_ids.add(sample_id)
            continue
        if not sample_id or sample_id in valid_ids:
            raise ValueError(f"row {line} has a blank or duplicate valid sample ID")
        valid_ids.add(sample_id)
        if results.keys() != step_names:
            raise ValueError(f"row {line} must have a result for each declared step")
        for name, result in results.items():
            label = f"row {line}, step {name!r}"
            if not isinstance(result, dict) or result.get("status") not in STATUSES:
                raise ValueError(f"{label} has an invalid status")
            evidence = result.get("evidence")
            if (
                not isinstance(evidence, dict)
                or not isinstance(evidence.get("directory"), str)
                or not strings(evidence.get("present"))
                or not strings(evidence.get("absent"))
            ):
                raise ValueError(f"{label} has invalid file evidence")
            counts[result["status"]] += 1
    if valid_ids & invalid_ids:
        raise ValueError("a sample ID appears in both valid and invalid rows")

    totals = snapshot.get("status_totals")
    if (
        not isinstance(totals, dict)
        or any(type(value) is not int for value in totals.values())
        or totals != counts
    ):
        raise ValueError("status totals do not match the step results")


def load_snapshot(path):
    try:
        with path.open(encoding="utf-8") as handle:
            snapshot = json.load(handle, parse_constant=reject_json_constant)
        validate_snapshot(snapshot)
    except (OSError, ValueError, RecursionError) as exc:
        raise ValueError(f"invalid snapshot {path}: {exc}") from exc
    return snapshot
