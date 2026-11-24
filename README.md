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
