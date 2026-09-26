"""Generate novel executable workflow worlds from an abstract rubric.

The generator uses a fictional application namespace and typed state machines.
It does not consume the benchmark prompts or assertion values.  A model may
later propose scenario blueprints, but compilation and grading remain
deterministic so malformed generator output cannot silently become training data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from .role_surface import capabilities_for_task, permute_task_surfaces


FICTIONAL_APPS = {
    "RuleVault": ("search", "read"),
    "CaseFlow": ("search", "read", "update", "create"),
    "GridWorks": ("search", "read", "update", "create"),
    "SignalPost": ("search", "read", "send"),
    "ValuePort": ("search", "read", "update", "create"),
    "WorkLoom": ("search", "read", "update", "create"),
    "PeopleHarbor": ("search", "read", "update", "create"),
    "PulseDesk": ("search", "read", "update", "create", "send"),
}
APP_CAPABILITIES = FICTIONAL_APPS
FORBIDDEN_BRANDS = {
    "airtable", "asana", "benchmark", "bamboohr", "basecamp", "calendly",
    "confluence", "docusign", "facebook", "freshdesk", "gmail", "google",
    "gorgias", "helpscout", "hubspot", "instagram", "intercom", "jira",
    "linkedin", "mailchimp", "monday", "notion", "recruitee", "salesforce",
    "slack", "trello", "twilio", "social_app", "x.com", "workflow_hub", "zendesk", "zoom",
}
FAMILIES = (
    "policy_filtered_update",
    "cross_source_join",
    "recency_resolution",
    "threshold_routing",
    "negative_guard_batch",
    "verified_multi_effect",
)
DOMAINS = ("sales", "marketing", "operations", "support", "finance", "hr")
TASK_SCHEMA_VERSION = "synthetic-workflow-task-v2"
VERIFICATION_SEMANTICS = (
    "dependency-ordered-entity-bound-readback+persistent-forbidden-touch-v3"
)
COMPILER_CONTROL_DEFAULTS = {
    "eligible_count_delta": 0,
    "excluded_count_scale": 1.0,
}
SPLIT_HARDENING_ROUTES = (
    ("PeopleHarbor", "profiles"),
    ("PulseDesk", "tickets"),
    ("WorkLoom", "tasks"),
    ("GridWorks", "rows"),
)


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _token(seed: int, index: int, label: str, length: int = 8) -> str:
    return hashlib.sha256(f"{seed}:{index}:{label}".encode()).hexdigest()[:length]


def _split(signature: str) -> str:
    bucket = int(hashlib.sha256(signature.encode()).hexdigest()[:8], 16) % 20
    if bucket < 14:
        return "development"
    if bucket < 17:
        return "calibration"
    return "heldout"


def _record(record_id: str, *, status: str, score: int, region: str, blocked: bool = False) -> dict:
    return {
        "id": record_id,
        "status": status,
        "score": score,
        "region": region,
        "blocked": blocked,
        "revision": 1,
    }


def normalize_compiler_controls(value: dict | None) -> dict:
    """Validate the tiny, auditable surface used by candidate rubric patches.

    The active v1 corpus takes the exact default path.  A reviewer cannot add
    arbitrary code or task content: the rule gate may only adjust two bounded
    cardinalities that already exist in the deterministic compiler.
    """
    controls = dict(COMPILER_CONTROL_DEFAULTS)
    if value is None:
        return controls
    if not isinstance(value, dict) or set(value) - set(controls):
        raise ValueError("unsupported compiler control")
    controls.update(value)
    delta = controls["eligible_count_delta"]
    scale = controls["excluded_count_scale"]
    if not isinstance(delta, int) or isinstance(delta, bool) or not -1 <= delta <= 1:
        raise ValueError("eligible_count_delta must be an integer between -1 and 1")
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not 0.5 <= float(scale) <= 1.5:
        raise ValueError("excluded_count_scale must be between 0.5 and 1.5")
    controls["excluded_count_scale"] = float(scale)
    return controls


def _split_hardened_instruction(task: dict, route_rows: list[dict], variant: int) -> str:
    """Render one answer-free surface for a topology-hardened candidate."""
    domain = str(task["domain_label"])
    family = str(task["family"])
    policy = next(
        row for row in task["initial_state"]["RuleVault"]["policies"]
        if row.get("active") is True
    )
    records = task["initial_state"]["CaseFlow"]["records"]
    region = str(records[0]["region"])
    opening = (
        "Resolve the fictional {domain} work queue from authoritative workspace state.",
        "Complete this fictional {domain} control review with an auditable evidence trail.",
        "Handle the pending fictional {domain} cases using only current structured records.",
        "Reconcile the fictional {domain} batch and preserve a replayable decision path.",
    )[variant % 4].format(domain=domain)
    discovery = (
        "First inspect the active RuleVault rule and independently enumerate CaseFlow candidates.",
        "Establish the governing RuleVault revision, then fetch the candidate set directly from CaseFlow.",
        "Ground the decision in a fresh RuleVault policy read plus an independent CaseFlow search.",
        "Read the current routing authority in RuleVault before examining CaseFlow records one by one.",
    )[(variant // 4) % 4]
    selection = (
        "Eligible records are unblocked entries in region {region} whose numeric score meets the policy minimum.",
        "Keep only {region} records with blocked=false and score at or above the live threshold.",
        "Apply the rule's numeric cutoff to the {region} subset, excluding every blocked record.",
        "Derive the action set by intersecting region={region}, sufficient score, and a false blocked flag.",
    )[(variant // 16) % 4].format(region=region)
    execution = (
        "Change only that action set to status {status} and send exactly one concise SignalPost notice per changed record on {channel}.",
        "For each qualifying record, write {status} once and emit one nonduplicated completion message to {channel}; touch nothing else.",
        "Commit the policy target {status} only for qualified IDs, paired one-to-one with notices in SignalPost channel {channel}.",
        "Perform one idempotent {status} update and one {channel} notification for every eligible entity, with no effects on exclusions.",
    )[(variant // 8) % 4].format(
        status=policy["target_status"], channel=policy["notification_channel"],
    )
    closure = (
        "After each effect, read both the changed record and the sent notice back from their authoritative stores.",
        "Close the loop with independent post-write reads of every record and its corresponding message.",
        "Do not claim completion until authoritative readback confirms each state change and external notice.",
        "Verify persistence by fetching every updated entity and delivered message after the writes finish.",
    )[(variant // 2) % 4]
    route = "; ".join(
        f"{row['app']}/{row['collection']} record {row['record_id']}"
        for row in route_rows
    )
    extras = [
        f"Before any state change, read these independent control markers in order: {route}.",
        "Never modify an excluded record, rewrite an authority source, reuse an inactive policy, or duplicate an effect.",
    ]
    if family == "cross_source_join":
        extras.append("Bind each entity through its matching verified GridWorks roster row before updating.")
    elif family == "recency_resolution":
        extras.append("When policy revisions conflict, use the newest active revision without mixing fields.")
    elif family == "threshold_routing":
        extras.append("Include the numeric threshold decision in each notice rather than relying on descriptive labels.")
    elif family == "negative_guard_batch":
        extras.append("Inspect the full candidate population so every negative guard is accounted for.")
    elif family == "verified_multi_effect":
        artifact = next(
            row.get("record_id") for row in task["assertions"]
            if row.get("id") == "followup-artifact-created"
        )
        extras.append(f"Also create exactly one WorkLoom follow-up task {artifact} and read it back.")
    if "ValuePort" in task["allowed_apps"]:
        extras.append("Cross-check the current ValuePort authorization for every proposed change.")
    return " ".join((opening, discovery, selection, execution, closure, *extras))


def _surface_diverse_instruction(task: dict, variant: int) -> str:
    """Render a higher-entropy visible surface without changing the reference path.

    Every clause is derived from the already compiled task state and abstract
    family.  No source benchmark wording or answer key is consulted.  The
    banks intentionally vary register, sentence order, and connective words;
    this candidate exists to test the independent character proxy, not to
    silently replace the active corpus.
    """
    domain = str(task["domain_label"])
    family = str(task["family"])
    policy = next(row for row in task["initial_state"]["RuleVault"]["policies"] if row.get("active") is True)
    records = task["initial_state"]["CaseFlow"]["records"]
    region = str(records[0]["region"])
    status = str(policy["target_status"])
    channel = str(policy["notification_channel"])
    openings = (
        f"Audit the fictional {domain} queue using only the workspace evidence provided.",
        f"You are closing a fictional {domain} control cycle; make the decision reproducible.",
        f"Reconcile the pending fictional {domain} batch against its current authorities.",
        f"Complete the fictional {domain} review while preserving every safety constraint.",
        f"Prepare a traceable disposition for the fictional {domain} workload.",
        f"Operate on the fictional {domain} records, with no assumptions beyond fresh reads.",
        f"Resolve this fictional {domain} workflow as an evidence-bound transaction.",
        f"Handle the fictional {domain} queue and leave a replayable audit trail.",
    )
    authority = (
        "Read the active RuleVault policy first, then enumerate candidates in CaseFlow.",
        "Establish the live RuleVault rule before querying the CaseFlow candidate set.",
        "Use a fresh policy lookup and an independent CaseFlow search as the decision basis.",
        "Treat the current RuleVault revision as authoritative and inspect CaseFlow separately.",
        "Start with authoritative policy state; do not infer eligibility from labels or memory.",
        "Fetch the governing rule and candidate records as separate evidence sources.",
        "Ground every mutation in a current RuleVault read followed by a CaseFlow enumeration.",
        "First establish which policy is active, then inspect all relevant CaseFlow entities.",
    )
    selection = (
        f"Choose only unblocked records in region {region} whose score reaches the live minimum.",
        f"The eligible set is the {region} slice with blocked=false and score at least the threshold.",
        f"Filter the candidate population by region={region}, sufficient numeric score, and a false blocked flag.",
        f"Use the policy cutoff on {region} records; blocked entries remain excluded even when their score passes.",
        f"Derive the action set from structured fields: region {region}, score >= minimum, blocked false.",
        f"Do not select by prose similarity: retain exactly the {region} records satisfying the numeric rule.",
        f"Eligibility requires all three facts simultaneously—{region} membership, enough score, and no block.",
        f"Inspect the full candidate set and keep only the records that satisfy the active {region} rule.",
    )
    effects = (
        f"For each selected ID, write status {status} once and send one concise notice to SignalPost channel {channel}.",
        f"Apply the target status {status} only to eligible entities, pairing each update with one notice on {channel}.",
        f"Perform one idempotent {status} update per qualifying record and one nonduplicated SignalPost message in {channel}.",
        f"Change no excluded state: eligible records receive {status}, and each resulting effect gets exactly one {channel} notice.",
        f"Commit the policy target {status} for the action set and emit a one-to-one completion message through {channel}.",
        f"Mutation scope is narrow: update eligible records to {status}, then notify through SignalPost/{channel} exactly once each.",
        f"Execute the paired effects—record status {status} and matching channel {channel} message—without duplicates.",
        f"Write only the approved target state and its corresponding SignalPost notice; leave every exclusion untouched.",
    )
    closure = (
        "After every write, fetch the changed record and the sent message from their authoritative stores before claiming success.",
        "A completion claim is valid only after independent readback confirms both the state effect and the external notice.",
        "Close the loop with post-write reads for every record and its corresponding message.",
        "Do not finish on a successful write response alone; verify persistence of both effects.",
        "Read back each changed entity and delivered notice, then finalize only when all checks pass.",
        "The final state must be witnessed by authoritative record and message reads, not inferred from tool acknowledgement.",
        "Require a paired readback for each mutation and notification before returning a success result.",
        "Only an all-clear from state and message readbacks permits finalization.",
    )
    safety = (
        "Never rewrite policy or identity evidence, touch an excluded record, or duplicate an effect.",
        "Keep authority sources read-only and preserve negative guards throughout the transaction.",
        "Any missing evidence blocks the mutation; do not substitute a guessed entity or stale policy.",
        "Treat every forbidden guard as persistent: exclusions and authority rows must remain unchanged.",
        "Use exact IDs and current evidence; abort rather than broadening the action set.",
        "No inactive rule, cross-entity substitution, repeated send, or unverified final claim is allowed.",
        "Preserve the original evidence and abstain when an entity-bound dependency is missing.",
        "Safety takes precedence over completion: an unverified write must not be attempted.",
    )
    reads = [
        row for row in task.get("operation_plan", [])
        if row.get("operation") == "read"
    ][:4]
    route = "Control reads: " + " → ".join(
        f"{row.get('app')}/{row.get('collection')}" for row in reads
    ) if reads else "Control reads must precede every state change."
    family_clause = {
        "cross_source_join": "Bind each selected entity to its verified roster identity before updating.",
        "recency_resolution": "When revisions conflict, use the newest active revision without mixing fields.",
        "threshold_routing": "Include the numeric threshold reasoning in each notice.",
        "negative_guard_batch": "Inspect all candidates so every exclusion is accounted for.",
        "verified_multi_effect": "The additional follow-up effect, if declared, also needs an independent readback.",
    }.get(family, "Keep the dependency order explicit from evidence to action to readback.")
    banks = (openings, authority, selection, effects, closure, safety)
    indices = [
        (variant * 3 + 1) % 8,
        (variant * 5 + 2) % 8,
        (variant * 7 + 3) % 8,
        (variant * 11 + 4) % 8,
        (variant * 13 + 5) % 8,
        (variant * 17 + 6) % 8,
    ]
    clauses = [bank[index] for bank, index in zip(banks, indices)]
    # Keep opening→authority→selection→effects→closure semantic order, while
    # rotating only the independent route/safety clauses.
    return " ".join((clauses[0], clauses[1], clauses[2], route, family_clause, clauses[3], clauses[4], clauses[5]))


def _surface_diverse_instruction_v2(task: dict, variant: int) -> str:
    """Render split-disjoint visible language while preserving one reference path.

    The split-specific banks are deliberately authored from the abstract task
    contract, not from any benchmark item or answer key.  Development,
    calibration and heldout use different clause families so a curriculum
    cannot pass a cross-split surface audit merely by recombining the same
    fixed sentences.  Exact app, field and value references remain because
    they are required to execute the already-compiled fictional world.
    """
    split = str(task["split"])
    if split not in {"development", "calibration", "heldout"}:
        raise ValueError(f"unsupported split for surface diversity: {split}")
    domain = str(task["domain_label"])
    family = str(task["family"])
    policy = next(
        row for row in task["initial_state"]["RuleVault"]["policies"]
        if row.get("active") is True
    )
    records = task["initial_state"]["CaseFlow"]["records"]
    region = str(records[0]["region"])
    status = str(policy["target_status"])
    channel = str(policy["notification_channel"])
    reads = [
        row for row in task.get("operation_plan", [])
        if row.get("operation") == "read"
    ][:4]
    route_text = " -> ".join(
        f"{row.get('app')}/{row.get('collection')}" for row in reads
    ) or "the declared read endpoints"

    # No sentence is shared between these three split banks.  Each tuple
    # contains four independently selectable realizations of the same
    # executable contract.
    if split == "development":
        banks = {
            "opening": (
                f"Work through the fictional {domain} assignment as a controlled operation.",
                f"Process this fictional {domain} workload with an explicit evidence trail.",
                f"Resolve the fictional {domain} queue under the workspace control rules.",
                f"Carry out the fictional {domain} disposition without relying on memory.",
            ),
            "ground": (
                "Retrieve the live RuleVault policy before independently listing CaseFlow candidates.",
                "Begin from a current RuleVault lookup, and obtain the CaseFlow population in a separate read.",
                "Establish the governing RuleVault revision first; enumerate CaseFlow records afterward.",
                "Use fresh policy evidence from RuleVault and a distinct CaseFlow query to build the action set.",
            ),
            "select": (
                f"Retain {region} records only when blocked is false and their numeric score meets the active cutoff.",
                f"Eligibility is the intersection of region {region}, a passing score, and blocked=false.",
                f"Apply the live threshold to the {region} slice while excluding every blocked entry.",
                f"Form the candidate set from structured facts: {region}, score at least minimum, no block.",
            ),
            "effect": (
                f"Write {status} once per eligible record and issue one SignalPost notice through {channel} for that record.",
                f"Each qualifying ID receives a single {status} transition plus one matching message on {channel}.",
                f"Commit only the approved {status} mutations, paired one-to-one with nonrepeated {channel} notifications.",
                f"For every selected entity, perform one status={status} update and exactly one send to {channel}.",
            ),
            "close": (
                "Fetch every changed record and every emitted message after the writes, then report completion.",
                "Post-write reads of both stored state and delivered notices are required before finishing.",
                "Confirm persistence through independent record retrieval and message retrieval for each effect.",
                "Do not finalize until authoritative reads witness all mutations and all notifications.",
            ),
            "safe": (
                "Leave authority data and excluded records untouched; never repeat a mutation or send.",
                "A missing dependency requires abstention, and protected evidence must remain read-only.",
                "Do not widen entity scope, use an inactive rule, alter source evidence, or duplicate an effect.",
                "Preserve every negative guard and stop rather than substituting an unverified identity.",
            ),
            "route": f"Development evidence path: {route_text}.",
        }
        family_text = {
            "cross_source_join": "Join each action target to the independently verified roster identity.",
            "recency_resolution": "Resolve competing rules by the newest active revision without field mixing.",
            "threshold_routing": "Carry the numeric cutoff decision into the corresponding notice.",
            "negative_guard_batch": "Scan the complete population so every exclusion remains represented.",
            "verified_multi_effect": "Create the declared follow-up artifact exactly once and retrieve it afterward.",
        }.get(family, "Keep evidence, decision, write, and confirmation in dependency order.")
    elif split == "calibration":
        banks = {
            "opening": (
                f"Run a control-room reconciliation for the invented {domain} case set.",
                f"Complete the simulated {domain} review as a traceable control cycle.",
                f"Evaluate the made-up {domain} batch with auditable checkpoints.",
                f"Handle the sandbox {domain} docket using evidence-bound decisions.",
            ),
            "ground": (
                "First pin the effective rule with a RuleVault read; separately inventory entities in CaseFlow.",
                "Anchor the verdict to a newly fetched RuleVault row and an independent CaseFlow inventory.",
                "Obtain present-tense governance from RuleVault, then inspect the CaseFlow set on its own terms.",
                "Two observations establish the starting state: the effective RuleVault rule and the CaseFlow inventory.",
            ),
            "select": (
                f"Admit an item only if it belongs to {region}, clears the policy number, and is not blocked.",
                f"The actionable subset combines {region} membership with sufficient score and an unset block flag.",
                f"Reject blocked or out-of-region entries; among the remainder, enforce the current numeric floor for {region}.",
                f"Compute the disposition set by checking region={region}, the cutoff comparison, and a false block value together.",
            ),
            "effect": (
                f"Move each admitted entity to {status} a single time, with one correlated SignalPost delivery in {channel}.",
                f"For the accepted set, pair one {status} state transition with one unique {channel} communication.",
                f"Execute a one-to-one mapping from qualifying IDs to {status} writes and SignalPost/{channel} sends.",
                f"Limit side effects to one {status} change and one {channel} dispatch for every approved target.",
            ),
            "close": (
                "Use fresh retrievals to attest the saved records and the delivered communications before closing the run.",
                "Closure depends on subsequent store reads for each updated entity and its paired delivery.",
                "A write acknowledgement is insufficient: re-open the resulting records and communications before exit.",
                "End only after later observations corroborate both classes of side effect for the whole set.",
            ),
            "safe": (
                "Keep rejected entities and governing sources invariant, and suppress all repeated operations.",
                "If an identity or control fact is absent, withhold action instead of extrapolating.",
                "Inactive governance, guessed joins, scope expansion, and duplicate dispatches are prohibited.",
                "Maintain the exclusion boundary and do not edit any fact used as decision authority.",
            ),
            "route": f"Calibration checkpoint sequence: {route_text}.",
        }
        family_text = {
            "cross_source_join": "Correlate a candidate with its confirmed roster key before side effects begin.",
            "recency_resolution": "Select the latest effective revision and avoid composing a synthetic hybrid rule.",
            "threshold_routing": "Record the quantitative routing basis inside its outbound communication.",
            "negative_guard_batch": "Account for the entire inventory, including all non-actionable members.",
            "verified_multi_effect": "The stipulated work item is also singular and needs a later retrieval checkpoint.",
        }.get(family, "Observe the causal sequence from authority through effects to corroboration.")
    else:
        banks = {
            "opening": (
                f"Treat the fabricated {domain} request as a closure ledger that needs defensible witnesses.",
                f"Settle the imaginary {domain} portfolio while producing replayable proof of outcome.",
                f"Bring the synthetic {domain} matter to a verified terminal state.",
                f"Adjudicate this artificial {domain} collection with conservative transaction semantics.",
            ),
            "ground": (
                "Independently obtain the operative RuleVault entry and survey CaseFlow before deciding anything.",
                "Consult RuleVault for controlling authority, then discover the CaseFlow universe through another observation.",
                "Let a contemporaneous RuleVault fetch define the rule while a separate CaseFlow survey supplies subjects.",
                "Source governance and candidate evidence independently from RuleVault and CaseFlow, respectively.",
            ),
            "select": (
                f"A subject qualifies precisely when its region is {region}, its score is no lower than required, and no block is set.",
                f"Constrain the set to unblocked {region} subjects satisfying the operative quantitative boundary.",
                f"Only entries simultaneously matching {region}, the score predicate, and the negative block predicate may proceed.",
                f"Derive the permitted IDs by intersecting the {region} cohort, threshold passers, and nonblocked subjects.",
            ),
            "effect": (
                f"For every permitted subject, persist {status} once and transmit a single associated SignalPost item via {channel}.",
                f"Realize two singular effects per allowed ID: status becomes {status}, and one message enters {channel}.",
                f"The authorized transaction is one {status} persistence together with one uniquely paired delivery to {channel}.",
                f"Apply no more than one {status} transition and one SignalPost/{channel} transmission to each permitted entity.",
            ),
            "close": (
                "Witness both persisted entities and transmitted items through later authoritative lookups prior to any success claim.",
                "Terminal success requires after-the-fact retrieval evidence for every state transition and every transmission.",
                "Re-observe the durable entity state and the messaging store; only complete when both ledgers agree.",
                "Finalize after independent downstream observations prove that each paired effect survived its write call.",
            ),
            "safe": (
                "Authority artifacts, denied subjects, and already-completed effects are outside the mutation boundary.",
                "Unresolved provenance forces a no-op; neither identity nor eligibility may be inferred.",
                "Forbid stale authority, entity substitution, protected-row edits, repeated writes, and repeated transmissions.",
                "Honor every disqualifier and preserve the evidence base in its original form.",
            ),
            "route": f"Heldout witness chain: {route_text}.",
        }
        family_text = {
            "cross_source_join": "Prove entity equivalence with the roster key before authorizing a transaction.",
            "recency_resolution": "The controlling revision is the most recent active one, used as an indivisible record.",
            "threshold_routing": "Embed the measured boundary result in the linked transmission.",
            "negative_guard_batch": "Survey every subject so nonqualifiers are demonstrably preserved.",
            "verified_multi_effect": "The required auxiliary artifact is unique and must acquire its own persistence witness.",
        }.get(family, "Respect the dependency graph from observation to transaction to terminal witness.")

    offsets = (1, 3, 5, 7, 11, 13)
    names = ("opening", "ground", "select", "effect", "close", "safe")
    selected = [banks[name][(variant * offset + position) % 4]
                for position, (name, offset) in enumerate(zip(names, offsets))]
    return " ".join((selected[0], selected[1], banks["route"], selected[2], family_text,
                     selected[3], selected[4], selected[5]))


def _surface_diverse_instruction_v3(task: dict, variant: int) -> str:
    """Add an explicit visible contract to the split-disjoint v2 surface.

    v2 intentionally compressed some identifiers and message requirements and
    consequently needed a semantic sufficiency check.  v3 keeps the v2
    split-specific prose and appends a split-specific, answer-free witness
    ledger derived from assertions.  It exposes only the IDs/queries a model
    must read or place in a notice; it never exposes expected outcomes.
    """
    base = _surface_diverse_instruction_v2(task, variant)
    split = str(task["split"])
    evidence = []
    controls = []
    message_tokens = []
    auth_reads = []
    artifact_ids = []
    for assertion in task.get("assertions") or []:
        if assertion.get("type") == "evidence_read":
            app = str(assertion.get("app") or "")
            collection = str(assertion.get("collection") or "")
            record_id = assertion.get("record_id")
            query = assertion.get("query")
            subject = f"{app}/{collection}"
            if record_id:
                subject += f" record={record_id}"
            elif isinstance(query, dict) and query:
                subject += f" query={json.dumps(query, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
            evidence.append(subject)
            if str(assertion.get("id", "")).startswith("blueprint-control-"):
                controls.append(f"{app}/{collection} record={record_id}")
            if app == "ValuePort":
                auth_reads.append(subject)
        if assertion.get("type") == "message_exists":
            message_tokens.extend(str(token) for token in (assertion.get("contains_all") or []))
        if assertion.get("type") == "record_exists" and str(assertion.get("id", "")).startswith("followup-"):
            artifact_ids.append(str(assertion.get("record_id") or ""))
    message_tokens = list(dict.fromkeys(token for token in message_tokens if token))
    evidence_text = " | ".join(evidence) or "the declared evidence reads"
    controls_text = " | ".join(controls) or "the declared control markers"
    token_text = ", ".join(message_tokens) or "the target identifier and current status"
    pieces = {
        "development": (
            f"Development witness ledger—perform these reads with the shown key or query before mutation: {evidence_text}.",
            f"The protected control markers are mandatory reads: {controls_text}.",
            f"Every SignalPost notice must carry these exact content tokens: {token_text}.",
            f"ValuePort authorization evidence is read-only and required: {' | '.join(auth_reads)}." if auth_reads else "",
            f"Create exactly one WorkLoom follow-up artifact and read it back: {', '.join(artifact_ids)}." if artifact_ids else "",
        ),
        "calibration": (
            f"Calibration evidence ledger (complete before side effects): {evidence_text}.",
            f"Do not omit the following control witnesses: {controls_text}.",
            f"The message body must include each of these literal tokens: {token_text}.",
            f"Treat these ValuePort authorization observations as read-only prerequisites: {' | '.join(auth_reads)}." if auth_reads else "",
            f"The singular follow-up object is {', '.join(artifact_ids)}; retrieve it after creation." if artifact_ids else "",
        ),
        "heldout": (
            f"Required observation ledger, in addition to the policy and candidate reads: {evidence_text}.",
            f"Before acting, witness every named control marker: {controls_text}.",
            f"A valid outbound notice contains all of these exact tokens: {token_text}.",
            f"Read-only authorization proof must cover: {' | '.join(auth_reads)}." if auth_reads else "",
            f"The extra durable object must be created once and subsequently read: {', '.join(artifact_ids)}." if artifact_ids else "",
        ),
    }[split]
    return " ".join([base, *(piece for piece in pieces if piece)])


def _surface_diverse_instruction_v4(task: dict, variant: int) -> str:
    """Expose generic execution rules without enumerating answer-bearing IDs.

    Exact blueprint-control and follow-up-artifact IDs are task inputs and are
    named.  Eligible business record IDs, roster bindings, authorization IDs,
    message targets, policy answers, and numeric decisions must instead be
    discovered from the visible state and are never enumerated here.
    """
    base = _surface_diverse_instruction_v2(task, variant)
    split = str(task["split"])
    family = str(task["family"])
    controls = [
        f"{row.get('app')}/{row.get('collection')} record={row.get('record_id')}"
        for row in task.get("assertions") or []
        if str(row.get("id", "")).startswith("blueprint-control-")
    ]
    artifacts = [
        str(row.get("record_id") or "")
        for row in task.get("assertions") or []
        if row.get("type") == "record_exists" and str(row.get("id", "")).startswith("followup-")
    ]
    control_text = " | ".join(controls)
    if split == "development":
        clauses = [
            f"Read each named development control marker before any write: {control_text}.",
            "For every proposed target, obtain any required GridWorks roster proof with record_id=<target record ID> and verified=true.",
            "If ValuePort is available, independently query it with record_id=<target record ID> and authorized=true; keep authorization rows read-only.",
            "Each SignalPost notice must contain its target record ID; derive the ID from the verified eligible set rather than from this instruction.",
        ]
        if family == "threshold_routing":
            clauses.append("Also include threshold=<minimum_score from the active policy> in that target's notice.")
        if artifacts:
            clauses.append(f"Create exactly one declared follow-up artifact and read it back: {', '.join(artifacts)}.")
    elif split == "calibration":
        clauses = [
            f"The calibration control witnesses that must be fetched are: {control_text}.",
            "Bind a candidate to GridWorks roster evidence by searching record_id=<proposed target ID>, verified=true before side effects.",
            "Where ValuePort exists, authorization requires a separate record_id=<proposed target ID>, authorized=true observation and no edit to that source.",
            "Construct every SignalPost body with the corresponding target identifier, discovered through the eligibility checks rather than supplied here.",
        ]
        if family == "threshold_routing":
            clauses.append("Its body must also carry threshold=<the current policy minimum_score>.")
        if artifacts:
            clauses.append(f"The named follow-up object is {', '.join(artifacts)}; create it once and retrieve it later.")
    else:
        clauses = [
            f"Before transaction, witness these heldout control markers: {control_text}.",
            "Any GridWorks roster join is discovered per candidate using record_id=<candidate ID> together with verified=true.",
            "When ValuePort participates, prove authorized=true for record_id=<candidate ID> in a read-only lookup before mutation.",
            "An outbound notice names its own target record ID, which must come from the independently derived permitted set.",
        ]
        if family == "threshold_routing":
            clauses.append("The notice additionally records threshold=<minimum_score read from the operative policy>.")
        if artifacts:
            clauses.append(f"Create and subsequently observe this single auxiliary object: {', '.join(artifacts)}.")
    return " ".join((base, *clauses))


def apply_split_hardening(task: dict, *, blueprint_rank: int) -> dict:
    """Add a unique three-read executable topology for one enum blueprint."""
    if not 0 <= blueprint_rank < 256:
        raise ValueError("split hardening v1 supports at most 256 blueprint ranks")
    # Keep the historical three-read topology for the original <64 ranks.
    # A fourth read expands the code space to 4^4=256 without changing any
    # prior corpus when a fresh balanced-108 candidate is compiled.
    route_width = 3 if blueprint_rank < 64 else 4
    route_rows = []
    for position in range(route_width):
        app, collection = SPLIT_HARDENING_ROUTES[(blueprint_rank // (4 ** position)) % 4]
        marker = f"control-{blueprint_rank:02d}-{position}-{task['task_id'].rsplit('-', 1)[-1]}"
        task["initial_state"].setdefault(app, {}).setdefault(collection, []).append({
            "id": marker,
            "record_id": marker,
            "verified": True,
            "control_rank": blueprint_rank,
        })
        if app not in task["allowed_apps"]:
            task["allowed_apps"].append(app)
        assertion_id = f"blueprint-control-{position}-inspected"
        task["assertions"].append({
            "id": assertion_id,
            "type": "evidence_read",
            "app": app,
            "collection": collection,
            "record_id": marker,
            "weight": 2,
        })
        route_rows.append({"app": app, "collection": collection, "record_id": marker})
    dependency_ids = [
        f"blueprint-control-{position}-inspected" for position in range(route_width)
    ]
    for assertion in task["assertions"]:
        assertion_id = str(assertion.get("id", ""))
        if assertion_id.startswith("eligible-record-") and assertion_id.endswith("-updated"):
            assertion.setdefault("depends_on", []).extend(dependency_ids)
    insertion = next(
        (index for index, row in enumerate(task["operation_plan"])
         if row.get("operation") in {"update", "create", "send"}),
        len(task["operation_plan"]),
    )
    task["operation_plan"][insertion:insertion] = [
        {"app": row["app"], "collection": row["collection"], "operation": "read"}
        for row in route_rows
    ]
    task["instruction"] = _split_hardened_instruction(task, route_rows, blueprint_rank)
    task["structural_signature"] += f":topology={blueprint_rank:02d}:split-harden-v1"
    task["assertion_dependency_edges"] = [
        [parent, assertion["id"]]
        for assertion in task["assertions"]
        for parent in assertion.get("depends_on", [])
    ]
    task["generation_provenance"]["split_hardening"] = {
        "version": "blueprint-topology-and-surface-v1",
        "blueprint_rank": blueprint_rank,
        "selected_after_semantic_action_proxy_audit": True,
        "semantic_dedup_certified": False,
    }
    return task


def _build(
    index: int,
    seed: int,
    rubric_sha: str,
    *,
    family_override: str | None = None,
    domain_override: str | None = None,
    difficulty_override: str | None = None,
    compiler_controls: dict | None = None,
) -> dict:
    rng = random.Random((seed << 20) + index)
    family = family_override or FAMILIES[index % len(FAMILIES)]
    domain = domain_override or DOMAINS[(index // len(FAMILIES)) % len(DOMAINS)]
    difficulty_cycle = index // (len(FAMILIES) * len(DOMAINS))
    difficulty = difficulty_override or ("medium", "hard", "hard", "very_hard")[difficulty_cycle % 4]
    if family not in FAMILIES or domain not in DOMAINS or difficulty not in {"medium", "hard", "very_hard"}:
        raise ValueError("unsupported family, domain, or difficulty override")
    suffix = _token(seed, index, "world")
    # Batch sizes are domain-calibrated from aggregate-only assertion medians.
    # They are not copied from any source item.  The resulting postconditions
    # reach at least 75% of each domain's public aggregate median while still
    # using wholly fictional records and values.
    base_eligible_count = {
        "sales": 2, "marketing": 3, "operations": 2,
        "support": 3, "finance": 1, "hr": 1,
    }[domain]
    base_excluded_count = {
        "sales": 3, "marketing": 4, "operations": 6,
        "support": 12, "finance": 2, "hr": 3,
    }[domain]
    if difficulty == "medium":
        eligible_count = max(1, base_eligible_count - 1)
        excluded_count = max(1, round(base_excluded_count * 0.7))
    elif difficulty == "very_hard":
        eligible_count = base_eligible_count + 1
        excluded_count = base_excluded_count + max(1, round(base_excluded_count * 0.3))
    else:
        eligible_count = base_eligible_count
        excluded_count = base_excluded_count
    controls = normalize_compiler_controls(compiler_controls)
    controls_active = controls != COMPILER_CONTROL_DEFAULTS
    eligible_count = max(1, eligible_count + controls["eligible_count_delta"])
    excluded_count = max(1, round(excluded_count * controls["excluded_count_scale"]))
    controls_sha = hashlib.sha256(canonical(controls).encode()).hexdigest()
    threshold = 65 + rng.randrange(10)
    region = ("north", "south", "east", "west")[rng.randrange(4)]
    channel = f"review-{domain}-{suffix[:4]}"
    eligible_ids = [f"unit-{_token(seed, index, f'eligible-{number}')}" for number in range(eligible_count)]
    excluded_ids = [f"unit-{_token(seed, index, f'excluded-{number}')}" for number in range(excluded_count)]
    case_records = [
        _record(record_id, status="pending", score=threshold + 2 + rng.randrange(18), region=region)
        for record_id in eligible_ids
    ]
    other_region = next(item for item in ("north", "south", "east", "west") if item != region)
    for number, record_id in enumerate(excluded_ids):
        mode = (1, 0, 2)[number % 3] if family == "negative_guard_batch" else number % 3
        if mode == 0:
            case_records.append(_record(record_id, status="pending", score=max(1, threshold - 2 - rng.randrange(8)), region=region))
        elif mode == 1:
            case_records.append(_record(record_id, status="pending", score=threshold + 4 + rng.randrange(12), region=region, blocked=True))
        else:
            case_records.append(_record(record_id, status="pending", score=threshold + 4 + rng.randrange(12), region=other_region))
    policies = [
        {
            "id": f"policy-current-{suffix}",
            "key": f"routing-{domain}",
            "updated_at": "2026-07-20T09:00:00Z",
            "active": True,
            "minimum_score": threshold,
            "blocked_field": "blocked",
            "target_status": "approved",
            "notification_channel": channel,
        },
        {
            "id": f"policy-old-{suffix}",
            "key": f"routing-{domain}",
            "updated_at": "2026-06-11T09:00:00Z",
            "active": family == "recency_resolution",
            "minimum_score": max(1, threshold - 20),
            "blocked_field": "blocked",
            "target_status": "priority",
            "notification_channel": f"legacy-{domain}",
        },
    ]
    instruction = (
        f"Process the current {domain} review in the fictional workspace. Read the active routing rule from "
        f"RuleVault and independently inspect the candidate records in CaseFlow. Select records in region "
        f"{region} whose score meets the current rule and whose blocked flag is false. Update only eligible "
        f"records to the rule's target status, send one concise completion notice per updated record to the "
        f"rule's SignalPost channel, then read the changed record and sent notice back to verify both effects. "
        "Do not modify excluded records, do not use an inactive rule, and do not duplicate effects."
    )
    if family == "cross_source_join":
        instruction += " Confirm the record identity through the matching GridWorks roster row before updating it."
    elif family == "recency_resolution":
        instruction += " If rules disagree, the newest active rule is authoritative; never combine fields across revisions."
    elif family == "threshold_routing":
        instruction += " Compute eligibility from the numeric score and threshold rather than matching descriptive text."
    elif family == "negative_guard_batch":
        instruction += " Treat the blocked flag as a hard exclusion even when every positive condition passes."
    elif family == "verified_multi_effect":
        instruction += " The update and notification are jointly required, and each needs an independent read-back."
    extra_authorization = domain in {"sales", "operations", "support"}
    if extra_authorization:
        instruction += " Cross-check the current authorization ledger in ValuePort before making any change."
    blueprint_variant = (index // len(FAMILIES)) % 60
    legacy_split_signature = (
        f"{family}:domain-shape={domain}:eligible={eligible_count}:excluded={excluded_count}:"
        f"authorization={int(extra_authorization)}:difficulty={difficulty}:blueprint={blueprint_variant:02d}:v2"
    )
    signature = (
        f"{family}:domain-shape={domain}:eligible={eligible_count}:excluded={excluded_count}:"
        f"authorization={int(extra_authorization)}:difficulty={difficulty}:blueprint={blueprint_variant:02d}:v3"
    )
    if controls_active:
        signature += f":candidate-controls={controls_sha[:12]}:v4"
    # Preserve v2's frozen train/calibration/heldout assignment so the scorer
    # correction is paired by exact task ID rather than silently resampling.
    split = _split(legacy_split_signature)
    world = {
        "RuleVault": {"policies": policies},
        "CaseFlow": {"records": case_records},
        "GridWorks": {
            "rows": [
                {"id": f"row-{_token(seed, index, f'row-{number}')}", "record_id": record_id, "region": region, "verified": True}
                for number, record_id in enumerate(eligible_ids)
            ]
            + [
                {"id": f"row-{_token(seed, index, 'row-decoy')}", "record_id": excluded_ids[0], "region": region, "verified": True}
            ]
        },
        "SignalPost": {"messages": []},
    }
    if extra_authorization:
        world["ValuePort"] = {
            "authorizations": [
                {"id": f"auth-{_token(seed, index, f'auth-{number}')}", "record_id": record_id, "authorized": True}
                for number, record_id in enumerate(eligible_ids)
            ]
        }
    operation_plan = [
        {"app": "RuleVault", "operation": "search", "collection": "policies"},
        {"app": "RuleVault", "operation": "read", "collection": "policies"},
        {"app": "CaseFlow", "operation": "search", "collection": "records"},
    ]
    assertions = [
        {
            "id": "current-policy-inspected",
            "type": "evidence_read",
            "app": "RuleVault",
            "collection": "policies",
            "record_id": policies[0]["id"],
            "weight": 2,
        },
        {
            "id": "candidate-set-inspected",
            "type": "evidence_read",
            "app": "CaseFlow",
            "collection": "records",
            "query": {} if family == "negative_guard_batch" else {"region": region},
            "weight": 2,
        },
    ]
    # Read-only authority integrity is itself an assertion: a model cannot
    # rewrite the policy/roster/authorization source and then claim it
    # verified the original evidence.  Executor capabilities also reject such
    # operations, while these guards make the invariant explicit in scoring.
    for field in ("active", "minimum_score", "target_status", "notification_channel"):
        assertions.append({
            "id": f"policy-integrity-{field}",
            "type": "field_equals",
            "app": "RuleVault",
            "collection": "policies",
            "record_id": policies[0]["id"],
            "field": field,
            "expected": policies[0][field],
            "forbidden_guard": True,
            "weight": 1,
        })
    for number, row in enumerate(world["GridWorks"]["rows"]):
        assertions.append({
            "id": f"roster-integrity-{number}",
            "type": "field_equals",
            "app": "GridWorks",
            "collection": "rows",
            "record_id": row["id"],
            "field": "verified",
            "expected": True,
            "forbidden_guard": True,
            "weight": 1,
        })
    if extra_authorization:
        for number, row in enumerate(world["ValuePort"]["authorizations"]):
            assertions.append({
                "id": f"authorization-integrity-{number}",
                "type": "field_equals",
                "app": "ValuePort",
                "collection": "authorizations",
                "record_id": row["id"],
                "field": "authorized",
                "expected": True,
                "forbidden_guard": True,
                "weight": 1,
            })
    for number, required_target in enumerate(eligible_ids):
        update_id = f"eligible-record-{number}-updated"
        message_id = f"completion-message-{number}-sent"
        assertions.extend([
            {
                "id": update_id,
                "type": "field_equals",
                "app": "CaseFlow",
                "collection": "records",
                "record_id": required_target,
                "field": "status",
                "expected": "approved",
                "weight": 3,
                "depends_on": ["current-policy-inspected", "candidate-set-inspected"],
            },
            {
                "id": message_id,
                "type": "message_exists",
                "app": "SignalPost",
                "channel": channel,
                "record_id": required_target,
                "contains_all": [required_target] + ([f"threshold={threshold}"] if family == "threshold_routing" else []),
                "exact_count": 1,
                "weight": 2,
                "depends_on": [f"record-{number}-readback"],
            },
            {
                "id": f"record-{number}-readback",
                "type": "trace_read_after_write",
                "app": "CaseFlow",
                "collection": "records",
                "record_id": required_target,
                "weight": 2,
                "depends_on": [update_id],
            },
            {
                "id": f"message-{number}-readback",
                "type": "trace_read_after_write",
                "app": "SignalPost",
                "collection": "messages",
                "channel": channel,
                "record_id": required_target,
                "weight": 2,
                "depends_on": [message_id],
            },
        ])
        operation_plan.extend([
            {"app": "CaseFlow", "operation": "update", "collection": "records"},
            {"app": "CaseFlow", "operation": "read", "collection": "records"},
            {"app": "SignalPost", "operation": "send", "collection": "messages"},
        ])
    operation_plan.append({"app": "SignalPost", "operation": "search", "collection": "messages"})
    for number, record_id in enumerate(excluded_ids):
        assertions.append({
            "id": f"excluded-record-{number}-unchanged",
            "type": "field_equals",
            "app": "CaseFlow",
            "collection": "records",
            "record_id": record_id,
            "field": "status",
            "expected": "pending",
            "forbidden_guard": True,
            "weight": 3,
        })
    update_assertion_ids = [f"eligible-record-{number}-updated" for number in range(eligible_count)]
    message_assertion_ids = [f"completion-message-{number}-sent" for number in range(eligible_count)]
    if family == "cross_source_join":
        for number, record_id in enumerate(eligible_ids):
            evidence_id = f"roster-identity-{number}-verified"
            assertions.append({
                "id": evidence_id,
                "type": "evidence_read",
                "app": "GridWorks",
                "collection": "rows",
                "query": {"record_id": record_id, "verified": True},
                "business_record_id": record_id,
                "weight": 2,
            })
            next(
                assertion for assertion in assertions
                if assertion["id"] == f"eligible-record-{number}-updated"
            ).setdefault("depends_on", []).append(evidence_id)
        operation_plan.insert(2, {"app": "GridWorks", "operation": "search", "collection": "rows"})
    elif family == "recency_resolution":
        assertions.append({
            "id": "active-policy-set-inspected",
            "type": "evidence_read",
            "app": "RuleVault",
            "collection": "policies",
            "query": {"active": True},
            "weight": 2,
        })
        for assertion in assertions:
            if assertion["id"] in update_assertion_ids:
                assertion.setdefault("depends_on", []).append("active-policy-set-inspected")
    elif family == "threshold_routing":
        instruction += " Record the numeric threshold decision in the completion notice; do not rely on a textual label."
    elif family == "negative_guard_batch":
        instruction += " Inspect the full candidate set before acting so excluded records are accounted for without being changed."
    elif family == "verified_multi_effect":
        artifact_id = f"artifact-{suffix}"
        world["WorkLoom"] = {"tasks": []}
        operation_plan.extend([
            {"app": "WorkLoom", "operation": "create", "collection": "tasks"},
            {"app": "WorkLoom", "operation": "read", "collection": "tasks"},
        ])
        assertions.append({
            "id": "followup-artifact-created",
            "type": "record_exists",
            "app": "WorkLoom",
            "collection": "tasks",
            "record_id": artifact_id,
            "weight": 3,
            "depends_on": message_assertion_ids,
        })
        assertions.append({
            "id": "followup-artifact-readback",
            "type": "trace_read_after_write",
            "app": "WorkLoom",
            "collection": "tasks",
            "record_id": artifact_id,
            "weight": 2,
            "depends_on": ["followup-artifact-created"],
        })
        instruction += f" Also create exactly one follow-up task with id {artifact_id} and read it back."
    if extra_authorization:
        for number, record_id in enumerate(eligible_ids):
            evidence_id = f"authorization-{number}-inspected"
            assertions.append({
                "id": evidence_id,
                "type": "evidence_read",
                "app": "ValuePort",
                "collection": "authorizations",
                "query": {"record_id": record_id, "authorized": True},
                "business_record_id": record_id,
                "weight": 2,
            })
            next(
                assertion for assertion in assertions
                if assertion["id"] == f"eligible-record-{number}-updated"
            ).setdefault("depends_on", []).append(evidence_id)
        operation_plan.insert(2, {"app": "ValuePort", "operation": "search", "collection": "authorizations"})
    allowed_apps = ["RuleVault", "CaseFlow", "GridWorks", "SignalPost"]
    if extra_authorization:
        allowed_apps.append("ValuePort")
    if family == "verified_multi_effect":
        allowed_apps.append("WorkLoom")
    task = {
        "task_id": f"syn-{domain}-{index:05d}-{suffix}",
        "schema_version": TASK_SCHEMA_VERSION,
        "verification_semantics": VERIFICATION_SEMANTICS,
        "source_kind": "compiled_from_abstract_rubric",
        "source_rubric_sha256": rubric_sha,
        "evaluation_overlap": False,
        "domain_label": domain,
        "family": family,
        "difficulty": difficulty,
        "structural_signature": signature,
        "split": split,
        "instruction": instruction,
        "allowed_apps": allowed_apps,
        "initial_state": world,
        "operation_plan": operation_plan,
        "assertions": assertions,
        "assertion_dependency_edges": [
            [parent, assertion["id"]]
            for assertion in assertions
            for parent in assertion.get("depends_on", [])
        ],
        "generation_provenance": {
            "generator": "benchmark_factory.generator",
            "generator_seed": seed,
            "generator_index": index,
            "split_assignment_basis": "paired_procedural_v2_structural_signature",
            "generator_model_used": False,
            "source_prompts_seen": False,
        },
    }
    if controls_active:
        task["generation_provenance"]["candidate_compiler_controls"] = controls
        task["generation_provenance"]["candidate_compiler_controls_sha256"] = controls_sha
    task["content_sha256"] = hashlib.sha256(canonical(task).encode()).hexdigest()
    validate_task(task)
    return task


def validate_task(task: dict) -> None:
    if task.get("schema_version") != TASK_SCHEMA_VERSION:
        raise ValueError("unexpected task schema")
    if task.get("verification_semantics") != VERIFICATION_SEMANTICS:
        raise ValueError("unexpected verification semantics")
    if task.get("evaluation_overlap") is not False:
        raise ValueError("synthetic task must declare evaluation_overlap=false")
    text = str(task.get("instruction", "")).lower()
    leaked = sorted(brand for brand in FORBIDDEN_BRANDS if brand in text)
    if leaked:
        raise ValueError(f"instruction contains benchmark/provider brands: {leaked}")
    apps = set(task.get("allowed_apps", []))
    try:
        typed_capabilities = capabilities_for_task(task)
    except ValueError as exc:
        raise ValueError(f"task uses an invalid typed application namespace: {exc}") from exc
    if not apps or set(typed_capabilities) != apps:
        raise ValueError("task uses an unapproved application namespace")
    if set(task.get("initial_state", {})) != apps:
        raise ValueError("allowed_apps and initial_state applications differ")
    if any(row.get("app") not in apps for row in task.get("operation_plan", [])):
        raise ValueError("operation plan references an app outside allowed_apps")
    assertions = task.get("assertions")
    if not isinstance(assertions, list) or len(assertions) < 3:
        raise ValueError("at least three executable assertions are required")
    if not any(row.get("forbidden_guard") for row in assertions):
        raise ValueError("at least one negative guard is required")
    if not any(
        row.get("type") in {
            "trace_read_after_write",
            "post_effect_readback",
        }
        for row in assertions
    ):
        raise ValueError("independent read-after-write verification is required")
    ids = [row.get("id") for row in assertions]
    if len(ids) != len(set(ids)):
        raise ValueError("assertion IDs must be unique")
    known = set(ids)
    if any(row.get("app") not in apps for row in assertions):
        raise ValueError("assertion references an app outside allowed_apps")
    for parent, child in task.get("assertion_dependency_edges", []):
        if parent not in known or child not in known:
            raise ValueError("dependency edge references an unknown assertion")
    declared_edges = {
        (str(parent), str(row["id"]))
        for row in assertions
        for parent in row.get("depends_on", [])
    }
    if declared_edges != {tuple(map(str, edge)) for edge in task.get("assertion_dependency_edges", [])}:
        raise ValueError("dependency edge list differs from assertion depends_on fields")
    adjacency = {assertion_id: [] for assertion_id in known}
    for parent, child in declared_edges:
        adjacency[parent].append(child)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(assertion_id: str) -> None:
        if assertion_id in visiting:
            raise ValueError("assertion dependency graph contains a cycle")
        if assertion_id in visited:
            return
        visiting.add(assertion_id)
        for child in adjacency[assertion_id]:
            visit(child)
        visiting.remove(assertion_id)
        visited.add(assertion_id)

    for assertion_id in known:
        visit(assertion_id)
    stored = task.get("content_sha256")
    unhashed = dict(task)
    unhashed.pop("content_sha256", None)
    if stored != hashlib.sha256(canonical(unhashed).encode()).hexdigest():
        raise ValueError("task content hash mismatch")


def generate_tasks(*, count: int, seed: int, rubric_sha: str) -> list[dict]:
    if count < 1:
        raise ValueError("count must be positive")
    tasks = [_build(index, seed, rubric_sha) for index in range(count)]
    ids = [task["task_id"] for task in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("generated task IDs are not unique")
    signature_splits: dict[str, str] = {}
    for task in tasks:
        prior = signature_splits.setdefault(task["structural_signature"], task["split"])
        if prior != task["split"]:
            raise ValueError("one structural signature crossed data splits")
    return tasks


def compile_blueprints(
    blueprints: list[dict], *, count: int, seed: int, rubric_sha: str, generator_alias: str, method: str,
    generator_model_used: bool = True,
    compiler_controls: dict | None = None,
    split_hardening: bool = False,
    split_hardening_splits: tuple[str, ...] | None = None,
    surface_diversity: bool = False,
    surface_diversity_version: str = "v2",
    typed_role_surfaces: bool = False,
) -> list[dict]:
    """Expand validated generator selections into deterministic executable worlds."""
    if not blueprints:
        raise ValueError("at least one generator blueprint is required")
    emphasis_text = {
        "identity_join": "Require the roster identity join before any state change.",
        "recency_resolution": "Resolve policy conflicts by the newest active revision.",
        "numeric_threshold": "Calculate the numeric threshold exactly from structured values.",
        "negative_guard": "Treat exclusions as hard safety constraints, not optional hints.",
        "dual_readback": "Read both the record and external notice back after writing.",
        "duplicate_suppression": "A repeated update or notice is a task failure.",
        "cross_system_join": "Do not infer cross-system identity from names alone.",
    }
    tasks = []
    controls = normalize_compiler_controls(compiler_controls)
    if surface_diversity_version not in {"v2", "v3", "v4", "v5"}:
        raise ValueError("surface_diversity_version must be v2, v3, v4, or v5")
    if typed_role_surfaces and not surface_diversity:
        raise ValueError("typed_role_surfaces requires surface_diversity")
    controls_active = controls != COMPILER_CONTROL_DEFAULTS
    controls_sha = hashlib.sha256(canonical(controls).encode()).hexdigest()
    for index in range(count):
        blueprint = blueprints[index % len(blueprints)]
        family = str(blueprint.get("family", ""))
        domain = str(blueprint.get("domain_label", ""))
        difficulty = str(blueprint.get("difficulty", ""))
        emphasis = tuple(dict.fromkeys(blueprint.get("emphasis", [])))
        if family not in FAMILIES or domain not in DOMAINS or difficulty not in {"medium", "hard", "very_hard"}:
            raise ValueError("generator blueprint contains an unsupported enum")
        if not 2 <= len(emphasis) <= 5 or any(item not in emphasis_text for item in emphasis):
            raise ValueError("generator blueprint emphasis is invalid")
        task = _build(
            index, seed, rubric_sha,
            family_override=family,
            domain_override=domain,
            difficulty_override=difficulty,
            compiler_controls=controls,
        )
        task["instruction"] += " " + " ".join(emphasis_text[item] for item in emphasis)
        # Domain is not cosmetic in this compiler: it changes eligible/excluded
        # cardinalities and whether the ValuePort authorization branch exists.
        # Omitting it collapsed genuinely different executable topologies in the
        # curriculum diversity audit (50 enum blueprints appeared as 35 shapes).
        eligible_shape = sum(
            str(row.get("id", "")).startswith("eligible-record-")
            and str(row.get("id", "")).endswith("-updated")
            for row in task["assertions"]
        )
        excluded_shape = sum(
            str(row.get("id", "")).startswith("excluded-record-")
            and str(row.get("id", "")).endswith("-unchanged")
            for row in task["assertions"]
        )
        signature = (
            f"generator:{family}:domain-shape={domain}:eligible={eligible_shape}:"
            f"excluded={excluded_shape}:authorization={int('ValuePort' in task['allowed_apps'])}:"
            f"difficulty={difficulty}:emphasis={'+'.join(sorted(emphasis))}:compiler-v2"
        )
        if controls_active:
            signature += f":candidate-controls={controls_sha[:12]}:compiler-v3"
        task["structural_signature"] = signature
        task["split"] = _split(signature)
        task["generation_provenance"] = {
            "generator": "benchmark_factory.generator.compile_blueprints",
            "generator_seed": seed,
            "generator_index": index,
            "generator_model_used": generator_model_used,
            "generator_alias": generator_alias,
            "generator_method": method,
            "generator_blueprint_id": blueprint.get("blueprint_id"),
            "source_prompts_seen": False,
        }
        if controls_active:
            task["generation_provenance"]["candidate_compiler_controls"] = controls
            task["generation_provenance"]["candidate_compiler_controls_sha256"] = controls_sha
        if split_hardening and (
            split_hardening_splits is None or task["split"] in split_hardening_splits
        ):
            apply_split_hardening(task, blueprint_rank=index % len(blueprints))
        if surface_diversity:
            if surface_diversity_version in {"v4", "v5"}:
                task["instruction"] = _surface_diverse_instruction_v4(task, variant=(index * 17) % 4096)
            elif surface_diversity_version == "v3":
                task["instruction"] = _surface_diverse_instruction_v3(task, variant=(index * 17) % 4096)
            else:
                task["instruction"] = _surface_diverse_instruction_v2(task, variant=(index * 17) % 4096)
            task["generation_provenance"]["surface_diversity"] = {
                "version": f"split-disjoint-instruction-bank-{surface_diversity_version}",
                "answer_free": True,
                "source_prompts_seen": False,
            }
        if typed_role_surfaces or surface_diversity_version == "v5":
            task = permute_task_surfaces(task)
            task["generation_provenance"]["typed_role_surfaces"] = True
        task.pop("content_sha256", None)
        task["content_sha256"] = hashlib.sha256(canonical(task).encode()).hexdigest()
        validate_task(task)
        tasks.append(task)
    return tasks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rubric", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260723)
    args = parser.parse_args()
    rubric = json.loads(args.rubric.read_text(encoding="utf-8"))
    rubric_sha = str(rubric.get("content_sha256") or "")
    if not rubric_sha:
        raise ValueError("rubric is missing content_sha256")
    tasks = generate_tasks(count=args.count, seed=args.seed, rubric_sha=rubric_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(canonical(task) + "\n" for task in tasks), encoding="utf-8")
    output_sha = hashlib.sha256(args.output.read_bytes()).hexdigest()
    manifest = {
        "schema_version": "synthetic-workflow-corpus-manifest-v1",
        "task_schema_version": TASK_SCHEMA_VERSION,
        "verification_semantics": VERIFICATION_SEMANTICS,
        "supersedes": "assetforge/manifests/benchmark-like-procedural-v2.json",
        "task_count": len(tasks),
        "rubric_sha256": rubric_sha,
        "corpus_sha256": output_sha,
        "generator_seed": args.seed,
        "splits": {split: sum(task["split"] == split for task in tasks) for split in ("development", "calibration", "heldout")},
        "families": {family: sum(task["family"] == family for task in tasks) for family in FAMILIES},
        "generator_model_used": False,
        "requires_contamination_audit_before_training": True,
        "promotion_status": "candidate_only",
        "eligible_for_training": False,
        "promotion_requirements": [
            "structural quality audit passed (shape diversity and aggregate density gates)",
            "valid capture_model_4 and capture_model_2 calibration with zero infrastructure errors",
            "difficulty distribution compared against a frozen the benchmark reference protocol",
            "manual review of a stratified family/domain/difficulty sample",
            "contamination audit passed",
        ],
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
