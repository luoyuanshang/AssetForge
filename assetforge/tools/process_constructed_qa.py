"""Incremental native revalidation and release qualification for one owned item."""
import argparse, hashlib, json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from assetforge.pipeline.construction_assets import immutable_write, require, digest
from assetforge.pipeline.construction_manifest import bound, reference, load_bundle

def prepare(a):
 plan=json.loads(bound({'path':str(a.plan.relative_to(ROOT)), 'sha256':a.plan_sha256}).read_text())
 cell=next(c for c in plan['cells'] if c['cell']==a.cell)
 completed=json.loads(a.completed.read_text());receipt=bound(completed['author_receipt']);author=json.loads(receipt.read_text())
 canonical=(author.get('final_markdown_matches_accepted_package') or
    (author.get('accepted_tool_submission_is_canonical') and author.get('canonical_markdown_source')=='accepted_tool_submission'))
 require(author.get('status')=='completed' and author.get('native_regression_strict_pass') is True and canonical,
         'Author did not complete canonical native submission')
 candidate=bound(completed['candidate']);cid=completed['root_task_id'];author_root=candidate.parent.parent
 taskpath=author_root/'tasks'/(cid+'.json');task=json.loads(taskpath.read_text());sha=reference(taskpath)['sha256']
 require(hashlib.sha256(candidate.read_text().strip().encode()).hexdigest()==author['candidate_sha256'],'canonical Author text drift')
 bundles=completed['construction_bundles']
 require(bundles or not cell.get('require_composition_bundle',True),'asset item lost external manifest')
 bundle=None
 if bundles:
  require(len(bundles)==1,'ambiguous accepted bundle')
  bundle=bound(bundles[0]['seal']).parent;values,_=load_bundle(bundle,'recover')
  require(digest(task)==digest(values['task.json']),'materialized task changed after construction')
 from assetforge.pipeline import release_runtime as release
 release.require_verified_protocol()
 try:
     from assetforge.tools.migrate_benchmark_qa_release import inspect_one
 except Exception:
     _missing_dependency(
         "the release-migration inspector",
         "It is tied to one runtime release; supply it with your own runtime build.")
 try:
     from assetforge.tools.revalidate_benchmark_native_qa import native_one
 except Exception:
     _missing_dependency(
         "the native re-validation helper",
         "It is tied to one runtime release; supply it with your own runtime build.")
 mechanical=inspect_one(taskpath);a.output.mkdir(parents=True,exist_ok=False)
 if bundle:mechanical['construction_bundle']=reference(bundle/'complete.json')
 immutable_write(a.output/'mechanical.json',mechanical)
 require(mechanical['mechanical_status']=='compatible_pending_native_and_semantic','mechanical incompatibility')
 native=native_one(mechanical);immutable_write(a.output/'native.json',native)
 require(native['native_status']=='submitted_execution_tests_passed_pending_semantic','native result failure')
 from assetforge.pipeline.contamination import audit
 official=json.loads((release.RUN/'the pinned public set.json').read_text())
 sources=[{'source_id':json.loads(row['info'])['task_name'],
    'text':'\n'.join(m['content'] for m in row['prompt'] if m['role']=='user')} for row in official]
 lexical=audit([task],sources,source_corpus_name='pinned public user requests')
 immutable_write(a.output/'lexical.json',lexical)
 inputs=dict(cell['historical_reference_row']['inputs'])
 inputs.update(rubric=cell['rubric'],candidate=reference(candidate),generated_task=dict(reference(taskpath),task_id=cid),
    author_receipt=reference(receipt),native_regression=reference(author_root/'audits'/(cid+'.native-regression.json')),
    lexical_contamination_audit=reference(a.output/'lexical.json'))
 row={'source_sha256':sha,'task_id':cid,'native_evidence':reference(a.output/'native.json'),'inputs':inputs,
    'historical_accepted_corpus_catalog':cell['historical_reference_row']['historical_accepted_corpus_catalog']}
 if bundle:row['construction_bundle']=reference(bundle/'complete.json')
 try:
     from assetforge.tools.revalidate_benchmark_original_profiles import evaluate
 except Exception:
     _missing_dependency(
         "the original-profile evaluator",
         "It is tied to one runtime release; supply it with your own runtime build.")
 full=evaluate(row);fp=a.output/'full_profile/tasks'/(sha+'.json');immutable_write(fp,full)
 require(full.get('full_original_profile_passed') is True,'full frozen execution profile did not pass')
 require(full['executed_profile']==cell['mechanical_profile'],'cell original profile changed')
 row['full_original_profile_evidence']=reference(fp)
 if bundle:row['construction_bundle']=reference(bundle/'complete.json')
 prompt=bound(plan['reviewer_prompt']) if plan.get('reviewer_prompt') else ROOT/'assetforge/artifacts/reviewer_prompts/automation_qa_reviewer_v13_release106_compact_20260908.md'
 value={'owner':'codex-root','target_release':'the frozen release','reviewer_prompt':reference(prompt),'items':[row],
    'production_plan':reference(a.plan),'root_completion':reference(a.completed),'cell':a.cell,
    'accepted_v106':False,'distribution_valid':False,'released':False}
 immutable_write(a.output/'review_plan.json',value);print(json.dumps(reference(a.output/'review_plan.json')))

def qualify(a):
 plan=json.loads(a.plan.read_text());require(hashlib.sha256(a.plan.read_bytes()).hexdigest()==a.plan_sha256,'review plan changed')
 row=plan['items'][0];bundle=row.get('construction_bundle')
 if bundle:
  values,check=load_bundle(bound(bundle).parent,'release')
  reviewid='v106-'+row['source_sha256'][:28]
  review=json.loads((a.review/'audits'/(reviewid+'.markdown-reviewer.json')).read_text())
  b=review['packet']['source_binding'].get('construction_manifest')
  require(b and b['validation']['manifest_sha256']==check['manifest_sha256'],'review omitted construction manifest')
 from assetforge.tools import bind_benchmark_qualified_qa as binder
 previous=sys.argv
 try:
  sys.argv=[str(Path(binder.__file__)),'--review',str(a.review),'--profile',str(a.plan.parent/'full_profile'),
    '--output',str(a.output)];binder.main()
 finally:sys.argv=previous
 result=json.loads((a.output/'manifest.json').read_text())
 companions={row['source_sha256']:bundle} if bundle else {}
 immutable_write(a.output/'construction_collection_binding.json',{'schema_version':'construction-collection-companion-v1',
   'qualified_manifest':reference(a.output/'manifest.json'),'construction_bundles':companions,
   'control_root_ids':[row['task_id']] if not bundle else []})
 require(len(result['items'])==1,'review/profile/hold qualification failed')

if __name__=='__main__':
 (ROOT/'POLICY.md').read_text();os.umask(0o077)
 p=argparse.ArgumentParser();p.add_argument('--mode',choices=['prepare','qualify'],required=True)
 p.add_argument('--plan',type=Path,required=True);p.add_argument('--plan-sha256',required=True)
 p.add_argument('--cell');p.add_argument('--completed',type=Path);p.add_argument('--review',type=Path)
 p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 a.plan=a.plan.resolve();a.output=a.output.resolve();a.output.relative_to(ROOT/'assetforge/runs')
 prepare(a) if a.mode=='prepare' else qualify(a)
