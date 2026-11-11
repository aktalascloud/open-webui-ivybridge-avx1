import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
import {filterToolServerSpecs, directToolServerKey, isSelectedDirectToolServer} from '../src/lib/utils/toolServerPolicy.js';
import {__assistantMicOrigin as mic} from '../src/lib/utils/assistantCompatibility.js';

const specs=[{name:'tool_search'},{name:'tool_delete'},{name:'tool_admin_delete'}];
test('suffix allow/block and quoted entries match backend policy without mutating schemas',()=>{
  const before=JSON.stringify(specs);
  assert.deepEqual(filterToolServerSpecs(specs,'search, delete, !admin_delete'),specs.slice(0,2));
  assert.deepEqual(filterToolServerSpecs(specs,[' "!delete" ',' search ']),specs.slice(0,1));
  assert.deepEqual(filterToolServerSpecs(specs,'!delete'),specs.slice(0,1));
  assert.equal(JSON.stringify(specs),before);
});
test('malformed filter does not expose every function',()=>{
  assert.deepEqual(filterToolServerSpecs(specs,{}),[]);
  assert.deepEqual(filterToolServerSpecs(specs,[4]),[]);
  assert.deepEqual(filterToolServerSpecs(specs,''),specs);
});
test('stable explicit id survives reorder and cannot alias an array index',()=>{
  const server={id:'123abc'};
  assert.equal(directToolServerKey(server,0),directToolServerKey(server,7));
  assert.equal(isSelectedDirectToolServer(server,0,['123abc']),true);
  assert.equal(isSelectedDirectToolServer(server,123,[123]),false);
  assert.equal(isSelectedDirectToolServer({id:'01'},3,['01']),true);
  assert.equal(isSelectedDirectToolServer({},3,['3']),true);
});
test('actual discovery function filters advertised tools and preserves connection identity',async()=>{
  const source=fs.readFileSync(new URL('../src/lib/apis/index.ts',import.meta.url),'utf8');
  const start=source.indexOf('export const getToolServersData =');
  const end=source.indexOf('export const executeToolServer =',start);
  assert.ok(start>=0&&end>start);
  const body=stripTypeScriptTypes(source.slice(start,end).replace('export const','const'));
  const discover=new Function('get','config','getToolServerData','convertOpenApiToToolPayload',
    'filterToolServerSpecs','fetch','TOOL_SERVER_FETCH_TIMEOUT','localStorage',
    body+';return getToolServersData;')(
      ()=>({features:{enable_tool_servers:true}}),{},async()=>({paths:{},info:{title:'Fixture'}}),
      ()=>specs,filterToolServerSpecs,async()=>({ok:false}),1000,{token:'fixture'});
  const result=await discover([{id:'123abc',url:'https://fixture.invalid',path:'/openapi.json',auth_type:'none',
    config:{enable:true,function_name_filter_list:'search'}}]);
  assert.equal(result.length,1);
  assert.equal(result[0].id,'123abc');assert.deepEqual(result[0].specs,[specs[0]]);
});

test('shared side-chat composer preserves mic provenance and exact tool IDs', () => {
  const source = fs.readFileSync(new URL('../src/lib/components/chat/Chat.svelte', import.meta.url), 'utf8');
  const side = fs.readFileSync(new URL('../src/lib/components/chat/Tabs/SideChat.svelte', import.meta.url), 'utf8');
  assert.match(side, /side=\{true\}/);
  const micExpression = source.match(/const microphoneMeta = (.*);/)[1];
  const select = source.match(/\.filter\(\s*\(server, idx\) => isSelectedDirectToolServer\(server, idx, toolServerIds\)\s*\)/)[0];
  const provenance = new Function('__assistantMicOrigin', 'userPrompt', 'inputId', 'return ' + micExpression);
  const filtered = new Function('servers', 'isSelectedDirectToolServer', 'toolServerIds', 'return servers' + select);
  const nodes = new Map(['chat-input', 'side-fixture'].map(id => [id, {textContent:'same', addEventListener(){}}]));
  globalThis.document = {getElementById:id => nodes.get(id)};
  mic.mark('same', 'chat-input');
  assert.equal(provenance(mic, 'same', 'side-fixture'), undefined);
  mic.mark('same', 'side-fixture');
  assert.deepEqual(provenance(mic, 'same', 'side-fixture'), {input_source:'microphone'});
  assert.deepEqual(provenance(mic, 'same', 'chat-input'), {input_source:'microphone'});
  assert.deepEqual(filtered([{id:'wrong',url:'https://wrong.invalid'}, {id:'kept',url:'https://kept.invalid'}], isSelectedDirectToolServer, ['kept','0']), [{id:'kept',url:'https://kept.invalid'}]);
});
