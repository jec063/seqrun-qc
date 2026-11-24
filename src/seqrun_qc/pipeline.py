"""Shared template expansion and status rules for pipeline steps."""

import re

PLACEHOLDER = re.compile(r"\{(sample_id|step)\}")


def validate_placeholders(template, field):
    remainder = PLACEHOLDER.sub("", template)
    if "{" in remainder or "}" in remainder:
        raise ValueError(f"{field} has an unknown or malformed placeholder")


def expand_template(template, sample_id, step_name):
    values = {"sample_id": sample_id, "step": step_name}
    return PLACEHOLDER.sub(lambda match: values[match[1]], template)


def step_status(present, outputs, done_marker, failed_marker):
    done = done_marker in present
    if failed_marker in present:
        return "incomplete" if done else "failed"
    if done and all(name in present for name in outputs):
        return "complete"
    return "incomplete" if present else "pending"
