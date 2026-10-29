# SPDX-License-Identifier: Apache-2.0
"""Cooperative per-user queue for clients sharing one browser DeepSeek account.

No credentials or account names enter this file. Closing the handle, including
process death, releases the OS lock. Never use this to retry vendor requests.
"""
import asyncio
import base64
import errno
import os
from pathlib import Path
import subprocess
import threading
import time

_SECURED = set()
_CREATED = set()
_SECURITY_GUARD = threading.Lock()


def _check_private_access(path, created_file):
    with _SECURITY_GUARD:
        identity = path.stat()
        cache_key = (str(path), identity.st_dev, identity.st_ino)
        if cache_key in _SECURED:
            return
        targets = [path.parent.parent, path.parent, path]
        if os.name == 'nt':
            # A static script receives its path only through a child-local
            # environment variable. Never interpolate paths into shell code.
            script = r'''
$ErrorActionPreference='Stop'
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$trusted=@($sid,'S-1-5-18','S-1-5-32-544')
$p=$env:AKTALAS_DSW_LEASE_FILE
$new=@($env:AKTALAS_DSW_LEASE_NEW_ROOT,$env:AKTALAS_DSW_LEASE_NEW_PRIVATE,$env:AKTALAS_DSW_LEASE_NEW_FILE)
$index=0
foreach($item in @([IO.Path]::GetDirectoryName([IO.Path]::GetDirectoryName($p)),[IO.Path]::GetDirectoryName($p),$p)) {
 $acl=if([IO.Directory]::Exists($item)){[IO.Directory]::GetAccessControl($item)}else{[IO.File]::GetAccessControl($item)}
 if($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -notin $trusted){throw 'Untrusted queue owner'}
 if($new[$index] -eq '1'){
  $isDirectory=[IO.Directory]::Exists($item)
  $acl=if($isDirectory){[Security.AccessControl.DirectorySecurity]::new()}else{[Security.AccessControl.FileSecurity]::new()}
  $acl.SetOwner([Security.Principal.SecurityIdentifier]::new($sid))
  $acl.SetAccessRuleProtection($true,$false)
  $inherit=if($isDirectory){[Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit}else{[Security.AccessControl.InheritanceFlags]::None}
  foreach($identity in @($sid,'S-1-5-18')){
   $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($identity),[Security.AccessControl.FileSystemRights]::FullControl,$inherit,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow))
  }
  if($isDirectory){[IO.Directory]::SetAccessControl($item,$acl)}else{[IO.File]::SetAccessControl($item,$acl)}
 }
 foreach($rule in $acl.Access){
  if($rule.AccessControlType -eq 'Allow' -and (([int]$rule.FileSystemRights -band 0xD0156) -ne 0) -and $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -notin $trusted){throw 'Queue is writable by another principal'}
 }
 $index++
}
'''
            environment = dict(os.environ, AKTALAS_DSW_LEASE_FILE=str(path),
                AKTALAS_DSW_LEASE_NEW_ROOT='1' if str(path.parent.parent) in _CREATED else '0',
                AKTALAS_DSW_LEASE_NEW_PRIVATE='1' if str(path.parent) in _CREATED else '0',
                AKTALAS_DSW_LEASE_NEW_FILE='1' if created_file else '0')
            executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
            result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-EncodedCommand',
                base64.b64encode(script.encode('utf-16le')).decode('ascii')], env=environment,
                capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError('Browser session queue ownership or write permissions are unsafe')
        else:
            for item in targets:
                value = item.stat()
                if value.st_uid != os.geteuid() or value.st_mode & 0o022:
                    raise RuntimeError('Browser session queue ownership or write permissions are unsafe')
        _SECURED.add(cache_key)
        _CREATED.discard(str(path.parent.parent))
        _CREATED.discard(str(path.parent))


class BrowserSessionLease:
    def __init__(self, file):
        self._file = file
        self._guard = threading.Lock()

    def release(self):
        with self._guard:
            file, self._file = self._file, None
            if file is None:
                return
            try:
                file.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(file.fileno(), fcntl.LOCK_UN)
            finally:
                file.close()


def _path():
    # The opt-in is managed-only. Independent clients agree on this exact
    # versioned per-user path; no private endpoint or token hash is needed.
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        raise RuntimeError('Per-user browser session queue directory unavailable')
    base = Path(base)
    if not base.is_absolute():
        raise RuntimeError('Browser session queue requires an absolute user directory')
    directory = base / 'Aktalas DSW2API' / 'private'
    for parent in [base, *base.parents]:
        if parent.is_symlink() or parent.is_junction():
            raise RuntimeError('Browser session queue refuses reparse points')
    for parent in [directory.parent, directory]:
        try:
            parent.mkdir(mode=0o700)
            _CREATED.add(str(parent))
        except FileExistsError:
            pass
        if parent.is_symlink() or parent.is_junction():
            raise RuntimeError('Browser session queue refuses reparse points')
    path = directory / 'browser-session-v1.lock'
    if path.is_symlink() or path.is_junction():
        raise RuntimeError('Browser session queue refuses reparse points')
    return path


def acquire_browser_session_lease(cancellation=None, *, enabled=None):
    if enabled is None:
        enabled = os.environ.get('DEEPSEEK_SHARED_BROWSER_LEASE') == '1'
    if not enabled:
        return BrowserSessionLease(None)
    path = _path()
    flags = os.O_RDWR | getattr(os, 'O_BINARY', 0)
    try:
        descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        created_file = True
    except FileExistsError:
        descriptor = os.open(path, flags)
        created_file = False
    os.set_inheritable(descriptor, False)
    file = os.fdopen(descriptor, 'r+b', buffering=0)
    try:
        # Check the opened object as well as its directory before taking it.
        if path.is_symlink() or path.is_junction() or not path.is_file():
            raise RuntimeError('Invalid browser session queue file')
        identity = os.fstat(file.fileno())
        target = path.stat()
        if (identity.st_dev, identity.st_ino) != (target.st_dev, target.st_ino):
            raise RuntimeError('Browser session queue identity changed')
        _check_private_access(path, created_file)
        deadline = time.monotonic() + 1800
        while True:
            if cancellation is not None and cancellation.is_set():
                raise asyncio.CancelledError()
            if time.monotonic() >= deadline:
                raise TimeoutError('DeepSeek browser session is still in use; request was not sent')
            try:
                file.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                lease = BrowserSessionLease(file)
                if cancellation is not None and cancellation.is_set():
                    lease.release()
                    raise asyncio.CancelledError()
                return lease
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if cancellation is None:
                    time.sleep(.1)
                else:
                    cancellation.wait(.1)
    except BaseException:
        file.close()
        raise
