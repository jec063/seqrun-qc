"""Render an offline comparison report with escaped snapshot values."""

from html import escape

from .reports import format_evidence
from .snapshots import STATUSES

STYLE = """
* { box-sizing: border-box; }
body { margin: 0; background: #f4f6fa; color: #19243a; font: 1rem/1.45 system-ui, sans-serif; }
main { max-width: 88rem; margin: auto; padding: 1.5rem; }
h1, h2 { line-height: 1.15; }
.summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: .75rem; }
.summary p { margin: 0; border-radius: .5rem; background: white; padding: .8rem 1rem; }
.summary strong { display: block; font-size: 1.6rem; }
.table-wrap { overflow: auto; border: 1px solid #d6deea; border-radius: .5rem; }
table { border-collapse: collapse; background: white; width: 100%; }
th, td { padding: .65rem .75rem; text-align: left; vertical-align: top; border-bottom: 1px solid #d6deea;
         overflow-wrap: anywhere; }
thead th { background: #e8edf5; }
tbody tr:last-child > * { border-bottom: 0; }
.samples { min-width: 45rem; }
.samples td:nth-child(3), .samples td:nth-child(4) { width: 32%; }
.status { display: inline-block; background: #e8edf5; border-radius: .4rem; padding: .1rem .4rem; }
.complete, .recovery { color: #125533; background: #e0f3e9; }
.failed, .regression { color: #871b25; background: #fbe5e7; }
.incomplete, .definition_changed { color: #744600; background: #fff1d1; }
.evidence { display: block; margin-top: .3rem; color: #3b4960; }
.changes { display: grid; grid-template-columns: minmax(9rem, max-content) 1fr; gap: .35rem 1rem; }
.changes dd { margin: 0; overflow-wrap: anywhere; }
"""


def cell_result(result):
    if result is None:
        return "—"
    status = escape(result["status"])
    evidence = escape(format_evidence(result["evidence"]))
    return f'<strong class="status {status}">{status}</strong><span class="evidence">{evidence}</span>'


def render_html(comparison):
    counts = comparison["counts"]
    validation = comparison["validation"]
    totals = comparison["status_totals"]
    changed = [item["step"] for item in comparison["changed_definitions"]]
    changes = []
    for label, names in (
        ("Added samples", comparison["added_samples"]),
        ("Removed samples", comparison["removed_samples"]),
        ("Added steps", comparison["added_steps"]),
        ("Removed steps", comparison["removed_steps"]),
        ("Changed step definitions", changed),
    ):
        changes.append(f"<dt>{label}</dt><dd>{', '.join(map(escape, names)) or 'None'}</dd>")

    headers = ("Sample rows", "Rows with issues", "Validation issues", *STATUSES)
    count_rows = []
    for side in ("before", "after"):
        values = [validation[side][key] for key in ("rows", "rows_with_issues", "issues")]
        values.extend(totals[side][status] for status in STATUSES)
        cells = "".join(f"<td>{value}</td>" for value in values)
        count_rows.append(f'<tr><th scope="row">{side.title()}</th>{cells}</tr>')

    sample_rows = []
    for sample in comparison["samples"]:
        sample_id = escape(sample["sample_id"])
        for step in sample["steps"]:
            name = escape(step["step"])
            change = escape(step["change"])
            label = change.replace("_", " ").capitalize()
            sample_rows.append(
                f'<tr><th scope="row">{sample_id}</th><td>{name}</td>'
                f'<td>{cell_result(step["before"])}</td><td>{cell_result(step["after"])}</td>'
                f'<td><strong class="status {change}">{label}</strong></td></tr>'
            )

    sample_header = ("Sample", "Step", "Before", "After", "Change")
    sample_body = "".join(sample_rows) or '<tr><td colspan="5">No valid samples to compare.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>seqrun-qc run comparison</title>
<style>{STYLE}</style>
</head>
<body><main>
<h1>Run snapshot comparison</h1>
<div class="summary">
<p><strong>{counts['transitions']}</strong>Status transitions</p>
<p><strong>{counts['regressions']}</strong>Regressions</p>
<p><strong>{counts['recoveries']}</strong>Recoveries</p>
</div>
<h2>Run counts</h2>
<div class="table-wrap"><table>
<thead><tr><th scope="col">Snapshot</th>{''.join(f'<th scope="col">{label.title()}</th>' for label in headers)}</tr></thead>
<tbody>{''.join(count_rows)}</tbody>
</table></div>
<h2>Sample and configuration changes</h2>
<dl class="changes">{''.join(changes)}</dl>
<h2>Sample results</h2>
<div class="table-wrap"><table class="samples">
<thead><tr>{''.join(f'<th scope="col">{label}</th>' for label in sample_header)}</tr></thead>
<tbody>{sample_body}</tbody>
</table></div>
</main></body>
</html>
"""
