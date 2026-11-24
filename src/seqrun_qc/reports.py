"""Shared formatting and destination checks for report writers."""

import json
import os
import stat


def file_identity(path):
    try:
        info = path.stat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    return info.st_dev, info.st_ino


def validate_destinations(destinations, inputs):
    protected_paths = set()
    protected_files = set()
    for path in inputs:
        protected_paths.add(path.resolve())
        identity = file_identity(path)
        if identity is not None:
            protected_files.add(identity)

    for path in destinations:
        resolved = path.resolve()
        identity = file_identity(path)
        if resolved in protected_paths or identity in protected_files:
            raise ValueError(f"report destination must differ from inputs and other reports: {path}")
        if not path.parent.is_dir() or not resolved.parent.is_dir():
            raise ValueError(f"report destination parent is not a directory: {path.parent}")
        if identity is not None and not stat.S_ISREG(resolved.stat().st_mode):
            raise ValueError(f"report destination must be a regular file: {path}")
        writable = resolved if identity is not None else resolved.parent
        if not os.access(writable, os.W_OK):
            raise ValueError(f"report destination is not writable: {path}")
        protected_paths.add(resolved)
        if identity is not None:
            protected_files.add(identity)


def write_json(path, document):
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def format_evidence(evidence):
    present = ", ".join(evidence["present"]) or "none"
    absent = ", ".join(evidence["absent"]) or "none"
    return f"{evidence['directory']}: present [{present}]; absent [{absent}]"
