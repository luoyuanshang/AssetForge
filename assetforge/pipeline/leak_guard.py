"""Fail-closed checks that keep a task-design artifact free of downstream-purpose wording.

A Rubric describes one task: the business area, the applications and their roles, the required
evidence and effects, the correct terminal state and the protected scope. It must not say
anything about how the resulting data will later be consumed, and it must not carry
portfolio-level distribution targets, which belong to the plan and the gates.

These checks are mechanical and occurrence-local: they refuse the artifact rather than editing
it, and an exemption applies only to the sentence that needs it.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

# Wording that describes how a dataset is consumed downstream rather than what a task requires.
# Business vocabulary that happens to overlap (a training record an HR application really
# exposes, an authorization value described as a model field) is exempted at the call site by
# matching its surrounding sentence, never by removing the word from the search.
_DOWNSTREAM_PURPOSE_PATTERNS = (
    r"(?i)\bupstream-teacher\b",
    r"(?i)\bK2\.7\b",
    r"(?i)\bK3\b",
    r"(?i)\b(?:student|teacher|model|distill(?:ation)?|training|fine[- ]?tun(?:e|ing)|"
    r"SFT|PPO|GRPO|GSPO|OPD)\b",
    r"(?i)\b(?:trajectory|rollout|reasoning_content|exact[- ]?token)\b",
    r"(?:student|teacher|model|distillation|training|finetun\w*|trajector\w*|training corpus)",
)

# A Rubric is the Author prompt, never a joint Author/Reviewer manual. Kept narrow enough that
# ordinary business workflows involving approval or review stay legal, while explicit
# review-role material fails closed before any model call.
_ROLE_LEAK_PATTERNS = (
    r"(?i)\breviewer\b",
    r"(?i)\breview(?:er)?[- _]?(?:prompt|report|decision|memo|checklist|rubric)\b",
    r"(?:reviewer|auditor|evaluator|review model)",
    r"(?:QA|task|candidate)(?:\s+quality)?\s+(?:review|audit)"
    r"(?:\s+(?:rule|process|report|conclusion|list|prompt))?",
    r"(?:Rubric|rule)\s*(?:revision|amendment)(?:\s+(?:memo|report|format))?",
)

# Portfolio-level targets belong to the plan and the selection gate, never to a per-task prompt.
_PORTFOLIO_PATTERNS = (
    r"\b18[, ]?000\b", r"\b6[, ]?000\b", r"\b10[, ]?800\b", r"\b3[, ]?600\b",
    r"\bquota\b",
    r"background_app_fraction", r"weak_scoring_app_fraction",
    r"official[ _]share", r"scored share", r"official share",
    r"anchor application", r"anchor band",
    r"≥\s?\d{2,3}\s?%", r"\b\d{1,2}\s?[–-]\s?\d{1,2}\s?%",
)


def safe_markdown(markdown: Any) -> bool:
    """Minimal surface-safety check, never a content-quality judgement.

    Quality, similarity and difficulty stay with the designated agents. This only stops a
    Markdown artifact from smuggling binary material into the record.
    """
    if not isinstance(markdown, str):
        return False
    normalized = markdown.strip()
    if not (32 <= len(normalized) <= 100_000):
        return False
    # Plain prose is valid Markdown. No heading, section list, word count or JSON-shaped
    # contract is imposed on an agent's judgement.
    return "\x00" not in normalized


def _business_use_exemption(markdown: str, match: re.Match, artifact: str) -> bool:
    """True when this occurrence names a business fact rather than a downstream purpose.

    Each exemption is occurrence-local and sentence-scoped: other uses of the same word in the
    same artifact still fail closed.
    """
    word = match.group(0).lower()
    if artifact == "rubric":
        if word == "model":
            return (markdown.endswith("native data ", 0, match.start())
                    and markdown[match.end():].startswith(" used by the official routes."))
        if word == "exact token":
            return (markdown.endswith("A semantic-fragment task must not imply ", 0, match.start())
                    and markdown[match.end():].startswith(" identity."))
        return False

    # Candidate tasks: an HR application may genuinely expose employee training records, and an
    # hours ledger or an event venue may legitimately be called a "training" something.
    if word == "training":
        if (re.search(r"(?i)\bBambooHR\b", markdown)
                and re.search(r"(?i)\bemployee(?:s)?\b", markdown)
                and (re.match(r"(?i)(?:[- ](?:type|record|note|channel)s?\b)",
                              markdown[match.end():])
                     or (markdown[max(0, match.start()-1):match.start()] == "#"
                         and re.match(r"-\d+\b", markdown[match.end():])))):
            return True
        context = markdown[max(0, match.start()-160):match.end()+160]
        hr_context = re.search(r"(?i)\b(?:employees?|onboarding|orientation)\b", markdown)
        ledger = (re.match(r"(?i)\s+ledger\b", markdown[match.end():])
                  and re.search(r"(?i)\b(?:sheets?|rows?|completed hours)\b", context))
        venue = (re.match(r"(?i)\s+bay\b", markdown[match.end():])
                 and re.search(r"(?i)\b(?:location|calendar|event)\b", context))
        return bool(hr_context and (ledger or venue))
    return False


def reject_downstream_purpose_leak(markdown: str, *, artifact: str) -> None:
    """Refuse an artifact that describes how its data will later be consumed."""
    for pattern in _DOWNSTREAM_PURPOSE_PATTERNS:
        for match in re.finditer(pattern, markdown):
            if _business_use_exemption(markdown, match, artifact):
                continue
            raise ValueError(
                f"{artifact} contains content outside the business-workflow scope at "
                f"character offsets {match.start()}:{match.end()}; describe only the requested "
                "business facts and constraints"
            )


def reject_role_leak(markdown: str) -> None:
    """Reject review-procedure material from the Author-visible Rubric surface."""
    for pattern in _ROLE_LEAK_PATTERNS:
        match = re.search(pattern, markdown)
        if match is not None:
            raise ValueError(
                "author rubric carries Reviewer-only role/process material: "
                f"{match.group(0)!r}"
            )


def reject_portfolio_leak(markdown: str) -> None:
    """Refuse portfolio-level distribution targets inside a per-task prompt.

    Per-task rules such as "exactly N scored applications" and the background-application
    allowance are legal; global totals, shares and bands are not.
    """
    for pattern in _PORTFOLIO_PATTERNS:
        match = re.search(pattern, markdown, re.IGNORECASE)
        if match:
            raise ValueError(
                "author rubric must not carry controller-level distribution targets "
                f"(found {match.group(0)!r}); keep portfolio quotas in the plan and the "
                "selection gate"
            )


def validate_candidate_markdown(markdown: str) -> str:
    """Validate a candidate task Markdown artifact."""
    if not safe_markdown(markdown):
        raise ValueError("candidate Markdown must be non-empty safe text")
    reject_downstream_purpose_leak(markdown, artifact="candidate task")
    return markdown


def validate_rubric_markdown(markdown: str) -> str:
    """Validate an Author Rubric Markdown artifact."""
    if not safe_markdown(markdown):
        raise ValueError("rubric Markdown must be non-empty safe text")
    reject_downstream_purpose_leak(markdown, artifact="rubric")
    reject_role_leak(markdown)
    reject_portfolio_leak(markdown)
    return markdown
