"""Compare generated instructions with public prompts without emitting source text."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .generator import FORBIDDEN_BRANDS


TOKEN = re.compile(r"[a-z0-9]+")
TOOL_NAME = "assetforge.pipeline.contamination"
TOOL_VERSION = "3.0.0"


def _source_prompts_from_result_root(result_root: Path) -> list[dict[str, str]]:
    """Read public task prompts from sealed the benchmark result files.

    The result tree already contains the exact public task messages used by the
    official runner.  Reading those files avoids importing and materializing
    every benchmark environment merely to recover the same 600 user prompts.
    Only prompt text is consumed; trajectories and scores are ignored.
    """
    by_id: dict[str, dict[str, str]] = {}
    for path in sorted(result_root.glob("*_chunks/chunk_*/**/benchmark-result.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for task in payload.get("tasks", []):
            if not isinstance(task, dict):
                continue
            source_id = str(task.get("name") or task.get("task") or task.get("id") or "")
            messages = task.get("messages") or []
            user_text = "\n".join(
                str(message.get("content") or "")
                for message in messages
                if isinstance(message, dict) and message.get("role") == "user"
            )
            if not source_id or not user_text.strip():
                continue
            row = {"source_id": source_id, "text": user_text}
            previous = by_id.get(source_id)
            if previous is not None and previous != row:
                raise ValueError(f"public prompt drift for {source_id} in {path}")
            by_id[source_id] = row
    if len(by_id) != 600:
        raise ValueError(
            f"expected exactly 600 unique public prompts under {result_root}, "
            f"found {len(by_id)}"
        )
    return [by_id[source_id] for source_id in sorted(by_id)]


def _instruction(task: dict[str, Any]) -> str:
    direct = task.get("instruction")
    if isinstance(direct, str) and direct.strip():
        return direct
    prompt = task.get("prompt")
    if isinstance(prompt, list):
        users = [
            str(message.get("content") or "")
            for message in prompt
            if isinstance(message, dict) and message.get("role") == "user"
        ]
        if len(users) == 1 and users[0].strip():
            return users[0]
    return ""


def _tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def _ngrams(tokens: list[str], n: int = 5) -> set[tuple[str, ...]]:
    return {tuple(tokens[index:index + n]) for index in range(max(0, len(tokens) - n + 1))}


def _jaccard(left: set, right: set) -> float:
    return len(left & right) / len(left | right) if left or right else 0.0


def audit(
    generated: list[dict],
    source_prompts: list[str | dict[str, Any]],
    *,
    jaccard_limit: float = 0.12,
    sequence_limit: float = 0.55,
    source_corpus_name: str = "provided-source-prompts",
) -> dict:
    sources = []
    source_manifest = []
    for index, item in enumerate(source_prompts):
        if isinstance(item, dict):
            source_id = str(item.get("source_id") or f"source-{index:06d}")
            text = str(item.get("text") or "")
        else:
            source_id = f"source-{index:06d}"
            text = str(item)
        source_hash = hashlib.sha256(text.encode()).hexdigest()
        tokens = _tokens(text)
        sources.append((source_id, source_hash, tokens, _ngrams(tokens)))
        source_manifest.append({
            "source_id": source_id,
            "prompt_sha256": source_hash,
        })
    flagged = []
    maxima = []
    nearest_sources = []
    for task in generated:
        text = _instruction(task)
        tokens = _tokens(text)
        grams = _ngrams(tokens)
        best = (0.0, 0.0, "", "")
        candidates = []
        for source_id, source_hash, source_tokens, source_grams in sources:
            jac = _jaccard(grams, source_grams)
            candidates.append((jac, source_id, source_hash, source_tokens))
        # A high token-sequence overlap necessarily shares local n-grams for
        # instructions of this length.  Shortlist by 5-gram Jaccard first so a
        # 1,000 x 600 audit does not run 600,000 quadratic sequence alignments.
        neighbors = []
        for jac, source_id, source_hash, source_tokens in sorted(
            candidates,
            key=lambda row: (row[0], row[1]),
            reverse=True,
        )[:5]:
            # SequenceMatcher is evaluated only on token sequences, never raw
            # source text, and its matching source is represented by a hash.
            seq = SequenceMatcher(None, tokens, source_tokens, autojunk=False).ratio()
            neighbors.append({
                "source_id": source_id,
                "source_prompt_sha256": source_hash,
                "normalized_5gram_jaccard": round(jac, 6),
                "token_sequence_ratio": round(seq, 6),
            })
            if (jac, seq) > (best[0], best[1]):
                best = (jac, seq, source_id, source_hash)
        # Historical fictional-runtime tasks were forbidden from borrowing real
        # product brands. Official-runtime-matched tasks necessarily use the
        # official service catalog (for example Slack and HubSpot), so brand
        # presence is not contamination for that schema.
        brands = (
            []
            if task.get("schema_version") == "agent-authored-official-automation-task-v1"
            else sorted(brand for brand in FORBIDDEN_BRANDS if brand in text.lower())
        )
        row = {
            "generated_task_id": task.get("task_id"),
            "max_5gram_jaccard": round(best[0], 6),
            "max_token_sequence_ratio": round(best[1], 6),
            "closest_source_id": best[2],
            "closest_source_sha256": best[3],
            "forbidden_brands": brands,
        }
        maxima.append(row)
        nearest_sources.append({
            "generated_task_id": task.get("task_id"),
            "neighbors": neighbors,
        })
        if best[0] >= jaccard_limit or best[1] >= sequence_limit or brands:
            flagged.append(row)
    instruction_bindings = [
        {
            "task_id": task.get("task_id"),
            "task_content_sha256": hashlib.sha256(
                json.dumps(
                    task,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "instruction_sha256": hashlib.sha256(
                _instruction(task).encode()
            ).hexdigest(),
        }
        for task in generated
    ]
    report = {
        "schema_version": "synthetic-workflow-contamination-audit-v3",
        "implementation": {
            "tool": TOOL_NAME,
            "version": TOOL_VERSION,
            "source_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        },
        "authority": {
            "runtime_generated_report": True,
            "supersedes_unverified_candidate_self_audit": True,
        },
        "generated_tasks": len(generated),
        "generated_corpus_sha256": hashlib.sha256(
            "".join(json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for task in generated).encode()
        ).hexdigest(),
        "source_corpus": {
            "name": source_corpus_name,
            "prompt_count": len(source_manifest),
            "manifest_sha256": hashlib.sha256(
                json.dumps(
                    source_manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "source_text_emitted": False,
        },
        "algorithm": {
            "normalization": "unicode-lowercase-ascii-alphanumeric-token-v1",
            "tokenization": "regex-[a-z0-9]+-v1",
            "lexical_shingle": "normalized-token-5gram-set-jaccard-v1",
            "sequence_similarity": "difflib-sequencematcher-token-sequence-autojunk-false-v1",
            "nearest_source_count": 5,
        },
        "source_prompts_compared": len(source_prompts),
        "generated_instruction_bindings": instruction_bindings,
        "thresholds": {"max_5gram_jaccard": jaccard_limit, "max_token_sequence_ratio": sequence_limit},
        "flagged_count": len(flagged),
        "passed": not flagged,
        "max_observed_5gram_jaccard": max((row["max_5gram_jaccard"] for row in maxima), default=0),
        "max_observed_token_sequence_ratio": max((row["max_token_sequence_ratio"] for row in maxima), default=0),
        "nearest_sources": nearest_sources,
        "flagged": flagged,
        "source_text_emitted": False,
    }
    report["content_sha256"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--runtime-root", type=Path)
    source.add_argument("--source-result-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.source_result_root is not None:
        source_prompts = _source_prompts_from_result_root(args.source_result_root)
        source_corpus_name = "the benchmark public-600 sealed official-run prompts"
    else:
        import sys

        import os
        if getattr(args, "runtime_root", None):
            os.environ["ASSETFORGE_RUNTIME_ROOT"] = str(args.runtime_root.resolve())
        from benchmark.domains import get_domain_dataset

        source_prompts = []
        for domain in ("sales", "marketing", "operations", "support", "finance", "hr"):
            for row in get_domain_dataset(domain):
                prompt = row.get("prompt", [])
                if isinstance(prompt, str):
                    prompt = json.loads(prompt)
                source_prompts.append({
                    "source_id": str(row.get("task") or row.get("id") or ""),
                    "text": "\n".join(
                        str(message.get("content", ""))
                        for message in prompt
                        if isinstance(message, dict)
                    ),
                })
        source_corpus_name = (
            "the benchmark public-600 via "
            "benchmark.domains.get_domain_dataset"
        )
    task_text = args.tasks.read_text(encoding="utf-8")
    try:
        parsed = json.loads(task_text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        generated = [parsed]
    elif isinstance(parsed, list):
        generated = parsed
    else:
        generated = [
            json.loads(line)
            for line in task_text.splitlines()
            if line.strip()
        ]
    report = audit(
        generated,
        source_prompts,
        source_corpus_name=source_corpus_name,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("generated_tasks", "flagged_count", "passed", "content_sha256")}))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
