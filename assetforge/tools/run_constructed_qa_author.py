"""One finite owned Author item, reusing the production Author and native compiler."""
import argparse, hashlib, json, os, signal, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from assetforge.pipeline.construction_assets import immutable_write, require
from assetforge.pipeline.construction_manifest import bound, reference, load_bundle

def configure(plan,cell):
 from assetforge.pipeline.qa_repair_profile import PROFILE_FLAGS, profile_environment
 for key in PROFILE_FLAGS:os.environ.pop(key,None)
 os.environ.update(profile_environment(cell['mechanical_profile']))
 os.environ.update(PIPELINE_RELEASE='the frozen release',CHANNEL_CAPS='1',
   QA18K_AUTHOR_EXACT_CONTRACT='1',QA106_COMPACT_AUTHOR_PROTOCOL='1')
 if os.environ.get('CAPTURE_ONLY') == '1':
  # New work is isolated from the retired GPT/model_b route manifest.
  os.environ.pop('QA18K_AUTHOR_ROUTE_MANIFEST', None)
 else:
  os.environ['QA18K_AUTHOR_ROUTE_MANIFEST'] = str(bound(plan['route']))

def _main():
 (ROOT/'POLICY.md').read_text();os.umask(0o077)
 p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--plan-sha256',required=True)
 p.add_argument('--cell',required=True);p.add_argument('--ordinal',type=int,required=True)
 p.add_argument('--arm',choices=['assets','control'],required=True);p.add_argument('--run-root',type=Path,required=True)
 p.add_argument('--preflight',action='store_true');a=p.parse_args()
 require(hashlib.sha256(a.plan.read_bytes()).hexdigest()==a.plan_sha256,'production plan drift')
 plan=json.loads(a.plan.read_text());cell=next(c for c in plan['cells'] if c['cell']==a.cell)
 for ref in plan.get('consumer_sources',[]):bound(ref)
 # Admission belongs to the finite owning controller. Calendar metadata in
 # old plans never changes whether an otherwise valid task can run.
 for path in (Path('/'),ROOT):
  stat=os.statvfs(path);require(stat.f_bavail*stat.f_frsize>=10*1024**3,'Author storage below 10 GiB')
 proof=json.loads(bound(cell['profile_source']).read_text())
 require(proof['executed_profile']==cell['mechanical_profile'],'full mandatory profile mismatch')
 rubric=bound(cell['rubric']);configure(plan,cell)
 root=a.run_root.resolve();root.relative_to(ROOT);root.mkdir(parents=True,exist_ok=True)
 namespace=hashlib.sha256(str(root.relative_to(ROOT)).encode()).hexdigest()[:8]
 candidate_id=os.environ.get('QA18K_ROOT_TASK_ID') or f'constructed-{a.arm}-{a.cell}-{namespace}-{a.ordinal:07d}'
 from assetforge.pipeline.release_native_author_proxy import PackageProxy,InspectorProxy
 from assetforge.tools import run_multiturn_agentic_qa_author as author
 session=None
 if a.arm=='assets':
  from assetforge.pipeline.construction_author_tools import ConstructionSession,ConstructionTool,package_class
  from assetforge.pipeline.construction_author_tools import MergeInstantiatedAssetsTool
  session=ConstructionSession(root_id=candidate_id,seed=a.ordinal,business_time=plan['business_time'],
    catalog_ref=plan['catalog'],output=root/'construction'/candidate_id,rubric_ref=cell['rubric'],
    expected_profile=cell['mechanical_profile'],require_admission=not a.preflight)
  package=package_class(session)
  # Ordered checklist for the Author: describe -> instantiate -> merge the
  # returned fragments verbatim -> state bindings -> compile.  The merge tool
  # exists because 13 of 16 cells only ever failed the transcription step.
  author.DIRECT_TOOL_GUARD_INSTALLER=lambda tools:[*tools,ConstructionTool(session),
      MergeInstantiatedAssetsTool(session)]
  if cell.get('require_admitted_asset'):
   # The asset arm exists to measure the effect of the admitted construction
   # assets.  A task that consumes no admitted asset is indistinguishable from
   # the control arm, so the requirement is enforced as a construction gate
   # rather than as an instruction inside the Author Rubric.  ``package`` is a
   # class, so the wrapper must accept both the session-built form and the
   # keyword form the Author pipeline uses.
   base_package=package
   class AssetArmPackage(base_package):
    def call(self, params, **kwargs):
     result=json.loads(super().call(params,**kwargs))
     if result.get('accepted') and not session.construction:
      session.accepted=False;session.bundles=[]
      object.__setattr__(self,'_snapshot',dict(self._snapshot,accepted_call_count=0,latest_candidate_markdown=None))
      result={'accepted':False,'construction_gate':True,'error_type':'MissingAdmittedAsset',
              'message':'the asset arm must instantiate at least one admitted construction asset; '
                        'select the asset whose stated native applicability matches the business '
                        'choice, or redesign the objective so that one admitted asset is causally '
                        'necessary'}
     return json.dumps(result,ensure_ascii=False)
   package=AssetArmPackage
 else:
  package=PackageProxy
 author.OfficialTaskPackageTool=package;author.OfficialContractInspectorTool=InspectorProxy
 flags=cell['author_flags']
 tool=package(candidate_relative_path=str((root/'candidates'/(candidate_id+'.md')).relative_to(ROOT)),
    candidate_id=candidate_id,domain=cell['domain'],rubric_sha256=cell['rubric']['sha256'],rubric_text=rubric.read_text(),**flags)
 try:
  require(tool._rubric_mechanical_profile==cell['mechanical_profile'],'provider preflight omitted mandatory gates')
  protocol=tool.validate_advertised_author_protocol()
 finally:tool.close()
 record={'owner':'codex-root','plan':reference(a.plan),'cell':a.cell,'arm':a.arm,'root_task_id':candidate_id,
  'started_at_epoch':time.time(),'complete_profile':cell['mechanical_profile'],'executed_protocol':protocol,
  'profile_source':cell['profile_source'],'rubric':cell['rubric'],'provider_calls':0 if a.preflight else None,
  'preflight_only':a.preflight,'source_files':[reference(Path(__file__))]}
 binding_path=root/'execution_bindings'/(candidate_id+('.preflight.json' if a.preflight else '.json'))
 if binding_path.exists() and not a.preflight:
  # A same-root infrastructure retry may load an immutable binding produced
  # by an older controller revision.  Preserve that evidence and record this
  # attempt separately; never overwrite the original binding or change the
  # business/root identity.
  old=json.loads(binding_path.read_text())
  require(old.get('root_task_id')==candidate_id and old.get('plan',{}).get('sha256')==record['plan']['sha256'],
          'existing execution binding belongs to another root/plan')
  recovery_path=root/'execution_bindings'/(candidate_id+'.recovery.json')
  immutable_write(recovery_path,{**record,'attempt_kind':'same_root_infrastructure_recovery',
      'original_binding':reference(binding_path),'original_binding_preserved':True})
 else:
  immutable_write(binding_path,record)
 if a.preflight:print(json.dumps({'passed':True,'provider_calls':0,'cell':a.cell,'arm':a.arm}));return
 # The owning controller enforces the item lifetime. The Author retains its full
 # semantic repair loop and transport fallback within that finite lifetime.
 candidate,audit=author.run(rubric_path=rubric,run_root=root,candidate_id=candidate_id,domain=cell['domain'],profile_flags=cell.get('mechanical_profile'),
   max_tool_rounds=int(plan.get('author_max_tool_rounds',300)),timeout=plan['provider_timeout_seconds'],rubric_wave_id='construction-'+a.cell+'-'+a.arm,
   coverage_direction=cell['coverage'],accepted_corpus_catalog_path=bound(cell['historical_reference_row']['historical_accepted_corpus_catalog']),
   minimal_author_tools=True,enable_operational_fallback=True,
   prefer_mog8_route=os.environ.get('QA18K_AUTHOR_PREFER_MOG8')=='1',**flags)
 bundles=[]
 if session:
  # A catalog declares an exact set of admitted versions and adapter scopes;
  # full task composition and the frozen cell's quality gates remain mandatory.
  require(session.accepted and (session.bundles or not cell.get('require_composition_bundle',True)),
          'Author output missing validated composition bundle')
  for ref in session.bundles:
   seal=bound(ref);values,check=load_bundle(seal.parent,'recover');bundles.append({'seal':ref,'check':check})
 result={'root_task_id':candidate_id,'candidate':reference(candidate),'author_receipt':reference(audit),
   'construction_bundles':bundles,'finished_at_epoch':time.time(),'materialized':True,
   'terminal_seal':{'schema_version':'constructed-author-terminal-v1','status':'completed',
                    'root_task_id':candidate_id,'candidate_sha256':reference(candidate)['sha256']},
   'reviewer_accepted':False,'distribution_valid':False,'released':False,'training_ready':False}
 immutable_write(root/'completed'/(candidate_id+'.json'),result);print(json.dumps(result))


def main():
 """Always leave an immutable terminal receipt for the owning controller.

 A missing success seal must not erase the distinction between a provider,
 native-pool, construction, and semantic failure.  The failure receipt is
 written before re-raising so the controller can resume the same root without
 creating a duplicate task.
 """
 try:
  return _main()
 except BaseException as error:
  try:
   args=sys.argv
   root=Path(args[args.index('--run-root')+1]).resolve()
   cell=args[args.index('--cell')+1]; arm=args[args.index('--arm')+1]
   ordinal=int(args[args.index('--ordinal')+1])
   namespace=hashlib.sha256(str(root.relative_to(ROOT)).encode()).hexdigest()[:8]
   candidate_id=f'constructed-{arm}-{cell}-{namespace}-{ordinal:07d}'
   immutable_write(root/'completed'/(candidate_id+'.failure.json'),{
    'schema_version':'constructed-author-terminal-v1','status':'failed',
    'root_task_id':candidate_id,'cell':cell,'arm':arm,'ordinal':ordinal,
    'finished_at_epoch':time.time(),'failure_type':type(error).__name__,
    'failure_message':str(error)[:4000],
    'recoverable':isinstance(error,(TimeoutError,ConnectionError,OSError))})
  except BaseException:
   pass
  raise

if __name__=='__main__':main()
