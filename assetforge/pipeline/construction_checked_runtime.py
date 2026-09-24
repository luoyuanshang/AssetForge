"""Cold consumers for independently admitted 1.0.1 constructors and their schema."""
from pathlib import Path
from . import construction_checked_assets as checked


def install():
    checked.install()
    from . import construction_manifest as manifest
    from . import construction_stage_admission as admission
    admission.install()
    if getattr(manifest, '_checked_runtime_installed', False):
        return
    paths = [Path(__file__), Path(checked.__file__), checked.legacy.ROOT / checked.CONTRACT_PATH]
    expected = [manifest.reference(p) for p in paths]
    original_create, original_validate = manifest.create_manifest, manifest.validate_manifest

    def create(**kwargs):
        value = original_create(**kwargs)
        value['validator_sources'].extend(expected)
        value['content_sha256'] = checked.legacy.digest({k: v for k, v in value.items() if k != 'content_sha256'})
        return value

    def validate(value, **kwargs):
        checked.legacy.require(all(ref in value['validator_sources'] for ref in expected),
                               'checked constructor/runtime/schema evidence missing')
        return original_validate(value, **kwargs)

    manifest.create_manifest, manifest.validate_manifest = create, validate
    manifest._checked_runtime_installed = True
