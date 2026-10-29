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
async function fixture(approved=true,initial={},nativeStatus={ok:true}){
 let message;const storage={...initial},calls=[],reads=[],cookies=[],timers=[],icons=[],badges=[],titles=[];
 const event={addListener(){}};
 const chrome={runtime:{id,onMessage:{addListener:f=>message=f},onInstalled:event,onStartup:event,
  async sendNativeMessage(host,body){calls.push({host,body:plain(body)});return body.action==='status'?nativeStatus:{ok:approved};}},
  action:{async setIcon(v){icons.push(v)},async setTitle(v){titles.push(v.title)},async setBadgeText(v){badges.push(v.text)},async setBadgeBackgroundColor(){}},
  alarms:{onAlarm:event,async create(){}},storage:{session:{async get(){return storage},async set(value){Object.assign(storage,value)},async remove(key){delete storage[key]}}},
  tabs:{async query(){return [{id:7,active:true}]},async create(){}},
  scripting:{async executeScript(options){reads.push(options);return [{result:{origin:'https://chat.deepseek.com',token:'fixture-token-'+'x'.repeat(32)}}]}},
  cookies:{async getAll(query){cookies.push(query);return [{name:'session',value:'fixture',domain:'.deepseek.com'},{name:'google',value:'forbidden',domain:'.google.com'}]}}};
 vm.runInNewContext(fs.readFileSync(new URL('background.js',root),'utf8'),{chrome,Date,setTimeout:cb=>timers.push(cb)});
 await new Promise(resolve=>setImmediate(resolve));
 async function send(value,sender=own){let reply;const pending=message(value,sender,v=>reply=v);for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));return {reply,pending};}
 return {send,calls,reads,cookies,storage,timers,icons,badges,titles};
}
test('legacy Cline click sends credentials only to unchanged Cline host',async()=>{
 const f=await fixture();assert.equal((await f.send({action:'connect'})).reply.ok,true);
 const sent=f.calls.filter(v=>v.body.action==='connect');assert.equal(sent.length,1);assert.equal(sent[0].host,'cloud.aktalas.cline_dsw');
 assert.equal(sent[0].body.cookies,'session=fixture');assert.equal(f.calls.some(v=>v.host==='cloud.aktalas.owui_dsw'),false);
});
test('OWUI validates nonce before any credential read and never sends to Cline',async()=>{
 const f=await fixture();await f.send({action:'owui-flow',state:'a'.repeat(64),port:8080},{id,url:'https://chat.deepseek.com/',tab:{id:7}});
 assert.equal(f.reads.length,0);assert.equal(f.calls.length,0);
 await f.send({action:'connect-owui'});
 assert.equal(f.calls[0].host,'cloud.aktalas.owui_dsw');assert.equal(f.calls[0].body.action,'check');assert.equal(f.calls[0].body.token,undefined);
 const sent=f.calls.filter(v=>v.body.action==='connect');assert.equal(sent.length,1);assert.equal(sent[0].host,'cloud.aktalas.owui_dsw');
 assert.equal(sent[0].body.cookies,'session=fixture');assert.equal(f.reads[0].target.tabId,7);
 assert.equal(f.storage.owuiFlow,undefined);assert.equal(JSON.stringify(f.storage).includes('fixture-token'),false);
});
test('unapproved nonce never reads credentials',async()=>{
 const f=await fixture(false);await f.send({action:'owui-flow',state:'a'.repeat(64),port:8080},{id,url:'https://chat.deepseek.com/',tab:{id:7}});
 await f.send({action:'connect-owui'});
 assert.equal(f.reads.length,0);assert.equal(f.cookies.length,0);assert.equal(f.calls.some(v=>v.body.action==='connect'),false);
});
test('Google, foreign extension, unrelated local port and page-origin Cline requests are rejected',async()=>{
 const f=await fixture();
 for(const sender of [{id,url:'https://accounts.google.com/',tab:{id:7}},{id:'other',url:'https://chat.deepseek.com/',tab:{id:7}}])await f.send({action:'owui-flow',state:'a'.repeat(64),port:8080},sender);
 await f.send({action:'owui-flow',state:'a'.repeat(64),port:9000},{id,url:'https://chat.deepseek.com/',tab:{id:7}});
 await f.send({action:'connect'},{id,url:'https://chat.deepseek.com/',tab:{id:7}});
 assert.equal(f.calls.length,0);assert.equal(f.reads.length,0);
});

test('one explicit both-app click uses one browser session and two authorized channels',async()=>{
 const f=await fixture();
 await f.send({action:'owui-flow',state:'b'.repeat(64),port:8080},{id,url:'https://chat.deepseek.com/',frameId:0,tab:{id:7}});
 const value=(await f.send({action:'connect-both'})).reply;
 assert.equal(value.ok,true);assert.equal(value.inference_verified,false);
 assert.equal(f.reads.length,1);assert.equal(f.cookies.length,1);
 const connects=f.calls.filter(c=>c.body.action==='connect');
 assert.deepEqual(connects.map(c=>c.host),['cloud.aktalas.cline_dsw','cloud.aktalas.owui_dsw']);
 assert.equal(connects[0].body.token,connects[1].body.token);
 assert.equal(connects[0].body.cookies,connects[1].body.cookies);
 assert.equal(JSON.stringify(f.storage).includes('fixture-token'),false);
});

test('both-app selection needs OWUI consent before any credential read',async()=>{
 const f=await fixture();assert.equal((await f.send({action:'connect-both'})).reply.code,'START_IN_OWUI');
 assert.equal(f.reads.length,0);assert.equal(f.cookies.length,0);
 const denied=await fixture(false);
 await denied.send({action:'owui-flow',state:'a'.repeat(64),port:8080},{id,url:'https://chat.deepseek.com/',tab:{id:7}});
 assert.equal((await denied.send({action:'connect-both'})).reply.code,'OWUI_HANDOFF_REJECTED');
 assert.equal(denied.reads.length,0);assert.equal(denied.calls.some(c=>c.body.action==='connect'),false);
});

test('startup never reconnects or reads cookies from a saved pending flow',async()=>{
 const f=await fixture(true,{owuiFlow:{state:'c'.repeat(64),tab:7,expires:Date.now()+100000}});
 assert.equal(f.calls.length,0);assert.equal(f.reads.length,0);assert.equal(f.cookies.length,0);assert.equal(f.timers.length,0);
});

test('saved credentials and a blocked vendor account never produce a green-working badge',async()=>{
 const saved=await fixture();await saved.send({action:'status'});
 assert.equal(saved.badges.at(-1),'S');assert.ok(saved.icons.at(-1).path[16].includes('connecting'));
 const blocked=await fixture(true,{}, {ok:true,inference_ready:true,verified_at:Date.now(),inference_blocked:true});
 await blocked.send({action:'status'});
 assert.equal(blocked.badges.at(-1),'!');assert.ok(blocked.titles.at(-1).includes('ограничение'));
 assert.ok(blocked.icons.at(-1).path[16].includes('connecting'));
 assert.equal(blocked.calls.some(c=>c.body.action==='connect'),false);
});

test('subframe handoff cannot select an application or read credentials',async()=>{
 const f=await fixture();
 await f.send({action:'owui-flow',state:'a'.repeat(64),port:8080},{id,url:'https://chat.deepseek.com/',frameId:2,tab:{id:7}});
 assert.equal(f.calls.length,0);assert.equal(f.reads.length,0);assert.equal(f.storage.owuiFlow,undefined);
});
