import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolveModelAvatar } from '../src/lib/utils/voice-avatar.ts';

const fallback = { file_id: 'default', states: {}, gestures: [] };
test('blank and provider-based new cards inherit the default', () => {
  assert.deepEqual(resolveModelAvatar(null, false, fallback), fallback);
  assert.deepEqual(resolveModelAvatar({}, false, fallback), fallback);
  assert.notEqual(resolveModelAvatar({}, false, fallback), fallback);
});
test('editing existing unassigned cards does not change them', () => {
  assert.equal(resolveModelAvatar({}, true, fallback), null);
});
test('explicit sphere and custom choices survive create, clone and edit', () => {
  const custom = { file_id: 'custom' };
  for (const editing of [false, true]) {
    assert.equal(resolveModelAvatar({ voice_avatar: null }, editing, fallback), null);
    assert.deepEqual(resolveModelAvatar({ voice_avatar: custom }, editing, fallback), custom);
  }
});
