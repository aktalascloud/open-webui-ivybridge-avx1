"""CPU-only JSON measurements; import a wheel extracted to --module-dir when supplied."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import ctypes
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.GetCurrentThread.restype=ctypes.c_void_p
kernel.QueryThreadCycleTime.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulonglong)]
thread_handle=kernel.GetCurrentThread()
def cpu_cycles():
    value=ctypes.c_ulonglong()
    if not kernel.QueryThreadCycleTime(thread_handle,ctypes.byref(value)):raise RuntimeError('CPU cycle counter unavailable')
    return value.value

def main(args):
    if args.module_dir:sys.path.insert(0,str(Path(args.module_dir).resolve()))
    import orjson
    fixtures={
      'stream_event':{'id':'synthetic','choices':[{'delta':{'content':'Ответ агента: проверка данных.'},'index':0}]},
      'tool_schema':{'tools':[{'type':'function','function':{'name':'tool_'+str(n),'description':'Synthetic tool schema','parameters':{'type':'object','properties':{'query':{'type':'string'},'limit':{'type':'integer'}},'required':['query']}}} for n in range(40)]},
      'report_rows':{'rows':[{'id':n,'amount':n*17.25,'vat':0.12,'name':'Синтетическая строка '+str(n),'ok':n%3==0} for n in range(1000)]},
      'unicode_text':{'text':('Проверка JSON и инструментов.\n'*2000)},
    }
    results={};outputs={}
    for name,payload in fixtures.items():
        encoded=orjson.dumps(payload);outputs[name]=hashlib.sha256(encoded).hexdigest()
        for op,fn in [('dumps',lambda p=payload:orjson.dumps(p)),('loads',lambda p=encoded:orjson.loads(p))]:
            for _ in range(20):fn()
            samples=[];count=100
            for sample in range(5):
                while True:
                    start=cpu_cycles()
                    for _ in range(count):fn()
                    elapsed=cpu_cycles()-start
                    if elapsed>=500000000:break
                    count*=2
                samples.append(elapsed/count)
            results[name+'_'+op]={'median_cpu_cycles':statistics.median(samples),'samples_cpu_cycles':samples,'iterations':count}
    result={'orjson':orjson.__version__,'scope':'Synthetic JSON dumps/loads CPU time; no model inference; five calibrated samples per case; QueryThreadCycleTime, high-resolution CPU cycles','fixtures_sha256':outputs,'results':results}
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--module-dir');parser.add_argument('--output',required=True);main(parser.parse_args())
