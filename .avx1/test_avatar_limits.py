"""Upload-size and high-resolution texture limits; no model inference."""
import importlib.util
import io
from pathlib import Path
import unittest
from PIL import Image

source=Path(__file__).resolve().parents[1]/'backend/open_webui/utils/voice_avatar.py'
spec=importlib.util.spec_from_file_location('avatar_limits',source)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


class Limits(unittest.TestCase):
    def test_new_card_inherits_avatar_without_overwriting_explicit_choices(self):
        chosen={'file_id':'fixture','states':{},'gestures':[]}
        self.assertEqual(module.new_model_avatar_default({}, {'voice_avatar':chosen}), chosen)
        self.assertIsNone(module.new_model_avatar_default({'voice_avatar':None}, {'voice_avatar':chosen}))
        self.assertIsNone(module.new_model_avatar_default({'voice_avatar':{'file_id':'custom'}}, {'voice_avatar':chosen}))
        self.assertIsNone(module.new_model_avatar_default({}, {}))

    def texture(self,size,count=1):
        output=io.BytesIO();Image.new('L',size).save(output,format='PNG');data=output.getvalue()
        model={'images':[{'bufferView':0,'mimeType':'image/png'} for _ in range(count)],
               'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':len(data)}]}
        return model,data

    def test_upload_is_twenty_mib(self):
        self.assertEqual(module.AVATAR_MAX_BYTES,20*1024*1024)
        with self.assertRaisesRegex(ValueError,'20 MiB'):
            module.validate_voice_avatar(bytes(20*1024*1024+1))

    def test_4k_and_8k_are_allowed_with_a_total_budget(self):
        for size,count in [((4096,4096),4),((8192,8192),1)]:
            model,data=self.texture(size,count);module._validate_textures(model,data,0,len(data))
        model,data=self.texture((8192,8192),3)
        with self.assertRaisesRegex(ValueError,'128 megapixel'):
            module._validate_textures(model,data,0,len(data))


if __name__=='__main__':unittest.main()
