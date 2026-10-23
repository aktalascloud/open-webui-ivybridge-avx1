import assert from 'node:assert/strict';
import { test } from 'node:test';
import { __assistantMicOrigin as mic, __assistantVoiceBudget as voice } from '../src/lib/utils/assistantCompatibility.js';

test('microphone provenance stays on the exact current draft and clears on replacement', () => {
  let callbacks = {};
  let node = {textContent: 'voice', innerText: 'voice', contains: () => true, addEventListener: (name, handler) => callbacks[name] = handler};
  globalThis.document = {getElementById: () => node};
  globalThis.getSelection = () => ({isCollapsed: false, anchorNode: node, focusNode: node, toString: () => 'voice'});
  mic.mark('voice');
  assert.deepEqual(mic.peek('voice'), {input_source: 'microphone'});
  assert.equal(mic.peek('unrelated typed message'), undefined);
  mic.change('voice edited');
  assert.deepEqual(mic.peek('voice edited'), {input_source: 'microphone'});
  callbacks.beforeinput();
  assert.equal(mic.peek('voice edited'), undefined);
  mic.mark('voice');
  node = {...node};
  assert.equal(mic.peek('voice'), undefined);
});

test('voice budget groups reports, stays message-scoped and preserves full text', () => {
  voice.start('one', 1);
  voice.start('two', 1);
  assert.equal(voice.hold('one', '1С: выручка 100'), true);
  assert.equal(voice.hold('two', 'Hello'), false);
  assert.equal(voice.hold('one', 'Прибыль 20'), true);
  const report = voice.finish('one', 'chat-one');
  assert.equal(report.text, '1С: выручка 100 Прибыль 20');
  assert.equal(report.options.speech_message_id, 'one');
  assert.equal(report.options.speech_chat_id, 'chat-one');
  assert.equal(voice.finish('two', 'chat-two'), null);
  assert.equal(voice.finish('one', 'chat-one'), null);
  assert.equal(voice.emoji('спасибо'), '😊');
});
