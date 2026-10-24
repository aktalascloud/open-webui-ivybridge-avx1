import os
from common import OUT
from native_json import build,EXPERIMENTS
profile=os.environ['JSON_EXPERIMENT']
if profile not in EXPERIMENTS:raise RuntimeError('Unknown compiler experiment')
OUT.mkdir()
build(OUT,experiment=profile)
