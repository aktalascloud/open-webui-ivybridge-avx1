import assert from 'node:assert/strict';
import { test } from 'node:test';
import { applyStrataReasoning, isStrataModel, selectedStrataReasoning } from '../src/lib/utils/strataReasoning.js';

const strata = {id: 'strata.test-model', name: 'Strata DavidAU Qwen3.8-Flash-Next', owned_by: 'openai'};
test('Strata aliases are detected without enabling controls for another provider', () => {
  assert.equal(isStrataModel(strata), true);
  assert.equal(isStrataModel({id: 'model', owned_by: 'strata'}), true);
  assert.equal(isStrataModel({id: 'other', name: 'Other provider'}), false);
  assert.equal(isStrataModel({...strata, pipe: true}), false);
});
test('automatic mode and other models preserve existing chat parameters by identity', () => {
  const params = {temperature: .7, reasoning_effort: 'medium', seed: 4};
  assert.equal(applyStrataReasoning(params, strata, {}), params);
  assert.equal(applyStrataReasoning(params, strata, {[strata.id]: 'auto'}), params);
  assert.equal(applyStrataReasoning(params, {id:'other'}, {[strata.id]:'low'}), params);
  assert.equal(selectedStrataReasoning(strata, {[strata.id]:'unsupported'}), 'auto');
});
test('every explicit level reaches both standard and template fields without mutating input', () => {
  const params = {temperature: .7, top_p:.95, custom_params:{min_p:.05,
    reasoning_effort:'high', chat_template_kwargs:'{"enable_thinking":false,"reasoning_effort":"high","keep":7}'}};
  const original = structuredClone(params);
  for (const level of ['none','low','medium','high','xhigh']) {
    const out = applyStrataReasoning(params, strata, {[strata.id]:level});
    assert.equal(out.reasoning_effort, level);
    assert.equal(out.custom_params.reasoning_effort, level);
    assert.equal(out.custom_params.chat_template_kwargs.reasoning_effort, level);
    assert.equal(out.custom_params.chat_template_kwargs.enable_thinking, level !== 'none');
    assert.equal(out.custom_params.chat_template_kwargs.keep, 7);
    assert.equal(out.custom_params.min_p, .05);
    assert.equal(out.temperature, .7);
  }
  assert.deepEqual(params, original);
});
test('a different selected model never receives the Strata override', () => {
  const params={custom_params:{keep:true}};
  assert.equal(applyStrataReasoning(params, {id:'other'}, {[strata.id]:'none'}),params);
});
test('Ultra is an explicit author mode; High/XHigh keep their standard transport values', () => {
  const author={...strata,info:{meta:{strata_reasoning_profile:'davidau',strata_reasoning_family:'qwen3.8-next',strata_reasoning_model_id:strata.id}}};
  for (const level of ['high','xhigh','ultra']) {
    const out=applyStrataReasoning({},author,{[author.id]:level});
    assert.equal(out.reasoning_effort,level==='ultra'?'xhigh':level);
    assert.equal(out.custom_params._strata_reasoning_mode,level);
  }
  assert.equal(selectedStrataReasoning(strata,{[strata.id]:'ultra'}),'auto');
});
test('Adaptive is independently gated and sends a real task-router control', () => {
  const model={...strata,info:{meta:{strata_reasoning_profile:'davidau',strata_reasoning_family:'qwen3.8-next',strata_reasoning_model_id:strata.id,strata_adaptive_enabled:true}}};
  const params=applyStrataReasoning({},model,{[model.id]:'adaptive'});
  assert.equal(params.reasoning_effort,'xhigh');
  assert.equal(params.custom_params._strata_reasoning_mode,'adaptive');
  assert.equal(params.custom_params.chat_template_kwargs.enable_thinking,true);
  assert.equal(selectedStrataReasoning(strata,{[strata.id]:'adaptive'}),'auto');
});

test('author modes reject another alias, family or rebound base while sampling stays unchanged', () => {
 const model={...strata,info:{base_model_id:'qwen-next',meta:{strata_reasoning_profile:'davidau',strata_reasoning_family:'qwen3.8-next',strata_reasoning_model_id:strata.id,strata_reasoning_base_model_id:'qwen-next',strata_adaptive_enabled:true}}};
 const params={temperature:.6,top_p:.9,seed:42};
 for(const candidate of [{...model,id:'strata.other'},{...model,info:{...model.info,base_model_id:'another-model'}},{...model,info:{...model.info,meta:{...model.info.meta,strata_reasoning_family:'deepseek'}}}]) {
   for(const level of ['ultra','adaptive']) assert.equal(applyStrataReasoning(params,candidate,{[candidate.id]:level}),params);
 }
 assert.equal(applyStrataReasoning(params,model,{[model.id]:'ultra'}).temperature,.6);
});

test('Swift cannot acquire author controls even through copied enrollment metadata', () => {
 const id='strata.davidau-qwen3.8-next-swift';const model={...strata,id,name:'Strata Swift Qwen3.8-Next',info:{meta:{strata_reasoning_profile:'davidau',strata_reasoning_family:'qwen3.8-next',strata_reasoning_model_id:id,strata_adaptive_enabled:true}}};
 for(const mode of ['ultra','adaptive']) assert.equal(selectedStrataReasoning(model,{[model.id]:mode}),'auto');
 const params={temperature:.55,top_p:.8};assert.equal(applyStrataReasoning(params,model,{[model.id]:'ultra'}),params);
});
