// Protected file URLs stay token-free; credentials are sent only to this origin.
export function protectedFileUrl(value: string, origin: string): URL | null {
	try {
		const base = new URL(origin);
		const url = new URL(value, base);
		if (url.origin !== base.origin || url.username || url.password || url.hash) return null;
		if (!/^\/api\/v1\/files\/[A-Za-z0-9_-]+\/content$/.test(url.pathname)) return null;
		if ([...url.searchParams.keys()].some((key) => key !== 'download')) return null;
		return url;
	} catch { return null; }
}

export function mediaSource(html: string, kind: 'video' | 'audio'): string {
	const tag = html.match(new RegExp(`<${kind}\\b([^>]*)>([\\s\\S]*?)</${kind}>`, 'i'));
	if (!tag) return '';
	const attribute = tag[1].match(/\bsrc\s*=\s*["']([^"']+)["']/i);
	const child = tag[2].match(/<source\b[^>]*\bsrc\s*=\s*["']([^"']+)["']/i);
	return (attribute?.[1] ?? child?.[1] ?? tag[2].trim()).replaceAll('&amp;', '&');
}

export async function protectedFileBlob(url: URL, token: string, signal?: AbortSignal) {
	if (!protectedFileUrl(url.href, window.location.origin)) throw new Error('Invalid file URL');
	const response = await fetch(url.href, {
		headers: token ? { Authorization: `Bearer ${token}` } : {},
		credentials: 'include', redirect: 'error', cache: 'no-store', signal
	});
	if (!response.ok) throw new Error(`File HTTP ${response.status}`);
	const limit = 256 * 1024 * 1024;
	if (Number(response.headers.get('content-length')) > limit) {
		await response.body?.cancel();
		throw new Error('File exceeds preview size limit');
	}
	const blob = await response.blob();
	if (blob.size > limit) throw new Error('File exceeds preview size limit');
	const disposition = response.headers.get('content-disposition') ?? '';
	let name = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1] ??
		disposition.match(/filename\s*=\s*"?([^";]+)/i)?.[1] ??
		(blob.type.startsWith('video/') ? 'video.mp4' : 'download');
	try { name = decodeURIComponent(name); } catch { /* Keep the original filename. */ }
	name = name.replace(/[\\/\x00-\x1f]/g, '_').slice(0, 200);
	return { blob, name };
}

export async function downloadProtectedFile(url: URL, token: string) {
	const { blob, name } = await protectedFileBlob(url, token);
	const objectUrl = URL.createObjectURL(blob);
	const anchor = document.createElement('a');
	anchor.href = objectUrl;
	anchor.download = name;
	document.body.appendChild(anchor);
	anchor.click();
	anchor.remove();
	setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}
