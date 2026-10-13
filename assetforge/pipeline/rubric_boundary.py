"""Check the Author specification without using its wording as configuration."""
from __future__ import annotations

import re

PROJECT_TEXT = re.compile(
    r"\b(?:quota|SFT|fine-tuning|training dataset|reviewer prompt|reviewer decision|"
    r"corpus release|tasks per cell|distribution ratios|benchmark)\b", re.IGNORECASE
)


def validate_rubric(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Rubric must be a nonempty Author specification")
    if PROJECT_TEXT.search(text):
        raise ValueError("Rubric contains project-level or review-procedure information")
