"""Finite independent asset review, reusing production routes/tools/journals."""
import argparse,copy,hashlib,json,os,re,shlex,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))


def _module_closure(seeds):
    """Local import closure of the given project files (relative and package imports)."""
    import ast
    seen={}
    queue=[Path(path).resolve() for path in seeds]
    while queue:
        path=queue.pop()
        if path in seen or not path.is_file():
            continue
        data=path.read_bytes();seen[path]=data
        if path.suffix!='.py':
            continue
        for node in ast.walk(ast.parse(data.decode('utf-8'))):
            candidates=[]
            if isinstance(node,ast.ImportFrom):
                if node.level:
                    base=path.parent
                    for _ in range(node.level-1):base=base.parent
                    module=base/(node.module.replace('.','/') if node.module else '')
                elif node.module and node.module.startswith('assetforge'):
                    module=ROOT/node.module.replace('.','/')
                else:
                    module=None
                if module is not None:
                    candidates=[module.with_suffix('.py')]
                    candidates += [module/(alias.name+'.py') for alias in node.names if alias.name!='*']
                    candidates += [module/alias.name/'__init__.py' for alias in node.names if alias.name!='*']
            elif isinstance(node,ast.Import):
                candidates=[ROOT/(alias.name.replace('.','/')+'.py') for alias in node.names
                            if alias.name.startswith('assetforge')]
            elif (isinstance(node,ast.Constant) and isinstance(node.value,str)
                  and '\n' not in node.value and len(node.value)<200 and '/' in node.value
                  and not node.value.startswith('/')):
                # Frozen support data referenced by literal repo-relative path (e.g. the pinned
                # native record contract that construction_checked_assets.validators() hash-checks).
                literal=ROOT/node.value
                if (literal.is_file() and '..' not in node.value and
                        node.value.startswith(('assetforge/artifacts/', 'assetforge/runs/',
                                               'assetforge/benchmark_factory/', 'docs/'))):
                    candidates=[literal]
            queue.extend(candidates)
    return seen


def _flat_shim(package_name):
    return ('"""Convenience flat alias; the declared implementation is the package module below."""\n'
            'import importlib as _importlib\n'
            '_real = _importlib.import_module('+repr(package_name)+')\n'
            'globals().update({k: v for k, v in vars(_real).items() if k not in '
            "('__name__','__loader__','__spec__','__package__','__file__','__builtins__')})\n").encode()


def prior_review_material(prior_path, prior_sha256, current_catalog):
    """Bind historical evidence and source bytes without shadowing current imports."""
    from assetforge.pipeline.construction_assets import digest, require
    from assetforge.pipeline.construction_manifest import reference
    raw=prior_path.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==prior_sha256,'prior review digest mismatch')
    prior=json.loads(raw);require(prior.get('complete') and prior.get('actual_provider_calls',0)>0,'prior review incomplete')
    payloads={}
    def include(ref):
        path=ROOT/ref['path'];raw=path.read_bytes() if path.is_file() else b''
        if hashlib.sha256(raw).hexdigest()!=ref['sha256']:
            frozen=ref.get('frozen_content')
            blob=(ROOT/frozen['path'] if frozen else
                  prior_path.parent.parent/'asset_source_blobs'/ref['sha256'])
            raw=blob.read_bytes()
        require(hashlib.sha256(raw).hexdigest()==ref['sha256'],'prior source bytes unavailable: '+ref['path'])
        payloads['prior_review/source/'+ref['path']]=raw
        return raw
    seal=json.loads(include(prior['completion_seal']));trajectory=json.loads(include(prior['trajectory']))
    require(seal['identity']['config_sha256']==digest(prior['inputs']) and
            seal['result']['status']=='completed' and seal['result']['asset_decisions']==prior['decision'] and
            seal['result']['trajectory_sha256']==digest(trajectory),'prior completed seal differs')
    old_catalog=json.loads(include(prior['inputs']['catalog']))
    old_validation=json.loads(include(prior['inputs']['validation']))
    for ref in old_catalog.get('dependencies',[])+old_catalog.get('review_context_dependencies',[]):include(ref)
    for row in old_catalog['assets']:
        for name in ('definition','description','implementation'):include(row[name])
    for row in old_validation['examples']:
        include(row['example']);include(row['native_results'])
    for name in ('validation_implementation','role_evidence_validator','protocol'):
        if old_validation.get(name):include(old_validation[name])
    include(prior['inputs']['prompt']);include(prior['inputs']['implementation'])
    old={r['id']:r for r in old_catalog['assets']}
    unchanged=[];changed=[]
    for row in current_catalog['assets']:
        prev=old.get(row['id'])
        stable=prev is not None and row['version']==prev['version'] and all(
            row[k]['sha256']==prev[k]['sha256'] for k in ('definition','description','implementation'))
        (unchanged if stable else changed).append(row['id']+'@'+row['version'])
    old_deps={r['path']:r['sha256'] for r in old_catalog.get('dependencies',[])}
    current={r['path']:r['sha256'] for r in current_catalog.get('dependencies',[])}
    delta={'prior_review':reference(prior_path),'unchanged_primary_assets':unchanged,'changed_primary_assets':changed,
           'changed_constructor_dependencies':[{'path':k,'prior_sha256':old_deps.get(k),'current_sha256':v}
                                             for k,v in current.items() if old_deps.get(k)!=v],
           'previous_dependencies_outside_current_constructor_closure':sorted(set(old_deps)-set(current)),
           'reuse_is_not_automatic_accept':True}
    payloads['prior_review/final.json']=raw
    payloads['prior_review/catalog.json']=json.dumps(old_catalog,ensure_ascii=False).encode()
    payloads['prior_review/validation.json']=json.dumps(old_validation,ensure_ascii=False).encode()
    payloads['prior_review/delta.json']=json.dumps(delta,ensure_ascii=False).encode()
    return payloads,delta


def _sandbox_payloads(catalog,examples,definitions):
    """Package layout of every declared implementation + flat aliases + evidence JSON.

    The declared implementation of each catalog asset is uploaded at its real repo-relative path
    (so a reviewer can hash it against catalog.json), together with the transitive local import
    closure.  Flat module names are aliases of the same module object, so scratch code written for
    the earlier flat-only sandbox keeps working and cannot silently import a different file.
    """
    factory=ROOT/'assetforge/benchmark_factory'
    tools=ROOT/'assetforge/tools'
    seeds=[ROOT/item['implementation']['path'] for item in catalog['assets']]
    seeds += [ROOT/item[k]['path'] for item in catalog['assets'] for k in ('definition','description')]
    seeds += [ROOT/ref['path'] for ref in catalog.get('dependencies', [])]
    seeds += [ROOT/ref['path'] for ref in catalog.get('review_context_dependencies', [])]
    seeds+=[factory/name for name in ('construction_manifest.py','construction_author_tools.py',
                                      'construction_review.py')]
    seeds+=[tools/name for name in ('process_constructed_qa.py','collect_constructed_qa.py')]
    # Dynamic dispatch: `_version_builder` resolves these through importlib, which a static import
    # scan cannot see, so they are seeded explicitly from the constructor's own version table.
    from assetforge.pipeline.construction_assets import VERSION_BUILDERS
    seeds+=sorted({ROOT/(module.replace('.','/')+'.py') for module,_ in VERSION_BUILDERS.values()})
    closure=_module_closure(seeds)
    declared={}
    payloads={'assetforge/__init__.py':b'',
              'assetforge/benchmark_factory/__init__.py':b'',
              'functional_examples.json':json.dumps(examples,ensure_ascii=False).encode(),
              'asset_definitions.json':json.dumps(definitions,ensure_ascii=False).encode(),
              'catalog.json':json.dumps(catalog,ensure_ascii=False).encode()}
    for path,data in sorted(closure.items()):
        relative=str(path.relative_to(ROOT))
        payloads[relative]=data
        if path.suffix=='.py':
            package_name=relative[:-3].replace('/','.')
            if path.parent==factory:
                flat=path.name
            else:
                flat=path.name
            payloads[flat]=_flat_shim(package_name)
            declared[relative]={'sha256':hashlib.sha256(data).hexdigest(),'flat_alias':flat}
    for example in examples:
        for ref in example.get('references', []):
            raw=(ROOT/ref['path']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=ref['sha256']:raise ValueError('native example bytes changed')
            payloads[ref['path']]=raw
    for ref in catalog.get('dependencies', [])+catalog.get('review_context_dependencies', [])+[row[key] for row in catalog['assets'] for key in ('definition','description','implementation')]:
        if ref.get('frozen_content'):
            frozen=ref['frozen_content'];raw=(ROOT/frozen['path']).read_bytes()
            if hashlib.sha256(raw).hexdigest()!=ref['sha256'] or frozen['sha256']!=ref['sha256']:
                raise ValueError('frozen source content drift')
            payloads[ref['path']]=raw
            payloads[frozen['path']]=raw
    payloads['source_binding.json']=json.dumps({
        'note':'package-layout files carry the declared implementation bytes; flat names are aliases',
        'package_layout_overrides': ['assetforge/__init__.py',
                                     'assetforge/benchmark_factory/__init__.py'],
        'declared_implementations':declared},ensure_ascii=False,indent=1).encode()
    return payloads,{'note':'declared == imported implementation closure','files':declared}


def _missing_dependency(what, hint):
    """Raise one explanatory error instead of a raw ImportError from inside a function."""
    raise SystemExit(
        f"this entry point needs {what}, which is deployment infrastructure and is not part "
        f"of this repository. {hint}"
    )


def main():


    (ROOT/'POLICY.md').read_text();os.umask(0o077)
    p=argparse.ArgumentParser();p.add_argument('--validation',type=Path,required=True)
    p.add_argument('--validation-sha256',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--preflight',action='store_true')
    p.add_argument('--prior-review',type=Path)
    p.add_argument('--prior-review-sha256')
    p.add_argument('--sandbox-preflight',action='store_true',
                   help='provision the native sandbox, upload every payload and verify digests; zero provider calls')
    args=p.parse_args()
    from assetforge.pipeline.construction_assets import load_catalog,immutable_write,digest
    from assetforge.pipeline.construction_manifest import reference,bound
    raw=args.validation.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.validation_sha256:raise ValueError('native validation drift')
    validation=json.loads(raw);catalog=load_catalog(bound(validation['catalog']),validation['catalog']['sha256'])
    if not validation['native_checks_passed'] or len({r['context'] for r in validation['examples']})<2:
        raise ValueError('two different native functional contexts required')
    examples=[]
    for row in validation['examples']:
        example=json.loads(bound(row['example']).read_text());native=json.loads(bound(row['native_results']).read_text())
        if not native['strict_pass']:raise ValueError('functional native execution incomplete')
        examples.append({'example':example,'native':native,'references':[row['example'],row['native_results']]})
    if bool(args.prior_review)!=bool(args.prior_review_sha256):raise ValueError('prior review path and hash must be paired')
    prompt_path=ROOT/('assetforge/artifacts/reviewer_prompts/construction_asset_reviewer_v5_20260913.md'
                      if args.prior_review else 'assetforge/artifacts/reviewer_prompts/construction_asset_reviewer_v4_20260913.md')
    instructions=prompt_path.read_text()
    definitions=[dict(item,description=(ROOT/item['description']['path']).read_text(),
                      definition=json.loads((ROOT/item['definition']['path']).read_text())) for item in catalog['assets']]
    out=args.output.resolve();out.relative_to(ROOT/'assetforge/runs');out.mkdir(parents=True,exist_ok=False)
    import fcntl
    owner=(out/'owner.lock').open('a');fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
    inputs={'validation':reference(args.validation),'catalog':validation['catalog'],'prompt':reference(prompt_path),
            'implementation':reference(Path(__file__))}
    if args.prior_review:inputs['prior_review']={'path':str(args.prior_review.relative_to(ROOT) if args.prior_review.is_absolute() else args.prior_review),'sha256':args.prior_review_sha256}
    immutable_write(out/'owner.json',{'owner':'codex-root','pid':os.getpid(),'inputs':inputs,
        'stop_condition':'One review,300 model responses (=200 + 50% margin),5400seconds/request (=3600 + 50%); sandbox closed in finally',
        'preflight':args.preflight,'qa_release_permission':False})
    first=examples[0]['example']['source']
    task={'task_id':'asset-functional-native-view','migration_target_commit':'frozen-release-commit',
          'prompt':[{'role':'user','content':first['task_instruction']}],
          'info':{'initial_state':first['initial_state'],'assertions':first['assertions'],'tool_names':[]}}
    immutable_write(out/'candidate.json',task)
    try:
        from assetforge.pipeline.native_review_sandbox import NativeReviewCodeExecTool, REMOTE
    except Exception:
        _missing_dependency(
            "the sandboxed native reviewer",
            "It is deployment infrastructure for reviewing on a live runtime; supply it with "
            "your runtime build.")
    from assetforge.tools import run_agentic_markdown_reviewer as r
    # The native sandbox backend needs the approved local LBG credentials.  They live in the
    # approved config file (unified_benchmark_eval/.env) and are injected with setdefault, so an
    # explicit empty HTTP_PROXY/HTTPS_PROXY in this process stays authoritative.  Credentials are
    # never printed, copied into the run directory or committed.
    sys.path.insert(0,str(ROOT/'unified_benchmark_eval'))
    from ube.env import load_env_file
    load_env_file()
    # The sandbox payload must be the *complete* import closure of every declared asset
    # implementation.  Two earlier reviews rejected 1.1.0/1.2.0 with ModuleNotFoundError only
    # because the new implementation modules were never uploaded, and the 1.0.1 revisions were
    # judged against `construction_assets.py` instead of the module the catalog declared.
    payloads,declared=_sandbox_payloads(catalog,examples,definitions)
    payloads[validation['catalog']['path']]=bound(validation['catalog']).read_bytes()
    payloads[reference(args.validation)['path']]=raw
    for name in ('validation_implementation','role_evidence_validator'):
        ref=validation.get(name)
        if ref:
            raw_source=bound(ref.get('frozen_content') or ref).read_bytes()
            if hashlib.sha256(raw_source).hexdigest()!=ref['sha256']:raise ValueError('validation source snapshot differs')
            payloads[ref['path']]=raw_source
    if args.prior_review:
        prior_payloads,delta=prior_review_material(args.prior_review,args.prior_review_sha256,catalog)
        payloads.update(prior_payloads)
        immutable_write(out/'prior_review_delta.json',delta)
    class AssetSandbox(NativeReviewCodeExecTool):
        def prepare(self):
            super().prepare()
            if getattr(self,'_assets_ready',False):return
            sandbox=self._get_or_create_sandbox()
            import gzip,io,tarfile
            hashes={name:hashlib.sha256(data).hexdigest() for name,data in payloads.items()}
            archive_payloads=dict(payloads,**{'asset_payload_hashes.json':json.dumps(hashes).encode()})
            buffer=io.BytesIO()
            with tarfile.open(fileobj=buffer,mode='w') as archive:
                for name,data in sorted(archive_payloads.items()):
                    if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('unsafe review payload path')
                    member=tarfile.TarInfo(name);member.size=len(data);member.mode=0o444;member.mtime=0
                    archive.addfile(member,io.BytesIO(data))
            archive=gzip.compress(buffer.getvalue(),mtime=0)
            sandbox._upload(archive,REMOTE+'/asset_payloads.tar.gz',timeout=120)
            unpack=sandbox.run_shell('cd '+shlex.quote(REMOTE)+' && tar -xzf asset_payloads.tar.gz',timeout=120)
            if unpack.exit_code:raise ValueError('asset payload archive extraction failed')
            code=('import hashlib,json,pathlib; expected=json.loads(pathlib.Path("asset_payload_hashes.json").read_text())'
                  +'; assert all(hashlib.sha256(pathlib.Path(k).read_bytes()).hexdigest()==v for k,v in expected.items())'
                  +'; import importlib; m=importlib.import_module("assetforge.pipeline.construction_assets")'
                  +'; import construction_assets as flat; assert flat.linking is m.linking'
                  +'; import jsonschema'
                  +'; catalog=json.loads(pathlib.Path("catalog.json").read_text())'
                  +'; [importlib.import_module(row["implementation"]["path"][:-3].replace("/",".")) for row in catalog["assets"]]'
                  +'; examples=json.loads(pathlib.Path("functional_examples.json").read_text())'
                  +'; assert all(m.construct(row["example"]["blueprint"],catalog)==row["example"]["construction"] for row in examples)'
                  +'; print("asset payload verified", m.__file__, jsonschema.__name__, len(catalog["assets"]))')
            result=sandbox.run_shell('cd '+shlex.quote(REMOTE)+'\nPYTHONPATH='+shlex.quote(REMOTE)
                                     +' python3 -c '+shlex.quote(code),timeout=120)
            if result.exit_code:
                raise ValueError('independent asset upload digest verification failed: '
                                 + str(result.stdout)[-800:] + str(result.stderr)[-1200:])
            immutable_write(out/'asset_sandbox.json',{'source_hashes':hashes,'passed':True,'sandbox_id':sandbox.sandbox_id,
                'import_check':str(result.stdout)[-400:]})
            immutable_write(out/'declared_implementations.json',declared)
            self._assets_ready=True
    index=[{'asset_id':row['id']+'@'+row['version'],'applications':row.get('applications'),
            'description_path':row['description']['path'],'definition_path':row['definition']['path'],
            'implementation_path':row['implementation']['path']} for row in catalog['assets']]
    prompt=instructions+'\n\nAsset catalog (first read these ASSET.md files in batches via code_exec):\n'+json.dumps(index,ensure_ascii=False)
    prompt+='\n\nThe native-evidence index is at '+reference(args.validation)['path']+'; it covers '+str(len(examples))+' distinct asset/adapter/context inputs.'
    prompt+=' All inputs and the real call/scoring results are also in functional_examples.json, and the original files are provided. The catalog is a lookup entry point; it does not replace reading in full and executing independently.'
    immutable_write(out/'input_binding.json',dict(inputs,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest()))
    if args.preflight:
        print(json.dumps({'preflight_passed':True,'provider_calls':0,'assets':len(definitions)}));return
    if args.sandbox_preflight:
        tool=AssetSandbox(item_id=out.name,registry_path=out/'sandbox_registry.jsonl',timeout=600,
            provisioning_receipt=out/'native_sandbox.json',candidate_path=out/'candidate.json',
            candidate_sha256=reference(out/'candidate.json')['sha256'])
        try:
            tool.prepare()
            print(json.dumps({'sandbox_preflight_passed':True,'provider_calls':0,
                              'payloads':len(payloads),'assets':len(definitions)},ensure_ascii=False))
        finally:
            tool.close()
        return
    from assetforge.pipeline.turn_journal import JournalIdentity,TurnJournal
    from assetforge.pipeline.multiturn_author_journal import MultiturnAuthorJournalBridge
    try:
        from assetforge.tools.run_multiturn_agentic_qa_author import ProviderCallDeadline
    except Exception:
        _missing_dependency(
            "the agent-runner deadline helper",
            "Use the packaged Author runner instead: python -m assetforge.tools.run_author.")
    # Journal identity must name the model that actually runs.  The legacy constants below point at
    # the provider_a/provider_b chain, which the operator forbids for new work; in capture mode the identity
    # therefore follows the capture primary route.
    if os.environ.get('CAPTURE_ONLY')=='1':
        from assetforge.pipeline import capture_model_routes as _capture
        _order=_capture.resolve(r.get_model_config)[1]
        _primary=_order[0]
        _alias,_model=_capture.ALIASES[_primary],_capture.MODELS[_primary]
    else:
        _alias,_model=r.ALIAS,r.MODEL
    identity=JournalIdentity(run_id=out.name,model_alias=_alias,model_name=_model,domain='construction_asset_review',
                             task_id=out.name,trial_index=0,config_sha256=digest(inputs))
    journal=TurnJournal(out/'journals',identity,attempt_index=0);bridge=MultiturnAuthorJournalBridge(journal)
    deadline=ProviderCallDeadline(5400)
    def before(**kwargs):
        import shutil
        waiting=time.monotonic()
        while shutil.disk_usage(ROOT).free < 10*1024**3:
            if time.monotonic()-waiting>3600:raise RuntimeError('data disk remained below 10GiB for bounded resource wait')
            time.sleep(5)
        deadline.arm(kwargs['turn_index']);return bridge.pre_model_call(**kwargs)
    def trace(value):
        try:bridge.provider_trace(value)
        finally:deadline.disarm()
    adapter=r.pure_tool_adapter
    # The harness module must be built for the model that will actually run.  Leaving the legacy
    # alias here made the adapter resolve the forbidden provider_a route even when the call list and the
    # journal identity had already switched to the capture-only chain.
    _module_alias = _alias if os.environ.get('CAPTURE_ONLY')=='1' else r.PRIMARY_ALIAS
    module=adapter._load_source_module(_module_alias,5400,0,out/'tool_timings',python_tool_factory=None,
        generation_temperature=None,pre_model_call_hook=before,responses_trace_callback=trace)
    if os.environ.get('CAPTURE_ONLY')=='1':
        # The operator forbids provider_a/provider_b GPT and model_b routes for new work, so the asset review
        # must use the same capture-only chain as the migration reviewer: the approved capture model,
        # approved capture models.  A review that silently fell back to a legacy provider route
        # was stopped and receipted on 2026-09-12.
        from assetforge.pipeline import capture_model_routes as capture
        (primary,secondary,fallback),order=capture.resolve(r.get_model_config)
        capture_provider=lambda cfg: str(getattr(cfg,'alias','')) in (capture.ALIASES['capture_2'],capture.ALIASES['capture_3'])
        def make(cfg,label):
            if capture_provider(cfg):
                return r.build_ube_responses_fallback_call(adapter=adapter,config=cfg,timeout=5400,
                    item_id=out.name+'-'+label,trace_callback=trace,tool_choice='auto')
            return r.build_streaming_responses_fallback_call(config=cfg,timeout=5400,
                item_id=out.name+'-'+label,trace_callback=trace,tool_choice='auto')
        pairs=[(make(primary,capture.NAMES[0]),capture.PROVIDERS[order[0]]),
               (make(secondary,capture.NAMES[1]),capture.PROVIDERS[order[1]]),
               (make(fallback,capture.NAMES[2]),capture.PROVIDERS[order[2]])]
    else:
        mog8,sol,mog6=r.resolve_mog_xhigh_routes(r.get_model_config)
        pairs=[(r.build_streaming_responses_fallback_call(config=sol,timeout=5400,item_id=out.name+'-sol',trace_callback=trace,tool_choice='auto'),'provider_a'),
               (r.build_ube_responses_fallback_call(adapter=adapter,config=mog8,timeout=5400,item_id=out.name+'-mog8',trace_callback=trace),'provider_b'),
               (r._build_mog6_call(config=mog6,timeout=5400,item_id=out.name+'-mog6',trace_callback=trace),'provider_b')]
    calls=[r._with_shared_provider_admission(call,provider=provider,timeout=5400,event_sink=journal.append_provider_event)
           for call,provider in pairs]
    module.call_glm5=r.StickyOperationalFallbackChain(calls=tuple(calls),attempts_per_route=3,retry_sleep_seconds=2,
        result_validator=r.require_nonempty_react_response)
    # 30 rounds ended the previous run with complete=false and no verdict (30 provider calls, no final
    # reply), so the reviewer budget carries the operator-authorised +50% margin.
    module._MAX_TOOL_ROUNDS=300
    previous=module._SAVE_TRAJECTORY_SNAPSHOT
    def observe(messages):previous(messages);bridge.observe(messages)
    module._SAVE_TRAJECTORY_SNAPSHOT=observe
    tool=AssetSandbox(item_id=out.name,registry_path=out/'sandbox_registry.jsonl',timeout=600,
        provisioning_receipt=out/'native_sandbox.json',candidate_path=out/'candidate.json',
        candidate_sha256=reference(out/'candidate.json')['sha256'])
    r._apply_v2_toolset(module,tool)
    started=time.time();error=None;output={}
    try:
        deadline.install();output=module.forward(None,None,None,{'id':out.name,'problem':prompt})
    except Exception as exc:error=exc
    finally:deadline.close();tool.close()
    messages=output.get('messages') or bridge.messages;memo=str(output.get('raw_answer') or '')
    immutable_write(out/'trajectory.json',messages)
    decision=None
    # A review memo must end with a fenced JSON decision, but two real runs produced the same object
    # unfenced (or inside a plain ``` block).  Parsing every fenced block AND the last decodable
    # JSON object keeps a correct independent decision from being discarded as "no decision".
    candidates=list(re.findall(r'```(?:json)?\s*\n(.*?)```',memo,re.S))
    decoder=json.JSONDecoder()
    for position in [m.start() for m in re.finditer(r'\{',memo)]:
        try:
            value,_=decoder.raw_decode(memo[position:])
        except ValueError:
            continue
        if isinstance(value,dict) and 'asset_decisions' in value:
            candidates.append(json.dumps(value,ensure_ascii=False))
            break
    for block in candidates:
        try:
            value=json.loads(block)
            if isinstance(value,dict) and 'asset_decisions' in value:decision=value
        except ValueError:pass
    from assetforge.pipeline.asset_review_decisions import normalize_decisions
    stop_reason=str(output.get('forward_stop_reason') or '')
    # Completion is judged by what the reviewer actually produced, not by a single harness stop
    # string: three consecutive real runs ended with a complete, per-asset decision in the last
    # assistant memo while `forward_stop_reason` was something other than
    # 'no_tool_calls_with_reply', so an exact-string gate silently discarded finished reviews.
    # The substantive requirements stay: no operational error, a provisioned+verified asset sandbox,
    # a final assistant memo, and exactly one accept/reject with a reason for every catalog asset.
    last_role=str(messages[-1].get('role') or '') if messages else ''
    decision_error=None
    try:
        normalize_decisions(decision,catalog)
        decisions_present=True
    except ValueError as exc:
        decisions_present=False
        decision_error=str(exc)
    valid=(error is None and last_role=='assistant' and (out/'asset_sandbox.json').exists()
           and decisions_present)
    completion_basis={'stop_reason':stop_reason,'last_message_role':last_role,
                      'decisions_present':decisions_present,'sandbox':(out/'asset_sandbox.json').exists(),
                      'exact_stop_reason_required':False,
                      'decision_identity':'asset_id_and_version',
                      'decision_error':decision_error}
    if error:failure={'type':type(error).__name__}
    else:failure=None
    if bridge.started and not journal.seal_path.exists():
        bridge.observe(messages)
        journal.complete_turn(step=max(1,bridge.turn_index+1),state={},trace=bridge.trace,messages=bridge.messages,
                              terminal=True,safe_resume=False)
        seal=journal.seal_completed({'status':'completed' if valid else 'failed','asset_decisions':decision,
                                     'trajectory_sha256':digest(messages)})
    else:seal=journal.seal_path
    immutable_write(out/'final.json',{'owner':'codex-root','complete':valid,'inputs':inputs,'decision':decision,
        'completion_basis':completion_basis,
        'completion_seal':reference(seal) if seal.exists() else None,
        'trajectory':reference(out/'trajectory.json'),'elapsed_seconds':time.time()-started,'error':failure,
        'actual_provider_calls':len([e for e in journal.provider_events() if e.get('event_type')=='request_started']),
        'qa_accepted':False,'released':False})
    (out/'review.md').write_text(memo)
    if not valid:raise RuntimeError('asset review did not complete; original evidence retained')
    print(json.dumps({'complete':True,'decision':decision,'qa_released':False},ensure_ascii=False))

if __name__=='__main__':main()
