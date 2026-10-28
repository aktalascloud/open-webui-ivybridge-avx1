"""Windows-user encrypted provider configuration; no plaintext credential files."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

class _Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]

def transform(value,*,decrypt=False):
    if os.name!='nt':raise RuntimeError('Windows user encryption is required')
    storage=ctypes.create_string_buffer(value);source=_Blob(len(value),ctypes.cast(storage,ctypes.POINTER(ctypes.c_ubyte)))
    target=_Blob();crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    function=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):raise RuntimeError('Provider credential encryption failed')
    try:return ctypes.string_at(target.data,target.size)
    finally:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.LocalFree.argtypes=[wintypes.HLOCAL]
        kernel.LocalFree(ctypes.cast(target.data,wintypes.HLOCAL))

def read_private(path):return json.loads(transform(Path(path).read_bytes(),decrypt=True))
def write_private(path,value):
    path=Path(path);temporary=path.with_suffix('.tmp')
    temporary.write_bytes(transform(json.dumps(value,ensure_ascii=False).encode()))
    temporary.replace(path)
