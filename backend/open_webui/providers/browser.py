"""Installed system browser plus an explicitly consented, isolated login connector.

No WebDriver, remote debugging, disabled TLS checks or ordinary-profile scraping.
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
from urllib.parse import quote

def default_browser():
    if os.name!='nt':raise RuntimeError('A local Windows browser is required')
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice') as key:
        progid=winreg.QueryValueEx(key,'ProgId')[0]
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,progid+r'\shell\open\command') as key:
        command=winreg.QueryValueEx(key,'')[0]
    shell=ctypes.WinDLL('shell32',use_last_error=True)
    shell.CommandLineToArgvW.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype=ctypes.POINTER(wintypes.LPWSTR)
    count=ctypes.c_int();argv=shell.CommandLineToArgvW(command,ctypes.byref(count))
    try:executable=Path(argv[0])
    finally:
        kernel=ctypes.WinDLL('kernel32');kernel.LocalFree.argtypes=[wintypes.HLOCAL]
        kernel.LocalFree(ctypes.cast(argv,wintypes.HLOCAL))
    if not executable.is_file() or executable.name.lower() not in {'brave.exe','chrome.exe','msedge.exe','chromium.exe','vivaldi.exe'}:
        raise RuntimeError('The default browser does not support the local account connector')
    return executable

def open_login(root,nonce,port,*,consent):
    if consent is not True:raise PermissionError('Account connector consent is required')
    if len(nonce)!=64 or any(c not in '0123456789abcdef' for c in nonce):raise ValueError('Invalid login state')
    if not 1<=port<=65535:raise ValueError('Invalid callback port')
    executable=default_browser();root=Path(root).resolve()
    extension=root/'browser-connector'
    if not (extension/'manifest.json').is_file():raise RuntimeError('The account connector is not installed')
    url='https://chat.deepseek.com/#owui-dsw2api='+quote(nonce+'.'+str(port),safe='.')
    process=subprocess.Popen([str(executable),'--user-data-dir='+str(root/'browser-profile-system'),
        '--load-extension='+str(extension),'--no-first-run','--no-default-browser-check',url],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return {'browser':executable.stem,'pid':process.pid}
