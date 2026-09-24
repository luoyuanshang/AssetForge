"""Typed JSON snapshots of already validated, live native WorldState objects.

Initial Author input is still validated by the official model. Restoration uses
only loaded, pinned schema classes and preserves native assignment values without
running model validators a second time. This module never imports a class named
by an input snapshot.
"""
from __future__ import annotations
import base64
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from functools import lru_cache
import hashlib
import json
import sys
from uuid import UUID
from pydantic import BaseModel

CONTRACT='native-world-typed-snapshot-transport-v1'
KEY='__qa_native_world_snapshot__'

@lru_cache(maxsize=1)
def registry():
    result={}
    for name,module in list(sys.modules.items()):
        if not name.startswith(('native_runtime.schema.', 'benchmark.schema.')) or module is None:continue
        for value in vars(module).values():
            if isinstance(value,type) and value.__module__.startswith(('native_runtime.schema.', 'benchmark.schema.')):
                if issubclass(value,(BaseModel,Enum)):
                    result[value.__module__+':'+value.__qualname__]=value
    if not any(k.endswith('schema.world:WorldState') for k in result):
        raise ValueError('pinned native schema classes must be loaded before transport')
    return result

def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def encode(value):
    kind=type(value)
    if isinstance(value,Enum):
        name=kind.__module__+':'+kind.__qualname__
        if registry().get(name) is not kind:raise ValueError('unregistered native enum')
        return ['enum',name,encode(value.value)]
    if value is None or kind in (str,int,float,bool):return value
    if isinstance(value,BaseModel):
        name=kind.__module__+':'+kind.__qualname__
        if registry().get(name) is not kind:raise ValueError('unregistered native model')
        if getattr(value,'__pydantic_extra__',None) or getattr(value,'__pydantic_private__',None):
            raise ValueError('unsupported private or extra native model fields')
        return ['model',name,sorted(value.model_fields_set),
                {key:encode(getattr(value,key)) for key in kind.model_fields}]
    if kind is dict:return ['dict',[[encode(k),encode(v)] for k,v in value.items()]]
    if kind in (list,tuple,set,frozenset):
        values=[encode(v) for v in value]
        if kind in (set,frozenset):values.sort(key=canonical)
        return [kind.__name__,values]
    if kind is datetime:return ['datetime',value.isoformat(),value.fold]
    if kind is date:return ['date',value.isoformat()]
    if kind is time:return ['time',value.isoformat(),value.fold]
    if kind is timedelta:return ['timedelta',value.days,value.seconds,value.microseconds]
    if kind is Decimal:return ['decimal',str(value)]
    if kind is UUID:return ['uuid',str(value)]
    if kind is bytes:return ['bytes',base64.b64encode(value).decode('ascii')]
    raise ValueError('unsupported native snapshot value type: '+kind.__name__)

def decode(value):
    if value is None or type(value) in (str,int,float,bool):return value
    if not isinstance(value,list) or not value or not isinstance(value[0],str):
        raise ValueError('malformed typed native snapshot')
    kind=value[0]
    if kind=='model':
        if len(value)!=4 or not isinstance(value[3],dict):raise ValueError('malformed native model snapshot')
        cls=registry().get(value[1])
        if cls is None or not issubclass(cls,BaseModel) or set(value[3])!=set(cls.model_fields):
            raise ValueError('native schema model or field set drift')
        fields=set(value[2])
        if not fields<=set(cls.model_fields):raise ValueError('native field presence drift')
        return cls.model_construct(_fields_set=fields,**{k:decode(v) for k,v in value[3].items()})
    if kind=='enum':
        cls=registry().get(value[1])
        if cls is None or not issubclass(cls,Enum):raise ValueError('unknown native enum')
        return cls(decode(value[2]))
    if kind=='dict':return {decode(k):decode(v) for k,v in value[1]}
    if kind in ('list','tuple','set','frozenset'):
        values=[decode(v) for v in value[1]]
        return {'list':list,'tuple':tuple,'set':set,'frozenset':frozenset}[kind](values)
    if kind=='datetime':return datetime.fromisoformat(value[1]).replace(fold=value[2])
    if kind=='date':return date.fromisoformat(value[1])
    if kind=='time':return time.fromisoformat(value[1]).replace(fold=value[2])
    if kind=='timedelta':return timedelta(days=value[1],seconds=value[2],microseconds=value[3])
    if kind=='decimal':return Decimal(value[1])
    if kind=='uuid':return UUID(value[1])
    if kind=='bytes':return base64.b64decode(value[1],validate=True)
    raise ValueError('unknown native snapshot tag')

def snapshot(world):
    tree=encode(world)
    return dict(contract=CONTRACT,tree=tree,sha256=hashlib.sha256(canonical(tree).encode()).hexdigest())

def restore(value,world_type):
    if value.get('contract')!=CONTRACT:raise ValueError('native snapshot contract drift')
    tree=value['tree']
    if hashlib.sha256(canonical(tree).encode()).hexdigest()!=value.get('sha256'):
        raise ValueError('native snapshot hash drift')
    world=decode(tree)
    if type(world) is not world_type:raise ValueError('snapshot is not the pinned WorldState')
    return world
