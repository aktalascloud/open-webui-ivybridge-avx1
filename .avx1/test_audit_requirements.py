from pathlib import Path
import tempfile
import unittest
from audit_requirements import resolved_requirements


class ResolvedAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def package(self, folder, name, version):
        info = self.root / (folder + '.dist-info')
        info.mkdir()
        (info / 'METADATA').write_text(f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n', encoding='utf-8')

    def test_local_app_is_separate_but_every_library_is_retained(self):
        self.package('app', 'Open_WebUI', '0.13.0')
        self.package('direct', 'direct', '1.2.3')
        self.package('transitive', 'transitive', '4.5.6')
        libraries, own = resolved_requirements(self.root, 'open-webui', '0.13.0')
        self.assertEqual(libraries, [{'name': 'direct', 'version': '1.2.3'}, {'name': 'transitive', 'version': '4.5.6'}])
        self.assertEqual(own, {'name': 'open-webui', 'version': '0.13.0'})

    def test_missing_wrong_or_duplicate_app_metadata_blocks_audit(self):
        self.package('direct', 'direct', '1')
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            resolved_requirements(self.root, 'open-webui', '0.13.0')
        self.package('app', 'open-webui', '0.12.5')
        with self.assertRaisesRegex(RuntimeError, 'version differs'):
            resolved_requirements(self.root, 'open-webui', '0.13.0')
        self.package('duplicate', 'direct', '2')
        with self.assertRaises(RuntimeError):
            resolved_requirements(self.root, 'open-webui', '0.12.5')


if __name__ == '__main__':
    unittest.main()
