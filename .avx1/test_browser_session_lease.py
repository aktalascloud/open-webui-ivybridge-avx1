# SPDX-License-Identifier: Apache-2.0
"""Real OS-lock contract across independent processes; no vendor calls."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

gateway = Path(__file__).resolve().parents[1] / 'backend/open_webui/providers/vendor/dsw2api'
sys.path.insert(0, str(gateway))
from browser_session_lease import acquire_browser_session_lease

if '--child' in sys.argv:
    lease = acquire_browser_session_lease()
    print('acquired', flush=True)
    if '--hold' in sys.argv:
        sys.stdin.readline()
    lease.release()
    raise SystemExit(0)

with tempfile.TemporaryDirectory(prefix='browser-lease-fixture-') as directory:
    os.environ.update(LOCALAPPDATA=directory, DEEPSEEK_SHARED_BROWSER_LEASE='1')
    # OWUI opts in from context-local configuration, without process env edits.
    os.environ.pop('DEEPSEEK_SHARED_BROWSER_LEASE')
    explicit = acquire_browser_session_lease(enabled=True)
    explicit.release()
    assert 'DEEPSEEK_SHARED_BROWSER_LEASE' not in os.environ
    os.environ['DEEPSEEK_SHARED_BROWSER_LEASE'] = '1'
    lease = acquire_browser_session_lease()
    child = subprocess.Popen([sys.executable, '-B', __file__, '--child'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        time.sleep(.25)
        assert child.poll() is None, 'Independent client bypassed the lock'
        cancelled = threading.Event()
        result = []
        def wait():
            try:
                unexpected = acquire_browser_session_lease(cancelled)
                unexpected.release()
                result.append('incorrectly-acquired')
            except asyncio.CancelledError:
                result.append('cancelled-before-send')
        thread = threading.Thread(target=wait)
        thread.start()
        cancelled.set()
        thread.join(3)
        assert result == ['cancelled-before-send'] and not thread.is_alive()
        lease.release()
        lease.release()  # Cleanup can run in generator and response finalizers.
        stdout, stderr = child.communicate(timeout=5)
        assert child.returncode == 0 and stdout.strip() == 'acquired', stderr
    finally:
        lease.release()
        if child.poll() is None:
            child.kill()
            child.wait()
    # The OS releases ownership when a client dies during its stream.
    child = subprocess.Popen([sys.executable, '-B', __file__, '--child', '--hold'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'acquired'
    finally:
        child.kill()
        child.wait()
    lease = acquire_browser_session_lease()
    lease.release()
    lock = Path(directory) / 'Aktalas DSW2API/private/browser-session-v1.lock'
    assert lock.stat().st_size == 0
    if os.name == 'nt':
        executable = str(Path(os.environ['SystemRoot']) / 'System32/icacls.exe')
        try:
            subprocess.run([executable,str(lock),'/grant','*S-1-1-0:(F)'],check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            rejected = subprocess.run([sys.executable,'-B',__file__,'--child'],capture_output=True,text=True,timeout=10)
            assert rejected.returncode != 0 and 'permissions are unsafe' in rejected.stderr
        finally:
            subprocess.run([executable,str(lock),'/remove:g','*S-1-1-0'],check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        lock.chmod(0o666)
        try:
            rejected = subprocess.run([sys.executable,'-B',__file__,'--child'],capture_output=True,text=True,timeout=10)
            assert rejected.returncode != 0 and 'permissions are unsafe' in rejected.stderr
        finally:
            lock.chmod(0o600)

print(json.dumps({'independent_clients_serialize': True, 'queued_cancel_sends_nothing': True,
 'process_death_releases_lock': True, 'idempotent_release': True, 'unsafe_existing_acl_rejected': True, 'account_data_in_lock': False,
 'real_vendor_requests': 0}))
