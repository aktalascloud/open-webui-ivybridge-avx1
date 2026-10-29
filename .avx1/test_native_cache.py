"""Never reuse an unmatching native input or corrupted cached wheel."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import native_cache as cache
from common import sha256,write_json

class NativeCacheGates(unittest.TestCase):
    def test_exact_cache_reuses_bytes_but_wrong_input_and_corruption_do_not(self):
        with tempfile.TemporaryDirectory(prefix='native-cache-fixture-') as name:
            root=Path(name);source=root/'produced';source.mkdir();destination=root/'restored';destination.mkdir()
            wheel=source/'orjson-fixture.whl';wheel.write_bytes(b'fixture-native-binary')
            write_json(source/'native-build.json',{'wheel_sha256':sha256(wheel),'pgo':False,'lto':'fat'})
            (source/'wheel.sha256').write_text(sha256(wheel)+'  '+wheel.name)
            with patch.object(cache,'ROOT',root):
                cache.store(source,'input-a',wheel)
                self.assertIsNone(cache.restore(destination,'input-b'))
                result=cache.restore(destination,'input-a')
                self.assertTrue(result['native_qualification_reuse']);self.assertEqual((destination/wheel.name).read_bytes(),wheel.read_bytes())
                (root/'.avx1-native-cache'/wheel.name).write_bytes(b'corrupt')
                self.assertIsNone(cache.restore(destination,'input-a'))

if __name__=='__main__':unittest.main()
