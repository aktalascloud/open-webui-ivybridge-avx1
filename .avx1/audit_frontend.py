"""Check npm advisories against the static frontend shipped in the wheel."""
import json
import re
from zipfile import ZipFile

from common import ROOT, WORK, run, write_json


REMOTE_FORM_DOS = 'https://github.com/advisories/GHSA-3r8g-jcqq-3p5j'
PICOMATCH_DOS = 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf'
PICOMATCH_BUILD_CHAIN = {
    '@sveltejs/kit', '@sveltejs/vite-plugin-svelte', '@sveltejs/vite-plugin-svelte-inspector',
    'fdir', 'picomatch', 'tinyglobby', 'vite',
}


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


def excludes_picomatch(wheel):
    frontend = 'open_webui/frontend/'
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        chunks = {name for name in names if name.startswith(frontend + '_app/') and name.endswith('.js')}
        maps = {name + '.map' for name in chunks if name + '.map' in names}
        if not maps:
            return False
        for name in chunks:
            if name + '.map' not in maps and not re.fullmatch(
                r'open_webui/frontend/_app/immutable/assets/(basis_transcoder|draco_decoder|draco_wasm_wrapper)\.[\w-]+\.js', name
            ):
                return False
        for name in names:
            if not name.startswith(frontend):
                continue
            if name.endswith('.js.map'):
                sources = json.loads(archive.read(name)).get('sources', [])
                if any('picomatch/' in source.replace('\\', '/') for source in sources):
                    return False
            elif name.endswith(('.js', '.mjs')) and b'picomatch' in archive.read(name).lower():
                return False
    return True


def audit(wheel, environment):
    report = json.loads(run('npm', 'audit', '--omit=dev', '--audit-level=none', '--json',
                            env=environment, capture=True).stdout)
    write_json(WORK / 'npm-audit.json', report)
    counts = report['metadata']['vulnerabilities']
    high = {name: finding for name, finding in report['vulnerabilities'].items()
            if finding['severity'] in ('high', 'critical')}
    if not high and not counts['high'] and not counts['critical']:
        return {'status': 'passed', 'scope': 'no high or critical findings'}
    expected = {'@sveltejs/kit': REMOTE_FORM_DOS, 'picomatch': PICOMATCH_DOS}
    findings = {(name, item['url']) for name, finding in high.items() for item in finding['via']
                if isinstance(item, dict) and item['severity'] in ('high', 'critical')}
    if (findings and findings <= expected.items() and counts['high'] == len(high)
            and not counts['critical'] and set(high) <= PICOMATCH_BUILD_CHAIN
            and ('picomatch' in high or set(high) == {'@sveltejs/kit'})
            and reviewed_static_scope(wheel)):
        # SvelteKit's remote form server is absent. Picomatch is used only by the
        # build chain, and the wheel must exclude it from the emitted modules.
        if 'picomatch' not in high or (('picomatch', PICOMATCH_DOS) in findings and excludes_picomatch(wheel)):
            return {'status': 'passed with applicability review', 'advisories': sorted(url for _, url in findings),
                    'scope': 'static adapter wheel; no remote form server or bundled picomatch'}
    raise RuntimeError('Unresolved high or critical frontend advisory')
