"""Reject missing Russian UI keys or changed interpolation parameters."""
import json
from pathlib import Path
import re
from common import ROOT

project=json.loads((ROOT/'.avx1/project.json').read_text('utf-8'))['id']
paths={
 'webui':('src/lib/i18n/locales/en-US/translation.json','src/lib/i18n/locales/ru-RU/translation.json'),
 'desktop':('src/renderer/src/lib/i18n/locales/en-US/translation.json','src/renderer/src/lib/i18n/locales/ru-RU/translation.json'),
 'conduit':('lib/l10n/app_en.arb','lib/l10n/app_ru.arb')
}
if project not in paths:
    print('Terminal UI is localized in its host applications; command output is unchanged.')
    raise SystemExit(0)
en,ru=[json.loads((ROOT/path).read_text('utf-8')) for path in paths[project]]
allow=json.loads((ROOT/'.avx1/locale-allowlist.json').read_text('utf-8'))
checked=0
for key,source in en.items():
    if key.startswith('@') or not isinstance(source,str):continue
    if project=='webui' and not source:source=key
    target=ru.get(key)
    if not isinstance(target,str) or not target.strip():raise RuntimeError('Missing Russian UI string: '+key)
    expression=r'\{\{\s*([^{}]+?)\s*\}\}' if project!='conduit' else r'\{([A-Za-z_]\w*)\}'
    if project=='conduit' and en.get('@'+key,{}).get('placeholders'):
        names=set(en['@'+key]['placeholders'])
        if set(ru.get('@'+key,{}).get('placeholders',{}))!=names or any(not re.search(r'\{'+re.escape(name)+r'\s*[,}]',target) for name in names):
            raise RuntimeError('Russian ICU parameters changed: '+key)
    elif set(re.findall(expression,source))!=set(re.findall(expression,target)):
        raise RuntimeError('Russian interpolation mismatch: '+key)
    visible=re.sub(expression,'',source)
    if source==target and re.search('[A-Za-z]',visible) and allow.get(key)!=source:
        raise RuntimeError('Unreviewed English UI string: '+key)
    checked+=1
print('RUSSIAN_LOCALE_KEYS_AND_PARAMETERS_VERIFIED='+str(checked))
