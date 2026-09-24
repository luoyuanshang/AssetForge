"""Independent-review consumer of construction manifests.

The reviewer reads a frozen construction bundle and adds the asset-assembly record to the
review packet, so a review sees both the generated task and the assets it was composed from.
The deployment-specific receipt packer is optional; when it is unavailable the plain reviewer
is returned, because a reviewer that refuses to run over an optional packer is worse than one
that runs and reports what it could check.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .construction_assets import digest, require
from .construction_manifest import load_bundle, reference

BUNDLE_ENV = "ASSETFORGE_CONSTRUCTION_BUNDLE"

ASSEMBLY_NOTE = (
    "\n\nConstruction-asset assembly record (for independent review only; not visible to the "
    "solver). Check every obligation and the actual task semantics item by item; a local pass "
    "never substitutes for a complete review.\n```json\n{payload}\n```\n"
)


class PlainReviewer:
    """Minimal reviewer entry point: verifies a frozen construction bundle and reports.

    It is used when the deployment-specific reviewer stack (receipt packer, provider fallback
    chains, a particular model-routing layer) is not installed.  It performs the checks that
    belong to this repository -- bundle integrity, the task matching the bound construction,
    and the asset-assembly record -- and states plainly that the model-based semantic review
    was not run.
    """

    name = "plain-reviewer"

    def build_packet(self, *, bundle=None, generated_task_path=None, **kwargs):
        """Return (packet_markdown, binding) for a bound construction bundle."""
        if bundle is None:
            bundle = os.environ.get(BUNDLE_ENV)
        if not bundle:
            raise ValueError("plain reviewer needs a construction bundle")
        values, check = load_bundle(Path(bundle), "review")
        binding = {"bundle": reference(Path(bundle)), "validation": check}
        packet = "## Construction review\n\n"
        if generated_task_path is not None:
            actual = json.loads(Path(generated_task_path).read_text())
            require(digest(actual) == digest(values["task.json"]),
                    "Reviewer task differs from bound construction")
            binding["task_sha256"] = digest(actual)
            packet += "The submitted task matches the bound construction.\n\n"
        manifest = values["construction_manifest.json"]
        detail = {
            "blueprint": manifest.get("blueprint"),
            "bindings": manifest.get("bindings"),
            "application_roles": manifest.get("application_roles"),
            "application_role_check": manifest.get("application_role_check"),
        }
        packet += ASSEMBLY_NOTE.format(payload=json.dumps(detail, ensure_ascii=False))
        packet += ("\n_Model-based semantic review was not run in this environment; only the "
                   "repository-owned checks above were performed._\n")
        return packet, binding

    def main(self, argv=None):
        import argparse
        parser = argparse.ArgumentParser(description="Plain construction reviewer")
        parser.add_argument("--bundle", type=Path, default=None)
        parser.add_argument("--generated-task", type=Path, default=None)
        parser.add_argument("--output", type=Path, default=None)
        args = parser.parse_args(argv)
        packet, binding = self.build_packet(bundle=args.bundle,
                                           generated_task_path=args.generated_task)
        payload = {"reviewer": self.name, "binding": binding, "packet": packet}
        if args.output:
            args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
            print(args.output)
        else:
            print(packet)
        return 0


def _plain_reviewer():
    """The reviewer used when the optional receipt packer is not present."""
    return PlainReviewer()


def install():
    """Return the reviewer, preferring the receipt-evidence path when it is available."""
    try:
        from .release_receipt_evidence import install as native_install
        reviewer = native_install()
    except Exception:
        return _plain_reviewer()

    original = reviewer.build_packet
    if getattr(original, "_construction_manifest", False):
        return reviewer

    def build_packet(**kwargs):
        packet, binding = original(**kwargs)
        bundle = os.environ.get(BUNDLE_ENV)
        if bundle:
            values, check = load_bundle(Path(bundle), "review")
            actual = json.loads(kwargs["generated_task_path"].read_text())
            require(digest(actual) == digest(values["task.json"]),
                    "Reviewer task differs from bound construction")
            manifest = values["construction_manifest.json"]
            binding["construction_manifest"] = {
                "manifest": reference(Path(bundle) / "construction_manifest.json"),
                "seal": reference(Path(bundle) / "complete.json"),
                "validation": check,
            }
            detail = {
                "blueprint": manifest["blueprint"],
                "bindings": manifest["bindings"],
                "construction": manifest["construction"],
                "execution_profile": manifest["execution_profile"],
                "expansion": manifest["expansion"],
                "application_roles": manifest.get("application_roles"),
                "application_role_check": manifest.get("application_role_check"),
                "native_role_evidence_location": (
                    "native_result.application_role_native_evidence in the bound reversible "
                    "native packet"
                ),
            }
            packet += ASSEMBLY_NOTE.format(payload=json.dumps(detail, ensure_ascii=False))
        return packet, binding

    build_packet._construction_manifest = True
    reviewer.build_packet = build_packet
    return reviewer
