import unittest
from common import scan_bytes


class PublicGateTests(unittest.TestCase):
    def test_tailwind_mask_classes_are_not_api_keys(self):
        scan_bytes(b'.mask-linear-from-transparent-to-transparent{mask-type:luminance}', 'fixture.css')

    def test_real_token_shapes_and_utf16_private_keys_still_fail_closed(self):
        for prefix, length in ((b'sk-', 48), (b'sk-proj-', 64), (b'ghp_', 40), (b'hf_', 36)):
            value = b'"' + prefix + b'a' * length + b'"'
            with self.subTest(prefix=prefix):
                with self.assertRaises(ValueError): scan_bytes(value, 'credential fixture')
                with self.assertRaises(ValueError): scan_bytes(value.decode().encode('utf-16-le'), 'UTF16 fixture')


if __name__ == '__main__':
    unittest.main()
