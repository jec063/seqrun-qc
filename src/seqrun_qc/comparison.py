"""Compare saved results by sample ID and step name."""

from .html_report import render_html
from .reports import validate_destinations, write_json
from .snapshots import DEFINITION_FIELDS, SCHEMA_VERSION, STATUSES, load_snapshot


def validation_counts(snapshot):
    rows = snapshot["rows"]
    return {
        "rows": len(rows),
        "rows_with_issues": sum(bool(row["issues"]) for row in rows),
        "issues": sum(len(row["issues"]) for row in rows),
    }


def step_definitions(snapshot):
    return {step["name"]: {key: step[key] for key in DEFINITION_FIELDS}
            for step in snapshot["steps"]}


def valid_samples(snapshot):
    return {row["sample_id"]: row["steps"] for row in snapshot["rows"] if not row["issues"]}


def compare_snapshots(before, after):
    old_steps, new_steps = step_definitions(before), step_definitions(after)
    old_samples, new_samples = valid_samples(before), valid_samples(after)
    added_steps = sorted(new_steps.keys() - old_steps.keys())
    removed_steps = sorted(old_steps.keys() - new_steps.keys())
    changed = {
        name: {"before": old_steps[name], "after": new_steps[name]}
        for name in sorted(old_steps.keys() & new_steps.keys())
        if old_steps[name] != new_steps[name]
    }

    samples = []
    transitions = []
    for sample_id in sorted(old_samples.keys() | new_samples.keys()):
        old_results = old_samples.get(sample_id, {})
        new_results = new_samples.get(sample_id, {})
        steps = []
        for name in sorted(old_results.keys() | new_results.keys()):
            old = old_results.get(name)
            new = new_results.get(name)
            if old is None:
                change = "added"
            elif new is None:
                change = "removed"
            elif name in changed:
                change = "definition_changed"
            elif old["status"] == new["status"]:
                change = "unchanged"
            else:
                change = "changed"
                if old["status"] == "complete":
                    change = "regression"
                elif new["status"] == "complete":
                    change = "recovery"
                transitions.append({
                    "sample_id": sample_id, "step": name, "before": old["status"],
                    "after": new["status"], "change": change,
                })
            steps.append({"step": name, "before": old, "after": new, "change": change})
        samples.append({"sample_id": sample_id, "steps": steps})

    return {
        "schema_version": SCHEMA_VERSION,
        "validation": {"before": validation_counts(before), "after": validation_counts(after)},
        "status_totals": {
            side: {status: snapshot["status_totals"][status] for status in STATUSES}
            for side, snapshot in (("before", before), ("after", after))
        },
        "added_samples": sorted(new_samples.keys() - old_samples.keys()),
        "removed_samples": sorted(old_samples.keys() - new_samples.keys()),
        "added_steps": added_steps,
        "removed_steps": removed_steps,
        "changed_definitions": [{"step": name, **details} for name, details in changed.items()],
        "transitions": transitions,
        "counts": {
            "transitions": len(transitions),
            "regressions": sum(item["change"] == "regression" for item in transitions),
            "recoveries": sum(item["change"] == "recovery" for item in transitions),
        },
        "samples": samples,
    }


def print_summary(comparison):
    counts = comparison["counts"]
    print(
        f"{counts['transitions']} status transitions, "
        f"{counts['regressions']} regressions, {counts['recoveries']} recoveries."
    )
    for side, counts in comparison["validation"].items():
        print(f"{side.title()}: {counts['issues']} validation issues in "
              f"{counts['rows_with_issues']} of {counts['rows']} rows.")
    for key, label in (
        ("added_samples", "Added samples"), ("removed_samples", "Removed samples"),
        ("added_steps", "Added steps"), ("removed_steps", "Removed steps"),
    ):
        print(f"{label}: " + (", ".join(repr(value) for value in comparison[key]) or "none"))
    changed = comparison["changed_definitions"]
    print("Changed step definitions: " + (", ".join(repr(item["step"]) for item in changed) or "none"))
    for item in comparison["transitions"]:
        print(f"  {item['sample_id']!r} / {item['step']!r}: "
              f"{item['before']} -> {item['after']} ({item['change']})")


def compare(before, after, *, json_report=None, html_report=None, fail_on_regression=False):
    result = compare_snapshots(load_snapshot(before), load_snapshot(after))
    destinations = [path for path in (json_report, html_report) if path is not None]
    if destinations:
        validate_destinations(destinations, [before, after])
    if json_report is not None:
        write_json(json_report, result)
    if html_report is not None:
        html_report.write_text(render_html(result), encoding="utf-8", errors="xmlcharrefreplace")
    print_summary(result)
    if json_report is not None:
        print(f"JSON report: {json_report}")
    if html_report is not None:
        print(f"HTML report: {html_report}")
    return int(fail_on_regression and result["counts"]["regressions"] > 0)
