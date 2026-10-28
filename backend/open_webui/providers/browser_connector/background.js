// Independent Cline/OWUI targets. No credential logging or storage.
const ORIGIN='https://chat.deepseek.com';
const CLINE_HOST='cloud.aktalas.cline_dsw',OWUI_HOST='cloud.aktalas.owui_dsw';
let connecting=false,owuiBusy=false,flow=null,owuiConnected=false;
chrome.storage.session.get(['owuiFlow','owuiConnected']).then(value=>{
 if(value.owuiFlow?.expires>Date.now()){flow=value.owuiFlow;void tryOwui();}
 owuiConnected=value.owuiConnected===true;
});
async function showState(state){
 const names={connected:'DeepSeek: Cline подключён',connecting:'Подключение DeepSeek к Cline…',disconnected:'DeepSeek: Cline не подключён'};
 await chrome.action.setIcon({path:{16:'icons/'+state+'-16.png',32:'icons/'+state+'-32.png'}});
 await chrome.action.setTitle({title:names[state]+'; OWUI: '+(owuiConnected?'подключён':'не подключён')});
 await chrome.action.setBadgeText({text:state==='connected'||owuiConnected?'ON':state==='connecting'?'…':''});
 await chrome.action.setBadgeBackgroundColor({color:state==='connected'||owuiConnected?'#168649':'#b87a12'});
}
async function refreshState(){
 if(connecting)return false;
 let connected=false;
 try{connected=(await chrome.runtime.sendNativeMessage(CLINE_HOST,{action:'status'}))?.ok===true;}catch{}
 if(!connecting)await showState(connected?'connected':'disconnected');
 return connected;
}
chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name==='cline-session-status')void refreshState();});
for(const event of [chrome.runtime.onInstalled,chrome.runtime.onStartup])event.addListener(()=>{
 void chrome.alarms.create('cline-session-status',{periodInMinutes:1});void refreshState();
});
async function sessionFor(tabId){
 const tabs=await chrome.tabs.query({url:ORIGIN+'/*'});
 const tab=tabId===undefined?(tabs.find(value=>value.active)||tabs[0]):tabs.find(value=>value.id===tabId);
 if(!tab)return null;
 const values=await chrome.scripting.executeScript({target:{tabId:tab.id},func:()=>{
  if(location.origin!=='https://chat.deepseek.com')return null;
  let raw=localStorage.getItem('userToken');if(!raw)return null;
  try{const parsed=JSON.parse(raw);raw=typeof parsed==='string'?parsed:parsed.value;}catch{}
  return typeof raw==='string'?{origin:location.origin,token:raw.replace(/^Bearer\s+/,'').trim()}:null;
 }});
 const session=values[0]?.result;
 if(!session?.token||session.token.length>16384||/[\r\n]/.test(session.token))return null;
 const cookies=await chrome.cookies.getAll({url:ORIGIN+'/api/v0/chat/completion'});
 session.cookies=cookies.filter(cookie=>['chat.deepseek.com','deepseek.com'].includes(cookie.domain.replace(/^\./,''))&&!/[\r\n]/.test(cookie.name+cookie.value)).map(cookie=>cookie.name+'='+cookie.value).join('; ');
 if(!session.cookies||session.cookies.length>65536)return null;
 return session;
}
async function connectCline(){
 if(connecting)return {ok:false,code:'CONNECTING'};
 connecting=true;
 try{
  await showState('connecting');const session=await sessionFor();
  if(!session){await chrome.tabs.create({url:ORIGIN+'/sign_in'});return {ok:false,code:'SIGN_IN_REQUIRED'};}
  try{return await chrome.runtime.sendNativeMessage(CLINE_HOST,{action:'connect',...session});}
  finally{session.token='';session.cookies='';}
 }finally{connecting=false;void refreshState();}
}
async function clearFlow(){flow=null;await chrome.storage.session.remove('owuiFlow');}
async function tryOwui(){
 if(owuiBusy)return {ok:false,code:'CONNECTING'};
 const current=flow;
 if(!current||current.expires<Date.now()){await clearFlow();return {ok:false,code:'START_IN_OWUI'};}
 owuiBusy=true;let retry=false;
 try{
  // Check an authorized OWUI nonce before reading any account data.
  const check=await chrome.runtime.sendNativeMessage(OWUI_HOST,{action:'check',state:current.state,port:8080});
  if(check?.ok!==true){await clearFlow();return {ok:false,code:'OWUI_HANDOFF_REJECTED'};}
  const session=await sessionFor(current.tab);
  if(!session){retry=true;return {ok:false,code:'SIGN_IN_REQUIRED'};}
  try{
   if(flow!==current)return {ok:false,code:'SUPERSEDED'};
   const result=await chrome.runtime.sendNativeMessage(OWUI_HOST,{action:'connect',state:current.state,port:8080,...session});
   if(result?.ok){owuiConnected=true;await chrome.storage.session.set({owuiConnected:true});await clearFlow();void refreshState();}
   return result;
  }finally{session.token='';session.cookies='';}
 }catch{return {ok:false,code:'OWUI_BRIDGE_UNAVAILABLE'};}
 finally{owuiBusy=false;if(flow&&flow!==current)setTimeout(()=>void tryOwui(),0);else if(retry&&flow===current)setTimeout(()=>void tryOwui(),2000);}
}
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
 if(sender.id!==chrome.runtime.id)return;
 if(message?.action==='owui-flow'){
  if(!sender.tab||!sender.url?.startsWith(ORIGIN+'/')||!/^[a-f0-9]{64}$/.test(message.state)||message.port!==8080)return;
  flow={state:message.state,tab:sender.tab.id,expires:Date.now()+600000};
  void chrome.storage.session.set({owuiFlow:flow}).then(()=>tryOwui()).then(reply);return true;
 }
 if(sender.tab&&!sender.url?.startsWith('chrome-extension://'+chrome.runtime.id+'/'))return;
 if(message?.action==='status'){void refreshState().then(ok=>reply({ok,owui:owuiConnected,pending:!!flow}));return true;}
 if(message?.action==='connect'){void connectCline().then(reply,()=>reply({ok:false,code:'BRIDGE_UNAVAILABLE'}));return true;}
 if(message?.action==='connect-owui'){void tryOwui().then(reply);return true;}
});
