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

Place each step's files under `OUTPUT_DIR/SAMPLE_ID/STEP/`. The two steps are assessed independently.

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
