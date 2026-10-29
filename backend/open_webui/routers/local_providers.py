"""Normal Connections setup and explicit browser-account handoff."""
import asyncio
import json
import base64
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,Field
from open_webui.providers.manager import manager,PACKAGE
from open_webui.utils.auth import get_admin_user,get_human_user
from open_webui.models.users import Users
from open_webui.providers.provider_crypto import open_browser_payload

router=APIRouter()

def callback_port(request):return request.url.port or 8080

@router.get('/dsw2api/status')
async def status(user=Depends(get_admin_user)):
    return await asyncio.to_thread(manager().status)

@router.post('/dsw2api/setup')
async def setup(request:Request,user=Depends(get_admin_user)):
    try:return await asyncio.to_thread(manager().connection,callback_port(request))
    except Exception:raise HTTPException(503,'DSW2API setup failed; the current connections were preserved')

class BrowserLogin(BaseModel):
    consent:bool=False

@router.post('/dsw2api/browser/login')
async def browser_login(form:BrowserLogin,request:Request,user=Depends(get_human_user)):
    get_admin_user(user)
    if manager().status().get('vendor_blocked'):
        raise HTTPException(403,{'code':'deepseek_account_restricted','message':'DeepSeek restricted this account. Reconnecting does not remove the restriction.'})
    try:return await asyncio.to_thread(manager().begin_login,user.id,callback_port(request),consent=form.consent)
    except PermissionError:raise HTTPException(403,'Allow the scoped DeepSeek account connector first')
    except Exception:raise HTTPException(503,'The installed system browser could not be opened; no security setting was disabled')

class BrowserSession(BaseModel):
    model_config={'extra':'forbid'}
    state:str=Field(min_length=64,max_length=64)
    protected_session:str=Field(min_length=64,max_length=131072)

def connector_origin(request):
    identity=json.loads((PACKAGE/'browser_connector/identity.json').read_text('utf-8'))['extension_id']
    if request.client is None or request.client.host not in {'127.0.0.1','::1'}:raise HTTPException(403,'Local connector required')
    origin=request.headers.get('origin')
    if origin is not None and origin!='chrome-extension://'+identity:raise HTTPException(403,'Unexpected account connector origin')
    if request.headers.get('x-owui-connector')!=identity:raise HTTPException(403,'Account connector identity required')

class BrowserState(BaseModel):
    model_config={'extra':'forbid'}
    state:str=Field(min_length=64,max_length=64)
    challenge:str=Field(min_length=64,max_length=8192)

def protected_message(value,purpose,state):
    try:
        data=open_browser_payload(value,purpose,state)
        if not isinstance(data.get('nonce'),str) or len(base64.b64decode(data['nonce'],validate=True))!=32:
            raise PermissionError()
        return data
    except Exception: raise HTTPException(401,'Invalid protected browser handoff') from None

@router.post('/dsw2api/browser/check')
async def browser_check(form:BrowserState,request:Request):
    connector_origin(request)
    try:flow=manager().validate_login_state(form.state)
    except PermissionError:raise HTTPException(401,'Invalid or expired account handoff')
    actor=await Users.get_user_by_id(flow['user_id'])
    if actor is None or actor.role!='admin':raise HTTPException(401,'Account handoff is no longer authorized')
    if manager().status().get('vendor_blocked'):
        return {'ok':False,'code':'DEEPSEEK_ACCOUNT_BLOCKED'}
    data=protected_message(form.challenge,'owui-dsw-check-v2',form.state)
    return {'ok':True,'expires':flow['expires'],'proof':data['nonce']}

@router.post('/dsw2api/browser/callback')
async def browser_callback(form:BrowserSession,request:Request):
    connector_origin(request)
    flow_path=manager().root/'login-flow.json'
    flow=json.loads(flow_path.read_text('utf-8')) if flow_path.exists() else {}
    actor=await Users.get_user_by_id(flow.get('user_id',''))
    if actor is None or actor.role!='admin':raise HTTPException(401,'Account handoff is no longer authorized')
    if manager().status().get('vendor_blocked'):
        raise HTTPException(403,{'code':'deepseek_account_restricted','message':'DeepSeek restricted this account; no authentication probe was sent.'})
    data=protected_message(form.protected_session,'owui-dsw-session-v2',form.state)
    if data.get('origin')!='https://chat.deepseek.com':raise HTTPException(401,'Invalid protected browser origin')
    try:
        result=await asyncio.to_thread(manager().complete_login,form.state,data.get('token'),data.get('cookies'))
        return {**result,'proof':data['nonce']}
    except PermissionError:raise HTTPException(401,'Invalid or expired account handoff')
    except Exception:raise HTTPException(502,'DeepSeek did not confirm the browser session; retry normal sign-in')
