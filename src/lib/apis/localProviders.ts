import { WEBUI_API_BASE_URL } from '$lib/constants';

export async function localProviderRequest(token: string, action: string, body?: object) {
	const response = await fetch(`${WEBUI_API_BASE_URL}/local-providers/dsw2api/${action}`, {
		method: body === undefined ? 'GET' : 'POST',
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
		...(body === undefined ? {} : { body: JSON.stringify(body) })
	});
	if (!response.ok) throw new Error('Local provider request failed');
	return response.json();
}
