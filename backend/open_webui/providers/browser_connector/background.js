// A transient connector for its own browser profile. No credential is persisted
// in extension storage, and no command, prompt or tool can be executed here.
const pending=new Map();
let activeFlow=null;
chrome.storage.session.get('flow').then(({flow})=>{if(flow?.expires>Date.now())activeFlow=flow;});
chrome.runtime.onMessage.addListener((message,sender)=>{
  if(message?.type!=='owui-login' || !sender.tab || !sender.url?.startsWith('https://chat.deepseek.com/'))return;
  if(!/^[a-f0-9]{64}$/.test(message.state) || !Number.isInteger(message.port) || message.port<1 || message.port>65535)return;
  activeFlow={state:message.state,port:message.port,tab:sender.tab.id,expires:Date.now()+600000};
  chrome.storage.session.set({flow:activeFlow});
});
chrome.webRequest.onBeforeSendHeaders.addListener(details=>{
  if(!activeFlow || activeFlow.expires<Date.now())return;
  const value=details.requestHeaders?.find(h=>h.name.toLowerCase()==='authorization')?.value;
  if(typeof value==='string' && value.startsWith('Bearer ') && value.length>20)
    pending.set(details.requestId,value.slice(7));
},{urls:['https://chat.deepseek.com/api/v0/*']},['requestHeaders','extraHeaders']);
chrome.webRequest.onErrorOccurred.addListener(details=>pending.delete(details.requestId),{urls:['https://chat.deepseek.com/api/v0/*']});
let sending=false;
chrome.webRequest.onCompleted.addListener(details=>{
  const token=pending.get(details.requestId);pending.delete(details.requestId);
  if(details.statusCode!==200 || !token || sending)return;
  void (async()=>{
    const flow=activeFlow;
    if(!flow || flow.expires<Date.now())return;
    sending=true;
    try {
      const rows=await chrome.cookies.getAll({url:'https://chat.deepseek.com/api/v0/users/current'});
      const cookies=rows.filter(c=>!/[\r\n]/.test(c.name+c.value)).map(c=>c.name+'='+c.value).join('; ');
      if(!cookies)return;
      const response=await fetch(`http://127.0.0.1:${flow.port}/api/v1/local-providers/dsw2api/browser/callback`,{
        method:'POST',headers:{'Content-Type':'application/json','X-OWUI-Connector':chrome.runtime.id},body:JSON.stringify({state:flow.state,token,cookies}),redirect:'error',credentials:'omit',cache:'no-store'});
      if(response.ok && (await response.json()).connected===true){
        activeFlow=null;
        await chrome.storage.session.remove('flow');
        await chrome.tabs.remove(flow.tab).catch(()=>{});
      }
    } catch {} finally {sending=false;}
  })();
},{urls:['https://chat.deepseek.com/api/v0/*']});
