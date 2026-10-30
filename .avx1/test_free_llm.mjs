import {test} from 'node:test';
import assert from 'node:assert/strict';
import {freeLlmPreset,FREE_LLM_CATALOG} from '../src/lib/utils/freeLlm.js';

test('one anonymous preset exposes three fixed models without changing the catalog',()=>{
 const preset=freeLlmPreset();
 assert.equal(preset.key,'');assert.equal(preset.auth_type,'none');
 assert.equal(preset.forward_cookies,false);assert.deepEqual(preset.headers,{});
 assert.equal(preset.provider,'freellm');assert.equal(preset.prefix_id,'FreeLLM');
 assert.equal(preset.model_ids.length,3);assert.equal(FREE_LLM_CATALOG.hourly_requests_per_ip,200);
 assert.equal(new Set(FREE_LLM_CATALOG.models.map(m=>m.vendor)).size,3);
 preset.model_ids.length=0;assert.equal(freeLlmPreset().model_ids.length,3);
 assert.equal(FREE_LLM_CATALOG.research_sources.length,3);
});
