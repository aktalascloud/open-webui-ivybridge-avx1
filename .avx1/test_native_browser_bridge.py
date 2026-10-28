"""Native framing, origin, bounded input and fixed loopback callback transport."""
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from build_browser_bridge import build

ORIGIN='chrome-extension://jaljomgoclehkemckjhifflhmlllfopc/'
requests=[]
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests.append((self.path,dict(self.headers),body))
        value={'ok':True} if self.path.endswith('/check') else {'connected':True}
        data=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

def run(exe,value,origin=ORIGIN,env=None,raw=None):
    data=json.dumps(value).encode()
    process=subprocess.run([str(exe),origin],input=struct.pack('<I',len(data))+data if raw is None else raw,
                           capture_output=True,timeout=90,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    assert len(process.stdout)>=4
    length=struct.unpack('<I',process.stdout[:4])[0]
    assert length==len(process.stdout)-4 and not process.stderr
    return json.loads(process.stdout[4:])

with tempfile.TemporaryDirectory(prefix='owui-native-bridge-test-') as folder:
    production=build(Path(folder)/'production.exe')
    test=build(Path(folder)/'fixture.exe',test=True)
    assert run(production,{},origin='chrome-extension://foreign/')['code']=='INVALID_EXTENSION'
    assert run(production,{},raw=struct.pack('<I',131073))['code']=='INVALID_SIZE'
    assert run(production,{'state':'a'*64,'port':9000,'action':'check'})['code']=='INVALID_PORT'
    assert run(production,{'state':'invalid','port':8080,'action':'check'})['code']=='INVALID_STATE'
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        env=dict(os.environ,OWUI_BRIDGE_TEST_PORT=str(server.server_port))
        result=run(test,{'action':'connect','state':'a'*64,'port':8080,'origin':'https://chat.deepseek.com','token':'synthetic-'+'x'*32,'cookies':'session=fixture'},env=env)
        assert result['ok'] is True and len(requests)==2
        assert requests[0][0].endswith('/check') and 'token' not in requests[0][2]
        assert requests[1][0].endswith('/callback') and requests[1][2]['cookies']=='session=fixture'
        assert requests[1][1]['X-OWUI-Connector']=='jaljomgoclehkemckjhifflhmlllfopc'
        assert 'synthetic' not in json.dumps(result)
    finally:server.shutdown();server.server_close();thread.join()
print('NATIVE_BROWSER_BRIDGE_ORIGIN_FRAMING_PORT_AND_TRANSPORT_PASSED; HTTP fixture only')
