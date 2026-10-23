import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { resolveLocalizedPromptSuggestions as resolve } from '../src/lib/utils/localizedContent.ts';
const ru = JSON.parse(fs.readFileSync(new URL('../src/lib/i18n/locales/ru-RU/translation.json', import.meta.url), 'utf8'));
const t = (key) => ru[key] || key;
test('stored stock English suggestions render in Russian without changing user records', () => {
 const original = resolve(null, null, 'en-US');
 const before = JSON.stringify(original);
 const localized = resolve(original, null, 'ru-RU', t);
 assert.equal(JSON.stringify(original), before);
 assert.equal(localized.length, 6);
 for (const prompt of localized) {
  assert.match(prompt.title.join(' '), /[А-Яа-яЁё]/u);
  assert.match(prompt.content, /[А-Яа-яЁё]/u);
 }
});
test('custom prompts, explicit locale overrides and disabled suggestions are preserved', () => {
 const stock = resolve(null, null, 'en-US')[0];
 const custom = { ...stock, id: 'custom', title: ['My title', 'My subtitle'] };
 assert.strictEqual(resolve([custom], null, 'ru-RU', t)[0], custom);
 assert.deepEqual(resolve([], null, 'ru-RU', t), []);
 const explicit = [{title: ['Авторский', 'запрос'], content: 'Текст пользователя'}];
 assert.strictEqual(resolve(null, {'ru-RU': explicit}, 'ru-RU', t), explicit);
});
