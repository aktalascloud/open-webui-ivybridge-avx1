"""Catch missing recipe inputs and contradictory dependency pins before compiling."""
import re
import tomllib
from pathlib import Path
root=Path(__file__).resolve().parents[1]
seen={}
for requirement in tomllib.loads((root/'pyproject.toml').read_text('utf-8'))['project']['dependencies']:
    if ';' in requirement:continue
    name=re.match(r'[A-Za-z0-9_.-]+',requirement).group().lower().replace('_','-')
    if name in seen:raise RuntimeError('Duplicate unconditional dependency: '+name)
    seen[name]=requirement
for name in ('Install.cmd','Install.ps1','bench_json.py','test_brotli.py','test_suggestions.mjs','test_frontend_browser.py','test_mcp_compat.py','native_json.py','security_scope.py'):
    if not (root/'.avx1'/name).is_file():raise RuntimeError('Missing build input: '+name)
print('WEBUI_BUILD_INPUTS_AND_DEPENDENCY_NAMES_VERIFIED')
