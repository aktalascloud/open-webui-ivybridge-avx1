"""Exercise the packaged picker with a disposable user and mocked model transport."""
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


class ReasoningProvider:
    def __init__(self):
        self.captured=[]
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def send(self,body,content_type='application/json'):
                raw=body.encode() if isinstance(body,str) else json.dumps(body).encode()
                self.send_response(200);self.send_header('Content-Type',content_type)
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def do_GET(self):
                self.send({'data':[{'id':mid,'object':'model','owned_by':'strata'} for mid in ['fixture-base','other-base']]})
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));owner.captured.append(body)
                reply={'id':'fixture-completion','object':'chat.completion','model':body.get('model','fixture-base'),
                    'choices':[{'index':0,'message':{'role':'assistant','content':'Fixture reply'},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
                if body.get('stream'):
                    reply['choices'][0]['delta']=reply['choices'][0].pop('message')
                    self.send('data: '+json.dumps(reply)+'\n\ndata: [DONE]\n\n','text/event-stream')
                else:self.send(reply)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.url='http://127.0.0.1:'+str(self.server.server_port)+'/v1'
        self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def close(self):self.server.shutdown();self.server.server_close()


def check_strata_reasoning(browser, base, work, provider):
    context=browser.new_context(viewport={'width':1280,'height':900},service_workers='block',locale='en-US')
    errors=[]
    response=context.request.post(base+'/api/v1/auths/signup',data={
        'name':'Reasoning fixture','email':'reasoning-fixture@example.com','password':'fixture-only-password-2026'})
    if not response.ok:raise RuntimeError('Disposable reasoning user could not be created')
    token=response.json()['token']
    headers={'Authorization':'Bearer '+token}
    for mid,name,profile in [('strata.fixture','Strata fixture','davidau'),('other.fixture','Other fixture',None)]:
        meta={'capabilities':{'vision':False}}
        if profile:meta.update(strata_reasoning_profile=profile,strata_adaptive_enabled=True,
                               strata_reasoning_modes=['off','ultra','coder','spoon','low','medium','xhigh'])
        result=context.request.post(base+'/api/v1/models/create',headers=headers,
            data={'id':mid,'base_model_id':'fixture-base' if profile else 'other-base','name':name,'params':{},'meta':meta,'access_grants':[]})
        if not result.ok:raise RuntimeError('Disposable reasoning model could not be created')
    result=context.request.post(base+'/api/v1/users/user/settings/update',headers=headers,data={'ui':{
        'theme':'dark','showChangelog':False,'showUpdateToast':False,'models':['strata.fixture'],
        'params':{'stream_response':False}}})
    if not result.ok:raise RuntimeError('Disposable reasoning settings failed')
    context.add_init_script('localStorage.setItem("token",'+json.dumps(token)+');localStorage.setItem("locale","en-US");localStorage.setItem("theme","dark");')
    page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
    captured=[]
    def outgoing(request):
        if request.url.split('?')[0].endswith('/api/chat/completions'):captured.append(request.post_data_json)
    page.on('request',outgoing)
    page.goto(base+'/?models=strata.fixture',wait_until='domcontentloaded')
    button=page.locator('[data-strata-reasoning]')
    button.wait_for(state='visible',timeout=60000)
    for level in ['high','xhigh','ultra','adaptive','none']:
        button.click()
        with page.expect_response('**/api/v1/users/user/settings/update') as saved:
            page.locator('[data-reasoning-effort="'+level+'"]').click()
        if not saved.value.ok:raise RuntimeError('Reasoning preference save failed')
        page.wait_for_function('!document.querySelector("[data-strata-reasoning]").disabled')
    page.reload(wait_until='domcontentloaded');button.wait_for(state='visible',timeout=60000)
    if 'None' not in button.inner_text():raise RuntimeError('Reasoning preference did not survive reload')
    button.click()
    with page.expect_response('**/api/v1/users/user/settings/update'):
        page.locator('[data-reasoning-effort="ultra"]').click()
    page.wait_for_function('!document.querySelector("[data-strata-reasoning]").disabled')
    button.click();page.locator('[data-reasoning-effort="ultra"]').wait_for(state='visible')
    page.wait_for_timeout(350)
    assert page.locator('html').evaluate('(e)=>e.classList.contains("dark")')
    page.screenshot(path=str(work/'strata-reasoning-dark.png'))
    page.keyboard.press('Escape')
    page.locator('#chat-input').fill('Reasoning integration fixture.')
    page.locator('#chat-input').press('Enter')
    deadline=time.monotonic()+25
    while not captured and time.monotonic()<deadline:page.wait_for_timeout(100)
    if not captured:raise RuntimeError('Reasoning request was not emitted by the packaged UI')
    params=captured[-1]['params']
    if params.get('reasoning_effort')!='xhigh' or params.get('custom_params',{}).get('_strata_reasoning_mode')!='ultra':
        raise RuntimeError('Packaged composer did not serialize the separate Ultra mode')
    deadline=time.monotonic()+25
    def matches(body):return any(m.get('role')=='user' and '{REASON:ultra}' in str(m.get('content')) for m in body.get('messages',[]))
    while not any(matches(b) for b in provider.captured) and time.monotonic()<deadline:page.wait_for_timeout(100)
    wire=next((b for b in provider.captured if matches(b)),None)
    if not wire or '_strata_reasoning_mode' in wire or wire.get('reasoning_effort')!='xhigh':
        raise RuntimeError('Actual OWUI provider boundary did not apply/strip the Ultra control')
    if '{REASON:' in json.dumps(captured[-1].get('messages',[])):
        raise RuntimeError('Composer changed the original user message')
    button.click()
    with page.expect_response('**/api/v1/users/user/settings/update'):
        page.locator('[data-reasoning-effort="adaptive"]').click()
    page.wait_for_function('!document.querySelector("[data-strata-reasoning]").disabled')
    page.locator('#chat-input').fill('fix the python bug and refactor the parser module')
    page.locator('#chat-input').press('Enter')
    deadline=time.monotonic()+25
    def adaptive_wire(body):return any(m.get('role')=='user' and '{REASON:coder}' in str(m.get('content')) for m in body.get('messages',[]))
    while not any(adaptive_wire(b) for b in provider.captured) and time.monotonic()<deadline:page.wait_for_timeout(100)
    if not any(adaptive_wire(b) for b in provider.captured):raise RuntimeError('Mnemosyne did not steer the actual provider request')
    page.evaluate('document.documentElement.classList.remove("dark")')
    button.click();page.locator('[data-reasoning-effort="ultra"]').wait_for(state='visible')
    page.wait_for_timeout(350)
    assert not page.locator('html').evaluate('(e)=>e.classList.contains("dark")')
    page.screenshot(path=str(work/'strata-reasoning-light.png'))
    page.keyboard.press('Escape');page.set_viewport_size({'width':360,'height':800})
    button.click();menu=page.locator('[role="menu"]:visible').last;box=menu.bounding_box()
    if not box or box['x']< -1 or box['x']+box['width']>361:raise RuntimeError('Reasoning menu overflows the mobile viewport')
    page.keyboard.press('Escape')
    page.goto(base+'/?models=other.fixture',wait_until='domcontentloaded')
    button.wait_for(state='hidden',timeout=45000)
    if errors:raise RuntimeError('Reasoning UI JavaScript error: '+errors[0])
    context.close()
    print('CHROMIUM_STRATA_REASONING_SAVE_RELOAD_ULTRA_ADAPTIVE_REAL_PROXY_LIGHT_DARK_MOBILE_PASSED; real model requests=0')
