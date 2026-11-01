import { afterEach, describe, expect, it, vi } from 'vitest';
import { mediaSource, protectedFileUrl, protectedFileBlob } from './protectedFiles';

const origin = 'http://localhost:8080';
const path = '/api/v1/files/owned-file/content';
afterEach(() => vi.unstubAllGlobals());

describe('authenticated generated media', () => {
	it('reads attribute, source-child and legacy inner-URL media', () => {
		expect(mediaSource(`<video src="${path}"></video>`, 'video')).toBe(path);
		expect(mediaSource(`<video>${path}</video>`, 'video')).toBe(path);
		expect(mediaSource(`<video><source src="${path}"></video>`, 'video')).toBe(path);
		expect(mediaSource(`<audio>${path}</audio>`, 'audio')).toBe(path);
	});
	it('allows only local file content URLs without credential parameters', () => {
		expect(protectedFileUrl(path, origin)?.pathname).toBe(path);
		for (const value of ['https://other.test'+path, 'http://user:pass@localhost:8080'+path,
			path+'?token=private', '/api/v1/files/%2e%2e/content', 'javascript:alert(1)']) {
			expect(protectedFileUrl(value, origin)).toBeNull();
		}
	});
	it('uses a header and cookies, never a bearer in the URL', async () => {
		vi.stubGlobal('window', { location: { origin } });
		const request = vi.fn().mockResolvedValue(new Response('mp4', {
			headers: { 'content-type':'video/mp4', 'content-disposition':"attachment; filename*=UTF-8''demo%20video.mp4" }
		}));
		vi.stubGlobal('fetch', request);
		const result = await protectedFileBlob(new URL(path, origin), 'fixture-token');
		expect(result.name).toBe('demo video.mp4');
		expect(request.mock.calls[0][0]).toBe(origin+path);
		expect(request.mock.calls[0][1]).toMatchObject({ headers: { Authorization:'Bearer fixture-token' }, credentials:'include', redirect:'error' });
	});
	it('does not send credentials outside the approved origin', async () => {
		vi.stubGlobal('window', { location: { origin } });
		const request = vi.fn(); vi.stubGlobal('fetch', request);
		await expect(protectedFileBlob(new URL(path,'https://other.test'),'fixture-token')).rejects.toThrow('Invalid file URL');
		expect(request).not.toHaveBeenCalled();
	});
	it('does not turn access denial into a playable blob', async () => {
		vi.stubGlobal('window', { location: { origin } });
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('denied',{status:403})));
		await expect(protectedFileBlob(new URL(path,origin),'fixture-token')).rejects.toThrow('403');
	});
	it('rejects an oversized response before buffering it', async () => {
		vi.stubGlobal('window', { location: { origin } });
		vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('small',{headers:{'content-length':String(300*1024*1024)}})));
		await expect(protectedFileBlob(new URL(path,origin),'fixture-token')).rejects.toThrow('size limit');
	});
});
