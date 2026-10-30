import catalog from '../../../backend/open_webui/utils/free_llm_catalog.json' with { type: 'json' };

export const FREE_LLM_CATALOG = catalog;
export function freeLlmPreset() {
  return {
    url: catalog.base_url, key: '', provider: 'freellm',
    auth_type: 'none', prefix_id: catalog.prefix_id,
    model_ids: catalog.models.map(model => model.id),
    forward_cookies: false, headers: {}, api_type: '', connection_type: 'external'
  };
}
