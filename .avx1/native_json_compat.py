"""Differential native-wheel fixtures; no private data or model generation."""
import base64
import datetime as dt
import json
import orjson

values=[None,False,True,0,-1,2**63-1,2**64-1,0.0,-0.0,5e-324,1.7976931348623157e308,
        float('nan'),float('inf'),float('-inf'),'Привет 世界 😀',{'tool':'fixture','args':[None,True,1.25]},
        dt.datetime(2026,10,23,7,0,tzinfo=dt.timezone(dt.timedelta(hours=6)))]
results=[]
for value in values:
    try:results.append(['dump',base64.b64encode(orjson.dumps(value)).decode()])
    except Exception as error:results.append(['dump-error',type(error).__name__])
for value in [b'{"a":1,"b":[true,null]}',b'1e309',b'NaN',b'{"a":}',b'"\xed\xa0\x80"',b'['*1100+b'0'+b']'*1100]:
    try:results.append(['load',json.dumps(orjson.loads(value),sort_keys=True,ensure_ascii=True)])
    except Exception as error:results.append(['load-error',type(error).__name__])
print(json.dumps(results,separators=(',',':')))
