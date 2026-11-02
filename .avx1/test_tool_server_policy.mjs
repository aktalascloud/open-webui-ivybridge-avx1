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

test('actual side-chat send isolates mic metadata and cannot alias an explicit server id to its index', async () => {
  const source=fs.readFileSync(new URL('../src/lib/components/chat/ChatTabs/SideChat.svelte',import.meta.url),'utf8');
  const start=source.indexOf('\tconst send =');
  const end=source.indexOf('\tconst stop =',start);
  assert.ok(start>=0&&end>start);
  const body=stripTypeScriptTypes(source.slice(start,end));
  for(const sideVoice of [false,true]){
    const nodes=new Map();
    for(const id of ['chat-input','side-fixture'])nodes.set(id,{textContent:'same',addEventListener(){}});
    globalThis.document={getElementById:id=>nodes.get(id)};
    mic.mark('same');
    if(sideVoice)mic.mark('same','side-fixture');
    let payload;
    const context={sideChatAllowed:true,draft:'same',files:[],busy:false,atSelectedModel:{id:'model'},
      selectedModels:['model'],error:'',id:'temporary-fixture',inputId:'side-fixture',
      $i18n:{t:value=>value},$socket:{connected:true,id:'fixture-socket'},sideModelId:'model',
      tick:async()=>{},input:{uploadPendingFiles:async()=>true,setText(){}},uuidv4:()=>String(Math.random()),
      messages:[],context:[],params:{},toolApprovalMode:'prompt',selectedToolIds:['direct_server:kept','direct_server:0'],
      selectedSkillIds:[],selectedFilterIds:[],autoScroll:false,scroll:async()=>{},request:null,
      localStorage:{token:'synthetic'},$models:[{id:'model'}],$config:{features:{enable_tool_servers:true}},
      $toolServers:[{id:'wrong',url:'https://wrong.invalid'},{id:'kept',url:'https://kept.invalid'}],
      $terminalServers:[],$selectedTerminalId:null,$settings:{},system:'',
      webSearchEnabled:false,imageGenerationEnabled:false,codeInterpreterEnabled:false,
      isRasterImageContentType:()=>false,__assistantMicOrigin:mic,isSelectedDirectToolServer,
      generateOpenAIChatCompletion:async(_token,data)=>{payload=data;return{};},getErrorMessage:String};
    const send=new Function('context',`with(context){${body};return send;}`)(context);
    await send();
    assert.deepEqual(payload.tool_servers,[{id:'kept',url:'https://kept.invalid'}]);
    assert.deepEqual(payload.user_message.meta,sideVoice?{input_source:'microphone'}:undefined);
    assert.deepEqual(mic.peek('same'),{input_source:'microphone'});
  }
});
