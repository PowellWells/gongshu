"""Evaluation-only boundary; simulation truth must not escape this package."""

from .interfaces import LocalizationEvaluator

__all__ = ["LocalizationEvaluator"]
