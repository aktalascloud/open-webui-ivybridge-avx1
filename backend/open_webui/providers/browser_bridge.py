"""Install only OWUI-owned shared assets; preserve Cline files and registry."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import winreg

import datetime

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha256(path):
    with Path(path).open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()
def write_json(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

ID='jaljomgoclehkemckjhifflhmlllfopc'
HOST='cloud.aktalas.owui_dsw'
VENDORS=('Google/Chrome','Microsoft/Edge','BraveSoftware/Brave-Browser','Vivaldi','Chromium')

def registry_snapshot():
    values={}
    for vendor in VENDORS:
        key='Software\\'+vendor.replace('/','\\')+'\\NativeMessagingHosts\\cloud.aktalas.cline_dsw'
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key) as handle:values[key]=winreg.QueryValue(handle,None)
        except FileNotFoundError:pass
    return hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()

def tree_hash(root):
    if not root.exists():return None
    return hashlib.sha256(json.dumps({str(p.relative_to(root)):sha256(p) for p in root.rglob('*') if p.is_file()},sort_keys=True).encode()).hexdigest()

def install(prepare_only=False):
    source=Path(__file__).resolve().parent/"browser_connector"
    manifest=json.loads((source/'manifest.json').read_text('utf-8'))
    encoded=hashlib.sha256(base64.b64decode(manifest['key'],validate=True)).digest()[:16].hex()
    identity=''.join(chr(97+int(c,16)) for c in encoded)
    if identity!=ID:raise RuntimeError('Shared extension identity differs')
    original=Path(os.environ['LOCALAPPDATA'])/'Cline Desktop AVX1 RU/bin/browser-bridge/extension'
    original_hash=tree_hash(original);registry_hash=registry_snapshot()
    root=Path(os.environ['LOCALAPPDATA'])/'OWUI DeepSeek Browser Bridge'
    if root.is_symlink() or getattr(root,'is_junction',lambda:False)() or root.resolve().parent!=Path(os.environ['LOCALAPPDATA']).resolve():
        raise RuntimeError('Shared bridge installation root differs')
    owner=root/'owner.json'
    if root.exists() and not owner.is_file() and any(root.iterdir()):
        raise RuntimeError('Unmanaged bridge directory preserved')
    root.mkdir(exist_ok=True)
    previous=json.loads(owner.read_text('utf-8')) if owner.exists() else {'owner':'OWUI','files':{}}
    if previous.get('owner')!='OWUI':raise RuntimeError('Bridge directory belongs to another application')
    for relative,expected in previous['files'].items():
        current=root/relative
        if not current.resolve().is_relative_to(root.resolve()) or current.is_symlink():raise RuntimeError('Unsafe managed path')
        if current.exists() and sha256(current)!=expected:raise RuntimeError('User-modified bridge file preserved: '+relative)
    write_json(owner,previous)
    files={}
    for item in source.rglob('*'):
        if not item.is_file() or 'native' in item.relative_to(source).parts:continue
        if item.is_symlink():raise RuntimeError('Shared extension source contains a symlink')
        relative=Path('extension')/item.relative_to(source)
        target=root/relative;target.parent.mkdir(parents=True,exist_ok=True)
        if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):raise RuntimeError('Unsafe extension target')
        if target.exists() and str(relative) not in previous['files'] and sha256(target)!=sha256(item):
            raise RuntimeError('Unmanaged extension file preserved')
        if not target.exists() or sha256(target)!=sha256(item):shutil.copyfile(item,target)
        files[str(relative)]=sha256(target)
    if not prepare_only:
        executable=source/'native/owui-native-host.exe'
        if not executable.is_file() or executable.read_bytes()[:2]!=b'MZ':raise RuntimeError('Qualified native host missing')
        target=root/'native-host.exe';temporary=root/'native-host.pending'
        if temporary.exists() or temporary.is_symlink():raise RuntimeError('Unfinished native-host copy preserved')
        shutil.copyfile(executable,temporary)
        if sha256(temporary)!=sha256(executable):raise RuntimeError('Native host copy differs')
        try:temporary.replace(target)
        except PermissionError:
            temporary.unlink();raise
        files['native-host.exe']=sha256(target)
        registration=root/(HOST+'.json')
        write_json(registration,{'name':HOST,'description':'OWUI explicit DeepSeek account handoff','path':str(target),
                                 'type':'stdio','allowed_origins':['chrome-extension://'+ID+'/']})
        files[registration.name]=sha256(registration)
        for vendor in VENDORS:
            key='Software\\'+vendor.replace('/','\\')+'\\NativeMessagingHosts\\'+HOST
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,key) as handle:winreg.SetValueEx(handle,'',0,winreg.REG_SZ,str(registration))
    else:
        for relative,value in previous['files'].items():
            if not relative.startswith('extension'):files.setdefault(relative,value)
    if tree_hash(original)!=original_hash or registry_snapshot()!=registry_hash:
        raise RuntimeError('Cline assets or registration changed concurrently; review required')
    write_json(owner,{'owner':'OWUI','extension_id':ID,'files':files})
    result={'utc':now(),'status':'prepared' if prepare_only else 'installed','extension_id':ID,
            'extension_folder':str(root/'extension'),'native_host_registered':not prepare_only,
            'cline_files':'unchanged','cline_native_registration':'unchanged','browser_profile':'existing',
            'browser_loaded_extension':'requires one ordinary user installation/reload; not claimed automatically',
            'credential_capture':'not performed'}
    return result

