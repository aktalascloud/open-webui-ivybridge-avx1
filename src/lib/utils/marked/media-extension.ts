import { mediaSource } from '../protectedFiles';

// Marked otherwise splits single-line media into opening/text/closing tokens.
// Keep a pair intact; HTMLToken still sanitizes it and applies URL/auth checks.
export function mediaExtension(level: 'block' | 'inline') {
	return {
		name: level === 'block' ? 'pairedMediaBlock' : 'pairedMediaInline',
		level,
		start: (src: string) => level === 'block'
			? src.search(/(?:^|\n)[ \t]{0,3}<(?:video|audio)\b/i)
			: src.search(/<(?:video|audio)\b/i),
		tokenizer(src: string) {
			const match = src.match(/^<(video|audio)\b[^>]*>[\s\S]*?<\/\1>/i);
			if (!match || !mediaSource(match[0], match[1].toLowerCase() as 'video' | 'audio')) return;
			return { type: 'html', raw: match[0], text: match[0], block: level === 'block' };
		}
	};
}
