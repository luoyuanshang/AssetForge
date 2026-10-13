"""Behavioral checks for task construction, review, repair and publication."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from assetforge.agent.author_runner import ModelEndpoint
from assetforge.pipeline.assets import AssetLibrary
from assetforge.pipeline.construction_assets import ROOT, construct
from assetforge.pipeline.flow import parse_object, run_pipeline
from assetforge.pipeline.runtime import DemoRuntime, load_runtime
from assetforge.pipeline.task_package import compile_task
from assetforge.pipeline.rubric_boundary import validate_rubric


def candidate():
    return {
        "instruction": "In the Support Tracker's Open Cases worksheet, mark ticket SUP-003 as "
                       "Ready for handover. Preserve its row key and existing customer note.",
        "assets": [{"id": "sheet_row_state", "version": "1.0.0", "alias": "tracker",
                    "reason": "Record the support handover status without changing the customer's note.",
                    "parameters": {
                        "business_context": "Support handover",
                        "spreadsheet_title": "Support Tracker", "worksheet_title": "Open Cases",
                        "headers": ["row_key", "status", "customer_note"],
                        "row_key": "SUP-003", "cells": {"status": "Ready for handover"},
                        "protected_fields": ["customer_note"],
                        "protected_values": {"customer_note": "Call after 10:00"},
                    }}],
    }


def verdict(decision="accept"):
    return {"decision": decision,
            "defects": [] if decision == "accept" else ["State the customer note preservation requirement."],
            "rubric_gaps": []}


def response(value):
    return {"choices": [{"message": {"role": "assistant", "content": json.dumps(value)},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}}


class ScriptedClient:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def chat(self, messages):
        self.calls.append(copy.deepcopy(messages))
        return response(self.values.pop(0))


@contextmanager
def endpoint(responses):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            try:
                result = response(responses[body["model"]].pop(0))
            except (KeyError, IndexError):
                self.send_error(400)
                return
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.library = AssetLibrary()

    def tearDown(self):
        self.temporary.cleanup()

    def compile(self, task):
        return compile_task(task, library=self.library, runtime=DemoRuntime(), task_id="test",
                            seed=9, business_time="2026-01-15T09:00:00Z")

    def run_flow(self, author, reviewer, **kwargs):
        return run_pipeline(rubric="Create a support tracker update and preserve its customer note.",
                            library=self.library, runtime=DemoRuntime(), author=author, reviewer=reviewer,
                            output=self.directory / "run", task_id="test", asset_ids=["sheet_row_state"], **kwargs)

    def test_catalog_all_descriptions_and_hashes(self):
        descriptions = self.library.describe()
        self.assertEqual(len(descriptions), 61)
        for row in descriptions:
            self.assertTrue(row["description"].strip())
            self.assertEqual(row["id"], row["definition"]["id"])
            self.assertEqual(row["version"], row["definition"]["version"])

    def test_all_documented_asset_parameters_construct(self):
        for entry in self.library.describe():
            examples = entry["definition"].get("parameter_examples", [])
            if entry["id"] == "sheet_row_state":
                examples = [{"parameters": candidate()["assets"][0]["parameters"]}]
            for position, example in enumerate(examples):
                with self.subTest(asset=entry["id"], example=position):
                    selected = {"id": entry["id"], "version": entry["version"],
                                "alias": "effect", "reason": "Business record construction.",
                                "parameters": example["parameters"]}
                    selections = []
                    if entry["id"] == "bounded_contact_batch":
                        target = example["adapter"]
                        source = "slack_users" if target == "hubspot_contacts" else "hubspot_contacts"

                        def records(adapter):
                            fields = ({"name": "Casey River", "status_text": "Initial", "status_emoji": ":memo:"}
                                      if adapter == "slack_users" else
                                      {"firstname": "Casey", "lastname": "River",
                                       "phone": "15550001", "jobtitle": "Initial"})
                            return [{"entity": name, "business_key": name + "@example.org", "fields": fields}
                                    for name in ("cedar", "maple")]

                        selections.append({"id": "customer_link", "version": self.library.entries["customer_link"]["version"],
                            "alias": "join", "reason": "Match existing business records.",
                            "parameters": {"business_context": "Customer service", "match_semantics": "exact_email_unique",
                                           "source": {"adapter": source, "records": records(source)},
                                           "target": {"adapter": target, "records": records(target)}}})
                    selections.append(selected)
                    _, fragments = self.library.compose(selections, task_id="matrix", seed=3,
                                                         business_time="2026-01-15T09:00:00Z")
                    self.assertTrue(fragments["world"])
                    self.assertEqual(set(fragments), {"world", "assertions", "entities", "relations", "writes",
                                                     "protected_fields", "asset_bindings", "blueprint_sha256"})

    def test_changed_asset_file_is_rejected(self):
        entry = self.library.catalog["assets"][0]
        path = ROOT / entry["description"]["path"]
        original = Path.read_bytes

        def read_bytes(target):
            value = original(target)
            return value + b"tampered" if target == path else value

        with patch.object(Path, "read_bytes", read_bytes):
            with self.assertRaisesRegex(ValueError, "drift"):
                AssetLibrary()

    def test_constructed_task_has_state_and_assertions(self):
        result = self.compile(candidate())
        self.assertTrue(result["passed"], result["diagnostics"])
        self.assertEqual(set(result["task"]), {"task_id", "instruction", "initial_state", "assertions"})
        self.assertEqual(len(result["task"]["assertions"]), 3)
        row = result["task"]["initial_state"]["google_sheets"]["rows"][0]
        self.assertEqual(row["cells"]["status"], "unset")
        self.assertEqual(row["cells"]["customer_note"], "Call after 10:00")

    def test_deterministic_task_construction(self):
        self.assertEqual(self.compile(candidate()), self.compile(candidate()))

    def test_composition_exports_only_task_fragments(self):
        blueprint, _ = self.library.compose(candidate()["assets"], task_id="test", seed=2,
                                           business_time="2026-01-15T09:00:00Z")
        fragments = construct(blueprint, self.library.catalog)
        self.assertEqual(set(fragments), {"world", "entities", "relations", "reads", "assertions",
                                         "writes", "protected_fields", "obligations",
                                         "asset_bindings", "blueprint_sha256"})

    def test_all_format_failures_reported(self):
        result = self.compile({"instruction": "", "assets": [], "extra_initial_state": [],
                               "extra_assertions": "invalid", "unexpected": True})
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["diagnostics"]), 5)
        self.assertTrue(all(set(row) >= {"gate", "pointer", "expected", "actual"}
                            for row in result["diagnostics"]))

    def test_row_key_header_diagnostic_gives_the_literal_name(self):
        task = candidate()
        task["assets"][0]["parameters"]["headers"][0] = "Ticket ID"
        result = self.compile(task)
        self.assertFalse(result["passed"])
        error = result["diagnostics"][0]
        self.assertEqual(error["expected"], {"contains": "row_key"})
        self.assertEqual(error["actual"], ["Ticket ID", "status", "customer_note"])
        self.assertEqual(error["pointer"], "/assets/0/parameters/headers")

    def test_runtime_reports_multiple_invalid_assertions(self):
        task = candidate()
        task["extra_assertions"] = [{"type": "unknown-one"}, {"type": "unknown-two"}]
        result = self.compile(task)
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["diagnostics"]), 2)

    def test_asset_state_cannot_be_overwritten(self):
        task = candidate()
        task["extra_initial_state"] = {"google_sheets": "wrong"}
        self.assertFalse(self.compile(task)["passed"])

    def test_success_publishes_qa_and_model_events(self):
        result = self.run_flow(ScriptedClient([candidate()]), ScriptedClient([verdict()]))
        self.assertEqual(result["status"], "accepted")
        out = self.directory / "run"
        self.assertEqual(hashlib.sha256((out / "qa.json").read_bytes()).hexdigest(), result["qa_sha256"])
        self.assertEqual(result["usage"], {"prompt_tokens": 14, "completion_tokens": 10})
        events = list((out / "events").glob("*.json"))
        self.assertEqual(len(events), 2)
        for event in events:
            value = json.loads(event.read_text())
            self.assertTrue(value["messages"])
            self.assertTrue(value["response"]["choices"])

    def test_gate_failure_does_not_call_reviewer(self):
        review = ScriptedClient([])
        result = self.run_flow(ScriptedClient([{"instruction": "", "assets": []}]), review, attempts=1)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(review.calls, [])
        self.assertFalse((self.directory / "run/qa.json").exists())

    def test_gate_repair_receives_all_findings(self):
        bad = candidate()
        bad["instruction"] = ""
        bad["extra_assertions"] = "invalid"
        author = ScriptedClient([bad, candidate()])
        result = self.run_flow(author, ScriptedClient([verdict()]), attempts=2)
        self.assertEqual(result["status"], "accepted")
        repair = json.loads(author.calls[1][1]["content"])
        self.assertEqual(len(repair["changes_needed"]), 2)

    def test_review_rejection_triggers_bounded_repair(self):
        author = ScriptedClient([candidate(), candidate()])
        reviewer = ScriptedClient([verdict("reject"), verdict()])
        result = self.run_flow(author, reviewer, attempts=2)
        self.assertEqual(result["attempt"], 2)
        self.assertEqual(len(author.calls), 2)
        self.assertEqual(len(reviewer.calls), 2)
        request = json.loads(author.calls[1][1]["content"])
        self.assertEqual(request["changes_needed"], verdict("reject")["defects"])
        self.assertNotEqual(author.calls[0][0]["content"], reviewer.calls[0][0]["content"])

    def test_repair_budget_exhaustion_does_not_publish_qa(self):
        result = self.run_flow(ScriptedClient([candidate(), candidate()]),
                               ScriptedClient([verdict("reject"), verdict("reject")]), attempts=2)
        self.assertEqual(result["status"], "rejected")
        self.assertFalse((self.directory / "run/qa.json").exists())

    def test_invalid_review_does_not_publish_qa(self):
        with self.assertRaisesRegex(ValueError, "Reviewer must return"):
            self.run_flow(ScriptedClient([candidate()]), ScriptedClient([{"decision": "accept"}]))
        self.assertEqual(json.loads((self.directory / "run/result.json").read_text())["status"], "failed")
        self.assertFalse((self.directory / "run/qa.json").exists())

    def test_response_with_one_json_block_is_parsed(self):
        fence = chr(96) * 3
        text = "Business review completed.\n" + fence + "json\n" + json.dumps(verdict()) + "\n" + fence
        self.assertEqual(parse_object(text), verdict())

    def test_multiple_json_blocks_are_refused(self):
        fence = chr(96) * 3
        block = fence + "json\n" + json.dumps(verdict()) + "\n" + fence
        with self.assertRaisesRegex(ValueError, "unambiguous"):
            parse_object(block + "\n" + block)

    def test_provider_failure_keeps_request_and_failure_record(self):
        class Unavailable:
            def chat(self, messages):
                raise RuntimeError("model endpoint is unreachable")
        with self.assertRaisesRegex(RuntimeError, "unreachable"):
            self.run_flow(Unavailable(), ScriptedClient([]))
        out = self.directory / "run"
        self.assertTrue((out / "requests/01.author.json").is_file())
        self.assertEqual(json.loads((out / "result.json").read_text())["status"], "failed")
        self.assertFalse((out / "qa.json").exists())

    def test_resume_reuses_matching_paid_responses(self):
        class Unavailable:
            def chat(self, messages):
                raise RuntimeError("model endpoint is unreachable")
        with self.assertRaises(RuntimeError):
            self.run_flow(ScriptedClient([candidate()]), Unavailable())
        author = ScriptedClient([])
        result = self.run_flow(author, ScriptedClient([verdict()]), resume=True)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["cached_calls"], 1)
        self.assertEqual(author.calls, [])
        self.assertTrue((self.directory / "run/recovery/result-01.json").is_file())

    def test_resume_rejects_input_drift(self):
        self.run_flow(ScriptedClient([candidate()]), ScriptedClient([verdict()]))
        with self.assertRaisesRegex(ValueError, "inputs differ"):
            self.run_flow(ScriptedClient([]), ScriptedClient([]), resume=True, seed=123)

    def test_resume_rejects_changed_qa(self):
        self.run_flow(ScriptedClient([candidate()]), ScriptedClient([verdict()]))
        (self.directory / "run/qa.json").write_text("{}\n")
        with self.assertRaisesRegex(ValueError, "published QA"):
            self.run_flow(ScriptedClient([]), ScriptedClient([]), resume=True)

    def test_malformed_asset_identity_gets_gate_feedback(self):
        task = candidate()
        task["assets"][0]["id"] = ["invalid"]
        result = self.run_flow(ScriptedClient([task]), ScriptedClient([]), attempts=1)
        self.assertEqual(result["status"], "rejected")

    def test_unknown_asset_is_refused_before_any_model_call(self):
        author, reviewer = ScriptedClient([]), ScriptedClient([])
        with self.assertRaisesRegex(ValueError, "unknown assets"):
            run_pipeline(rubric="One task", library=self.library, runtime=DemoRuntime(),
                         author=author, reviewer=reviewer, output=self.directory / "invalid",
                         task_id="test", asset_ids=["missing-asset"])
        self.assertFalse(author.calls)

    def test_missing_model_review_configuration_fails(self):
        with patch.dict(os.environ, {"ASSETFORGE_API_BASE_URL": "http://localhost/v1",
                                     "ASSETFORGE_API_KEY": "test-key",
                                     "ASSETFORGE_MODEL": "author"}, clear=True):
            with self.assertRaisesRegex(ValueError, "REVIEWER_MODEL"):
                ModelEndpoint(role="reviewer")

    def test_unknown_runtime_refused(self):
        with self.assertRaisesRegex(ValueError, "runtime must"):
            load_runtime(None)

    def test_author_specification_excludes_controller_information(self):
        for text in ("Create tasks to satisfy this quota.", "Follow the reviewer prompt.",
                     "Build a training dataset.", "Use these distribution ratios."):
            with self.assertRaisesRegex(ValueError, "project-level"):
                validate_rubric(text)
        validate_rubric("Update this spreadsheet cell for an employee training registration.")

    def test_existing_run_is_not_overwritten(self):
        self.run_flow(ScriptedClient([candidate()]), ScriptedClient([verdict()]))
        original = (self.directory / "run/result.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_flow(ScriptedClient([candidate()]), ScriptedClient([verdict()]))
        self.assertEqual(original, (self.directory / "run/result.json").read_bytes())

    def test_http_endpoint_and_real_cli_publish_qa(self):
        with endpoint({"author": [candidate()], "reviewer": [verdict()]}) as (base_url, calls):
            env = {**os.environ, "ASSETFORGE_API_BASE_URL": base_url, "ASSETFORGE_API_KEY": "test-key",
                   "ASSETFORGE_MODEL": "author", "ASSETFORGE_REVIEWER_MODEL": "reviewer",
                   "ASSETFORGE_REVIEWER_API_BASE_URL": base_url, "ASSETFORGE_REVIEWER_API_KEY": "test-key",
                   "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"}
            process = subprocess.run([sys.executable, "-m", "assetforge.tools.run_pipeline",
                "--rubric", str(ROOT / "examples/rubric_support.md"), "--runtime", "demo",
                "--output", str(self.directory / "cli"), "--attempts", "1"],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual([request["model"] for request in calls], ["author", "reviewer"])
        self.assertEqual(json.loads(process.stdout)["status"], "accepted")
        self.assertTrue((self.directory / "cli/qa.json").is_file())


if __name__ == "__main__":
    unittest.main()
