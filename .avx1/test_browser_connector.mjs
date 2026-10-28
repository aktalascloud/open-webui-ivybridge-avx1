import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';
import {createHash} from 'node:crypto';
const root=new URL('../backend/open_webui/providers/browser_connector/',import.meta.url);
const id='jaljomgoclehkemckjhifflhmlllfopc',own={id,url:'chrome-extension://'+id+'/connect.html'};
const plain=value=>JSON.parse(JSON.stringify(value));
test('shared identity preserves Cline; no Google, debugger, localhost or webRequest permissions',()=>{
 const m=JSON.parse(fs.readFileSync(new URL('manifest.json',root),'utf8'));
 assert.deepEqual(m.host_permissions,['https://chat.deepseek.com/*','https://deepseek.com/*']);
 assert.deepEqual(m.permissions,['cookies','scripting','nativeMessaging','alarms','storage']);
 assert.equal(JSON.parse(fs.readFileSync(new URL('identity.json',root))).extension_id,id);
 assert.ok(m.key);assert.equal(m.update_url,undefined);
 const derived=createHash('sha256').update(Buffer.from(m.key,'base64')).digest('hex').slice(0,32).split('').map(c=>String.fromCharCode(97+parseInt(c,16))).join('');
 assert.equal(derived,id);
});
async function fixture(approved=true){
 let message;const storage={},calls=[],reads=[],cookies=[],timers=[];
 const event={addListener(){}};
 const chrome={runtime:{id,onMessage:{addListener:f=>message=f},onInstalled:event,onStartup:event,
  async sendNativeMessage(host,body){calls.push({host,body:plain(body)});return {ok:approved};}},
  action:{async setIcon(){},async setTitle(){},async setBadgeText(){},async setBadgeBackgroundColor(){}},
  alarms:{onAlarm:event,async create(){}},storage:{session:{async get(){return storage},async set(value){Object.assign(storage,value)},async remove(key){delete storage[key]}}},
  tabs:{async query(){return [{id:7,active:true}]},async create(){}},
  scripting:{async executeScript(options){reads.push(options);return [{result:{origin:'https://chat.deepseek.com',token:'fixture-token-'+'x'.repeat(32)}}]}},
  cookies:{async getAll(query){cookies.push(query);return [{name:'session',value:'fixture',domain:'.deepseek.com'},{name:'google',value:'forbidden',domain:'.google.com'}]}}};
 vm.runInNewContext(fs.readFileSync(new URL('background.js',root),'utf8'),{chrome,Date,setTimeout:cb=>timers.push(cb)});
 await new Promise(resolve=>setImmediate(resolve));
 async function send(value,sender=own){let reply;const pending=message(value,sender,v=>reply=v);for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));return {reply,pending};}
 return {send,calls,reads,cookies,storage,timers};
}
test('legacy Cline click sends credentials only to unchanged Cline host',async()=>{
 const f=await fixture();assert.equal((await f.send({action:'connect'})).reply.ok,true);
 const sent=f.calls.filter(v=>v.body.action==='connect');assert.equal(sent.length,1);assert.equal(sent[0].host,'cloud.aktalas.cline_dsw');
 assert.equal(sent[0].body.cookies,'session=fixture');assert.equal(f.calls.some(v=>v.host==='cloud.aktalas.owui_dsw'),false);
});
test('OWUI validates nonce before any credential read and never sends to Cline',async()=>{
 const f=await fixture();await f.send({action:'owui-flow',state:'a'.repeat(64),port:8080},{id,url:'https://chat.deepseek.com/',tab:{id:7}});
 assert.equal(f.calls[0].host,'cloud.aktalas.owui_dsw');assert.equal(f.calls[0].body.action,'check');assert.equal(f.calls[0].body.token,undefined);
 const sent=f.calls.filter(v=>v.body.action==='connect');assert.equal(sent.length,1);assert.equal(sent[0].host,'cloud.aktalas.owui_dsw');
 assert.equal(sent[0].body.cookies,'session=fixture');assert.equal(f.reads[0].target.tabId,7);
 assert.equal(f.storage.owuiFlow,undefined);assert.equal(JSON.stringify(f.storage).includes('fixture-token'),false);
});
test('unapproved nonce never reads credentials',async()=>{
 const f=await fixture(false);await f.send({action:'owui-flow',state:'a'.repeat(64),port:8080},{id,url:'https://chat.deepseek.com/',tab:{id:7}});
 assert.equal(f.reads.length,0);assert.equal(f.cookies.length,0);assert.equal(f.calls.some(v=>v.body.action==='connect'),false);
});
test('Google, foreign extension, unrelated local port and page-origin Cline requests are rejected',async()=>{
 const f=await fixture();
 for(const sender of [{id,url:'https://accounts.google.com/',tab:{id:7}},{id:'other',url:'https://chat.deepseek.com/',tab:{id:7}}])await f.send({action:'owui-flow',state:'a'.repeat(64),port:8080},sender);
 await f.send({action:'owui-flow',state:'a'.repeat(64),port:9000},{id,url:'https://chat.deepseek.com/',tab:{id:7}});
 await f.send({action:'connect'},{id,url:'https://chat.deepseek.com/',tab:{id:7}});
 assert.equal(f.calls.length,0);assert.equal(f.reads.length,0);
});
