"""Actual native asset checks with separately persisted self-authored inputs."""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))

def main():
    (ROOT/'PROJECT_CONSTRAINTS.md').read_text()
    p=argparse.ArgumentParser();p.add_argument('--catalog',type=Path,required=True)
    p.add_argument('--catalog-sha256',required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    from assetforge.pipeline import release_runtime as release
    from assetforge.pipeline.construction_assets import load_catalog, immutable_write
    from assetforge.pipeline.construction_examples import full_example,execute_example
    from assetforge.pipeline.construction_manifest import reference
    release.require_verified_protocol();catalog=load_catalog(args.catalog,args.catalog_sha256)
    out=args.output.resolve();out.relative_to(ROOT/'assetforge/runs');start=time.monotonic();examples=[]
    if catalog.get('dependency_contract') in ('asset-import-closure-v1', 'asset-construction-closure-v2'):
        from assetforge.pipeline.construction_native_matrix import run_matrix
        result=run_matrix(catalog,reference(args.catalog),out)
        print(json.dumps({'validation':reference(out/'validation.json'),'native_checks_passed':result['native_checks_passed'],
                          'examples':len(result['examples']),'failures':result['failures']},ensure_ascii=False))
        if not result['native_checks_passed']:raise SystemExit(1)
        return
    for context,seed in [('renewal',1709),('hr_training',2901)]:
        example=full_example(context,'asset-admission-'+context,seed,catalog)
        immutable_write(out/context/'example.json',example)
        result=execute_example(example);immutable_write(out/context/'native_results.json',result)
        examples.append({'context':context,'example':reference(out/context/'example.json'),
                         'native_results':reference(out/context/'native_results.json')})
    result={'owner':'codex-root','catalog':reference(args.catalog),'examples':examples,
            'native_checks_passed':True,'provider_calls':0,'independent_semantic_review_complete':False,
            'production_admitted':False,'elapsed_seconds':time.monotonic()-start,'protocol':reference(release.PROTOCOL)}
    immutable_write(out/'validation.json',result);print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
