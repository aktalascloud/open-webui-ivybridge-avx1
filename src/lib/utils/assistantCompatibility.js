// Copyright (c) 2026 aktalascloud. Distributed under the repository license.
/* assistant microphone input v1 */
const __assistantMicOrigin = (() => {
  const drafts = new WeakMap(), bound = new WeakSet();
  const editor = () => document.getElementById("chat-input");
  const normal = value => String(value || "").replace(/\s+/g, " ").trim();
  return {
    clear() { const node = editor(); if (node) drafts.delete(node); },
    mark(text) {
      const node = editor(), draft = String(text || "");
      if (!node || !draft.trim()) return;
      drafts.set(node, draft);
      if (bound.has(node)) return;
      bound.add(node);
      node.addEventListener("beforeinput", () => {
        const selection = globalThis.getSelection();
        const all = normal(node.innerText || node.textContent);
        if (all && selection && !selection.isCollapsed &&
            node.contains(selection.anchorNode) && node.contains(selection.focusNode) &&
            normal(selection.toString()) === all) drafts.delete(node);
      });
      node.addEventListener("input", () => {
        if (!normal(node.textContent)) drafts.delete(node);
      });
    },
    change(text) {
      const node = editor();
      if (!node || !drafts.has(node)) return;
      const draft = String(text || "");
      if (draft.trim()) drafts.set(node, draft); else drafts.delete(node);
    },
    peek(text) {
      const node = editor(), draft = node && drafts.get(node);
      const content = String(text || "");
      if (!draft || (content !== draft && !content.startsWith(
          draft + "\n\nSelected note text for replace_note_content operations:\n"))) return;
      return {input_source: "microphone"};
    }
  };
})();
/* assistant voice budget v1 */
const __assistantVoiceBudget = (() => {
  const states = new Map();
  const cost = text => String(text || "").length + 6 * (String(text || "").match(/\d/g) || []).length;
  return {
    start(id, rate=1) { rate=Number(rate); if(!Number.isFinite(rate)||rate<=0)rate=1; states.set(id, {prefix: [], pending: [], used: 0, rate:Math.min(1,rate)}); while (states.size > 8) states.delete(states.keys().next().value); },
    hold(id, text) {
      const state = states.get(id); if (!state) return false;
      const report = /(?:1[сc]:|выручк|прибыл|отч[её]т|дебитор|остатки)/iu.test(text);
      if (state.pending.length || report || state.used + cost(text) > 240*state.rate) { state.pending.push(text); return true; }
      state.prefix.push(text); state.used += cost(text); return false;
    },
    finish(id, chat) {
      const state = states.get(id); states.delete(id);
      if (!state || !state.pending.length) return null;
      return {text: state.pending.join(" "), options: {speech_message_id: id, speech_chat_id: chat,
        speech_prefix: state.prefix.join(" "), speech_max_chars: Math.max(80, Math.floor(900*state.rate) - state.used)}};
    },
    emoji(text) {
      const explicit = String(text || "").match(/[😀😃😄😁😆😂🤣😊🙂😉😇🥰😍🤩😔😞😟😥😢😭🥺🥹❤👍🎉]/u);
      if (explicit) return explicit[0];
      if (/(?:сожалению|жаль|сочувств|груст)/iu.test(text)) return "😔";
      if (/(?:ура|отлично|спасибо|поздрав|получилось)/iu.test(text)) return "😊";
      return /\?/.test(text) ? "🤔" : null;
    }
  };
})();

export { __assistantMicOrigin, __assistantVoiceBudget };
