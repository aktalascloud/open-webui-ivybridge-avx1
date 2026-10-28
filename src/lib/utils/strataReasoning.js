// Composer preferences are scoped to a model, never injected into other providers.
export const STRATA_REASONING_LEVELS = ['auto', 'none', 'low', 'medium', 'high', 'xhigh', 'ultra', 'adaptive'];

export function isStrataModel(model) {
  if (!model || model.pipe || model.direct) return false;
  return String(model.owned_by ?? '').toLowerCase() === 'strata' ||
    model.info?.meta?.backend === 'strata' ||
    /^strata(?:[.:/_-]|$)/i.test(model.id ?? '') || /^strata\b/i.test(model.name ?? '');
}

export function selectedStrataReasoning(model, preferences = {}) {
  const value = preferences?.[model?.id];
  if (value === 'ultra' && !hasStrataAuthorTemplate(model)) return 'auto';
  if (value === 'adaptive' && !hasStrataAdaptiveProfile(model)) return 'auto';
  return isStrataModel(model) && STRATA_REASONING_LEVELS.includes(value) ? value : 'auto';
}

export function hasStrataAuthorTemplate(model) {
  const info = model?.info;
  const meta = info?.meta;
  const identity = [model?.id, model?.name, info?.id, info?.name, info?.base_model_id].filter(Boolean).join(' ').toLowerCase();
  return isStrataModel(model) && /david[._ -]?au/.test(identity) && /qwen[._ -]?3[._ -]?8/.test(identity) &&
    /next/.test(identity) && !/swift/.test(identity) && meta?.strata_reasoning_profile === 'davidau' &&
    meta.strata_reasoning_family === 'qwen3.8-next' &&
    meta.strata_reasoning_model_id === model.id &&
    (meta.strata_reasoning_base_model_id ?? null) === (info.base_model_id ?? null);
}

export function hasStrataAdaptiveProfile(model) {
  return hasStrataAuthorTemplate(model) && model.info?.meta?.strata_adaptive_enabled === true;
}

function object(value) {
  if (typeof value === 'string') {
    try { value = JSON.parse(value); } catch { return {}; }
  }
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

export function applyStrataReasoning(params, model, preferences) {
  const effort = selectedStrataReasoning(model, preferences);
  if (effort === 'auto') return params;
  const transport = ['ultra', 'adaptive'].includes(effort) ? 'xhigh' : effort;
  const custom = object(params?.custom_params);
  const template = object(custom.chat_template_kwargs ?? params?.chat_template_kwargs);
  return {
    ...params,
    reasoning_effort: transport,
    custom_params: {
      ...custom,
      reasoning_effort: transport,
      ...(hasStrataAuthorTemplate(model) ? { _strata_reasoning_mode: effort } : {}),
      chat_template_kwargs: {
        ...template,
        ...(Object.hasOwn(template, 'reasoning_effort') ? { reasoning_effort: transport } : {}),
        enable_thinking: effort !== 'none'
      }
    }
  };
}
