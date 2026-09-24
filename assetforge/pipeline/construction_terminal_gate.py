"""A native acceptance cannot terminate an unaccepted business composition."""
import json


def install():
    from . import construction_author_tools as tools
    if getattr(tools, '_composition_terminal_gate_installed', False):
        return
    original = tools.package_class

    def package_class(session):
        base = original(session)

        class TerminalBoundPackage(base):
            @property
            def accepted_call_count(self):
                if not session.accepted or not session.bundles:
                    return 0
                return self._snapshot.get('accepted_call_count', 0)

            @property
            def latest_candidate_markdown(self):
                if not session.accepted or not session.bundles:
                    return None
                return self._snapshot.get('latest_candidate_markdown')

            def call(self, params, **kwargs):
                result = json.loads(super().call(params, **kwargs))
                if not result.get('accepted') and result.get('construction_gate'):
                    # A wrapper can reject after native compilation has advanced
                    # the draft. Return its actual revision for the next repair.
                    revision = self._snapshot.get('_draft_revision_sha256')
                    if revision:
                        result['draft_revision_sha256'] = revision
                return json.dumps(result, ensure_ascii=False)

        return TerminalBoundPackage

    tools.package_class = package_class
    tools._composition_terminal_gate_installed = True
