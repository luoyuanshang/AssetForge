"""Finite managed production owner with incremental, overlapping per-item stages."""
import argparse, asyncio, collections, contextlib, fcntl, hashlib, json, os, signal, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from assetforge.pipeline.active_command_registry import read_registry
from assetforge.pipeline.construction_assets import immutable_write, require
from assetforge.pipeline.construction_manifest import reference, bound

WORKERS={'author':'benchmark_106_constructed_author_worker_20260908',
 'native':'benchmark_106_constructed_native_worker_20260908',
 'reviewer':'benchmark_106_constructed_reviewer_worker_20260908',
 'collection':'benchmark_106_constructed_collection_worker_20260908'}
AUTHOR_NAMES={'run_multiturn_agentic_qa_author.py','run_benchmark_release_author.py','run_constructed_qa_author.py'}
REVIEW_NAMES={'run_agentic_markdown_reviewer.py','run_agentic_markdown_reviewer_compact.py',
 'run_agentic_markdown_reviewer_native106.py','run_constructed_qa_reviewer.py','review_construction_assets.py'}

def global_items():
 authors=reviews=0
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit():continue
  try:
   argv=(proc/'cmdline').read_bytes().split(b'\0')
   if not argv or not Path(argv[0].decode(errors='replace')).name.startswith('python'):continue
   names={Path(x.decode(errors='replace')).name for x in argv[1:] if x}
   authors+=bool(names&AUTHOR_NAMES);reviews+=bool(names&REVIEW_NAMES)
  except OSError:continue
 return {'author':authors,'reviewer':reviews,'total':authors+reviews}

def atomic(path,value):
 temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False));temporary.replace(path)

def imperative_write(path,text):
 """Create-once text writer for repair briefs (never overwrite evidence)."""
 with Path(path).open('x') as handle:
  handle.write(text)

@contextlib.contextmanager
def stage_logs(logs,stem):
 """Open `<stem>.stdout.log`/`<stem>.stderr.log` for one attempt, never colliding.

 The controller legitimately re-enters the same stem: an Author root gets one
 bounded continuation after ending without an accepted compile, and a collection
 epoch can be re-driven.  A fixed `.open('x')` name therefore raised
 FileExistsError inside the controller and killed the root before the retry ever
 ran -- measured 2026-09-15 02:28-04:34 on contract56o: 122 continuations, 122
 FileExistsError, 122 dead roots, 0 accepted compiles.  The first attempt keeps
 the historical name; later attempts get an explicit `.attemptN.` suffix so no
 two runs share or truncate the same evidence file.
 """
 handles=[]
 try:
  for stream in ('stdout','stderr'):
   for attempt in range(1,65):
    name=f"{stem}.{stream}.log" if attempt==1 else f"{stem}.attempt{attempt}.{stream}.log"
    try:handle=(logs/name).open('x');break
    except FileExistsError:continue
   else:raise RuntimeError(f'stage log attempt space exhausted: {stem}.{stream}')
   if attempt>1:
    handle.write(f"# attempt {attempt} of {stem} ({stream}) opened {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    handle.flush()
   handles.append(handle)
  yield handles
 finally:
  for handle in handles:handle.close()

def key_dir(state,attempt):
 return f"{state['key']}-repair-{attempt}"

def _author_budget_exhausted(failure):
 """True only for the 'author ran out of response budget without an accepted compile' class.

 Infrastructure faults, construction/parameter failures and provider errors are
 deliberately excluded: those must not be retried blindly by the controller.
 """
 if not isinstance(failure,dict):return False
 message=str(failure.get('failure_message') or '')
 traceback=str(failure.get('traceback') or '')
 marker='multi-turn complete-task author rejected'
 return (failure.get('failure_type')=='RuntimeError'
   and (marker in message or marker in traceback)
   and failure.get('failure_type') not in {'SystemExit','KeyboardInterrupt'})

def _classify_author_terminal(failure):
 """Split the single 'author_runtimeerror' bucket into the three real causes.

 Supervisor 19:46: budget-exhausted-without-accept, infrastructure failure and
 semantic rejection were counted identically, so the counter could not tell a
 capability/budget outcome from a crash.
 """
 if not isinstance(failure,dict):return 'author_other'
 message=str(failure.get('failure_message') or '');traceback=str(failure.get('traceback') or '')
 text=message+'\n'+traceback
 if 'construction source binding drift' in text:return 'author_infra_error'
 if 'native tool worker exited before response' in text:return 'author_infra_error'
 if failure.get('failure_type') in {'SystemExit','KeyboardInterrupt'}:return 'author_infra_error'
 if 'multi-turn complete-task author rejected' in text:return 'author_budget_exhausted_no_accept'
 if 'construction obligation' in text or 'binding' in text or 'assertion' in text:return 'author_semantic_reject'
 return 'author_other'

def _remaining_author_budget(root,key):
 """Remaining original response budget for a root, from its own trajectory."""
 path=root/'trajectories'/(key+'.json')
 if not path.exists():return None
 try:messages=json.loads(path.read_text())
 except (OSError,ValueError):return None
 used=sum(1 for m in messages if isinstance(m,dict) and m.get('role')=='assistant')
 return max(0,300-used)

class Factory:
 def __init__(self,a):
  self.a=a;self.plan=json.loads(bound({'path':str(a.plan.resolve().relative_to(ROOT)),'sha256':a.plan_sha256}).read_text())
  # Disjoint cell sharding: several owners may run the same frozen plan, but
  # they must not each walk the identical cell sequence, otherwise two owners
  # produce near-duplicate business content under different root ids.
  # QA6K_CELL_SHARD="i/n" selects cells whose index % n == i.
  self.cells=list(self.plan['cells'])
  shard=os.environ.get('QA6K_CELL_SHARD')
  if shard:
   index,total=(int(x) for x in shard.split('/'))
   require(0<=index<total>0,'invalid QA6K_CELL_SHARD')
   self.cells=[c for position,c in enumerate(self.plan['cells']) if position%total==index]
   require(self.cells,'cell shard selected no cells')
  self.out=a.output.resolve();self.out.relative_to(ROOT/'assetforge/runs')
  self.started=time.time()
  self.maximum_roots=int(getattr(a,'max_roots',None) or self.plan.get('maximum_roots') or 0)
  require(self.maximum_roots>0,'production owner requires an explicit finite maximum_roots budget')
  registry=read_registry();self.commands={}
  for stage,name in (self.plan.get('worker_entries') or WORKERS).items():
   row=registry[name];require(row['status']=='active' and row['owner']=='codex-root' and row['stop_condition'],'unregistered worker')
   self.commands[stage]=row['command']
   if self.plan.get('worker_argv'):
    require(self.commands[stage]==self.plan['worker_argv'][stage],'worker command differs from frozen plan')
  self.events=[];self.counts=collections.Counter();self.active=collections.Counter();self.pending=collections.Counter()
  self.tasks=set();self.children={};self.ordinal=0;self.qualified=[];self.collection_tasks=set();self.stopping=False
  # Short-window infrastructure protection: a control-plane fault (stale
  # calendar gate, provider outage, pool not ready) otherwise keeps admitting
  # roots that all fail in seconds.  Hold new admission while in-flight work
  # drains, and report the bottleneck instead of manufacturing error counts.
  self.recent_outcomes=collections.deque(maxlen=int(os.environ.get('QA6K_ERROR_WINDOW','12')))
  self.error_window_failures=int(os.environ.get('QA6K_ERROR_STOP_AFTER','8'))
  self.failure_signatures=collections.Counter()
  self.latest_failure_signature=None
  self.native_slots=max(1,int(os.environ.get('QA6K_NATIVE_SLOTS','96')))
  lane_model=os.environ.get('QA18K_AUTHOR_LANE_MODEL','').strip()
  lane_caps={'model_b1':400,'model_b2':50,'model_a1':75,'model_a1-sol':75}
  configured=os.environ.get('QA6K_AUTHOR_ACTIVE_CAP')
  if configured is None: configured=str(lane_caps.get(lane_model, self.plan.get('logical_author_cap',1500)))
  self.author_slots=max(1,min(int(self.plan.get('logical_author_cap',1500)),int(configured)))
  self.native=asyncio.Semaphore(self.native_slots);self.reviewer=asyncio.Semaphore(450)
  self.latest_global={'author':0,'reviewer':0,'total':0};self.last_scan=0

 def event(self,kind,**data):
  row={'epoch':time.time(),'event':kind,**data};self.events.append(row)
  with (self.out/'events.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')

 def observe_outcome(self,key,ok,**data):
  """Track recent per-root outcomes and stop admission on a sustained fault."""
  self.recent_outcomes.append(bool(ok))
  window=list(self.recent_outcomes)
  if len(window)<self.error_window_failures:return
  if any(window) or self.stopping:return
  self.stopping=True
  self.event('infrastructure_error_rate_stop',key=key,failures=len(window),
    window=self.error_window_failures,no_success_in_window=True,**data)

 def observe_failure_signature(self,key,signature,**data):
  """Signature-level circuit breaker (supervisor 20:18 §5).

  A rolling window counts identical ``failure_type|message`` signatures among
  finished roots.  Ten identical failures - or a quarter of all admitted roots -
  stops *new* admission while letting in-flight roots drain, records a
  ``systemic_failure_signature`` event plus a progress field, and does NOT
  auto-recover inside the same wave.  This is what would have turned today's
  780/780 total losses into an 8-10 root loss.
  """
  self.failure_signatures[signature]+=1
  count=self.failure_signatures[signature]
  fraction=(count/max(1,self.counts.get('started',0)))
  self.latest_failure_signature={'signature':signature,'count':count,'fraction':round(fraction,4)}
  threshold_hit=(count>=int(os.environ.get('QA6K_SIGNATURE_BREAKER_COUNT','10'))
                 or fraction>=float(os.environ.get('QA6K_SIGNATURE_BREAKER_FRACTION','0.25')))
  if threshold_hit and not self.stopping:
   self.stopping=True
   self.event('systemic_failure_signature',key=key,signature=signature,count=count,
     fraction=round(fraction,4),new_admission_stopped=True,in_flight_retained=True,**data)

 def verify_sources(self):
  # Owner start-up verifies the FULL binding (a wave may never start drifted), but
  # later child spawns only fail closed on runtime-critical sources; controller /
  # factory / runner / report drift is reported instead of killing in-flight roots
  # (supervisor 19:40 §4.1).
  from assetforge.pipeline import source_layering
  # Wave start hashes every source exactly once and publishes the manifest; later
  # child spawns only stat-compare against it (supervisor 20:18 §3.1 - per-root
  # hashing of ~599 sources saturated GPFS metadata and stalled whole waves).
  if getattr(self,'_source_manifest',None) is None:
   verdict=source_layering.verify(
     self.sources, verify_orchestration=True,
     on_orchestration_drift=lambda rows:self.event('orchestration_source_drift',rows=rows))
   manifest=source_layering.build_stat_manifest(self.sources)
   path=self.out/'source_verification.json'
   immutable_write(path,{'schema_version':'wave-source-verification-v1','rows':manifest})
   self._source_manifest=manifest
   self._source_manifest_ref=reference(path)
   self.event('source_verification_manifest',manifest=self._source_manifest_ref,
              sources=len(self.sources))
   return verdict
  return source_layering.verify_via_manifest(
    self.sources,self._source_manifest,
    on_drift=lambda rows:self.event('source_stat_drift',rows=rows))

 def author_route_env(self,key):
  """Shard new Author roots across every approved capture model.

  The legacy contract only allowed a sequential fallback chain, so 100% of
  Author traffic landed on the first route while the approved capture models sat
  idle.  With `AUTHOR_MODEL_SHARD=1` each root is assigned one capture
  model by a stable hash of its key, weighted 5:3:5 to match the declared
  250/150/250 channel caps.  Nothing else about the route changes: same
  reasoning profile, same tools, same native docs, same quality gates.
  """
  if os.environ.get('CAPTURE_ONLY')!='1' or os.environ.get('AUTHOR_MODEL_SHARD')!='1':
   return None
  mix=(('capture_1',5),('capture_2',3),('capture_3',5))
  total=sum(weight for _name,weight in mix)
  slot=int(hashlib.sha256(key.encode()).hexdigest()[-8:],16)%total
  for name,weight in mix:
   if slot<weight:
    env=dict(os.environ);env['CAPTURE_PRIMARY']=name
    return env
   slot-=weight
  raise RuntimeError('author route shard resolution failed')

 async def child(self,stage,key,argv,env=None):
  self.verify_sources();logs=self.out/'logs';logs.mkdir(exist_ok=True)
  if getattr(self,'_source_manifest_ref',None) is not None:
   env=dict(env or os.environ)
   env['QA106_SOURCE_VERIFICATION']=self._source_manifest_ref['path']
   env['QA106_SOURCE_VERIFICATION_SHA256']=self._source_manifest_ref['sha256']
  started=time.time();self.active[stage]+=1
  try:
   with stage_logs(logs,f"{key}.{stage}") as (stdout,stderr):
    child=await asyncio.create_subprocess_exec(*argv,cwd=ROOT,env=env,stdout=stdout,stderr=stderr,
      stdin=asyncio.subprocess.DEVNULL,start_new_session=True)
    self.children[child.pid]=(child,stage,key);self.event('stage_started',stage=stage,key=key,pid=child.pid)
    # `repair` runs a full Author revision (compile + native regression), so it
    # belongs with the long-lived stages; a 900s budget killed every revision
    # with SIGTERM and surfaced as an empty SystemExit.
    try:code=await asyncio.wait_for(child.wait(),7500 if stage in ('author','reviewer','repair') else 900)
    except asyncio.TimeoutError:
     os.killpg(child.pid,signal.SIGTERM)
     try:code=await asyncio.wait_for(child.wait(),30)
     except asyncio.TimeoutError:
      os.killpg(child.pid,signal.SIGKILL)
      try:code=await asyncio.wait_for(child.wait(),30)
      except asyncio.TimeoutError:
       self.event('cleanup_pending',stage=stage,key=key,pid=child.pid)
       # Remains owned and counts as a live child until the kernel reaps it.
       code=await child.wait()
    self.children.pop(child.pid,None)
   self.event('stage_finished',stage=stage,key=key,returncode=code,elapsed_seconds=time.time()-started)
   return code
  finally:self.active[stage]-=1

 async def capacity(self,stage):
  # `stopping` only stops new root admission.  Already-admitted roots must
  # still be able to reach native/Reviewer/qualification/collection, otherwise
  # an infrastructure guard or a controller error would poison in-flight work
  # and manufacture review_admission_deadline failures instead of protecting
  # the work already paid for.
  #
  # This must NOT spin while the pool is full: a bounded probe that returns
  # False hands control back to the main loop, which keeps writing progress,
  # detecting controller/task errors, batching collection and honouring
  # stop_admission.json.  A blocking loop here froze the whole owner for the
  # entire Author lifetime (measured: 19 minutes of no bookkeeping).
  deadline_probe=time.monotonic()+float(os.environ.get('QA6K_CAPACITY_PROBE_SECONDS','2') or 2)
  while stage!='author' or not self.stopping:
   # Walking every /proc entry is a full-host scan; when the owner is declared
   # independent of the global process census, skip it instead of letting a
   # stale census block admission for minutes at a time.
   if time.time()-self.last_scan>10 and os.environ.get('QA6K_IGNORE_GLOBAL_PROCESS_COUNT')!='1':
    self.latest_global=await asyncio.to_thread(global_items);self.last_scan=time.time()
   disks=[ROOT] if stage=='reviewer' else [Path('/'),ROOT]
   enough=all(os.statvfs(p).f_bavail*os.statvfs(p).f_frsize>=10*1024**3 for p in disks)
   ramp=min(self.plan['logical_author_cap'], self.author_slots)
   # Global process enumeration is advisory only: old owners and wrapper
   # processes are not a reliable measure of this owner's admission.  Use the
   # local stage counters and the declared provider/channel slots for actual
   # backpressure; never leave an otherwise healthy lane waiting on a stale
   # cross-owner count.
   global_ok = os.environ.get('QA6K_IGNORE_GLOBAL_PROCESS_COUNT') == '1' or self.latest_global['total'] < self.plan['logical_total_cap']
   if enough and global_ok and (stage!='author' or self.active['author']<ramp):
    self.latest_global[stage]+=1;self.latest_global['total']+=1;return True
   if time.monotonic()>=deadline_probe:return False
   await asyncio.sleep(.2)
  return False

 async def item(self,cell,arm,ordinal):
  lane=self.out/'author'/(cell['cell']+'-'+arm);root=lane/cell['domain'];root.mkdir(parents=True,exist_ok=True)
  namespace=hashlib.sha256(str(root.relative_to(ROOT)).encode()).hexdigest()[:8]
  key=f'constructed-{arm}-{cell["cell"]}-{namespace}-{ordinal:07d}';start=time.time()
  immutable_write(lane/'preflight.json',{'passed':True,'production_plan':reference(self.a.plan),
    'rubrics':{cell['domain']:{'relative_path':cell['rubric']['path'],'sha256':cell['rubric']['sha256'],
       'mechanical_profile':cell['mechanical_profile']}},'asset_arm':arm=='assets'})
  state={'key':key,'cell':cell['cell'],'arm':arm,'root_task_id':key,'started_at_epoch':start}
  # Explicit alarm: an independently accepted QA that never reaches
  # `collection_eligible` is a data-loss event, not a normal reject.  The
  # UnboundLocalError above cost 70+ accepted roots precisely because nothing
  # counted that gap; keep it visible even though the binding is now fixed.
  accepted=False
  self.event('root_started',**state);self.counts['started']+=1
  if self.counts['started'] in self.plan['automatic_checkpoints']:
   self.event('automatic_checkpoint',root_count=self.counts['started'],no_admission_pause=True)
  try:
   author_argv=self.commands['author']+['--plan',str(self.a.plan),'--plan-sha256',self.a.plan_sha256,
     '--cell',cell['cell'],'--ordinal',str(ordinal),'--arm',arm,'--run-root',str(root)]
   code=await self.child('author',key,author_argv,env=self.author_route_env(key))
   # Bounded same-root continuation (supervisor 19:25 §6 / 18:55, budget corrected to 2 by the
   # user ruling: a root that ends with "Author response budget
   # exhausted before an accepted compile" dies as a non-recoverable loss even though its draft,
   # journals and compile diagnostics are all on disk.  Allow up to TWO continuations of the
   # *same* root (1 first construction + 2 collect-side repairs + 2 Reviewer-side repairs = 5);
   # every gate still re-runs and the marker records how many attempts were used, so the extra
   # attempts stay auditable and bounded.
   if code:
    failures=list((root/'completed').glob('*.failure.json'))
    exhausted=bool(failures) and _author_budget_exhausted(json.loads(failures[-1].read_text()))
    marker=root/'.continuation_used.json'
    remaining=_remaining_author_budget(root,key) if exhausted else None
    used=0
    if marker.exists():
     try: used=int((json.loads(marker.read_text()) or {}).get('attempt') or 0)
     except (OSError,ValueError): used=0
    if exhausted and used<2 and remaining:
     immutable_write(marker,{'reason':'author_budget_exhausted','attempt':used+1,
       'first_failure':reference(failures[-1]),'started_at_epoch':time.time(),
       'owner':'codex-root','remaining_original_responses':remaining,
       'note':'bounded same-root continuation (max 2 collect-side repairs, user ruling 1+2+2=5); '
              'resumes from the checkpoint and keeps the ORIGINAL response budget (no new rounds '
              'are granted); all gates re-run'})
     self.event('author_continuation_scheduled',**state,reason='author_budget_exhausted',
                first_failure=reference(failures[-1]),remaining_original_responses=remaining)
     self.counts['author_continuation']+=1
     code=await self.child('author',key,author_argv,env=self.author_route_env(key))
     if code:
      self.counts['author_continuation_failed']+=1
     else:
      self.counts['author_continuation_accepted']+=1
    elif exhausted and used>=2:
     self.counts['author_continuation_exhausted']+=1
   if code:
    failures=list((root/'completed').glob('*.failure.json'))
    if failures:
     failure=json.loads(failures[-1].read_text())
     classification=_classify_author_terminal(failure)
     self.counts[classification]+=1
     self.event('author_terminal_failed',**state,failure_type=failure.get('failure_type'),
                recoverable=failure.get('recoverable',False),classification=classification,
                failure_receipt=reference(failures[-1]))
     self.observe_failure_signature(
       key,str(failure.get('failure_type'))+'|'+str(failure.get('failure_message'))[:160],
       classification=classification)
     self.observe_outcome(key,False,failure_type=failure.get('failure_type'))
     return
    raise RuntimeError('author_operational_or_construction_failure')
   completed=root/'completed'/(key+'.json');require(completed.exists(),'Author completion seal missing')
   completed_value=json.loads(completed.read_text())
   require(completed_value.get('terminal_seal',{}).get('status')=='completed',
           'Author completion seal missing or incomplete')
   self.counts['materialized']+=1;self.event('materialized',**state)
   self.observe_outcome(key,True)
   review_input=self.out/'native'/key
   self.pending['native']+=1
   async with self.native:
    self.pending['native']-=1
    code=await self.child('native',key,self.commands['native']+['--mode','prepare','--plan',str(self.a.plan),
      '--plan-sha256',self.a.plan_sha256,'--cell',cell['cell'],'--completed',str(completed),'--output',str(review_input)])
   if code:raise RuntimeError('native_revalidation_failed')
   review_plan=review_input/'review_plan.json';rp=json.loads(review_plan.read_text());row=rp['items'][0]
   review=self.out/'review'/key;review.mkdir(parents=True)
   try:
       from assetforge.tools.run_release_reviews_compact import arguments
   except Exception:
       _missing_dependency(
           "the compact review driver",
           "It is tied to one runtime release; supply it with your own runtime build.")
   rid,argv,env=arguments(row,rp,review)
   # Capture-only workers resolve only capture_1/capture_2/capture_3; the legacy
   # historical chain resolves mog8/sol/mog6.  Select the primary from the same
   # opt-in the Author uses so a batch run cannot silently ask for a route the
   # active policy no longer installs.
   if os.environ.get('CAPTURE_ONLY')=='1':
    env['CAPTURE_ONLY']='1'
    env['QA18K_REVIEW_PRIMARY']=os.environ.get('QA18K_REVIEW_PRIMARY') or os.environ.get('CAPTURE_PRIMARY') or 'capture_1'
   else:
    env['QA18K_REVIEW_PRIMARY']=os.environ.get('QA18K_REVIEW_PRIMARY') or 'mog8'
   # The worker command includes the same production environment and transport limits.
   argv=self.commands['reviewer']+argv[2:]
   if row.get('construction_bundle'):env['AUTOMATION106_CONSTRUCTION_BUNDLE']=str(bound(row['construction_bundle']).parent)
   self.pending['reviewer']+=1
   async with self.reviewer:
    # Real resource pressure queues accepted Author work; it is not a task
    # rejection and never depends on an obsolete calendar deadline.
    while not await self.capacity('reviewer'):
     await asyncio.sleep(1)
    self.pending['reviewer']-=1
    code=await self.child('reviewer',key,argv,env)
   receipt=review/'audits'/(rid+'.markdown-reviewer.json')
   require(code==0 and receipt.exists(),'reviewer_operational_failure')
   rr=json.loads(receipt.read_text());require(rr['status']=='completed','reviewer incomplete')
   decision=rr['decision'];status='reviewer_'+decision
   immutable_write(review/'results.jsonl.marker.json',{'receipt':reference(receipt),'decision':decision})
   with (review/'results.jsonl').open('x') as f:f.write(json.dumps({'source_sha256':row['source_sha256'],
     'task_id':row['task_id'],'status':status,'receipt':reference(receipt)})+'\n')
   self.counts[status]+=1;self.event(status,**state,elapsed_seconds=time.time()-start,receipt=reference(receipt))
   if decision!='accept':
    # Bounded same-root revision: hand the review's findings back to
    # the Author and re-review the repaired bundle instead of rebuilding a new
    # task.  Two revisions after the first build; a third negative decision is
    # recorded as a reject.
    self.event('reviewer_reject_repair_queued',**state)
    repaired=await self.repair_after_reject(state,cell,root,review_input,review_plan,review,row,rp,rid,attempts=2)
    if not repaired:
     return
    review=repaired['review'];review_plan=repaired['plan'];row=repaired['row']
    receipt=repaired['receipt']
    # The repaired bundle carries its own independent decision; the pre-repair
    # `reject` must never leak into the qualification assertion below.
    decision=json.loads(receipt.read_text())['decision']
    if decision!='accept':
     self.counts['reviewer_reject_after_repair']+=1
     self.event('reviewer_reject_after_repair',**state,receipt=reference(receipt))
     return
   # Bind the qualification target on every accepted path.  When this lived
   # inside the `decision!='accept'` branch a direct accept raised
   # `UnboundLocalError: qualified` and the paid QA was silently discarded
   # (measured: 70+ accepted roots across r17/r20/r23/w1..w4/v1..v3).
   qualified=self.out/'qualified'/key
   require(decision=='accept','qualification_requested_without_accept')
   accepted=True
   async with self.native:
    code=await self.child('native',key+'-qualify',self.commands['native']+['--mode','qualify','--plan',str(review_plan),
      '--plan-sha256',reference(review_plan)['sha256'],'--review',str(review),'--output',str(qualified)])
   if code:raise RuntimeError('release_qualification_failed')
   # Collection consumes a separate frozen quota selection. A new accepted
   # candidate must not be sent to all generators merely because it qualified.
   self.counts['qualified_candidates']+=1
   self.event('qualified_candidate',**state,elapsed_seconds=time.time()-start,manifest=reference(qualified/'manifest.json'),
     distribution_selected=False,collection_started=False)
  except Exception as error:
   if accepted:
    self.counts['accept_without_eligible']+=1
    self.event('accept_without_eligible',**state,error_type=type(error).__name__,message=str(error)[:1500])
   self.counts['errors']+=1;self.event('root_error',**state,error_type=type(error).__name__,message=str(error)[:1500])
   self.observe_outcome(key,False,failure_type=type(error).__name__)
  finally:
   self.counts['finished']+=1;self.event('root_finished',**state,elapsed_seconds=time.time()-start)

 async def collect_batch(self,paths,epoch):
  directory=self.out/'collection'/f'epoch{epoch:05d}';directory.mkdir(parents=True)
  inputs=[json.loads((p/'manifest.json').read_text()) for p in paths]
  manifest={k:v for k,v in inputs[0].items() if k not in ('items','pending','accepted_v106')}
  manifest.update(items=[row for d in inputs for row in d['items']],pending=[])
  manifest['accepted_v106']=len(manifest['items']);immutable_write(directory/'manifest.json',manifest)
  companions=[json.loads((p/'construction_collection_binding.json').read_text()) for p in paths]
  companion={'schema_version':'construction-collection-companion-v1','qualified_manifest':reference(directory/'manifest.json'),
   'construction_bundles':{k:v for d in companions for k,v in d['construction_bundles'].items()},
   'control_root_ids':[r for d in companions for r in d['control_root_ids']]}
  immutable_write(directory/'companion.json',companion)
  async def one(alias):
   if os.environ.get('QA6K_COLLECTION_NEXT')=='1':
    argv=[sys.executable,'assetforge/tools/run_benchmark_release_collection_next.py']
   else:
    argv=self.commands['collection']
   argv=argv+['--manifest',str(directory/'manifest.json'),'--manifest-sha256',reference(directory/'manifest.json')['sha256'],
    '--companion',str(directory/'companion.json'),'--companion-sha256',reference(directory/'companion.json')['sha256'],
    '--alias',alias,'--output',str(directory/alias),'--attempts','10']
   # Collection has its own separate global model slots and exact finite 6h+2h lifetime.
   key=f'collection-{epoch}-{alias}';log=self.out/'logs';started=time.time()
   with stage_logs(log,f"{key}") as (stdout,stderr):
    child=await asyncio.create_subprocess_exec(*argv,cwd=ROOT,stdout=stdout,stderr=stderr,start_new_session=True)
    self.children[child.pid]=(child,'collection',key);self.event('stage_started',stage='collection',key=key,pid=child.pid,qa_count=len(manifest['items']))
    code=await child.wait();self.children.pop(child.pid,None)
   self.event('stage_finished',stage='collection',key=key,returncode=code,elapsed_seconds=time.time()-started)
  await asyncio.gather(*(one(alias) for alias in (('capture_model_2_max','capture_model_3_xhigh','capture_model_1_flash') if os.environ.get('QA6K_COLLECTION_NEXT')=='1' else ('capture_model_2_max','capture_model_1_max','capture_model_3_xhigh'))))
  self.distribution_gate(directory,manifest)

 def distribution_gate(self,directory,manifest):
  """Run the frozen distribution contract on the collected batch.

  The batch is far below the contract total for most of the run, so this is
  expected to fail until enough qualified items exist.  The point is that the
  release decision is produced by the real gate over the real taskset instead
  of being hard-coded to zero, and that every failure reason is recorded.
  """
  from assetforge.tools.gate_automation_18k_distribution import audit
  try:
      from assetforge.tools.run_benchmark_release_collection import collection_rows
  except Exception:
      _missing_dependency(
          "the release-collection driver",
          "It is tied to one runtime release; supply it with your own runtime build.")
  binding=bound(self.plan['distribution'])
  contract=json.loads(binding.read_text())
  try:
   self._distribution_gate(directory,manifest,binding,contract,audit,collection_rows)
  except Exception as error:
   # The gate must never be able to poison in-flight roots.  Record the full
   # traceback as its own receipt so the failure is diagnosable instead of
   # surfacing as a truncated controller_stage_error.
   import traceback
   detail=traceback.format_exc()
   self.counts['distribution_gate_errors']+=1
   receipt=directory/'distribution_gate_error.json'
   immutable_write(receipt,{'schema_version':'construction-distribution-gate-error-v1',
     'owner':'codex-root','error_type':type(error).__name__,'message':str(error)[:2000],
     'traceback':detail[-8000:],'contract':reference(binding),
     'qualified_items':len(manifest.get('items') or []),'provider_calls':0})
   self.event('distribution_gate_error',epoch=directory.name,error_type=type(error).__name__,
     message=str(error)[:400],receipt=reference(receipt))
   return

 def _distribution_gate(self,directory,manifest,binding,contract,audit,collection_rows):
  old=contract.get('old_pool_reference') or {}
  if not hasattr(self,'baseline_combinations'):
    baseline=ROOT/str(old.get('taskset') or '')
    rows=[json.loads(line) for line in baseline.read_text().splitlines() if line.strip()]
    require(len(rows)==int(old.get('rows') or 0),'old pool reference cardinality mismatch')
    from assetforge.tools.gate_automation_18k_distribution import scorer_apps
    self.baseline_combinations={'+'.join(scorer_apps(task)) for task in rows}
  _native,bindings=collection_rows(manifest)
  tasks=[]
  for row in bindings:
   path=bound(row['source_task'])
   tasks.append(json.loads(path.read_text()))
  result=audit(tasks,contract,'live',baseline_combinations=self.baseline_combinations)
  # ``passed`` from the gate is a per-item legality verdict: it says every row in
  # this batch obeys the prompt/assertion/membership/novelty rules.  It is NOT a
  # statement that the aggregate distribution target has been reached, so a
  # one-row batch can be legal and still be nowhere near the contract total.
  # Distribution validity therefore requires BOTH a clean batch and the
  # contract cardinality, and the deficit is recorded either way.
  contract_total=int(contract.get('total') or 0)
  rows=len(tasks)
  result['contract_total']=contract_total
  result['aggregate_target_met']=rows>=contract_total if contract_total else False
  result['rows_deficit']=max(0,contract_total-rows)
  result['distribution_valid']=bool(result['passed'] and result['aggregate_target_met'])
  result['contract']=reference(binding)
  result['qualified_items']=rows
  result['gate_output']=str((directory/'distribution.json').relative_to(ROOT))
  immutable_write(directory/'distribution.json',result)
  self.counts['distribution_checked_batches']+=1
  self.event('distribution_gate',epoch=directory.name,passed=bool(result['passed']),rows=result['rows'],
    failures=len(result.get('failures') or []),contract=reference(binding),
    contract_total=contract_total,rows_deficit=result['rows_deficit'],
    aggregate_target_met=result['aggregate_target_met'],distribution_valid=result['distribution_valid'],
    batch_distribution_evidence=reference(directory/'distribution.json'))
  if result['distribution_valid']:
   self.counts['distribution_valid']+=rows

 @staticmethod
 def repair_brief_from_memo(memo,profile=None):
  """Extract a separate task-local diagnosis; never erase business vocabulary."""
  import re
  from assetforge.pipeline.qa_repair_context import validate_brief
  text=str(memo or '').strip()
  match=re.search(r'TASK_LOCAL_REPAIR_BRIEF_BEGIN\s*(.*?)\s*TASK_LOCAL_REPAIR_BRIEF_END',text,re.S)
  if match or (profile or {}).get('construction_application_roles'):
   from assetforge.pipeline.task_repair_diagnosis import delivery,BEGIN,END
   if not delivery(BEGIN+' '+END,text,'reject')['passed']:
    raise ValueError('independent task-local repair diagnosis must have unique nonempty markers')
  if match:text=match.group(1).strip()
  profile=profile or {}
  if profile.get('construction_application_roles') and not match:
   raise ValueError('independent task-local repair diagnosis is missing; do not pass the complete review to Author')
  count=profile.get('application_count')
  shape=('keep the requirement of '+str(count)+' necessary applications for this task, ' if count else 'keep the original application scope, ')
  head=('Keep the original public business request, business goal, necessary dependencies, legal alternative paths and exclusion/protection obligations; '+shape+
        'world records, entity mappings, asset instance parameters, correct operations and wrong scoring predicates may be corrected.'
        'A business commitment must not be weakened; after fixing the implementation, re-verify the correct outcome, key errors and protection scope of the whole task.\n\n')
  if len(head+text)>12000:raise ValueError('task-local repair diagnosis exceeds bounded input; no silent truncation')
  return validate_brief(head+text)

 async def repair_after_reject(self,state,cell,root,review_input,review_plan,review,row,rp,rid,attempts=2):
  """Same-root repair driven by the review, then re-review.

  Rebuilding a task from scratch is far more expensive than repairing the one
  already judged, so a rejected root gets a bounded number of same-root
  revisions.  No gate is weakened: the repaired bundle must pass native
  prepare and a fresh review.
  """
  decision=None
  for attempt in range(1,attempts+1):
   memo_path=review/'review_memos'/(rid+'.md')
   memo=memo_path.read_text() if memo_path.exists() else ''
   repair_dir=self.out/'repair'/key_dir(state,attempt)
   if repair_dir.exists():continue
   repair_dir.mkdir(parents=True)
   brief=repair_dir/'brief.md'
   try:brief_text=self.repair_brief_from_memo(memo,cell['mechanical_profile'])
   except ValueError as error:
    self.counts['repair_diagnosis_delivery_errors']+=1
    self.event('repair_diagnosis_delivery_error',**state,message=str(error),
        semantic_reject_preserved=True,author_repair_attempt_consumed=False)
    return None
   imperative_write(brief,brief_text)
   self.event('repair_started',**state,attempt=attempt,brief=reference(brief))
   # The repair entry runs under the unified benchmark environment (it imports
   # a local agent framework/json5 and the the author runtime tool layer).  Using this controller's own
   # interpreter aborts every repair at import time, which showed up as a 100%
   # repair_failed rate across 31 attempted revisions.
   repair_python=os.environ.get('ASSETFORGE_RUNTIME_VENV', sys.executable)
   code=await self.child('repair',key_dir(state,attempt),
     [repair_python,'assetforge/tools/run_constructed_qa_repair.py',
      '--review-plan',str(review_plan),'--review-plan-sha256',reference(review_plan)['sha256'],
      '--review',str(review),'--brief',str(brief),'--brief-sha256',reference(brief)['sha256'],
      '--output',str(repair_dir),'--repair-mode','semantic'],
     env=dict(os.environ,CAPTURE_ONLY='1',
              AUTOMATION106_OWNER_CONTROLLED_LIFETIME='1',CHANNEL_CAPS_V2='1'))
   completed=repair_dir/'completed'/(state['root_task_id']+'.json')
   if code or not completed.exists():
    self.counts['repair_failed']+=1
    self.event('repair_failed',**state,attempt=attempt,returncode=code)
    return None
   self.counts['repair_completed']+=1
   new_review_input=self.out/'native'/f"{state['key']}-rev{attempt}"
   async with self.native:
    code=await self.child('native',f"{state['key']}-rev{attempt}",
      self.commands['native']+['--mode','prepare','--plan',str(self.a.plan),'--plan-sha256',self.a.plan_sha256,
       '--cell',cell['cell'],'--completed',str(completed),'--output',str(new_review_input)])
   if code:return None
   new_plan=new_review_input/'review_plan.json';new_rp=json.loads(new_plan.read_text());new_row=new_rp['items'][0]
   new_review=self.out/'review'/f"{state['key']}-rev{attempt}";new_review.mkdir(parents=True)
   try:
       from assetforge.tools.run_release_reviews_compact import arguments
   except Exception:
       _missing_dependency(
           "the compact review driver",
           "It is tied to one runtime release; supply it with your own runtime build.")
   new_rid,new_argv,new_env=arguments(new_row,new_rp,new_review)
   if os.environ.get('CAPTURE_ONLY')=='1':
    new_env['CAPTURE_ONLY']='1'
    new_env['QA18K_REVIEW_PRIMARY']=os.environ.get('QA18K_REVIEW_PRIMARY') or os.environ.get('CAPTURE_PRIMARY') or 'capture_1'
   new_argv=self.commands['reviewer']+new_argv[2:]
   if new_row.get('construction_bundle'):
    new_env['AUTOMATION106_CONSTRUCTION_BUNDLE']=str(bound(new_row['construction_bundle']).parent)
   async with self.reviewer:
    code=await self.child('reviewer',f"{state['key']}-rev{attempt}",new_argv,new_env)
   receipt=new_review/'audits'/(new_rid+'.markdown-reviewer.json')
   if code or not receipt.exists():return None
   rr=json.loads(receipt.read_text())
   if rr.get('status')!='completed':return None
   immutable_write(new_review/'results.jsonl.marker.json',{'receipt':reference(receipt),'decision':rr['decision'],
     'repaired_from':reference(review/'results.jsonl.marker.json') if (review/'results.jsonl.marker.json').exists() else None})
   with (new_review/'results.jsonl').open('x') as handle:
    handle.write(json.dumps({'source_sha256':new_row['source_sha256'],'task_id':new_row['task_id'],
      'status':'reviewer_'+rr['decision'],'receipt':reference(receipt)},ensure_ascii=False)+'\n')
   self.counts['reviewer_'+rr['decision']]+=1
   self.event('reviewer_'+rr['decision'],**state,attempt=attempt,repaired=True)
   if rr['decision']=='accept':
    return {'review':new_review,'plan':new_plan,'row':new_row,'receipt':receipt,'rid':new_rid}
   review,review_plan,row,rp,rid=new_review,new_plan,new_row,new_rp,new_rid
  return None

 async def run(self):
  (ROOT/'POLICY.md').read_text();os.umask(0o077)
  pre=json.loads(bound(reference(self.a.preflight)).read_text());require(pre['passed'] and pre['provider_calls']==0,'cell preflight missing')
  # Cell preflights are written by more than one generator.  The legacy shape
  # used ``plan``; the current capture preflight binds the same immutable plan
  # under ``production_plan``.  Accept either, but still require the frozen
  # cells/route to match the production plan exactly.
  preflight_plan=pre.get('plan') or pre.get('production_plan')
  require(preflight_plan,'cell preflight does not bind a production plan')
  before=json.loads(bound(preflight_plan).read_text())
  require(before['cells']==self.plan['cells'] and before['route']==self.plan['route'],'profile preflight differs from production')
  if not self.a.control_only:
   from assetforge.pipeline.construction_assets import load_catalog
   from assetforge.pipeline.construction_admission import require_admitted_catalog
   catalog=load_catalog(bound(self.plan['catalog']),self.plan['catalog']['sha256']);require_admitted_catalog(catalog,self.plan['catalog'])
  self.out.mkdir(parents=True,exist_ok=False)
  lock=(self.out/'owner.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  sources=[Path(__file__),ROOT/'assetforge/tools/run_constructed_qa_author.py',ROOT/'assetforge/tools/process_constructed_qa.py',
    ROOT/'assetforge/tools/run_constructed_qa_reviewer.py',ROOT/'assetforge/tools/collect_constructed_qa.py',
    *[ROOT/'assetforge/benchmark_factory'/name for name in ('construction_author_tools.py','construction_manifest.py','construction_review.py')]]
  if os.environ.get('QA6K_COLLECTION_NEXT')=='1': sources.append(ROOT/'assetforge/tools/run_benchmark_release_collection_next.py')
  self.sources=self.plan.get('consumer_sources') or [reference(p) for p in sources]
  self.verify_sources()
  immutable_write(self.out/'owner.json',{'owner':'codex-root','pid':os.getpid(),'plan':reference(self.a.plan),
    'started_at_epoch':self.started,'sources':self.sources,'control_only':self.a.control_only,
    'maximum_roots':self.maximum_roots,'logical_author_cap':self.plan['logical_author_cap'],'reviewer_logical_cap':450,'local_native_slots':self.native_slots,'author_active_cap':self.author_slots,
    'channel_caps':self.plan['actual_channel_maximum'],'per_item_seconds':7200,'strict_rs_maximum':10,
    'stop_condition':'finite root budget, explicit stop or infrastructure guard stops admission; owned children drain',
    'release_counts_are_not_acceptance_counts':True})
  epoch=0;last_status=0
  while not self.stopping or self.tasks or self.collection_tasks or self.qualified:
   if self.ordinal>=self.maximum_roots and not self.stopping:
    self.stopping=True;self.event('admission_stopped',reason='root_budget_complete',maximum_roots=self.maximum_roots)
   stop_file=self.out/'stop_admission.json'
   if stop_file.exists() and not self.stopping:
    self.stopping=True;self.event('admission_stopped',reason='owner_stop_file',receipt=reference(stop_file))
   for task in [*self.tasks,*self.collection_tasks]:
    if task.done() and task.exception():
     self.event('controller_stage_error',error_type=type(task.exception()).__name__,message=str(task.exception())[:1500]);self.stopping=True
   self.tasks={task for task in self.tasks if not task.done()};self.collection_tasks={t for t in self.collection_tasks if not t.done()}
   if self.a.control_until_catalog and self.a.control_until_catalog.exists():
    from assetforge.pipeline.construction_admission import require_admitted_catalog
    cat=json.loads(self.a.control_until_catalog.read_text());require_admitted_catalog(cat,reference(self.a.control_until_catalog))
    if not self.stopping:self.event('control_admission_sealed',reason='independently admitted assets available; baseline paid tasks drain')
    self.stopping=True
   if self.stopping and not self.tasks and not self.collection_tasks and not self.qualified:break
   if self.qualified and len(self.collection_tasks)<4:
    epoch+=1;paths,self.qualified=self.qualified,[];t=asyncio.create_task(self.collect_batch(paths,epoch));self.collection_tasks.add(t)
   if time.time()-last_status>=30:
    if os.environ.get('QA6K_IGNORE_GLOBAL_PROCESS_COUNT')!='1':
     self.latest_global=await asyncio.to_thread(global_items);self.last_scan=time.time()
    atomic(self.out/'progress.json',{'observed_at_epoch':time.time(),'elapsed_seconds':time.time()-self.started,
     'counts':dict(self.counts),'active_stage_workers':dict(self.active),'queued_stages':dict(self.pending),
     'global_logical_items':self.latest_global,'live_roots':len(self.tasks),'active_collection_batches':len(self.collection_tasks),
     'systemic_failure_signature':self.latest_failure_signature,
     'source_verification_manifest':getattr(self,'_source_manifest_ref',None),
     'distribution_valid':self.counts.get('distribution_valid',0),'released':self.counts.get('released',0),'training_ready':self.counts.get('training_ready',0)})
    last_status=time.time()
   if not self.stopping and self.pending['reviewer']<450 and self.pending['native']<48:
    admitted = await self.capacity('author')
    # Explicit lanes already have independent provider slot locks.  When a
    # lane is launched for parallel-capacity use, do not let a stale global
    # process census hold it at zero; disk/host checks still run inside each
    # child stage and the shared provider locks remain authoritative.
    if admitted:
     self.ordinal+=1;cell=self.cells[(self.ordinal-1)%len(self.cells)]
     arm='control' if self.a.control_only else 'assets'
     t=asyncio.create_task(self.item(cell,arm,self.ordinal));self.tasks.add(t)
   await asyncio.sleep(.2 if not self.stopping else 1)
  atomic(self.out/'final.json',{'complete':True,'counts':dict(self.counts),'all_children_drained':not self.children,
    'distribution_valid':self.counts.get('distribution_valid',0),'released':self.counts.get('released',0),'training_ready':self.counts.get('training_ready',0)})

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--plan-sha256',required=True)
 p.add_argument('--preflight',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 p.add_argument('--control-only',action='store_true');p.add_argument('--control-until-catalog',type=Path)
 p.add_argument('--max-roots',type=int)
 asyncio.run(Factory(p.parse_args()).run())
