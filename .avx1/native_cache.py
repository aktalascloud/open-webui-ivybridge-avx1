"""Exact native-only input cache; application changes do not impersonate native builds."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import sysconfig
import importlib.metadata
from common import ROOT,sha256,run,write_json

def toolchain():
    packaging={}
    for name in ('maturin','wheel','pip'):
        try:packaging[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:packaging[name]=None
    return {'image':os.environ.get('ImageVersion',''),'rustc':run('rustc','-Vv',capture=True).stdout.strip(),
            'packaging':packaging,
            'python':sys.version,'abi':sysconfig.get_config_var('SOABI'),'machine':platform.machine(),
            'windows_sdk':os.environ.get('WindowsSDKVersion',''),'vc_tools':os.environ.get('VCToolsVersion',''),
            'environment':{key:os.environ.get(key,'') for key in ('RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','CARGO_PROFILE_RELEASE_LTO',
                'CARGO_PROFILE_RELEASE_CODEGEN_UNITS','CARGO_PROFILE_RELEASE_OPT_LEVEL','CC','CXX','CFLAGS','CXXFLAGS','LDFLAGS')}}

def signature(source,lto,flags,profile):
    descriptor={'toolchain':toolchain(),'source_sha256':source,'lto':lto,'flags':flags,'profile':profile,
                'recipes':{name:sha256(ROOT/'.avx1'/name) for name in ('native_json.py','native_cache.py','common.py','native-policy.json')}}
    return hashlib.sha256(json.dumps(descriptor,sort_keys=True).encode()).hexdigest()

def enabled():
    # The hosted image identity pins its linker/SDK as well as Windows tools.
    # Unknown/custom native wrappers must be freshly qualified instead.
    return bool(os.environ.get('ImageVersion')) and not any(os.environ.get(key) for key in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','PYO3_CONFIG_FILE','CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER'))

def restore(destination,input_hash):
    cache=ROOT/'.avx1-native-cache';receipt=cache/'receipt.json'
    if not receipt.is_file() or cache.is_symlink():return None
    value=json.loads(receipt.read_text('utf-8'))
    if value.get('input_hash')!=input_hash:return None
    for name,digest in value.get('files',{}).items():
        if Path(name).name!=name or not (cache/name).is_file() or (cache/name).is_symlink() or sha256(cache/name)!=digest:return None
    files=value.get('files',{})
    if 'native-build.json' not in files or 'wheel.sha256' not in files or len([n for n in files if n.startswith('orjson-') and n.endswith('.whl')])!=1:return None
    for name in files:shutil.copy2(cache/name,Path(destination)/name)
    result=json.loads((cache/'native-build.json').read_text('utf-8'))
    result.update(native_qualification_reuse=True,native_input_hash=input_hash)
    write_json(Path(destination)/'native-build.json',result)
    return result

def store(destination,input_hash,wheel):
    cache=ROOT/'.avx1-native-cache'
    if cache.is_symlink():raise RuntimeError('Unsafe native cache directory')
    cache.mkdir(exist_ok=True)
    names=[wheel.name,'native-build.json','wheel.sha256']
    for name in names:shutil.copy2(Path(destination)/name,cache/name)
    write_json(cache/'receipt.json',{'input_hash':input_hash,'files':{name:sha256(cache/name) for name in names}})

if __name__=='__main__':
    descriptor=toolchain();key=hashlib.sha256(json.dumps(descriptor,sort_keys=True).encode()).hexdigest()
    with Path(os.environ['GITHUB_OUTPUT']).open('a',encoding='utf-8') as output:
        output.write('key='+key+'\ncacheable='+str(enabled()).lower()+'\n')
