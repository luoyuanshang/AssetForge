#!/usr/bin/env python3
"""Run one Author session: compose a task from the admitted assets and compile it.

This is the entry point for the Author stage.  It supplies the agent loop itself (see
``assetforge/agent/author_runner.py``), so only a model endpoint and the native runtime are
needed:

    export ASSETFORGE_API_KEY=...  ASSETFORGE_API_BASE_URL=...  ASSETFORGE_MODEL=...
    export ASSETFORGE_RUNTIME_ROOT=/path/containing/the/runtime
    python -m assetforge.tools.run_author --rubric my_rubric.md --domain sales \
        --assets assetforge/artifacts/construction_assets --run-root runs/demo --ordinal 1

The task the Author hands back is compiled and native-validated by the pipeline's own
``official_task_package`` tool before it is written; a task that does not compile is reported,
not silently kept.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from assetforge.agent import author_runner, tools as agent_tools  # noqa: E402
from assetforge.pipeline import operator_config  # noqa: E402
from assetforge.pipeline.construction_assets import immutable_write, require  # noqa: E402


def asset_catalog_markdown(assets_dir: Path, limit: int | None = None) -> str:
    """The Markdown catalogue the Author reads: one entry per admitted asset."""
    entries = []
    for d in sorted(assets_dir.glob("*/*")):
        desc = d / "ASSET.md"
        if not desc.exists():
            continue
        entries.append(f"### {d.parent.name}@{d.name}\n\n{desc.read_text(encoding='utf-8').strip()}")
        if limit and len(entries) >= limit:
            break
    return "\n\n".join(entries)


def build_system_prompt(rubric_text: str, catalog: str) -> str:
    return f"""You are a multi-turn QA-authoring agent designing one original, stateful,
evidence-dependent business-workflow task.

The Author Rubric below is the sole semantic task-generation specification. Everything before it
is only the minimal tool/submission protocol and must not add or change a target distribution,
task family, application count or quality criterion.

Work in three steps:

1. READ. A read-only catalogue of the admitted construction assets is included below. Each entry
   states the business effect that asset produces and the parameters it accepts. Read it, and use
   `code_exec` if you need to inspect files or check consistency.
2. BUILD. Write the complete natural-language specification of the task first -- the public
   request, the business setting, and the key business rules -- and treat it as the single source
   of truth. Compose the task out of the admitted assets, inside the capability the catalogue
   reports: an asset that produces no scored effect may hold background or act as a distractor,
   but must never carry the required effect or the decisive private fact.
3. SUBMIT. Call `compile_and_test_task_package` with the task. It validates the task against the
   native runtime and the scorer. Fix what it reports and call it again until it accepts. Do not
   edit the public request or the business rules to make it pass -- fix the world, the assertions
   or the oracle path. When it accepts, you are done.

Use fresh business names, people, organizations, values and dates. Do not copy a published task.

---

{('Here is the read-only asset catalogue:' + chr(10) + chr(10) + catalog) if catalog else ''}

---

Here is the complete Author Rubric:

{rubric_text.strip()}
"""


def main(argv=None):
    operator_config.apply()
    parser = argparse.ArgumentParser(description="Run one Author session")
    parser.add_argument("--rubric", type=Path, required=True, help="the Author Rubric (Markdown)")
    parser.add_argument("--domain", required=True, help="business domain for this task")
    parser.add_argument("--assets", type=Path,
                        default=ROOT / "assetforge/artifacts/construction_assets",
                        help="directory of admitted assets")
    parser.add_argument("--run-root", type=Path, required=True, help="where outputs are written")
    parser.add_argument("--ordinal", type=int, default=1, help="task ordinal within the run")
    parser.add_argument("--max-turns", type=int,
                        default=int(operator_config.value("ASSETFORGE_AUTHOR_MAX_TURNS", "40")))
    parser.add_argument("--catalog-limit", type=int, default=None,
                        help="include at most this many assets in the catalogue (for a quick run)")
    parser.add_argument("--allow-unvalidated", action="store_true",
                        help="keep a task even if the compiler rejects it (report it either way)")
    args = parser.parse_args(argv)

    (ROOT / "POLICY.md").read_text(encoding="utf-8")     # fail early outside the repository
    rubric_text = args.rubric.read_text(encoding="utf-8")
    require(len(rubric_text.strip()) > 40, "the Rubric must be substantive Markdown")

    run_root = args.run_root.resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    # The compiler records a repository-relative candidate path, so keep run outputs inside the
    # repository; that also makes a run self-describing when it is copied elsewhere.
    try:
        run_root.relative_to(ROOT)
    except ValueError:
        raise SystemExit(f"--run-root must be inside the repository ({ROOT})") from None
    candidate_id = f"author-{args.domain}-{args.ordinal:07d}"

    catalog = asset_catalog_markdown(args.assets, args.catalog_limit)

    # The controller-side tools: the contract inspector and the compiler.  Both come from the
    # pipeline, so the validation the Author sees is the pipeline's own.
    #
    # Compiling a task means validating it against the native runtime, so this stage genuinely
    # needs the runtime.  Say so clearly instead of letting a raw import error surface.
    from assetforge.pipeline.native_runtime_interface import is_available as _runtime_available
    if not _runtime_available():
        raise SystemExit(
            "the Author stage needs the native runtime: its job is to compile the authored task "
            "and check it against the runtime's schema, API and scorer.\n"
            "Install the runtime, or set ASSETFORGE_RUNTIME_ROOT to the directory that contains "
            "its package (and ASSETFORGE_RUNTIME_PACKAGE to that package's importable name if it "
            "is not discovered automatically), then retry.")
    from assetforge.pipeline.official_task_package import (OfficialContractInspectorTool,
                                                           OfficialTaskPackageTool)
    candidate_path = run_root / "candidates" / (candidate_id + ".json")
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    inspector = OfficialContractInspectorTool()
    compiler = OfficialTaskPackageTool(
        candidate_relative_path=str(candidate_path.relative_to(ROOT)),
        candidate_id=candidate_id,
        domain=args.domain,
        rubric_sha256=hashlib.sha256(rubric_text.encode("utf-8")).hexdigest(),
        rubric_text=rubric_text,
    )

    def compile_tool(call_args):
        result = compiler.call(call_args)
        ok = False
        try:
            payload = json.loads(result) if isinstance(result, str) else result
            ok = bool(payload.get("accepted"))
        except Exception:
            ok = "accepted" in str(result)[:400]
        if ok:
            immutable_write(candidate_path, json.loads(result) if isinstance(result, str) else result)
            return {"__emit__": True, "record": candidate_path.read_text(encoding="utf-8")}
        return result

    tool_map = {
        "code_exec": agent_tools.code_exec,
        "visit": agent_tools.visit,
        "search": agent_tools.search,
        "inspect_task_contract": lambda a: inspector.call(a),
        "compile_and_test_task_package": compile_tool,
    }
    tool_defs = [
        author_runner.tool_schema("code_exec", "Run a short Python snippet or shell command.",
                                  {"code": {"type": "string"}, "language": {"type": "string"}},
                                  ["code"]),
        author_runner.tool_schema("visit", "Fetch a URL and return its text.",
                                  {"url": {"type": "string"}}, ["url"]),
        author_runner.tool_schema("search", "Search the web when it is configured.",
                                  {"query": {"type": "string"}}, ["query"]),
        author_runner.tool_schema("inspect_task_contract",
                                  "Inspect the native runtime's application and endpoint contract.",
                                  {"app": {"type": "string"}, "endpoint": {"type": "string"}}),
        author_runner.tool_schema("compile_and_test_task_package",
                                  "Submit the authored task for compilation and native validation.",
                                  {"candidate_markdown": {"type": "string"},
                                   "task_source": {"type": "object"}},
                                  ["candidate_markdown", "task_source"]),
    ]

    print(f"run root   : {run_root}")
    print(f"candidate  : {candidate_id}")
    print(f"assets     : {len(catalog.split('### ')) - 1} in the catalogue")
    print(f"endpoint   : {operator_config.value('ASSETFORGE_API_BASE_URL', '(unset)')}")
    print(f"model      : {operator_config.value('ASSETFORGE_MODEL', '(unset)')}")
    print()

    result = author_runner.run_author(
        system_prompt=build_system_prompt(rubric_text, catalog),
        user_prompt=(f"Author exactly one complete, executable task for the {args.domain} "
                     f"domain. Follow the Rubric."),
        tools=tool_map, tool_defs=tool_defs, max_turns=args.max_turns)

    immutable_write(run_root / "author_trace.json",
                    {"candidate_id": candidate_id, "status": result["status"],
                     "turns": result["turns"], "trace": result["trace"]})
    print(f"status     : {result['status']} after {result['turns']} turn(s)")
    if result.get("record") is None:
        print("no task was emitted; see author_trace.json")
        return 1
    print(f"task       : {candidate_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
