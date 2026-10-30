// PR27145 adaptation: match the backend's suffix allow/block semantics.
export function filterToolServerSpecs(specs, rawFilter) {
  if (rawFilter == null || rawFilter === '') return specs;
  const entries = typeof rawFilter === 'string' ? rawFilter.split(',') : rawFilter;
  if (!Array.isArray(entries) || entries.some((value) => typeof value !== 'string')) return [];
  const clean = (value) => value.trim().replace(/^["']+|["']+$/g, '').trim();
  const allow = [], block = [];
  for (const raw of entries) {
    const entry = clean(raw);
    const blocked = entry.startsWith('!');
    const value = clean(blocked ? entry.slice(1) : entry);
    if (value) (blocked ? block : allow).push(value);
  }
  return specs.filter((spec) => {
    const name = spec?.name;
    return typeof name === 'string' && (!allow.length || allow.some((value) => name.endsWith(value))) &&
      !block.some((value) => name.endsWith(value));
  });
}

export function directToolServerKey(server, index) {
  return `direct_server:${server?.id ?? index}`;
}

export function isSelectedDirectToolServer(server, index, selectedIds) {
  const key = String(server?.id ?? index);
  return selectedIds.some((id) => String(id) === key);
}
