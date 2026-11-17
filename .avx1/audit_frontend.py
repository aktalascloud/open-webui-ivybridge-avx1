"""Check npm advisories against the static frontend shipped in the wheel."""
import json
from zipfile import ZipFile

from common import ROOT, WORK, run, write_json


REMOTE_FORM_DOS = 'https://github.com/advisories/GHSA-3r8g-jcqq-3p5j'


def reviewed_static_scope(wheel):
    lock = json.loads((ROOT / 'package-lock.json').read_text('utf-8'))
    if lock['packages']['node_modules/@sveltejs/kit']['version'] != '2.70.4':
        return False
    config = (ROOT / 'svelte.config.js').read_text('utf-8')
    layout = (ROOT / 'src/routes/+layout.js').read_text('utf-8')
    if ("import adapter from '@sveltejs/adapter-static';" not in config
            or "fallback: 'index.html'" not in config
            or 'export const ssr = false;' not in layout
            or any('remoteFunctions' in text for text in (config, (ROOT / 'vite.config.ts').read_text('utf-8')))):
        return False
    for path in (ROOT / 'src').rglob('*'):
        if not path.is_file() or path.suffix not in {'.js', '.ts', '.svelte', '.mjs'}:
            continue
        if '.remote.' in path.name or '+server.' in path.name or '.server.' in path.name:
            return False
        if '$app/server' in path.read_text('utf-8'):
            return False
    with ZipFile(wheel) as archive:
        names = archive.namelist()
        return ('open_webui/frontend/index.html' in names
                and not any('node_modules/' in name or '.svelte-kit/' in name
                            or name.startswith('open_webui/frontend/server/') for name in names))


def audit(wheel, environment):
    report = json.loads(run('npm', 'audit', '--omit=dev', '--audit-level=none', '--json',
                            env=environment, capture=True).stdout)
    write_json(WORK / 'npm-audit.json', report)
    counts = report['metadata']['vulnerabilities']
    high = {name: finding for name, finding in report['vulnerabilities'].items()
            if finding['severity'] in ('high', 'critical')}
    if not high and not counts['high'] and not counts['critical']:
        return {'status': 'passed', 'scope': 'no high or critical findings'}
    if set(high) == {'@sveltejs/kit'} and counts['high'] == 1 and not counts['critical']:
        findings = [item['url'] for item in high['@sveltejs/kit']['via']
                    if isinstance(item, dict) and item['severity'] in ('high', 'critical')]
        # The advisory requires a SvelteKit remote-function server. The
        # verified wheel serves static files through Python.
        if findings == [REMOTE_FORM_DOS] and reviewed_static_scope(wheel):
            return {'status': 'passed with applicability review', 'advisory': REMOTE_FORM_DOS,
                    'scope': 'static adapter wheel; no SvelteKit server or remote functions'}
    raise RuntimeError('Unresolved high or critical frontend advisory')
