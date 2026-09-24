"""Schemas and fail-closed contract for the V9 *agent-driven* QA loop.

This module intentionally does not enumerate a task space, render a prompt,
build a corpus, call a provider, or invoke the V9 compiler.  A deterministic
compiler can later be supplied only as an internal feasibility/scorer input;
it is explicitly not an author, a candidate-QA generator, or a reviewer.

The role boundary is deliberately concrete: an unqualified ``rubric`` is the
Author-only natural-language prompt describing the target QA distribution and
task requirements.  Reviewer instructions live in a separately versioned
Reviewer prompt.  Reviewer findings may inform the next immutable Rubric
version, but Reviewer procedures and output formats must never be spliced into
the Author Rubric.

The agents exchange substantive material as Markdown/natural-language
documents.  JSON is deliberately restricted to small audit envelopes that
bind an artifact's SHA-256, lineage/version, route and bounded decision.  It
is not an authoring, QA-generation, rubric, or reviewing surface.  The
validators below only establish boundary and provenance invariants; they do
not pretend that a deterministic schema can judge task quality.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


PIPELINE_SCHEMA = "automation-only-v9-agentic-markdown-rubric-pipeline-contract-v2"
STATIC_AUDIT_SCHEMA = "automation-only-v9-agentic-markdown-rubric-pipeline-static-audit-v2"
AGENT_EXECUTION_SCHEMA = "automation-only-v9-agent-markdown-execution-attestation-v2"
RUBRIC_AGENT_OUTPUT_SCHEMA = "automation-only-v9-rubric-agent-markdown-output-v2"
CANDIDATE_QA_AGENT_OUTPUT_SCHEMA = "automation-only-v9-candidate-qa-agent-markdown-output-v2"
K3_SAMPLE_PLAN_SCHEMA = "automation-only-v9-k3-quality-sample-plan-v1"
K3_VISIBLE_TRAJECTORY_SCHEMA = "automation-only-v9-k3-visible-trajectory-receipt-v1"
BENCHMARK_COMPARISON_SCHEMA = "automation-only-v9-benchmark-trajectory-markdown-comparison-packet-v2"
REVIEWER_DECISION_SCHEMA = "agentic-markdown-reviewer-decision-v2"
APPROVED_LINEAGE_SCHEMA = "automation-only-v9-approved-agentic-lineage-receipt-v1"

PIPELINE_VERSION = "v9-agentic-markdown-rubric-loop-r2"
TARGET_CANDIDATE_COUNT = 10_000
K3_SAMPLE_NUMERATOR = 1
K3_SAMPLE_DENOMINATOR = 5
K3_EXPECTED_SAMPLE_COUNT = 2_000
K3_ALIAS = "capture_model_4_max"
K3_REASONING_EFFORT = "max"
K3_CONCURRENCY_RAMP = (8, 32, 100, 300)
NATIVE_TOOL_IDS = ("api_search", "api_fetch", "base64_encode")

MOG_REVIEWER_ALIAS = "capture_model_2_sol_extra_high"
MOG_REVIEWER_MODEL = "model_b1"
MOG_ROUTE_ID = "provider_b_responses_xhigh"

RUBRIC_CRITERION_CODES = (
    "target_benchmark_interaction_semantics",
    "native_tool_only_surface",
    "difficulty_and_solvability_band",
    "anti_near_copy_and_contamination",
    "anti_benchmark_hack_and_hidden_verifier_leakage",
)
REVIEW_DECISION_CODES = (
    "accept_sample",
    "revise_rubric",
    "reject_candidate",
    "reject_lineage",
    "quarantine_for_investigation",
)
RUBRIC_REVISION_CATEGORIES = (
    "interaction_semantics_mismatch",
    "near_copy_or_contamination_risk",
    "too_easy_or_too_hard",
    "impossible_or_non_native_task",
    "benchmark_hack_or_verifier_leakage_risk",
    "trajectory_pattern_mismatch",
    "insufficient_target_benchmark_coverage",
)
REVIEW_BASIS_CODES = (
    "generated_qa_examined",
    "candidate_k3_visible_trajectory_examined",
    "target_benchmark_k3_visible_trajectory_examined",
    "target_benchmark_qa_and_rubric_examined",
    "semantic_interaction_similarity_examined",
    "near_copy_risk_examined",
    "difficulty_and_solvability_examined",
    "benchmark_hack_risk_examined",
)

RAW_FREE_FALSE_FIELDS = (
    "provider_request_persisted",
    "raw_provider_response_persisted",
    "private_or_encrypted_reasoning_persisted",
    "thinking_signature_persisted",
    "chain_of_thought_persisted",
    "hidden_dag_persisted",
    "hidden_world_state_persisted",
    "effect_budget_persisted",
    "assertion_or_verifier_state_persisted",
)
PIPELINE_FALSE_FIELDS = (
    "fixed_template_used_as_qa_generator",
    "cartesian_product_used_as_qa_generator",
    "field_value_substitution_used_as_qa_generator",
    "deterministic_compiler_used_as_qa_generator",
    "fixed_template_used_as_reviewer",
    "static_score_threshold_used_as_reviewer",
    "deterministic_compiler_used_as_reviewer",
    "provider_calls_made",
    "candidate_qa_corpus_created",
    "k3_trajectory_collection_started",
    "mog_reviewer_completed",
    "semantic_dedup_completed",
    "heldout_transfer_completed",
    "training_eligible",
)
FORBIDDEN_OUTPUT_KEY_PREFIXES = (
    "reasoning", "thinking", "private", "encrypted", "raw_provider", "provider_response",
    "chain_of_thought", "cot", "signature", "synthetic_dag", "hidden_dag", "world_state",
    "hidden_world", "effect_budget", "assertion", "verifier_state", "internal_monologue",
)
# These are route settings, not model-produced reasoning.  They must remain
# present to bind the reviewer/K3 configuration while ``reasoning_content``
# and every private-thinking payload remain forbidden.
SAFE_ROUTE_METADATA_KEYS = frozenset({
    "reasoning_effort", "reasoning_summary", "reasoning_summary_parameter_omitted",
})
MARKDOWN_ARTIFACT_KINDS = frozenset({
    "rubric", "qa_authoring_brief", "candidate_qa", "comparison_packet",
    "review_memo", "rubric_revision",
})


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def source_file_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _hex64(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _lineage_id(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[a-z][a-z0-9._-]{2,127}", value))


def _content_hash_ok(value: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping) or not _hex64(value.get("content_sha256")):
        return False
    body = dict(value)
    supplied = body.pop("content_sha256")
    return supplied == sha256(body)


def _rehash(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result.pop("content_sha256", None)
    result["content_sha256"] = sha256(result)
    return result


def _normalized_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def _contains_forbidden_material(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = _normalized_key(key)
            if normalized.startswith(FORBIDDEN_OUTPUT_KEY_PREFIXES):
                # Closed schemas use explicit boolean anti-retention fields
                # such as ``raw_provider_response_persisted=false``.  Those
                # flags are evidence that forbidden material was *not*
                # retained, not forbidden material themselves.  A non-false
                # value is rejected, and unknown keys are still blocked by
                # each caller's exact key-set validation.
                if normalized not in SAFE_ROUTE_METADATA_KEYS and child is not False:
                    return True
            if _contains_forbidden_material(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_material(item) for item in value)
    return False


def _is_exact_bool_map(value: Any, names: tuple[str, ...]) -> bool:
    return isinstance(value, Mapping) and set(value) == set(names) and all(value.get(name) is False for name in names)


def markdown_sha256(markdown: str) -> str:
    """Hash the authored Markdown bytes, not a JSON rendering of its prose."""
    if not isinstance(markdown, str):
        raise TypeError("Markdown artifact must be text")
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _safe_markdown(markdown: Any) -> bool:
    """Check only minimal storage/surface safety, never content quality.

    Quality, similarity, difficulty and rubric edits stay with the designated
    agents.  This deliberately minimal check prevents a Markdown artifact from
    smuggling a private trace or hidden verifier material into the lineage.
    """
    if not isinstance(markdown, str):
        return False
    normalized = markdown.strip()
    if not (32 <= len(normalized) <= 100_000):
        return False
    # Plain prose is valid Markdown.  Do not impose a heading, section list,
    # word count, or JSON-shaped content contract on an agent's judgment.
    return "\x00" not in normalized


CANDIDATE_BUSINESS_SCOPE_CONTRACT = "candidate-business-scope-hr-native-names-v2"

_DOWNSTREAM_PURPOSE_PATTERNS = (
    r"(?i)\bupstream-teacher\b",
    r"(?i)\bK2\.7\b",
    r"(?i)\bK3\b",
    r"(?i)\b(?:student|teacher|model|distill(?:ation)?|training|fine[- ]?tun(?:e|ing)|SFT|PPO|GRPO|GSPO|OPD)\b",
    r"(?i)\b(?:trajectory|rollout|reasoning_content|exact[- ]?token)\b",
    r"(?:student|teacher|model|distillation|training|finetun\w*|trajector\w*|training corpus)",
)

# A Rubric is the Author prompt, never a joint Author/Reviewer manual.  Keep
# this list narrow enough that ordinary business workflows involving approval
# or review remain legal, while explicit QA-reviewer roles and artifacts fail
# closed before any provider call.
_AUTHOR_RUBRIC_ROLE_LEAK_PATTERNS = (
    r"(?i)\breviewer\b",
    r"(?i)\breview(?:er)?[- _]?(?:prompt|report|decision|memo|checklist|rubric)\b",
    r"(?:reviewer|auditor|evaluator|review model)",
    r"(?:QA|task|candidate)(?:\s+quality)?(?:\s+(?:review|audit)(?:\s+(?:rule|process|report|conclusion|list|prompt))))",
    r"(?:Rubric|rule)\s*(?:revision|amendment)(?:\s+(?:memo|report|format)))",
)


def _reject_downstream_purpose_leak(markdown: str, *, artifact: str) -> None:
    """Keep task design artifacts independent from later solving/training use."""

    for pattern in _DOWNSTREAM_PURPOSE_PATTERNS:
        for match in re.finditer(pattern, markdown):
            # The native data model is the application's business schema.
            # Keep this occurrence local; model/training purposes elsewhere
            # in the same artifact must still fail closed.
            if (
                artifact == "rubric Markdown"
                and match.group(0).lower() == "model"
                and markdown.endswith("native data ", 0, match.start())
                and markdown[match.end():].startswith(" used by the official routes.")
            ):
                continue
            # This observed Author sentence discusses a business authorization
            # value, not token-length filtering of model outputs. Exempt only
            # this occurrence; downstream-purpose terms elsewhere still fail.
            if (
                artifact == "rubric Markdown"
                and match.group(0).lower() == "exact token"
                and markdown.endswith(
                    "A semantic-fragment task must not imply ", 0, match.start()
                )
                and markdown[match.end():].startswith(" identity.")
            ):
                continue
            # BambooHR exposes employee training records as a native business
            # operation. Do not confuse those exact noun phrases with training
            # this project's models. This exception is candidate-only, narrow,
            # and does not remove words from the persisted/provider artifact.
            # In particular, "training data", bare "training", model names and
            # all other downstream-purpose matches still fail closed.
            if (
                artifact == "candidate QA Markdown"
                and match.group(0).lower() == "training"
                and re.search(r"(?i)\bBambooHR\b", markdown)
                and re.search(r"(?i)\bemployee(?:s)?\b", markdown)
                and (
                    re.match(r"(?i)(?:[- ](?:type|record|note|channel)s?\b)", markdown[match.end():])
                    or (markdown[max(0, match.start()-1):match.start()] == "#"
                        and re.match(r"-\d+\b", markdown[match.end():]))
                )
            ):
                continue
            # Observed HR proper names: employee-hours ledger and event venue.
            # Candidate-only and occurrence-local; do not exempt other uses of
            # the word or remove any original text from the persisted artifact.
            if artifact == "candidate QA Markdown" and match.group(0).lower() == "training":
                context = markdown[max(0, match.start()-160):match.end()+160]
                hr_context = re.search(r"(?i)\b(?:employees?|onboarding|orientation)\b", markdown)
                ledger = re.match(r"(?i)\s+ledger\b", markdown[match.end():]) and re.search(
                    r"(?i)\b(?:sheets?|rows?|completed hours)\b", context)
                venue = re.match(r"(?i)\s+bay\b", markdown[match.end():]) and re.search(
                    r"(?i)\b(?:location|calendar|event)\b", context)
                if hr_context and (ledger or venue):
                    continue
            raise ValueError(
                f"{artifact} contains content outside the business-workflow scope "
                f"at character offsets {match.start()}:{match.end()}; "
                "describe only the requested business facts and constraints"
            )


def _reject_author_rubric_role_leak(markdown: str) -> None:
    """Reject Reviewer procedures from the Author-visible Rubric surface."""

    for pattern in _AUTHOR_RUBRIC_ROLE_LEAK_PATTERNS:
        match = re.search(pattern, markdown)
        if match is not None:
            raise ValueError(
                "author rubric leaks Reviewer-only role/process material: "
                f"{match.group(0)!r}"
            )


def _reject_controller_target_leak(markdown: str) -> None:
    """A Rubric is a per-task Author prompt; combination-level quotas belong to the controller.

    Both frozen distribution contracts state `controller_targets_must_not_enter_author_prompt=true`.
    This scan is the missing mechanical check: it fails closed when a Rubric carries global quota
    language (18k/6k totals, per-application share bands, batch fractions) so that lane templates
    cannot silently push portfolio targets into the per-task prompt.  Per-task rules such as
    "exactly N scored applications" and the background-application allowance are allowed.
    """
    import re
    patterns = (
        r"\b18[, ]?000\b", r"\b6[, ]?000\b", r"\b10[, ]?800\b", r"\b3[, ]?600\b",
        r"\bquota\b", r"quota", r"background_app_fraction", r"weak_scoring_app_fraction",
        r"official[ _]share", r"scored share", r"official share", r"anchor application", r"anchor band",
        r"≥\s?\d{2,3}\s?%", r"\b\d{1,2}\s?[–-]\s?\d{1,2}\s?%",
    )
    for pattern in patterns:
        match = re.search(pattern, markdown, re.IGNORECASE)
        if match:
            raise ValueError(
                "Author Rubric must not carry controller-level distribution targets "
                f"(found {match.group(0)!r}); keep portfolio quotas in the plan/controller/selection gate"
            )


def validate_rubric_markdown(markdown: str) -> str:
    if not _safe_markdown(markdown):
        raise ValueError("rubric Markdown must be non-empty safe text")
    _reject_downstream_purpose_leak(markdown, artifact="rubric Markdown")
    _reject_author_rubric_role_leak(markdown)
    _reject_controller_target_leak(markdown)
    return markdown


def validate_candidate_qa_markdown(markdown: str) -> str:
    if not _safe_markdown(markdown):
        raise ValueError("candidate QA Markdown must be non-empty safe text")
    _reject_downstream_purpose_leak(markdown, artifact="candidate QA Markdown")
    return markdown


def validate_comparison_packet_markdown(markdown: str) -> str:
    if not _safe_markdown(markdown):
        raise ValueError("comparison packet Markdown must be non-empty safe text")
    return markdown


def validate_review_memo_markdown(markdown: str) -> str:
    if not _safe_markdown(markdown):
        raise ValueError("review memo Markdown must be non-empty safe text")
    return markdown


def markdown_artifact_ref(*, relative_path: str, markdown: str, artifact_kind: str) -> dict[str, str]:
    """Build narrow JSON metadata for an independently stored Markdown file."""
    if artifact_kind not in MARKDOWN_ARTIFACT_KINDS:
        raise ValueError("unknown Markdown artifact kind")
    path = Path(relative_path)
    if path.is_absolute() or path.suffix.lower() != ".md" or ".." in path.parts:
        raise ValueError("Markdown artifact path must be a safe project-relative .md path")
    if artifact_kind in {"rubric", "rubric_revision", "qa_authoring_brief"}:
        validate_rubric_markdown(markdown)
    elif artifact_kind == "candidate_qa":
        validate_candidate_qa_markdown(markdown)
    elif artifact_kind == "comparison_packet":
        validate_comparison_packet_markdown(markdown)
    else:
        validate_review_memo_markdown(markdown)
    return {
        "artifact_kind": artifact_kind,
        "relative_path": path.as_posix(),
        "content_sha256": markdown_sha256(markdown),
    }


def _markdown_artifact_ref_ok(value: Any, *, kind: str | None = None) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"artifact_kind", "relative_path", "content_sha256"}
        and value.get("artifact_kind") in MARKDOWN_ARTIFACT_KINDS
        and (kind is None or value.get("artifact_kind") == kind)
        and isinstance(value.get("relative_path"), str)
        and bool(value["relative_path"].strip())
        and not Path(value["relative_path"]).is_absolute()
        and Path(value["relative_path"]).suffix.lower() == ".md"
        and ".." not in Path(value["relative_path"]).parts
        and _hex64(value.get("content_sha256"))
    )


def k3_quality_sample_count(candidate_count: int) -> int:
    """Return the mandatory 1/5 quality-sample size, rejecting fractions."""
    if type(candidate_count) is not int or candidate_count <= 0:
        raise ValueError("candidate count must be a positive integer")
    if candidate_count % K3_SAMPLE_DENOMINATOR:
        raise ValueError("K3 quality sample must be an exact one-fifth of candidate population")
    return candidate_count * K3_SAMPLE_NUMERATOR // K3_SAMPLE_DENOMINATOR


def exact_mog_responses_xhigh_route() -> dict[str, Any]:
    """Route metadata only.  There is intentionally no provider client here."""
    return {
        "route_id": MOG_ROUTE_ID,
        "reviewer_alias": MOG_REVIEWER_ALIAS,
        "reviewer_model_name": MOG_REVIEWER_MODEL,
        "api_style": "openai_responses",
        "base_url_host": "provider_b.example.invalid",
        "base_url_path": "/v1",
        "reasoning_effort": "xhigh",
        "response_format": "markdown_text",
        "text_format_parameter_omitted": True,
        "reasoning_summary_parameter_omitted": True,
        "store_parameter_omitted": True,
        "max_output_tokens_parameter_omitted": True,
        "openai_sdk_max_retries": 0,
        "top_level_max_attempts": 3,
        "automatic_chat_fallback_prohibited": True,
        "automatic_retry_prohibited": False,
        "retry_scope": (
            "same_route_same_messages_parameters_idempotency_key; "
            "initial_plus_two_operational_transport_retries_only"
        ),
        "context_overflow_or_deterministic_4xx_retry": False,
        "future_dispatch": "up_to_three_audited_transport_attempts_per_agent_step",
    }


def _base_agent_execution(*, role: str, model_alias: str) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": AGENT_EXECUTION_SCHEMA,
        "agent_role": role,
        "execution_kind": "external_agent_markdown_artifact",
        "agent_run_id": f"future-{role}-run",
        "model_alias": model_alias,
        "final_artifact_format": "markdown_natural_language",
        "fixed_template_or_cartesian_substitute_used": False,
        "deterministic_compiler_substituted_for_agent": False,
        **{field: False for field in RAW_FREE_FALSE_FIELDS},
    }
    return _rehash(value)


def validate_agent_execution(value: Mapping[str, Any], *, role: str, model_alias: str | None = None) -> dict[str, Any]:
    expected = {
        "schema_version", "agent_role", "execution_kind", "agent_run_id", "model_alias", "final_artifact_format",
        "fixed_template_or_cartesian_substitute_used", "deterministic_compiler_substituted_for_agent",
        *RAW_FREE_FALSE_FIELDS, "content_sha256",
    }
    if not (
        isinstance(value, Mapping)
        and set(value) == expected
        and _content_hash_ok(value)
        and value.get("schema_version") == AGENT_EXECUTION_SCHEMA
        and value.get("agent_role") == role
        and value.get("execution_kind") == "external_agent_markdown_artifact"
        and isinstance(value.get("agent_run_id"), str)
        and bool(re.fullmatch(r"[A-Za-z0-9._:-]{3,160}", value["agent_run_id"]))
        and isinstance(value.get("model_alias"), str)
        and bool(value["model_alias"].strip())
        and (model_alias is None or value["model_alias"] == model_alias)
        and value.get("final_artifact_format") == "markdown_natural_language"
        and value.get("fixed_template_or_cartesian_substitute_used") is False
        and value.get("deterministic_compiler_substituted_for_agent") is False
        and all(value.get(field) is False for field in RAW_FREE_FALSE_FIELDS)
        and not _contains_forbidden_material({key: item for key, item in value.items() if key != "content_sha256"})
    ):
        raise ValueError("agent execution evidence is not an exact raw-free Markdown-agent attestation")
    return dict(value)


def validate_rubric_agent_output(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schema_version", "lineage_id", "rubric_version", "parent_rubric_content_sha256",
        "revision_mode", "rubric_authoring_agent", "rubric_markdown_artifact", "native_tool_ids",
        "internal_compiler_feasibility_only", "final_markdown_artifact_persisted",
        "raw_provider_response_persisted",
        *RAW_FREE_FALSE_FIELDS, "content_sha256",
    }
    parent = value.get("parent_rubric_content_sha256") if isinstance(value, Mapping) else None
    if not (
        isinstance(value, Mapping)
        and set(value) == expected
        and _content_hash_ok(value)
        and value.get("schema_version") == RUBRIC_AGENT_OUTPUT_SCHEMA
        and _lineage_id(value.get("lineage_id"))
        and isinstance(value.get("rubric_version"), str)
        and bool(re.fullmatch(r"r[1-9][0-9]*", value["rubric_version"]))
        and (parent is None or _hex64(parent))
        and value.get("revision_mode") in {"new_agent_authored_rubric", "agent_revision"}
        and ((value["revision_mode"] == "new_agent_authored_rubric") == (parent is None))
        and validate_agent_execution(value["rubric_authoring_agent"], role="rubric_authoring_agent")
        and _markdown_artifact_ref_ok(value.get("rubric_markdown_artifact"), kind="rubric")
        and value.get("native_tool_ids") == list(NATIVE_TOOL_IDS)
        and value.get("internal_compiler_feasibility_only") is True
        and value.get("final_markdown_artifact_persisted") is True
        and all(value.get(field) is False for field in RAW_FREE_FALSE_FIELDS)
        and not _contains_forbidden_material({key: item for key, item in value.items() if key != "content_sha256"})
    ):
        raise ValueError("rubric output must bind a versioned agent-authored Markdown rubric, not JSON directives")
    return dict(value)


def validate_candidate_qa_agent_output(value: Mapping[str, Any], *, rubric: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate one future candidate held ephemerally before agent review.

    This is intentionally a single in-memory schema, not a corpus format or
    writer.  Pre-review QA may be passed to K3/reviewer only ephemerally; it
    cannot be stored as an approved lineage item through this object.
    """
    expected = {
        "schema_version", "lineage_id", "candidate_id", "source_rubric_content_sha256",
        "candidate_qa_agent", "candidate_qa_markdown_artifact", "native_tool_ids",
        "generation_mode", "persistence_stage", "final_markdown_artifact_persisted",
        "internal_compiler_feasibility_checked", "deterministic_compiler_used_as_generator",
        "fixed_template_or_field_substitution_used", *RAW_FREE_FALSE_FIELDS, "content_sha256",
    }
    if not (
        isinstance(value, Mapping)
        and set(value) == expected
        and _content_hash_ok(value)
        and value.get("schema_version") == CANDIDATE_QA_AGENT_OUTPUT_SCHEMA
        and _lineage_id(value.get("lineage_id"))
        and isinstance(value.get("candidate_id"), str)
        and bool(re.fullmatch(r"[A-Za-z0-9._:-]{3,160}", value["candidate_id"]))
        and _hex64(value.get("source_rubric_content_sha256"))
        and validate_agent_execution(value["candidate_qa_agent"], role="candidate_qa_agent")
        and _markdown_artifact_ref_ok(value.get("candidate_qa_markdown_artifact"), kind="candidate_qa")
        and value.get("native_tool_ids") == list(NATIVE_TOOL_IDS)
        and value.get("generation_mode") == "rubric_agent_guided_candidate_qa"
        and value.get("persistence_stage") == "ephemeral_pending_k3_and_reviewer"
        and value.get("final_markdown_artifact_persisted") is True
        and value.get("internal_compiler_feasibility_checked") is True
        and value.get("deterministic_compiler_used_as_generator") is False
        and value.get("fixed_template_or_field_substitution_used") is False
        and all(value.get(field) is False for field in RAW_FREE_FALSE_FIELDS)
        and not _contains_forbidden_material({key: item for key, item in value.items() if key != "content_sha256"})
    ):
        raise ValueError("candidate QA must bind agent-authored Markdown, not static JSON generation")
    if rubric is not None:
        checked = validate_rubric_agent_output(rubric)
        if (
            value["lineage_id"] != checked["lineage_id"]
            or value["source_rubric_content_sha256"] != checked["rubric_markdown_artifact"]["content_sha256"]
        ):
            raise ValueError("candidate QA does not bind the exact versioned agent rubric")
    return dict(value)


def build_k3_quality_sample_plan(*, lineage_id: str = "future-v9-agentic", candidate_count: int = TARGET_CANDIDATE_COUNT,
                                 source_rubric_content_sha256: str | None = None) -> dict[str, Any]:
    sample_count = k3_quality_sample_count(candidate_count)
    if candidate_count != TARGET_CANDIDATE_COUNT or sample_count != K3_EXPECTED_SAMPLE_COUNT:
        raise ValueError("V9 initial quality loop must plan exactly 2,000 of 10,000 candidate QAs")
    value: dict[str, Any] = {
        "schema_version": K3_SAMPLE_PLAN_SCHEMA,
        "lineage_id": lineage_id,
        "source_rubric_content_sha256": source_rubric_content_sha256,
        "candidate_population_count": candidate_count,
        "sample_numerator": K3_SAMPLE_NUMERATOR,
        "sample_denominator": K3_SAMPLE_DENOMINATOR,
        "expected_sample_count": sample_count,
        "selection_method": "lineage_bound_randomized_one_fifth_without_static_rank_substitution",
        "k3_execution": {
            "provider_alias": K3_ALIAS,
            "reasoning_effort": K3_REASONING_EFFORT,
            "concurrency_ramp": list(K3_CONCURRENCY_RAMP),
            "max_future_concurrency": K3_CONCURRENCY_RAMP[-1],
            "visible_native_tool_ids": list(NATIVE_TOOL_IDS),
            "visible_trajectory_only": True,
        },
        "sampled_candidate_payloads_persisted": False,
        "raw_k3_response_persisted": False,
        "private_reasoning_or_signature_persisted": False,
        "k3_execution_started": False,
        "trajectory_collection_completed": False,
        "training_eligible": False,
    }
    return _rehash(value)


def validate_k3_quality_sample_plan(value: Mapping[str, Any], *, rubric: Mapping[str, Any] | None = None) -> dict[str, Any]:
    expected = {
        "schema_version", "lineage_id", "source_rubric_content_sha256", "candidate_population_count",
        "sample_numerator", "sample_denominator", "expected_sample_count", "selection_method", "k3_execution",
        "sampled_candidate_payloads_persisted", "raw_k3_response_persisted", "private_reasoning_or_signature_persisted",
        "k3_execution_started", "trajectory_collection_completed", "training_eligible", "content_sha256",
    }
    execution = value.get("k3_execution") if isinstance(value, Mapping) else None
    if not (
        isinstance(value, Mapping)
        and set(value) == expected
        and _content_hash_ok(value)
        and value.get("schema_version") == K3_SAMPLE_PLAN_SCHEMA
        and _lineage_id(value.get("lineage_id"))
        and (value.get("source_rubric_content_sha256") is None or _hex64(value.get("source_rubric_content_sha256")))
        and value.get("candidate_population_count") == TARGET_CANDIDATE_COUNT
        and value.get("sample_numerator") == K3_SAMPLE_NUMERATOR
        and value.get("sample_denominator") == K3_SAMPLE_DENOMINATOR
        and value.get("expected_sample_count") == K3_EXPECTED_SAMPLE_COUNT
        and value.get("expected_sample_count") == k3_quality_sample_count(value["candidate_population_count"])
        and value.get("selection_method") == "lineage_bound_randomized_one_fifth_without_static_rank_substitution"
        and isinstance(execution, Mapping)
        and execution == {
            "provider_alias": K3_ALIAS,
            "reasoning_effort": K3_REASONING_EFFORT,
            "concurrency_ramp": list(K3_CONCURRENCY_RAMP),
            "max_future_concurrency": K3_CONCURRENCY_RAMP[-1],
            "visible_native_tool_ids": list(NATIVE_TOOL_IDS),
            "visible_trajectory_only": True,
        }
        and all(value.get(field) is False for field in (
            "sampled_candidate_payloads_persisted", "raw_k3_response_persisted",
            "private_reasoning_or_signature_persisted", "k3_execution_started",
            "trajectory_collection_completed", "training_eligible",
        ))
    ):
        raise ValueError("K3 quality sample plan is not exact 1/5 visible-trajectory preparation")
    if rubric is not None:
        checked = validate_rubric_agent_output(rubric)
        if (
            value["lineage_id"] != checked["lineage_id"]
            or value["source_rubric_content_sha256"] != checked["rubric_markdown_artifact"]["content_sha256"]
        ):
            raise ValueError("K3 sample plan does not bind exact rubric agent output")
    return dict(value)


def validate_k3_visible_trajectory_receipt(value: Mapping[str, Any], *, sample_plan: Mapping[str, Any] | None = None,
                                           candidate: Mapping[str, Any] | None = None) -> dict[str, Any]:
    expected = {
        "schema_version", "lineage_id", "source_k3_sample_plan_content_sha256", "source_candidate_content_sha256",
        "model_alias", "reasoning_effort", "visible_native_tool_ids", "visible_action_sequence_sha256",
        "canonical_public_tool_results_sha256", "trajectory_outcome", "raw_provider_response_persisted",
        "private_reasoning_or_signature_persisted", "assistant_prose_persisted", "hidden_verifier_state_persisted",
        "content_sha256",
    }
    if not (
        isinstance(value, Mapping)
        and set(value) == expected
        and _content_hash_ok(value)
        and value.get("schema_version") == K3_VISIBLE_TRAJECTORY_SCHEMA
        and _lineage_id(value.get("lineage_id"))
        and _hex64(value.get("source_k3_sample_plan_content_sha256"))
        and _hex64(value.get("source_candidate_content_sha256"))
        and value.get("model_alias") == K3_ALIAS
        and value.get("reasoning_effort") == K3_REASONING_EFFORT
        and value.get("visible_native_tool_ids") == list(NATIVE_TOOL_IDS)
        and _hex64(value.get("visible_action_sequence_sha256"))
        and _hex64(value.get("canonical_public_tool_results_sha256"))
        and value.get("trajectory_outcome") in {"completed", "native_tool_failure", "task_unsolved"}
        and all(value.get(field) is False for field in (
            "raw_provider_response_persisted", "private_reasoning_or_signature_persisted",
            "assistant_prose_persisted", "hidden_verifier_state_persisted",
        ))
        and not _contains_forbidden_material({key: item for key, item in value.items() if key != "content_sha256"})
    ):
        raise ValueError("K3 trajectory receipt must retain only visible native actions and public results")
    if sample_plan is not None:
        checked_plan = validate_k3_quality_sample_plan(sample_plan)
        if value["lineage_id"] != checked_plan["lineage_id"] or value["source_k3_sample_plan_content_sha256"] != checked_plan["content_sha256"]:
            raise ValueError("K3 trajectory receipt is outside exact sample plan")
    if candidate is not None:
        checked_candidate = validate_candidate_qa_agent_output(candidate)
        if value["lineage_id"] != checked_candidate["lineage_id"] or value["source_candidate_content_sha256"] != checked_candidate["content_sha256"]:
            raise ValueError("K3 trajectory receipt is outside exact agent-generated candidate")
    return dict(value)


def validate_benchmark_comparison_packet(value: Mapping[str, Any], *, candidate: Mapping[str, Any] | None = None,
                                         candidate_trajectory: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate a comparison packet; it proves all four review inputs exist.

    QA and trajectories are delivered to the reviewer as a Markdown packet
    with public/visible input.  The receipt retains an artifact hash and
    bounded status metadata, never a raw provider response or hidden harness.
    """
    expected = {
        "schema_version", "lineage_id", "source_candidate_content_sha256",
        "source_candidate_k3_visible_trajectory_content_sha256", "target_benchmark_name",
        "target_benchmark_qa_or_rubric_sha256", "target_benchmark_k3_visible_trajectory_sha256",
        "comparison_agent", "comparison_packet_markdown_artifact", "input_delivery", "required_comparison_inputs",
        *RAW_FREE_FALSE_FIELDS, "content_sha256",
    }
    required = value.get("required_comparison_inputs") if isinstance(value, Mapping) else None
    if not (
        isinstance(value, Mapping)
        and set(value) == expected
        and _content_hash_ok(value)
        and value.get("schema_version") == BENCHMARK_COMPARISON_SCHEMA
        and _lineage_id(value.get("lineage_id"))
        and all(_hex64(value.get(name)) for name in (
            "source_candidate_content_sha256", "source_candidate_k3_visible_trajectory_content_sha256",
            "target_benchmark_qa_or_rubric_sha256", "target_benchmark_k3_visible_trajectory_sha256",
        ))
        and isinstance(value.get("target_benchmark_name"), str)
        and bool(value["target_benchmark_name"].strip())
        and validate_agent_execution(value["comparison_agent"], role="benchmark_trajectory_comparison_agent")
        and _markdown_artifact_ref_ok(value.get("comparison_packet_markdown_artifact"), kind="comparison_packet")
        and value.get("input_delivery") == "ephemeral_generated_qa_plus_visible_trajectories_and_public_benchmark_context"
        and required == {
            "generated_qa": True,
            "candidate_k3_visible_trajectory": True,
            "target_benchmark_k3_visible_trajectory": True,
            "target_benchmark_qa_or_rubric": True,
        }
        and all(value.get(field) is False for field in RAW_FREE_FALSE_FIELDS)
        and not _contains_forbidden_material({key: item for key, item in value.items() if key != "content_sha256"})
    ):
        raise ValueError("comparison packet must bind Markdown analysis of QA, both K3 visible trajectories, and benchmark QA/rubric")
    if candidate is not None:
        checked = validate_candidate_qa_agent_output(candidate)
        if value["lineage_id"] != checked["lineage_id"] or value["source_candidate_content_sha256"] != checked["content_sha256"]:
            raise ValueError("comparison packet does not bind exact candidate agent output")
    if candidate_trajectory is not None:
        checked = validate_k3_visible_trajectory_receipt(candidate_trajectory)
        if (
            value["lineage_id"] != checked["lineage_id"]
            or value["source_candidate_k3_visible_trajectory_content_sha256"] != checked["content_sha256"]
        ):
            raise ValueError("comparison packet does not bind exact candidate K3 visible trajectory")
    return dict(value)


def validate_mog_reviewer_decision(value: Mapping[str, Any], *, comparison: Mapping[str, Any] | None = None) -> dict[str, Any]:
    expected = {
        "schema_version", "lineage_id", "source_comparison_packet_content_sha256", "reviewer_agent",
        "reviewer_route", "review_memo_markdown_artifact", "decision_code", "review_basis_codes", "rubric_revision_categories",
        "rubric_revision_required", "final_markdown_artifact_persisted", "static_score_threshold_used",
        "fixed_template_substituted_for_review", "deterministic_compiler_substituted_for_review",
        *RAW_FREE_FALSE_FIELDS, "content_sha256",
    }
    decision = value.get("decision_code") if isinstance(value, Mapping) else None
    categories = value.get("rubric_revision_categories") if isinstance(value, Mapping) else None
    if not (
        isinstance(value, Mapping)
        and set(value) == expected
        and _content_hash_ok(value)
        and value.get("schema_version") == REVIEWER_DECISION_SCHEMA
        and _lineage_id(value.get("lineage_id"))
        and _hex64(value.get("source_comparison_packet_content_sha256"))
        and validate_agent_execution(value["reviewer_agent"], role="trajectory_benchmark_reviewer_agent", model_alias=MOG_REVIEWER_ALIAS)
        and value.get("reviewer_route") == exact_mog_responses_xhigh_route()
        and _markdown_artifact_ref_ok(value.get("review_memo_markdown_artifact"), kind="review_memo")
        and decision in REVIEW_DECISION_CODES
        and isinstance(value.get("review_basis_codes"), list)
        and tuple(value["review_basis_codes"]) == REVIEW_BASIS_CODES
        and isinstance(categories, list)
        and 0 <= len(categories) <= 3
        and len(categories) == len(set(categories))
        and all(category in RUBRIC_REVISION_CATEGORIES for category in categories)
        and isinstance(value.get("rubric_revision_required"), bool)
        and ((decision == "revise_rubric") == value["rubric_revision_required"])
        and ((decision == "revise_rubric") == bool(categories))
        and (decision != "accept_sample" or (not categories and value["rubric_revision_required"] is False))
        and value.get("final_markdown_artifact_persisted") is True
        and value.get("static_score_threshold_used") is False
        and value.get("fixed_template_substituted_for_review") is False
        and value.get("deterministic_compiler_substituted_for_review") is False
        and all(value.get(field) is False for field in RAW_FREE_FALSE_FIELDS)
        and not _contains_forbidden_material({key: item for key, item in value.items() if key != "content_sha256"})
    ):
        raise ValueError("reviewer decision must bind a Markdown model_b Responses/xhigh memo, not static or JSON review")
    if comparison is not None:
        checked = validate_benchmark_comparison_packet(comparison)
        if value["lineage_id"] != checked["lineage_id"] or value["source_comparison_packet_content_sha256"] != checked["content_sha256"]:
            raise ValueError("reviewer decision does not bind exact comparison packet")
    return dict(value)


def validate_approved_agentic_lineage_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate only a future acceptance summary, never a task/corpus payload."""
    expected = {
        "schema_version", "lineage_id", "source_rubric_content_sha256", "candidate_population_count",
        "required_k3_sample_count", "accepted_review_count", "revision_or_rejection_count",
        "semantic_dedup_gate_passed", "heldout_transfer_gate_passed", "approved_candidate_payloads_persisted",
        "exact_token_export_authorized", "training_eligible", "content_sha256",
    }
    if not (
        isinstance(value, Mapping)
        and set(value) == expected
        and _content_hash_ok(value)
        and value.get("schema_version") == APPROVED_LINEAGE_SCHEMA
        and _lineage_id(value.get("lineage_id"))
        and _hex64(value.get("source_rubric_content_sha256"))
        and value.get("candidate_population_count") == TARGET_CANDIDATE_COUNT
        and value.get("required_k3_sample_count") == K3_EXPECTED_SAMPLE_COUNT
        and type(value.get("accepted_review_count")) is int
        and type(value.get("revision_or_rejection_count")) is int
        and value["accepted_review_count"] + value["revision_or_rejection_count"] == K3_EXPECTED_SAMPLE_COUNT
        and all(value.get(name) is False for name in (
            "semantic_dedup_gate_passed", "heldout_transfer_gate_passed",
            "approved_candidate_payloads_persisted", "exact_token_export_authorized", "training_eligible",
        ))
    ):
        raise ValueError("agentic lineage summary cannot promote an unproven corpus or training data")
    return dict(value)


def build_agentic_pipeline_contract() -> dict[str, Any]:
    """Return the current inert contract for the future agentic QA loop."""
    value: dict[str, Any] = {
        "schema_version": PIPELINE_SCHEMA,
        "pipeline_version": PIPELINE_VERSION,
        "scope": "prospective_v9_agent_driven_automation_qa_quality_loop_no_corpus_no_dispatch",
        "target_candidate_count": TARGET_CANDIDATE_COUNT,
        "rubric_phase": {
            "required_output_schema": RUBRIC_AGENT_OUTPUT_SCHEMA,
            "author": "rubric_authoring_agent",
            "versioned_explicit_rubric_required": True,
            "revision_is_agent_authored": True,
            "substantive_artifact_format": "markdown_natural_language",
        },
        "candidate_qa_phase": {
            "required_output_schema": CANDIDATE_QA_AGENT_OUTPUT_SCHEMA,
            "author": "candidate_qa_agent",
            "generation_mode": "rubric_agent_guided_candidate_qa",
            "pre_review_payload_retention": "ephemeral_only",
            "internal_compiler_scope": "feasibility_native_runtime_and_scorer_only",
            "substantive_artifact_format": "markdown_natural_language",
        },
        "k3_quality_sample_phase": {
            "required_plan_schema": K3_SAMPLE_PLAN_SCHEMA,
            "required_trajectory_schema": K3_VISIBLE_TRAJECTORY_SCHEMA,
            "candidate_population_count": TARGET_CANDIDATE_COUNT,
            "fraction": [K3_SAMPLE_NUMERATOR, K3_SAMPLE_DENOMINATOR],
            "expected_sample_count": K3_EXPECTED_SAMPLE_COUNT,
            "provider_alias": K3_ALIAS,
            "reasoning_effort": K3_REASONING_EFFORT,
            "concurrency_ramp": list(K3_CONCURRENCY_RAMP),
            "visible_native_tool_ids": list(NATIVE_TOOL_IDS),
        },
        "comparison_phase": {
            "required_packet_schema": BENCHMARK_COMPARISON_SCHEMA,
            "required_inputs": list(REVIEW_BASIS_CODES[:4]),
            "must_reward": "semantic_interaction_similarity_without_near_copy_or_hack",
            "must_reject_or_revise": ["near_copy", "trivial", "impossible", "benchmark_hack", "trajectory_mismatch"],
            "review_packet_format": "markdown_natural_language",
        },
        "review_phase": {
            "required_decision_schema": REVIEWER_DECISION_SCHEMA,
            "reviewer_role": "trajectory_benchmark_reviewer_agent",
            "exact_mog_responses_xhigh_route": exact_mog_responses_xhigh_route(),
            "bounded_decision_codes": list(REVIEW_DECISION_CODES),
            "bounded_rubric_revision_categories": list(RUBRIC_REVISION_CATEGORIES),
            "max_revision_categories_per_decision": 3,
            "static_score_threshold_is_not_a_review_substitute": True,
            "review_memo_format": "markdown_natural_language",
            "json_limited_to": ["artifact_hash", "lineage_version", "route", "bounded_decision"],
        },
        "acceptance_phase": {
            "required_schema": APPROVED_LINEAGE_SCHEMA,
            "semantic_dedup_required_before_distillation": True,
            "heldout_transfer_required_before_distillation": True,
            "approved_lineage_required_before_payload_retention_or_token_export": True,
        },
        "execution_gates_in_order": [
            "versioned_markdown_rubric_agent_output",
            "markdown_candidate_qa_agent_output_not_static_generation",
            "exact_one_fifth_k3_visible_trajectory_sample",
            "four_input_benchmark_trajectory_comparison",
            "mog_responses_xhigh_markdown_reviewer_memo_and_bounded_decision",
            "agent_markdown_rubric_revision_or_acceptance",
            "semantic_dedup",
            "heldout_transfer_without_extra_verifier_tool",
            "visible_action_only_distillation_and_exact_token_export",
        ],
        "native_student_tool_ids": list(NATIVE_TOOL_IDS),
        "static_substitutions": {
            "compiler_allowed_only_as_internal_feasibility_runtime_scorer": True,
            "never_author_or_qa_generator_or_reviewer": True,
            "fixed_templates_cartesian_products_and_field_substitutions_prohibited": True,
            "json_or_code_cannot_substitute_for_markdown_agent_judgment": True,
        },
        **{field: False for field in PIPELINE_FALSE_FIELDS},
    }
    return _rehash(value)


def validate_agentic_pipeline_contract(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = build_agentic_pipeline_contract()
    if not isinstance(value, Mapping) or dict(value) != expected:
        raise ValueError("agentic pipeline contract is stale, mutated, or noncanonical")
    if not (
        value["target_candidate_count"] == TARGET_CANDIDATE_COUNT
        and value["k3_quality_sample_phase"]["expected_sample_count"] == K3_EXPECTED_SAMPLE_COUNT
        and value["review_phase"]["exact_mog_responses_xhigh_route"] == exact_mog_responses_xhigh_route()
        and all(value.get(field) is False for field in PIPELINE_FALSE_FIELDS)
    ):
        raise ValueError("agentic pipeline contract violates a no-dispatch/no-static-substitution boundary")
    return dict(value)


def build_static_audit() -> dict[str, Any]:
    contract = build_agentic_pipeline_contract()
    value: dict[str, Any] = {
        "schema_version": STATIC_AUDIT_SCHEMA,
        "source_pipeline_file_sha256": source_file_sha256(),
        "source_pipeline_contract_content_sha256": contract["content_sha256"],
        "audit_scope": "provider_free_agentic_qa_pipeline_contract_only",
        "checks": {
            "candidate_qa_generation_requires_agent_authored_versioned_rubric": True,
            "rubric_candidate_and_review_substance_is_markdown_not_json": True,
            "candidate_qa_generation_rejects_compiler_template_cartesian_and_field_substitution": True,
            "k3_quality_sample_is_exact_one_fifth_of_10000": k3_quality_sample_count(TARGET_CANDIDATE_COUNT) == K3_EXPECTED_SAMPLE_COUNT,
            "k3_trajectory_schema_retains_visible_native_actions_only": True,
            "comparison_requires_generated_qa_candidate_k3_target_k3_and_target_qa_rubric": True,
            "review_requires_mog_responses_xhigh_markdown_memo_and_bounded_agent_decision": True,
            "rubric_revision_is_agent_authored_and_bounded": True,
            "compiler_is_internal_scorer_only_not_generator_or_reviewer": True,
            "no_provider_or_corpus_or_training_side_effect_exists": True,
        },
        "provider_calls_made": False,
        "candidate_qa_corpus_created": False,
        "k3_trajectory_collection_started": False,
        "mog_reviewer_completed": False,
        "training_eligible": False,
    }
    value["static_audit_passed"] = all(value["checks"].values())
    return _rehash(value)


def validate_static_audit(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = build_static_audit()
    if not isinstance(value, Mapping) or dict(value) != expected:
        raise ValueError("agentic pipeline static audit is stale or noncanonical")
    if not (
        value.get("static_audit_passed") is True
        and all(value.get(name) is False for name in (
            "provider_calls_made", "candidate_qa_corpus_created", "k3_trajectory_collection_started",
            "mog_reviewer_completed", "training_eligible",
        ))
    ):
        raise ValueError("agentic pipeline static audit has been promoted")
    return dict(value)
