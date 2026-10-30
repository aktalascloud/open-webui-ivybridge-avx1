import fs from 'node:fs';
import assert from 'node:assert/strict';
import {test} from 'node:test';
const source=fs.readFileSync(new URL('../src/lib/components/chat/Chat.svelte',import.meta.url),'utf8');
const body=source.match(/const saveControls = async \(models: string\[\] \| null = null\) => \{([\s\S]*?)\n\t\};/)?.[1];
assert.ok(body,'Actual saveControls callback must be found');
const AsyncFunction=Object.getPrototypeOf(async()=>{}).constructor;
async function execute(overrides={},models=null){
 const calls=[];
 const context={models,isShared:false,$chatId:'saved',$temporaryChatEnabled:false,chat:{id:'saved',chat:{models:['original'],files:[]}},
  selectedModels:['fallback'],$models:[{id:'fallback'}],chatFiles:[],equal:(a,b)=>JSON.stringify(a)===JSON.stringify(b),
  localStorage:{token:'fixture'},console:{error(){}},updateChatById:async(token,id,params)=>{calls.push(params);return null;},...overrides};
 await new AsyncFunction(...Object.keys(context),body)(...Object.values(context));return calls;
}
test('temporary provider outage cannot autosave fallback over the saved model',async()=>{assert.equal((await execute()).length,0);});
test('file edits during outage save files without rewriting the model',async()=>{
 const calls=await execute({chatFiles:[{id:'file'}]});assert.equal(calls.length,1);assert.deepEqual(calls[0].files,[{id:'file'}]);assert.equal(calls[0].models,undefined);
});
test('explicit model selection still saves when original is available',async()=>{
 const calls=await execute({},['fallback']);assert.deepEqual(calls[0].models,['fallback']);
});
test('shared/read-only chat causes no autosave',async()=>{assert.equal((await execute({isShared:true})).length,0);});

test('background provider recovery does not autosave fallback either',async()=>{assert.equal((await execute({$models:[{id:'original'},{id:'fallback'}]})).length,0);});
