"""Admit only individually verified repaired versions of still-held originals.

Original defects remain quarantined. A repaired version retains the same QA
root and is not a new original; its own bytes, acceptance and native repair
evidence must all be bound before it can bypass a historical root exclusion.
"""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
INDEX='assetforge/artifacts/qa_quality_holds/automation_qa18k_verified_repair_versions.json'
CONTRACT='accepted-repair-version-with-native-counterexample-clearance-v1'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_native_repair_record(proof,task):
    lineage=(task.get('generation_provenance') or {}).get('qa_repair_lineage') or {}
    if (proof.get('task_id')!=task.get('task_id') or proof.get('lineage')!=lineage
            or proof.get('passed') is not True or proof.get('provider_calls')!=0
            or proof.get('original_decisions_unchanged') is not True
            or proof.get('hold_ledger_modified') is not False
            or lineage.get('repair_attempt') not in (1,2)
            or lineage.get('root_task_id')==task.get('task_id')):
        raise ValueError('native accepted repair identity/lineage/verification invalid')
    cases=proof.get('cases')
    if not isinstance(cases,list) or not 2<=len(cases)<=64:
        raise ValueError('repair needs positive and defect counterexample native evidence')
    labels=set();positive=False;blocked_defect=False
    for case in cases:
        label=case.get('label')
        if not isinstance(label,str) or not label or label in labels:raise ValueError('duplicate/invalid native repair case')
        labels.add(label);expected=case.get('expected_strict');score=(case.get('score') or {}).get('strict_pass')
        if type(expected) is not bool or score is not expected or case.get('matches_expected') is not True:
            raise ValueError('native repair case does not meet its expected result')
        positive |= label=='positive' and expected
        blocked_defect |= label!='positive' and not expected
    if not positive or not blocked_defect:raise ValueError('repair lacks passing positive or failing original defect evidence')
    return lineage


def load_verified_versions(*,root=ROOT,index_path=None):
    path=(index_path if index_path is not None else root/INDEX).resolve()
    path.relative_to(root/'assetforge')
    if not path.exists():return {},None
    raw=path.read_bytes();index=json.loads(raw)
    if index.get('schema_version')!=CONTRACT or not isinstance(index.get('versions'),list):
        raise ValueError('invalid accepted repair version index')
    from assetforge.tools import gate_automation_18k_distribution as gate
    from assetforge.pipeline.qa_review_lineage import valid_review_rubric_binding
    from assetforge.tools.run_agentic_markdown_reviewer_batch import _receipt_complete
    gate.unresolved_quality_holds([])
    holds={r['task_id']:r for r in json.loads(gate.DEFAULT_QUALITY_HOLDS.read_text())['holds']}
    def bound(ref,base):
        p=(root/ref['path']).resolve();p.relative_to(base.resolve())
        if sha(p)!=ref['sha256']:raise ValueError('accepted repair version source hash drift')
        return p
    versions={};base=root/'assetforge/runs/automation_qa18k_native_diversity_20260831_r1'
    for row in index['versions']:
        tid=row['task_id']
        if tid in versions:raise ValueError('duplicate accepted repair version')
        native_path=bound(row['native_repair_verification'],base/'audits')
        proof=json.loads(native_path.read_text());source=bound({'path':proof['task_path'],'sha256':proof['task_sha256']},base/'author')
        task=json.loads(source.read_text());lineage=verify_native_repair_record(proof,task)
        if tid!=task['task_id'] or row['root_task_id']!=lineage['root_task_id'] or row['original_hold']!=holds.get(lineage['root_task_id']):
            raise ValueError('accepted repair does not bind the original unresolved hold')
        current=task
        for _ in range(lineage['repair_attempt']):
            lin=current['generation_provenance']['qa_repair_lineage']
            parent=bound({'path':lin['parent_task_path'],'sha256':lin['parent_task_sha256']},base/'author')
            current=json.loads(parent.read_text())
            if current['task_id']!=lin['parent_task_id']:raise ValueError('repair parent identity drift')
        if current['task_id']!=lineage['root_task_id']:raise ValueError('repair ancestor chain does not reach its declared root')
        review_path=bound(proof['accepted_review'],base/'reviewer');review=json.loads(review_path.read_text())
        if (review.get('status')!='completed' or review.get('decision')!='accept'
                or review['packet']['source_binding']['generated_task']!={'path':proof['task_path'],'sha256':proof['task_sha256'],'task_id':tid}
                or not valid_review_rubric_binding(review,root)
                or not _receipt_complete(review_path.parent.parent,review['review_id'],tid)):
            raise ValueError('repaired version requires its own complete independent acceptance')
        versions[tid]=dict(task_id=tid,task_path=proof['task_path'],task_sha256=proof['task_sha256'],
            root_task_id=lineage['root_task_id'],native_repair_verification=row['native_repair_verification'],
            accepted_review=proof['accepted_review'],original_hold_remains=True,new_original_qa=False)
    return versions,dict(contract=CONTRACT,path=str(path.relative_to(root)),sha256=hashlib.sha256(raw).hexdigest())


def unseen_identity(task,roots,task_ids,verified_versions):
    lineage=(task.get('generation_provenance') or {}).get('qa_repair_lineage') or {}
    tid=task['task_id'];root=lineage.get('root_task_id') or tid
    return root not in roots or tid not in task_ids and tid in verified_versions
