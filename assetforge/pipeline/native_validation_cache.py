"""Reuse immutable proof results only inside one fully bound compile call."""
import copy
from contextvars import ContextVar
from functools import wraps
import hashlib
import json
from pathlib import Path
import time

_scope = ContextVar('native_compile_evidence', default=None)

def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        default=str, separators=(',', ':')).encode()).hexdigest()

def evidence_scope(function):
    @wraps(function)
    def run(self, params, **kwargs):
        from .official_task_package import OFFICIAL_SOURCE_CONTRACT
        directory=Path(__file__).parent
        files=('official_task_package.py','construction_application_roles.py',
               'construction_policy_causality.py','multi_app_policy_dependencies.py',
               'native_validation_cache.py')
        binding=_hash({'submission':params,'draft':getattr(self,'_draft_task_source',None),
            'profile':self._rubric_mechanical_profile,
            'roles':getattr(self,'_construction_role_context',None),
            'protocol':OFFICIAL_SOURCE_CONTRACT,
            'implementation':{f:hashlib.sha256((directory/f).read_bytes()).hexdigest() for f in files}})
        token=_scope.set({'binding':binding,'values':{},'checks':{}})
        try:return function(self,params,**kwargs)
        finally:_scope.reset(token)
    return run

def immutable_proof(function):
    @wraps(function)
    def run(*args,**kwargs):
        scope=_scope.get()
        if scope is None:return function(*args,**kwargs)
        key=_hash([scope['binding'],function.__module__,function.__name__,args,kwargs])
        stats=scope['checks'].setdefault(function.__name__,{'executions':0,'hits':0,'execution_seconds':0.0})
        if key in scope['values']:
            stats['hits']+=1
            return copy.deepcopy(scope['values'][key])
        start=time.monotonic()
        try:result=function(*args,**kwargs)
        finally:
            stats['executions']+=1;stats['execution_seconds']+=time.monotonic()-start
        # Exceptions are never cached; values must be serializable proof data, not worlds.
        json.dumps(result)
        scope['values'][key]=copy.deepcopy(result)
        return copy.deepcopy(result)
    return run

def evidence_statistics():
    scope=_scope.get()
    return ({'contract':'same-compile-immutable-proof-v1','binding_sha256':scope['binding'],
        'checks':copy.deepcopy(scope['checks']),'independent_counterfactual_resets_preserved':True}
        if scope else None)
