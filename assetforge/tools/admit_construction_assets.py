"""Admit accepted immutable assets individually; never publish QA here."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))

def main():
    (ROOT/'PROJECT_CONSTRAINTS.md').read_text()
    p=argparse.ArgumentParser();p.add_argument('--review',type=Path,required=True)
    p.add_argument('--review-sha256',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--review-plan',type=Path);p.add_argument('--review-plan-sha256');args=p.parse_args()
    from assetforge.pipeline.construction_assets import load_catalog,immutable_write,require
    from assetforge.pipeline.construction_manifest import bound,reference
    from assetforge.pipeline.construction_admission import check_asset_admission
    from assetforge.pipeline.asset_review_decisions import normalize_decisions,versioned_id
    ref=reference(args.review);require(ref['sha256']==args.review_sha256,'independent review digest changed')
    review=json.loads(args.review.read_text());validation_ref=review['inputs']['validation']
    validation=json.loads(bound(validation_ref).read_text());catalog=load_catalog(bound(validation['catalog']),validation['catalog']['sha256'])
    decisions=normalize_decisions(review.get('decision'),catalog)
    accepted={key for key,row in decisions.items() if row['decision']=='accept'}
    admitted=[];blocked=[];memo={}
    for asset in catalog['assets']:
        if versioned_id(asset) not in accepted:continue
        asset=dict(asset,admission={'native_validation':validation_ref,'independent_review':ref})
        if args.review_plan:
            plan_ref=reference(args.review_plan);require(plan_ref['sha256']==args.review_plan_sha256,'parallel review plan drift')
            asset['admission']['review_plan']=plan_ref
        try:check_asset_admission(asset,asset['admission'],catalog=catalog,catalog_ref=validation['catalog'],_memo=memo)
        except ValueError as error:
            blocked.append({'asset_id':asset['id'],'version':asset['version'],'reason':str(error)});continue
        admitted.append(asset)
    require(admitted,'no independently accepted assets')
    result=dict(catalog,assets=admitted,production_admitted=True,qa_accepted=False,qa_released=False,
                blocked_asset_admissions=blocked)
    out=args.output.resolve();out.relative_to(ROOT/'assetforge/runs')
    from assetforge.pipeline.asset_catalog_metadata import derive_metadata,verify_catalog_metadata
    correction=derive_metadata(validation_ref)
    correction_path=out.with_name(out.stem+'.capabilities.json');immutable_write(correction_path,correction)
    result['capability_metadata_correction']=reference(correction_path)
    for asset in result['assets']:
        asset.update(correction['assets'][versioned_id(asset)])
    verify_catalog_metadata(result)
    immutable_write(out,result)
    print(json.dumps({'admitted_catalog':reference(out),'admitted_asset_ids':sorted(versioned_id(a) for a in admitted),
                     'blocked_asset_admissions':blocked,'qa_released':0}))

if __name__=='__main__':main()
