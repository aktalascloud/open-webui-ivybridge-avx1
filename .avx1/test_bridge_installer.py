"""Shared extension ownership and application-scoped registry installation."""
import contextlib
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from open_webui.providers import browser_bridge as bridge
from build_browser_bridge import build

class InstallerGates(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='shared-extension-install-')
        self.root=Path(self.directory.name);self.package=self.root/'package';self.package.mkdir()
        source=Path(bridge.__file__).parent/'browser_connector'
        shutil.copytree(source,self.package/'browser_connector')
        executable=self.package/'browser_connector/native/owui-native-host.exe'
        if not executable.exists():build(executable)
        self.calls=[]
        @contextlib.contextmanager
        def create(*args):self.calls.append(args);yield object()
        self.patches=[patch.dict(os.environ,LOCALAPPDATA=str(self.root)),patch.object(bridge,'__file__',str(self.package/'browser_bridge.py')),
                      patch.object(bridge.winreg,'OpenKey',side_effect=FileNotFoundError),patch.object(bridge.winreg,'CreateKey',side_effect=create),
                      patch.object(bridge.winreg,'SetValueEx')]
        for item in self.patches:item.start()
        self.cline=self.root/'Cline Desktop AVX1 RU/bin/browser-bridge/extension/keep.txt'
        self.cline.parent.mkdir(parents=True);self.cline.write_text('unchanged')
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.directory.cleanup()
    def test_full_install_has_same_id_and_only_own_native_registration(self):
        result=bridge.install();self.assertEqual(result['extension_id'],'jaljomgoclehkemckjhifflhmlllfopc')
        self.assertEqual(len(self.calls),5)
        self.assertTrue(all(args[1].endswith('\\cloud.aktalas.owui_dsw') for args in self.calls))
        self.assertEqual(self.cline.read_text(),'unchanged')
        self.assertTrue((Path(result['extension_folder']).parent/'native-host.exe').exists())
    def test_unmanaged_directory_is_preserved(self):
        target=self.root/'OWUI DeepSeek Browser Bridge';target.mkdir();(target/'personal.txt').write_text('keep')
        with self.assertRaisesRegex(RuntimeError,'Unmanaged'):bridge.install()
        self.assertEqual((target/'personal.txt').read_text(),'keep');self.assertEqual(self.calls,[])
    def test_user_modified_extension_is_preserved(self):
        result=bridge.install(True);self.calls.clear();background=Path(result['extension_folder'])/'background.js'
        background.write_text('personal edit')
        with self.assertRaisesRegex(RuntimeError,'User-modified'):bridge.install()
        self.assertEqual(background.read_text(),'personal edit');self.assertEqual(self.calls,[])
    def test_preparation_does_not_register_or_capture_credentials(self):
        result=bridge.install(True)
        self.assertEqual(self.calls,[]);self.assertFalse(result['native_host_registered'])
        self.assertEqual(result['credential_capture'],'not performed');self.assertEqual(self.cline.read_text(),'unchanged')

if __name__=='__main__':unittest.main()
