"""Cold independent-review consumer of external construction manifests."""
import json, os
from pathlib import Path
from .construction_assets import digest, require
from .construction_manifest import load_bundle, reference

def install():
 from .release_receipt_evidence import install as native_install
 reviewer=native_install();original=reviewer.build_packet
 if getattr(original,'_construction_manifest',False):return reviewer
 def build_packet(**kwargs):
  packet,binding=original(**kwargs)
  bundle=os.environ.get('AUTOMATION106_CONSTRUCTION_BUNDLE')
  if bundle:
   values,check=load_bundle(Path(bundle),'review')
   actual=json.loads(kwargs['generated_task_path'].read_text())
   require(digest(actual)==digest(values['task.json']),'Reviewer task differs from bound construction')
   manifest=values['construction_manifest.json']
   binding['construction_manifest']={'manifest':reference(Path(bundle)/'construction_manifest.json'),
       'seal':reference(Path(bundle)/'complete.json'),'validation':check}
   detail={'blueprint':manifest['blueprint'],'bindings':manifest['bindings'],
     'construction':manifest['construction'],'execution_profile':manifest['execution_profile'],
     'expansion':manifest['expansion'],'application_roles':manifest.get('application_roles'),
     'application_role_check':manifest.get('application_role_check'),
     'native_role_evidence_location':'native_result.application_role_native_evidence in the bound reversible native packet'}
   packet+='\n\nConstruction-asset assembly record (for independent review only; not visible to the solver). Check every obligation and the actual task semantics item by item; a local pass never substitutes for a complete review.\n```json\n'+json.dumps(detail,ensure_ascii=False)+'\n```\n'
  return packet,binding
 build_packet._construction_manifest=True;reviewer.build_packet=build_packet
 return reviewer
