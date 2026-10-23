import unittest
import brotli
import brotlicffi

class BrotliCompatibility(unittest.TestCase):
    def test_valid_payloads_match_across_bindings(self):
        for data in (b'',b'hello',bytes(range(256))*8,'Русский интерфейс'.encode()):
            for encoder in (brotli,brotlicffi):
                packed=encoder.compress(data)
                for decoder in (brotli,brotlicffi):self.assertEqual(decoder.decompress(packed),data)

    def test_both_bindings_reject_trailing_data(self):
        for module in (brotli,brotlicffi):
            with self.assertRaises(module.error):module.decompress(module.compress(b'valid stream')+b'trailing junk')

if __name__=='__main__':unittest.main()
