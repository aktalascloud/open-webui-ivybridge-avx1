<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { user } from '$lib/stores';
	import { protectedFileUrl, protectedFileBlob } from '$lib/utils/protectedFiles';
	export let src = '';
	export let kind: 'video' | 'audio' = 'video';
	const i18n: any = getContext('i18n');
	let mounted = false;
	let resolved = '';
	let error = '';
	let controller: AbortController | undefined;
	let objectUrl = '';
	let generation = 0;

	function release() {
		controller?.abort();
		if (objectUrl) URL.revokeObjectURL(objectUrl);
		objectUrl = '';
		resolved = '';
	}

	async function load(value: string, actor: string) {
		const current = ++generation;
		release();
		error = '';
		const file = protectedFileUrl(value, window.location.origin);
		if (!file) {
			try {
				const url = new URL(value, window.location.origin);
				if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw 0;
				if (url.pathname.startsWith('/api/v1/files/')) throw 0;
				resolved = url.href;
			} catch { error = 'Invalid media URL'; }
			return;
		}
		if (!actor) { error = 'Sign in to view this file'; return; }
		controller = new AbortController();
		try {
			const { blob } = await protectedFileBlob(file, localStorage.getItem('token') ?? '', controller.signal);
			if (current !== generation) return;
			if (!blob.type.startsWith(kind + '/')) throw new Error('Unexpected media type');
			objectUrl = URL.createObjectURL(blob);
			resolved = objectUrl;
		} catch (reason) {
			if (current === generation && !controller?.signal.aborted) error = 'File unavailable or access denied';
		}
	}
	onMount(() => { mounted = true; });
	onDestroy(() => { generation++; release(); });
	$: if (mounted) load(src, $user?.id ?? '');
</script>

{#if error}
	<p role="status" class="text-sm text-gray-500">{$i18n.t(error)}</p>
{:else if resolved}
	{#if kind === 'video'}
		<!-- svelte-ignore a11y-media-has-caption -->
		<video class="w-full my-2" src={resolved} controls playsinline preload="metadata" title={$i18n.t('Video player')}></video>
	{:else}
		<audio class="w-full my-2" src={resolved} controls preload="metadata" title={$i18n.t('Audio player')}></audio>
	{/if}
{:else}
	<p role="status" class="text-sm text-gray-500">{$i18n.t('Loading...')}</p>
{/if}
