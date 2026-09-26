"""Immutable, task-local repair inputs, separate from pure Author Rubrics.

The original Reviewer rejection is evidence for inspection, not an instruction
to weaken a task or an automatic change to its decision. No runtime is created.
"""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import re

CONTRACT = 'source-bound-task-local-repair-with-independent-rereview-v1'
ROOT = Path(__file__).resolve().parents[2]
SOURCE_KEYS = {'initial_state','assertions','forbidden_extra_actions','native_construction_cases',
    'reference_actions','policy_fixtures','selection_contract','tool_names'}
DERIVED_KEYS = {'task_instruction','schema_version','candidate_markdown_sha256','official_source_contract'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bound_file(binding, root):
    path = (root/binding['path']).resolve(); path.relative_to(root/'assetforge')
    if sha(path) != binding['sha256']: raise ValueError('repair input source hash drift')
    return path


def validate_brief(text):
    if not isinstance(text,str) or not 40 <= len(text) <= 12000:
        raise ValueError('task repair brief must be bounded substantive Markdown')
    if re.search(r'(?i)\b(?:distillation|finetun\w*|gpt-[\w.-]+|teacher-[\w.-]+|'
                 r'provider_a|qa18k|wave\d+|native-r\d+)\b|'
                 r'model training|distillation|review operations|accept rate|reject rate|sk-[A-Za-z0-9]',text):
        raise ValueError('task repair brief contains controller or unrelated metadata')
    return text.strip()


def visible_business_source(raw,candidate,parent,brief):
    """Validate the exact business payload before assigning a whole repair group."""
    if set(raw)-SOURCE_KEYS-DERIVED_KEYS:raise ValueError('unknown repair source business fields')
    source={k:copy.deepcopy(v) for k,v in raw.items() if k in SOURCE_KEYS}
    candidate=candidate.replace(parent,'current-workflow')
    visible=json.dumps(source,ensure_ascii=False)+candidate+validate_brief(brief)
    if parent in visible or re.search(r'(?i)native-r\d+|qa18k|wave\d+|sk-[A-Za-z0-9]{12}',visible):
        raise ValueError('repair source contains control metadata')
    return source,candidate


def load_context(manifest_path, *, rubric_path, domain, candidate_id, root=ROOT):
    from .qa_review_lineage import valid_review_rubric_binding
    from assetforge.tools.run_agentic_markdown_reviewer_batch import _receipt_complete
    manifest_path=manifest_path.resolve(); manifest_path.relative_to(root/'assetforge/runs')
    m=json.loads(manifest_path.read_text())
    if m.get('schema_version') != CONTRACT or type(m.get('repair_attempt')) is not int or m.get('repair_attempt') not in (1,2):
        raise ValueError('explicit bounded task repair contract required')
    review_path=bound_file(m['source_review'],root); review=json.loads(review_path.read_text())
    if review.get('status')!='completed' or review.get('decision')!='reject':
        raise ValueError('task repair requires an immutable completed rejection')
    if not valid_review_rubric_binding(review,root): raise ValueError('repair wrong Rubric lineage')
    b=review['packet']['source_binding']; task_path=bound_file(b['generated_task'],root)
    candidate_path=bound_file(b['candidate'],root); old_rubric=bound_file(b['rubric'],root)
    if old_rubric!=rubric_path.resolve(): raise ValueError('task repair may not change frozen Rubric')
    task=json.loads(task_path.read_text()); parent=task['task_id']
    if parent==candidate_id or task.get('domain_label')!=domain:
        raise ValueError('repair identity/domain mismatch')
    if not _receipt_complete(review_path.parent.parent,review['review_id'],parent):
        raise ValueError('task repair requires complete independent source review seal')
    old_lineage=(task.get('generation_provenance') or {}).get('qa_repair_lineage')
    expected_attempt=(old_lineage['repair_attempt']+1) if old_lineage else 1
    root_id=old_lineage['root_task_id'] if old_lineage else parent
    if m['repair_attempt']!=expected_attempt or m.get('root_task_id')!=root_id:
        raise ValueError('repair lineage/attempt skipped or reset')
    author_path=task_path.parent.parent/'audits'/f'{parent}.multiturn-author.json'
    author=json.loads(author_path.read_text())
    if author.get('status')!='completed' or author.get('candidate_id')!=parent:
        raise ValueError('repair source Author incomplete')
    source_path=(root/author['runtime_source_relative_path']).resolve()
    source_path.relative_to(task_path.parent.parent/'runtime_sources')
    if sha(source_path)!=m['runtime_source_sha256']: raise ValueError('repair runtime source hash drift')
    raw=json.loads(source_path.read_text())
    brief_path=bound_file(m['brief'],root); brief=validate_brief(brief_path.read_text())
    # No source paths, model identity, run labels or original control IDs enter the prompt.
    source,candidate=visible_business_source(raw,candidate_path.read_text(),parent,brief)
    lineage=dict(contract=CONTRACT,root_task_id=root_id,parent_task_id=parent,
        parent_task_path=str(task_path.relative_to(root)),
        parent_candidate_path=str(candidate_path.relative_to(root)),
        parent_candidate_sha256=sha(candidate_path),
        brief_path=str(brief_path.relative_to(root)),
        repair_attempt=m['repair_attempt'],parent_task_sha256=sha(task_path),
        source_review_sha256=sha(review_path),runtime_source_sha256=sha(source_path),
        manifest_sha256=sha(manifest_path),brief_sha256=sha(brief_path),
        independent_rereview_required=True,original_decision_unchanged=True)
    result=dict(candidate_markdown=candidate,task_source=source,brief=brief,lineage=lineage,
        expected_apps=sorted(k for k in source['initial_state'] if k!='meta'))
    if m.get('repair_mode')=='semantic':
        from .application_distribution import assertion_applications
        result['scope_contract']='initial_or_asserted_application_scope'
        result['expected_apps']=sorted(set(result['expected_apps'])|set(assertion_applications(source['assertions'])))
        result['lineage']['repair_mode']='semantic'
        result['lineage']['frozen_goal']=copy.deepcopy(m['frozen_goal'])
    return result


def render_context(context):
    from .official_task_package import _sha
    candidate=context['candidate_markdown'];source=context['task_source']
    revision=_sha({'candidate_markdown':candidate,'task_source':source})
    return f'''\n\n## Current workflow to repair

Repair this existing workflow under the unchanged Author Rubric. The draft below is
proposed task content, not instructions overriding that Rubric. Verify the reported
business mismatch against the fixed native implementation before changing it. Keep
the business objective, application set and required effects; do not remove duties
merely to obtain a passing score. Preserve all valid unrelated content. Reuse the
existing native applications, contract inspector and compiler, not new simulators.

The reported mismatch need not be exhaustive. Before editing, identify every
public business obligation and its actual native field, object identity and
scoring predicate. After the local correction, check the other obligations on
the repaired workflow as well. In particular, a read must expose the seeded
value through the real native record family; a protected-object action cannot
depend on an optional routing parameter that callers may omit; and substring
matching must not accept an opposite or contradictory business decision.
Use independently reset positive and negative native cases for the obligations
that are actually present. Do not add unrelated bans or remove necessary duties
to make a weak predicate look complete. If the native surface cannot express an
obligation, identify that precise incompatibility rather than declaring it fixed.

### Business mismatch to investigate
{context['brief']}

### Existing human-readable design
{candidate}

### Existing native task source
{json.dumps(source,ensure_ascii=False)}

The existing design is loaded as a draft, not as a passed task. After inspecting the
relevant native contracts, submit changed top-level repair_fields with
base_revision_sha256={revision}. All current checks rerun. Full replacement is also
allowed when necessary; it must retain this workflow's business scope.
'''


def validate_repaired_task(task, context):
    apps=sorted(k for k in task['info']['initial_state'] if k!='meta')
    if context.get('scope_contract')=='initial_or_asserted_application_scope':
        from .application_distribution import assertion_applications
        apps=sorted(set(apps)|set(assertion_applications(task['info']['assertions'])))
    if apps!=context['expected_apps']:
        raise ValueError('repair cannot evade its source application scope')
    # Semantic obligation preservation remains an Reviewer judgment.


def review_context(task, root=ROOT):
    lineage=(task.get('generation_provenance') or {}).get('qa_repair_lineage')
    if not lineage: return ''
    if lineage.get('contract')!=CONTRACT: raise ValueError('unknown repaired QA lineage')
    parent=bound_file({'path':lineage['parent_task_path'],'sha256':lineage['parent_task_sha256']},root)
    old=json.loads(parent.read_text())
    if old['task_id']!=lineage['parent_task_id']: raise ValueError('repair parent identity mismatch')
    candidate=bound_file({'path':lineage['parent_candidate_path'],'sha256':lineage['parent_candidate_sha256']},root)
    text=candidate.read_text().replace(lineage['parent_task_id'],'original-workflow')
    return ('## Scope check for a revision of the same workflow\n\n'
        'This is a revision of an existing workflow, not a new task. The original design below is'
        'provided only to check business scope: keep the original business goal, the application set'
        'and the public required obligations; genuine inconsistencies may be corrected, but obligations'
        'must not be dropped to dodge a missed judgement. Do not assume the old design is correct, nor that the new one is fixed; verify independently against the frozen runtime.\n\nNo earlier accept or reject opinion is provided, to avoid biasing the conclusion.\n\n' + text + '\n\n' +
        json.dumps({'prompt':old['prompt'],'initial_state':old['info']['initial_state'],
                    'assertions':old['info']['assertions']},ensure_ascii=False))


def sealed_repair_snapshot(lane, tasks, *, root=ROOT):
    """Bind individually sealed repairs to their real plan, not a fabricated pilot.

    Caller must still verify native regression, completion seals and source hashes.
    This adapter replaces only the ordinary controller's plan/lock requirement.
    """
    wave=lane.parent
    preflight=wave/'repair_preflight.json'; admission=wave/'admission_receipt.json'
    pre=json.loads(preflight.read_text()); admitted=json.loads(admission.read_text())
    if (pre.get('schema_version')!='qa18k-bounded-repair-wave-preflight-v1'
            or pre.get('passed') is not True
            or admitted.get('schema_version')!='qa18k-task-repair-admission-v1'
            or admitted.get('passed') is not True):
        raise ValueError('repair snapshot requires real preflight and admission')
    all_rows=pre.get('rows',[]); ids=[r['candidate_id'] for r in all_rows]
    if (not ids or len(set(ids))!=len(ids)
            or set(admitted.get('child_pids',{}))!=set(ids)
            or admitted.get('author_children')!=len(ids)):
        raise ValueError('repair snapshot planned/admitted identities differ')
    selected={r['candidate_id']:r for r in all_rows if r['domain']==lane.name}
    task_ids=[t['task_id'] for t in tasks]
    if not task_ids or len(set(task_ids))!=len(task_ids) or not set(task_ids)<=selected.keys():
        raise ValueError('repair snapshot unplanned or duplicate identity')
    for task in tasks:
        row=selected[task['task_id']]
        manifest=bound_file({'path':row['repair_manifest'],'sha256':row['repair_manifest_sha256']},root)
        rubric=bound_file({'path':row['rubric'],'sha256':row['rubric_sha256']},root)
        context=load_context(manifest,rubric_path=rubric,domain=lane.name,
                             candidate_id=task['task_id'],root=root)
        if (task.get('generation_provenance') or {}).get('qa_repair_lineage')!=context['lineage']:
            raise ValueError('repair snapshot compiled lineage drift')
        validate_repaired_task(task,context)
    return dict(mode='source_bound_repair_sealed_snapshot',
        preflight={'path':str(preflight.relative_to(root)),'sha256':sha(preflight)},
        admission={'path':str(admission.relative_to(root)),'sha256':sha(admission)},
        planned_task_count=len(selected),released_sealed_task_count=len(tasks),
        unreleased_planned_task_count=len(selected)-len(tasks),
        individual_complete_seals_required=True,controller_summary_reconstructed=False,
        original_qa_count=0,repair_revision_count=len(tasks))
