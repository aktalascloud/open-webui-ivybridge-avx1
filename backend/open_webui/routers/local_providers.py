"""Normal Connections setup and explicit browser-account handoff."""
import asyncio
import json
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,Field
from open_webui.providers.manager import manager,PACKAGE
from open_webui.utils.auth import get_admin_user,get_human_user
from open_webui.models.users import Users

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
    try:return await asyncio.to_thread(manager().begin_login,user.id,callback_port(request),consent=form.consent)
    except PermissionError:raise HTTPException(403,'Allow the scoped DeepSeek account connector first')
    except Exception:raise HTTPException(503,'The installed system browser could not be opened; no security setting was disabled')

class BrowserSession(BaseModel):
    state:str=Field(min_length=64,max_length=64)
    token:str=Field(min_length=20,max_length=16384)
    cookies:str=Field(min_length=1,max_length=65536)

def connector_origin(request):
    identity=json.loads((PACKAGE/'browser_connector/identity.json').read_text('utf-8'))['extension_id']
    if request.client is None or request.client.host not in {'127.0.0.1','::1'}:raise HTTPException(403,'Local connector required')
    origin=request.headers.get('origin')
    if origin is not None and origin!='chrome-extension://'+identity:raise HTTPException(403,'Unexpected account connector origin')
    if request.headers.get('x-owui-connector')!=identity:raise HTTPException(403,'Account connector identity required')

class BrowserState(BaseModel):
    state:str=Field(min_length=64,max_length=64)

@router.post('/dsw2api/browser/check')
async def browser_check(form:BrowserState,request:Request):
    connector_origin(request)
    try:flow=manager().validate_login_state(form.state)
    except PermissionError:raise HTTPException(401,'Invalid or expired account handoff')
    actor=await Users.get_user_by_id(flow['user_id'])
    if actor is None or actor.role!='admin':raise HTTPException(401,'Account handoff is no longer authorized')
    return {'ok':True,'expires':flow['expires']}

@router.post('/dsw2api/browser/callback')
async def browser_callback(form:BrowserSession,request:Request):
    connector_origin(request)
    flow_path=manager().root/'login-flow.json'
    flow=json.loads(flow_path.read_text('utf-8')) if flow_path.exists() else {}
    actor=await Users.get_user_by_id(flow.get('user_id',''))
    if actor is None or actor.role!='admin':raise HTTPException(401,'Account handoff is no longer authorized')
    try:return await asyncio.to_thread(manager().complete_login,form.state,form.token,form.cookies)
    except PermissionError:raise HTTPException(401,'Invalid or expired account handoff')
    except Exception:raise HTTPException(502,'DeepSeek did not confirm the browser session; retry normal sign-in')
