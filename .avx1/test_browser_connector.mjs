import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';

const root=new URL('../backend/open_webui/providers/browser_connector/',import.meta.url);
test('connector is least-scope and cannot collect Google/password data',()=>{
 const manifest=JSON.parse(fs.readFileSync(new URL('manifest.json',root),'utf8'));
 assert.deepEqual(manifest.permissions,['cookies','webRequest','storage']);
 assert.deepEqual(manifest.host_permissions,['https://chat.deepseek.com/*','http://127.0.0.1/*']);
 assert.equal(manifest.content_scripts[0].run_at,'document_start');
 assert.equal(manifest.update_url,undefined);
});
test('only a registered flow sends credentials to the fixed local callback; exact domain only',async()=>{
 const listeners={};const storage={};const posted=[];const cookieQueries=[];const closed=[];
 const chrome={runtime:{id:'fixture-id',onMessage:{addListener:f=>listeners.message=f}},storage:{session:{
  async get(key){return {[key]:storage[key]}},async set(value){Object.assign(storage,value)},async remove(key){delete storage[key]}
 }},webRequest:{onBeforeSendHeaders:{addListener:(f,s)=>{listeners.before=f;assert.deepEqual(JSON.parse(JSON.stringify(s.urls)),['https://chat.deepseek.com/api/v0/*'])}},onCompleted:{addListener:f=>listeners.complete=f},onErrorOccurred:{addListener:f=>listeners.error=f}},
 cookies:{async getAll(query){cookieQueries.push(query);return [{name:'fixture',value:'cookie'}]}},tabs:{async remove(id){closed.push(id)}}};
 const context={chrome,Map,Date,fetch:async(url,options)=>{posted.push({url,options});return {ok:true,async json(){return {connected:true}}}}};
 vm.runInNewContext(fs.readFileSync(new URL('background.js',root),'utf8'),context);
 await Promise.resolve();
 listeners.before({requestId:'unregistered',requestHeaders:[{name:'Authorization',value:'Bearer '+'x'.repeat(40)}]});
 listeners.complete({requestId:'unregistered',statusCode:200});await new Promise(r=>setImmediate(r));assert.equal(posted.length,0);
 listeners.message({type:'owui-login',state:'a'.repeat(64),port:8080},{url:'https://evil.invalid',tab:{id:1}});
 assert.equal(storage.flow,undefined);
 listeners.message({type:'owui-login',state:'a'.repeat(64),port:8080},{url:'https://chat.deepseek.com/',tab:{id:7}});
 listeners.before({requestId:'owned',requestHeaders:[{name:'Authorization',value:'Bearer '+'x'.repeat(40)}]});
 listeners.complete({requestId:'owned',statusCode:200});await new Promise(r=>setImmediate(r));
 assert.equal(posted.length,1);assert.equal(posted[0].url,'http://127.0.0.1:8080/api/v1/local-providers/dsw2api/browser/callback');
 assert.equal(posted[0].options.credentials,'omit');assert.equal(posted[0].options.headers['X-OWUI-Connector'],'fixture-id');
 assert.deepEqual(JSON.parse(JSON.stringify(cookieQueries)),[{url:'https://chat.deepseek.com/api/v0/users/current'}]);
 assert.deepEqual(closed,[7]);assert.equal(storage.flow,undefined);
 listeners.before({requestId:'after',requestHeaders:[{name:'Authorization',value:'Bearer '+'z'.repeat(40)}]});
 listeners.complete({requestId:'after',statusCode:200});await new Promise(r=>setImmediate(r));assert.equal(posted.length,1);
});
