"""Custom exceptions for the context module."""

from __future__ import annotations


class ContextFileError(Exception):
    """File I/O related errors (invalid JSON, permission errors, etc.)."""
