# seqrun-qc

`seqrun-qc check` validates paired-end read paths and reports pipeline status from files already on disk. It checks file presence without reading FASTQ contents or running pipeline steps.

## Install and run

From the repository root, with Python 3.10 or later:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/seqrun-qc check demo/samples.csv demo/output --report /tmp/seqrun-qc-demo.csv
```

For your own run, replace the sample sheet and pipeline output directory. If you omit `--report`, the command writes `seqrun-qc-status.csv` in the current directory. An existing report at the selected path is overwritten.

## Sample sheet

Use UTF-8 CSV with unique column names and at least `sample_id`, `read1`, and `read2`. Extra columns are ignored. Values in the required columns are trimmed. IDs are case-sensitive and may contain ASCII letters, digits, underscores, hyphens and periods, with a letter, digit, underscore or hyphen first. This makes each ID a single directory name. Read paths can be absolute or relative to the sample sheet's directory. Each must point to a regular file.

The report has one record per input row in sheet order. The `row` column gives its starting line in the CSV, counting the header as line 1. Rows with validation issues list all detected corrections and have empty step columns. Every occurrence of a duplicate ID is flagged.

## Pipeline file conventions

Place each step's files under `OUTPUT_DIR/SAMPLE_ID/STEP/`. Steps are assessed independently. By default the command checks these two steps in order.

| Step | Expected output files |
| --- | --- |
| `trim` | `read1.trimmed.fastq` and `read2.trimmed.fastq` |
| `qc` | `metrics.tsv` |

Each step uses `done.marker` for completion and `failed.txt` for an explicit failure. A marker can be empty. The CSV evidence lists the step directory and which known files are present or absent. Unrecognized files are ignored.

| Status | Evidence |
| --- | --- |
| `complete` | Completion marker and every expected output file are present. |
| `failed` | Failure record is present and the completion marker is absent, even if outputs remain. |
| `incomplete` | Both records are present, the completion marker lacks expected outputs, or outputs exist without either record. |
| `pending` | Neither record nor any expected output is present. |

Exit code `0` means every row validates and all checked steps are complete. Exit code `1` means the report was written and at least one row or step needs attention. Exit code `2` means a usage, input, or I/O error prevented a successful check.

## Configure pipeline steps

Pass `--config PATH` to replace the default steps with an ordered list from a UTF-8 JSON file.

```json
{
  "steps": [
    {"name": "align", "outputs": ["aligned.bam", "aligned.bam.bai"]},
    {"name": "qc", "outputs": ["metrics.tsv"]}
  ]
}
```

The `steps` list and each step's `outputs` list must be nonempty. Step names must be unique regardless of case. Step names and expanded output and marker filenames must each be a single safe path component. Avoid path separators, control characters, Windows-reserved characters and device names, and trailing dots or spaces. Output and marker filenames within a step must be distinct regardless of case. Use the spelling and case of the files on disk.

The same directory layout, markers, and status rules apply. The CSV adds a status and evidence column for each configured step in the order listed. An invalid config exits with code `2` without changing the report.

After installing, run the custom demo from the repository root.

```sh
.venv/bin/seqrun-qc check demo/custom/samples.csv demo/custom/output --config demo/custom/steps.json --report /tmp/seqrun-qc-custom.csv
```

The one sample has two complete steps and exits with code `0`. The report lists `align_status`, `align_evidence`, `qc_status`, and `qc_evidence` in that order after the sample columns. The tiny alignment files are empty placeholders because the CLI checks file presence.

### Flat and nested layouts

Each step can override where its files are stored and how its markers are named.

| Optional field | Default | Example |
| --- | --- | --- |
| `directory` | `{sample_id}/{step}` | `.` for `OUTPUT_DIR`, or `results/{sample_id}/{step}` for nested output |
| `done_marker` | `done.marker` | `{sample_id}.done` |
| `failed_marker` | `failed.txt` | `{sample_id}.failed` |

These fields and each entry in `outputs` accept `{sample_id}` and `{step}`, for example `{sample_id}.filtered.bam`. Use `/` between directory components. Directories must be relative to `OUTPUT_DIR` and cannot contain `..`. Any symlink used by an expanded path must resolve inside `OUTPUT_DIR`. Invalid templates, unsafe paths, and filenames that collide after expansion exit with code `2` and leave the report untouched.

Run the flat demo from the repository root.

```sh
.venv/bin/seqrun-qc check demo/flat/samples.csv demo/flat/output --config demo/flat/steps.json --report /tmp/seqrun-qc-flat.csv
```

Both samples share one output directory. The `complete` sample has both empty BAM placeholders and its done marker. The `missing-index` sample has a BAM and done marker but no index, so its alignment step is incomplete. The command writes the report and exits with code `1`.

## Expected demo results

The six rows use tiny synthetic FASTQ files and mock outputs included in the repository. The demo intentionally exits with code `1`.

| CSV line | Sample | Trim | QC | Row issue |
| --- | --- | --- | --- | --- |
| 2 | success | complete | complete | |
| 3 | duplicate | | | Duplicate ID |
| 4 | duplicate | | | Duplicate ID and missing read2 file |
| 5 | failure | failed | pending | |
| 6 | interrupted | incomplete | pending | |
| 7 | pending | pending | pending | |

The terminal summary reports **6 rows checked, 2 needing correction** and **2 complete, 1 failed, 1 incomplete, 4 pending** steps.

Run the tests after installation with `.venv/bin/python -m unittest discover -s tests -v`.

## Save and compare run snapshots

Pass `--json-report PATH` to `check` to save a snapshot alongside the CSV. Later, run `compare BEFORE.json AFTER.json` to compare the saved results even if the original files have moved. Reports require an existing parent directory. Output paths must be distinct from inputs and each other.

Run this from the repository root after installing. Each check exits with code `1` because each snapshot has one incomplete step.

```sh
reports=$(mktemp -d)
qc=.venv/bin/seqrun-qc
"$qc" check demo/rerun/samples.csv demo/rerun/before --config demo/flat/steps.json \
  --report "$reports/before.csv" --json-report "$reports/before.json" || test "$?" -eq 1
"$qc" check demo/rerun/samples.csv demo/rerun/after --config demo/flat/steps.json \
  --report "$reports/after.csv" --json-report "$reports/after.json" || test "$?" -eq 1
"$qc" compare "$reports/before.json" "$reports/after.json" \
  --json-report "$reports/comparison.json" --html-report "$reports/comparison.html"
printf 'Open %s/comparison.html in your browser\n' "$reports"
```

The embedded styles and saved evidence let you open the HTML report offline.

| Sample | Before | After | Explanation |
| --- | --- | --- | --- |
| `recovers` | incomplete | complete | Its missing BAM index appears. |
| `regresses` | complete | incomplete | Its BAM disappears. |
| `unchanged` | complete | complete | Both expected outputs remain present. |

### Snapshot JSON schema, version 1

The root is an object with these fields:

| Field | Contents |
| --- | --- |
| `schema_version` | Integer `1`. |
| `steps` | Ordered array of step definitions with `name`, `directory`, `done_marker`, `failed_marker`, and an ordered `outputs` array. Omitted config fields are stored with their defaults. |
| `status_totals` | Object with integer counts for `complete`, `failed`, `incomplete`, and `pending`. |
| `rows` | Array in sample-sheet order. Each row has its original starting line number (`row`), the three sample-sheet fields, an `issues` array, and a `steps` object keyed by step name. |

A valid row has one result for each configured step. A result has a `status` string and an `evidence` object with a `directory` string and `present` and `absent` filename arrays. Each expanded output and marker filename must appear exactly once across those arrays, and the saved status must agree with the evidence. Comparison checks these rules offline. Invalid rows, including duplicate IDs, are kept with their validation messages and an empty `steps` object.

### Comparison and exit codes

Comparison matches valid rows by exact sample ID and steps by exact name. A sample that becomes invalid appears as removed from the valid sample set. A step with a changed definition appears separately from status transitions. Step list order has no effect on matching. In a step definition, its directory, marker templates, and ordered outputs are compared as stored. A regression moves from complete to any other status. A recovery moves from a non-complete status to complete.

The comparison JSON also has `schema_version: 1`. It includes `validation` and `status_totals` for both sides, lists of added and removed samples and steps, `changed_definitions`, `transitions`, and summary `counts`. Its `samples` array carries per-step results with before and after evidence, using `null` when a result exists on only one side.

| Command | Exit code | Meaning |
| --- | --- | --- |
| `check` | `0` | Every row validates and all checked steps are complete. |
| `check` | `1` | Reports were written and at least one row or step needs attention. |
| `compare` | `0` | Comparison succeeded. This is the default even if there are regressions. |
| `compare --fail-on-regression` | `1` | Comparison succeeded and at least one step regressed under the same definition. Requested reports are still written. |
| Either | `2` | Usage, validation, or I/O error, including an unsupported snapshot schema. |
