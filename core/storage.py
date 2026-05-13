"""Secure helpers for attachment path resolution."""

from __future__ import annotations

import os
from pathlib import Path


ATTACHMENTS_DIR = Path(
    os.getenv("ATTACHMENTS_DIR", Path(__file__).resolve().parent.parent / "attachments")
).resolve()


def get_attachment_path(stored_path: str) -> Path:
    """Return a safe path for an attachment stored under ATTACHMENTS_DIR.

    Only the basename is used so path traversal segments like ``../`` are discarded.
    The final resolved path must still live inside ``ATTACHMENTS_DIR``.
    """

    filename = os.path.basename(str(stored_path).strip())
    if not filename:
        raise ValueError("Attachment path must include a filename")

    candidate = (ATTACHMENTS_DIR / filename).resolve()

    try:
        candidate.relative_to(ATTACHMENTS_DIR)
    except ValueError as exc:
        raise ValueError("Resolved attachment path escapes the attachments directory") from exc

    return candidate
