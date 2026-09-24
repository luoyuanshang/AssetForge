"""Cold production guards; preserve the original frozen manifest consumers."""
import json
from pathlib import Path
from . import construction_assets as assets

def validate_native_obligation_links(manifest, native_regression):
    cases={c['case_id']:c for c in native_regression['result']['native_construction_case_results']['cases']}
    for binding in manifest['bindings']:
        for name in binding['case_ids']:
            case=cases[name]
            if case['expected_strict'] is False:
                assets.require(set(binding['assertion_indices']) & set(case['failed_assertion_indices']),
                    'negative fails a different obligation: '+binding['obligation_id']+'/'+name)

def validate_policy_fixture_links(source,native_regression):
    fixtures=source.get('policy_fixtures') or []
    results=native_regression['result'].get('policy_fixture_results') or []
    assets.require(len(fixtures)==len(results),'policy fixture execution coverage changed')
    for fixture,result in zip(fixtures,results):
        assets.require(result.get('fixture_sha256')==assets.digest(fixture),'policy fixture differs from executed evidence')
        assets.require(result.get('passed') is True and result.get('same_public_instruction') is True and
            result.get('official_scorer_modified') is False,'policy fixture protocol proof incomplete')
        assets.require(result['alternate_correct']['strict_pass'] is True,'alternate policy solution failed')
        for name in ('base_path_in_alternate','alternate_path_in_base'):
            case=result[name]
            assets.require(case['strict_pass'] is False and case['failed_assertion_indices'],
                'policy cross-world negative must fail a business assertion')

def validate_policy_channel_identity(manifest,source):
    """Every policy carrier must be identified by exactly one readable native object.

    The 1.1.0 carrier extension adds `gmail_message_body`, whose identity is the sent message to the
    declared recipient rather than a Slack channel name.  Assuming `channel_name` unconditionally
    raised KeyError for that carrier; the check is now carrier-aware and does not relax the Slack
    rule (one readable channel per declaration, unique names across declarations).
    """
    policies=[row for row in manifest['blueprint']['assets'] if row['id']=='readable_policy_exception']
    channels=source['initial_state'].get('slack',{}).get('channels',[])
    messages=source['initial_state'].get('gmail',{}).get('messages',[])
    slack_names=[]
    for policy in policies:
        parameters=policy['parameters']
        carrier=parameters.get('readable_carrier','slack_topic')
        if carrier=='slack_topic':
            name=parameters['channel_name']
            matches=[channel for channel in channels if channel.get('name')==name]
            assets.require(len(matches)==1,'policy channel name must identify one readable channel: '+name)
            slack_names.append(name)
        elif carrier=='gmail_message_body':
            recipient=parameters['recipient']
            matches=[message for message in messages
                     if recipient in (message.get('to') or []) and 'SENT' in (message.get('label_ids') or [])]
            assets.require(len(matches)==1,
                'gmail policy carrier must identify one readable sent message for: '+recipient)
        else:
            assets.require(False,'unsupported policy carrier: '+str(carrier))
    assets.require(len(set(slack_names))==len(slack_names),
        'composed policy channel names must be unique')

def install():
    from . import construction_manifest as manifest
    from .construction_admission import require_admitted_catalog
    if getattr(manifest,'_production_admission_installed',False):return
    original_load=manifest.load_catalog
    def load(path,sha256):
        catalog=original_load(path,sha256)
        require_admitted_catalog(catalog,manifest.reference(path))
        return catalog
    # Both direct imports and future imports use the same checked loader.
    assets.load_catalog=manifest.load_catalog=load
    original_create=manifest.create_manifest
    def create(**kwargs):
        value=original_create(**kwargs)
        validate_native_obligation_links(value,kwargs['native_regression'])
        validate_policy_fixture_links(kwargs['source'],kwargs['native_regression'])
        validate_policy_channel_identity(value,kwargs['source'])
        value['validator_sources'].append(manifest.reference(Path(__file__)))
        value['content_sha256']=assets.digest({k:v for k,v in value.items() if k!='content_sha256'})
        return value
    original_validate=manifest.validate_manifest
    def validate(value,**kwargs):
        result=original_validate(value,**kwargs)
        validate_native_obligation_links(value,kwargs['native_regression'])
        validate_policy_fixture_links(kwargs['source'],kwargs['native_regression'])
        validate_policy_channel_identity(value,kwargs['source'])
        return result
    manifest.create_manifest=create;manifest.validate_manifest=validate
    manifest._production_admission_installed=True
