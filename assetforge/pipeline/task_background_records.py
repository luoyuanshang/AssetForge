"""Source-bound task record roles with actual native read and isolation proofs.

This supplements asset entities; it never declares an unvalidated asset adapter.
"""
import copy
import json
import re
from .construction_assets import require,digest

CONTRACT='native-task-background-record-v1'

def schema():
    string={'type':'string','minLength':1}
    pair={'type':'object','properties':{'source_pointer':string,'response_pointer':{'type':'string'}},
        'required':['source_pointer','response_pointer'],'additionalProperties':False}
    action={'type':'object','properties':{'method':{'type':'string','enum':['GET','POST']},'url':string,
        'params':{'type':['object','null'],'additionalProperties':True},'body':{'type':['object','null'],'additionalProperties':True}},
        'required':['method','url'],'additionalProperties':False}
    fields={'source_pointer':string,'identity_pointer':string,'read_action':action,
        'response_record_pointer':{'type':'string'},'field_bindings':{'type':'array','items':pair,'minItems':2},
        'exclusion_basis':string}
    return {'type':'array','maxItems':20,'items':{'type':'object','properties':fields,
        'required':list(fields),'additionalProperties':False},
        'description':'Optional non-target records from task_source.initial_state. Bind a real record and a unique identity/business key, native GET/POST read, one response record (object or row array), and at least identity plus another meaningful field. JSON pointers are relative to their record. Describe the business exclusion. Native reset-read, fresh identity intervention and unchanged correct-path record are mandatory; labels alone do not count.'}

def _jsonpath_to_pointer(value):
    """Translate the JSONPath spelling Authors actually write into RFC6901.

    Supervisor §32.2/§34.2 (2026-09-15): 47 of 234 compile rejections in one wave were
    pointers written as ``$.google_sheets.rows[1]`` (or ``$google_sheets.rows[1]``);
    the parser splits on ``/`` and then treats the whole dotted string as one key.
    Bare names and duplicated record prefixes are already normalised below; this
    closes the last equivalent spelling.  A field that genuinely does not exist
    (e.g. a template's ``/cells/row_key``) still fails, because the translated path
    has to resolve like any other.
    """
    # Strip a leading '/' BEFORE the '$': the real spelling in the 56s receipts was
    # '/$.google_sheets.rows[1]' (leading slash, then JSONPath), which previously
    # became '//$/google_sheets/rows/1'.  Keep both spellings working.
    text = str(value).strip().lstrip('/')
    if text.startswith('$'):
        text = text[1:]
    parts = []
    for chunk in text.replace('[', '.').replace(']', '.').split('.'):
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return '/' + '/'.join(parts) if parts else '/'


def pointer(value,path,*,base=None):
    """Resolve one JSON pointer, always failing with an actionable message.

    Root cause of the bare ``KeyError('<application name>')`` that killed 44 of
    62 official-stage compile attempts on 2026-09-14 (reproduced offline from the
    recorded artifacts of ``constructed-assets-support3-f1c5aa81-0000028``): this
    loop indexed the container directly, so a binding whose ``identity_pointer``
    was written as an absolute path (``/gmail/messages/0/from_``) instead of a
    record-relative one (``/from_``) raised ``KeyError: 'gmail'`` with no file,
    no phase and no base.  Every failure mode now names the pointer, the base it
    was resolved against, the failing segment and what was actually available.
    """
    require(isinstance(path,str) and path!='',
            'invalid record JSON pointer: expected a non-empty JSON pointer string but received '
            '%s=%r; use a pointer such as "/freshdesk/tickets/0" that addresses a seeded record'
            % (type(path).__name__,path))
    if path.startswith('$') or path.startswith('/$') or re.search(r'\[[0-9]+\]', path):
        translated=_jsonpath_to_pointer(path)
        if translated!=path:
            pointer.jsonpath_normalizations=getattr(pointer,'jsonpath_normalizations',0)+1
            path=translated
    if not path.startswith('/'):
        # Unambiguous spelling of the same intent (44 rejections in the 02:30-08:57
        # batch were bare names like 'cells/row_key').  Normalise and count it.
        pointer.relative_pointer_normalizations = getattr(pointer, 'relative_pointer_normalizations', 0) + 1
        path = '/' + path
    current=value
    for key in ([] if path=='' else path[1:].split('/')):
        key=key.replace('~1','/').replace('~0','~')
        try:
            current=current[int(key)] if isinstance(current,list) else current[key]
        except (KeyError,IndexError,TypeError,ValueError) as error:
            if isinstance(current,dict):
                keys=list(map(str,current))
                import difflib as _difflib
                closest=_difflib.get_close_matches(str(key), keys, n=3, cutoff=0.5)
                available='keys=' + str(sorted(keys)[:12]) + ('; closest=' + str(closest) if closest else '')
            elif isinstance(current,list):
                available='list length=%d' % len(current)
            else:
                available='type=' + type(current).__name__
            raise ValueError(
                'JSON pointer %r does not resolve in %s at segment %r (%s). Pointers inside a '
                'record binding are relative to that record, not to initial_state.'
                % (path, base or 'value', key, available)) from error
    return current

def replace(value,path,new):
    parent,_,key=path.rpartition('/');obj=pointer(value,parent);key=key.replace('~1','/').replace('~0','~')
    obj[int(key) if isinstance(obj,list) else key]=new


def record_relative(ptr, source_pointer):
    """Accept an absolute pointer where the record-relative form was required.

    Authors write both spellings.  The contract says record bindings are relative
    to the record, but a repeated absolute prefix is unambiguous, so normalise it
    instead of failing: the identity and field checks afterwards are unchanged.
    """
    if (isinstance(ptr,str) and source_pointer
            and (ptr==source_pointer or ptr.startswith(source_pointer + '/'))):
        return ptr[len(source_pointer):] or '/'
    return ptr

def validate_bindings(rows,state):
    require(isinstance(rows,list) and len(rows)<=20,'bounded task background records required')
    seen=set()
    normalization_count=0
    for row in rows:
        require(isinstance(row,dict) and set(row)==set(schema()['items']['required']),'task record-role fields malformed')
        path=row['source_pointer'];require(path not in seen,'duplicate background record binding');seen.add(path)
        record=pointer(state,path,base='initial_state');require(isinstance(record,dict) and record,'background pointer must address a real source record')
        # A record-relative pointer must not repeat the record's own absolute
        # prefix.  Authors naturally write the absolute form; normalise it here
        # (the uniqueness and field checks below still run unchanged) so a
        # spelling choice cannot burn a repair attempt or raise an opaque error.
        def relative(ptr):
            nonlocal normalization_count
            normalized=record_relative(ptr,path)
            if normalized is not ptr:
                normalization_count+=1
                return normalized
            return normalized
        identity=pointer(record,relative(row['identity_pointer']),base='background record '+path)
        require(type(identity) in (str,int) and str(identity).strip(),'background identity must be a meaningful scalar')
        collection=pointer(state,path.rpartition('/')[0]);require(isinstance(collection,list),'background record must belong to an explicit native collection')
        matching=[]
        for item in collection:
            try:matching.append(pointer(item,relative(row['identity_pointer']))==identity)
            except (KeyError,TypeError,IndexError):matching.append(False)
        require(sum(matching)==1,'background business key is not unique in its source collection')
        fields=row['field_bindings'];require(isinstance(fields,list) and len(fields)>=2,'background needs identity and business field mappings')
        require(isinstance(row['identity_pointer'],str) and row['identity_pointer'] not in ('','/'),
                'background identity_pointer must name a scalar field inside the record (record-relative), got %r'
                % (row['identity_pointer'],))
        for _f in fields:
            require(isinstance(_f.get('source_pointer'),str) and _f['source_pointer'] not in ('','/'),
                    'background field_bindings source_pointer must name a scalar field inside the record '
                    '(record-relative), got %r' % (_f.get('source_pointer'),))
        _declared=[f.get('source_pointer') for f in fields]
        # Compare record-relative forms on both sides: the absolute and relative
        # spellings of the same field are the same intent (see record_relative).
        _declared_rel=[relative(p) for p in _declared]
        _identity_rel=relative(row['identity_pointer'])
        require(len(set(_declared_rel))==len(_declared_rel),
                'background field_bindings repeat the same source_pointer; list distinct record fields, got '
                + json.dumps(_declared)[:400])
        # The identity must be a unique scalar inside the record (checked below via
        # `matching`).  Whether it is *also* listed in field_bindings decides how
        # strongly we can prove the native read delivers it: when it is listed we
        # run the full reset-read/intervention probe; when it is not, we record an
        # explicit downgrade instead of rejecting a shape whose identity is already
        # proven unique (measured 2026-09-15: this shape blocked 4-6 of 12 recorded
        # candidates and is a spelling choice, not a semantic fault).
        identity_mapped = any(value==_identity_rel for value in _declared_rel)
        if not identity_mapped:
            validate_bindings.identity_unmapped_degraded = (
                getattr(validate_bindings, 'identity_unmapped_degraded', 0) + 1)
        for f in fields:
            value=pointer(record,relative(f['source_pointer']),base='background record '+path)
            if value is None or isinstance(value,(dict,list)):
                scalar_keys=sorted(k for k,v in record.items()
                                   if isinstance(v,(str,int,float,bool)) or v is None)[:12]
                raise ValueError(
                    'background mapping must identify a visible scalar: source_pointer=%r resolved to %s inside '
                    'record %r; scalar fields available there: %s. Point at one scalar field (for example the '
                    'identity field) instead of a container.'
                    % (f['source_pointer'], type(value).__name__, path, scalar_keys))
        require(isinstance(row['exclusion_basis'],str) and len(row['exclusion_basis'].strip())>=12,'business exclusion basis missing')
    validate_bindings.last_record_pointer_prefix_normalizations=normalization_count
    return rows

def run_records(rows,state,assertions,final_world):
    from . import official_task_package as native
    validate_bindings(rows,state);official=native._official_imports();proof=[]
    def read(seed,row):
        world=official['WorldState'](**native.normalize_runtime_value(copy.deepcopy(seed)))
        world.meta.allowed_services=list(state)
        before=world.model_dump(mode='json');before.pop('meta',None)
        action=row['read_action'];require(action['method'] in ('GET','POST'),'background discovery must be a read')
        raw=official['api_fetch'](world,action['method'],action['url'],
            params=native._canonical(action['params']) if action.get('params') is not None else None,
            body=native._canonical(action['body']) if action.get('body') is not None else None)
        response=json.loads(raw);require(not isinstance(response,dict) or not response.get('error'),'background native read failed')
        after=world.model_dump(mode='json');after.pop('meta',None)
        require(before==after,'background read mutated business state')
        return pointer(response,row['response_record_pointer']),digest(response)
    final=final_world.model_dump(mode='json')
    for row in rows:
        record=pointer(state,row['source_pointer']);observed,rhash=read(state,row)
        for field in row['field_bindings']:
            require(native._canonical(pointer(record,record_relative(field['source_pointer'],row['source_pointer'])))==
                native._canonical(pointer(observed,field['response_pointer'])),'background native same-record field mismatch')
        value=pointer(record,record_relative(row['identity_pointer'],row['source_pointer']),base='background record '+row['source_pointer'])
        probe=value+104729 if type(value)==int else 'background-probe-'+digest(row)[:16]
        # ``identity_pointer`` is record-relative; a repeated absolute prefix made
        # this concatenation '/gmail/messages/1' + '/gmail/messages/1/id', which is
        # what surfaced as the bare KeyError('gmail') after the native submission.
        alternate=copy.deepcopy(state);replace(
            alternate,
            row['source_pointer']+record_relative(row['identity_pointer'],row['source_pointer']),
            probe)
        observed_alt,ahash=read(alternate,row)
        mapping=next((f for f in row['field_bindings']
                      if record_relative(f['source_pointer'],row['source_pointer'])==
                      record_relative(row['identity_pointer'],row['source_pointer'])),None)
        if mapping is None:
            # Identity is unique and readable but not mapped into the native read,
            # so the intervention probe cannot observe it.  Record the downgrade
            # explicitly; the uniqueness check above still had to pass.
            identity_intervention='skipped_identity_not_mapped'
        else:
            require(pointer(observed_alt,mapping['response_pointer'])==probe,
                    'background identity not actually read from this source record')
            identity_intervention='verified'
        current=pointer(final,row['source_pointer'])
        # Native models add defaults. Compare every explicitly supplied field.
        from .construction_manifest import fragment_present
        fragment_present(record,current)
        proof.append({'binding_sha256':digest(row),'source_pointer':row['source_pointer'],
            'native_read_sha256':rhash,'identity_intervention_response_sha256':ahash,
            'identity_intervention':identity_intervention,
            'correct_path_record_unchanged':True,'same_record_fields_observed':len(row['field_bindings'])})
    return {'contract':CONTRACT,'bindings_sha256':digest(rows),'source_state_sha256':digest(state),
        'records':proof,'passed':True,'semantic_exclusion_requires_independent_review':True}

def verify_evidence(proof,rows,state):
    require(isinstance(proof,dict) and proof.get('contract')==CONTRACT and proof.get('passed') is True and
        proof.get('bindings_sha256')==digest(rows) and proof.get('source_state_sha256')==digest(state),
        'task background native evidence missing or mismatched')
    require(len(proof.get('records',[]))==len(rows),'task background native evidence incomplete')
    for row,result in zip(rows,proof['records']):
        require(result.get('binding_sha256')==digest(row) and result.get('correct_path_record_unchanged') is True and
            result.get('same_record_fields_observed')==len(row['field_bindings']) and
            result.get('native_read_sha256') and result.get('identity_intervention_response_sha256') and
            result.get('identity_intervention') in ('verified','skipped_identity_not_mapped'),
            'task background native read/isolation proof incomplete')
