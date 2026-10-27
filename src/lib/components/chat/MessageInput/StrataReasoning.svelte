<script lang="ts">
  import { getContext, tick } from 'svelte';
  import { models, settings, user } from '$lib/stores';
  import { updateUserSettings } from '$lib/apis/users';
  import { toast } from 'svelte-sonner';
  import Dropdown from '$lib/components/common/Dropdown.svelte';
  import DropdownMenu from '$lib/components/common/DropdownMenu.svelte';
  import Tooltip from '$lib/components/common/Tooltip.svelte';
  import Sparkles from '$lib/components/icons/Sparkles.svelte';
  import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
  import Check from '$lib/components/icons/Check.svelte';
  import { isStrataModel, hasStrataAuthorTemplate, hasStrataAdaptiveProfile, selectedStrataReasoning, STRATA_REASONING_LEVELS } from '$lib/utils/strataReasoning';

  const i18n: any = getContext('i18n');
  export let selectedModels: string[] = [];
  export let disabled = false;
  let saving = false;
  let trigger: HTMLButtonElement;
  $: model = selectedModels.length === 1 ? $models.find((m) => m.id === selectedModels[0]) : undefined;
  $: value = selectedStrataReasoning(model, $settings.strataReasoningEfforts);
  $: levels = STRATA_REASONING_LEVELS.filter((level) =>
    (level !== 'ultra' || hasStrataAuthorTemplate(model)) &&
    (level !== 'adaptive' || hasStrataAdaptiveProfile(model)));
  const labels: Record<string, string> = {auto: 'Reasoning default', none: 'Reasoning off', low: 'Reasoning low',
    medium: 'Reasoning medium', high: 'Reasoning high', xhigh: 'Reasoning xhigh', ultra: 'Reasoning ultra', adaptive: 'Reasoning adaptive'};

  async function select(level: string) {
    if (!model || saving || disabled || !STRATA_REASONING_LEVELS.includes(level)) return;
    const id = model.id;
    const previous = $settings.strataReasoningEfforts ?? {};
    const next = {...previous};
    next[id] = level;
    settings.set({...$settings, strataReasoningEfforts: next});
    saving = true;
    try {
      if (!await updateUserSettings(localStorage.token, {ui: {strataReasoningEfforts: next}})) {
        throw new Error($i18n.t('Failed to save settings'));
      }
    } catch (error) {
      settings.set({...$settings, strataReasoningEfforts: previous});
      toast.error(String(error));
    } finally {
      saving = false;
      await tick();
      if (model?.id === id && trigger?.isConnected) trigger.focus();
    }
  }
</script>

{#if isStrataModel(model) && ($user?.role === 'admin' || ($user?.permissions?.chat?.params ?? true))}
  <Dropdown align="end" visualViewportAware closeOnSelect>
    <Tooltip content={`${$i18n.t(labels[value])}. ${$i18n.t('Strata reasoning description')}`} placement="top">
      <button bind:this={trigger} type="button" data-strata-reasoning aria-label={`${$i18n.t('Strata reasoning')}: ${$i18n.t(labels[value])}`}
        disabled={disabled || saving}
        class="flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2 text-[0.8125rem] text-gray-600 transition-colors hover:bg-gray-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-400 disabled:opacity-50 dark:text-gray-300 dark:hover:bg-gray-800 dark:focus-visible:outline-gray-500">
        <Sparkles className="size-4" />
        <span class="hidden max-w-24 truncate sm:inline">{$i18n.t(labels[value])}</span>
        <ChevronDown className="size-3" />
      </button>
    </Tooltip>
    <div slot="content">
      <DropdownMenu className="w-52 max-w-[calc(100vw-2rem)]">
        <div class="px-2 py-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">{$i18n.t('Strata reasoning')}</div>
        {#each levels as level}
          {#if level === 'ultra'}<hr />{/if}
          <button type="button" role="menuitemradio" aria-checked={value === level}
            disabled={disabled || saving} data-reasoning-effort={level}
            class="flex min-h-9 w-full items-center justify-between gap-3 rounded-lg px-2 text-left text-sm text-gray-800 hover:bg-gray-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-gray-400 disabled:opacity-50 dark:text-gray-100 dark:hover:bg-gray-800"
            on:click={() => select(level)}>
            <span>{$i18n.t(labels[level])}</span>
            {#if level === 'ultra' || level === 'adaptive'}
              <span class="ml-auto text-[0.6875rem] text-gray-500 dark:text-gray-400">{level === 'ultra' ? 'DavidAU' : 'Mnemosyne'}</span>
            {/if}
            {#if value === level}<Check className="size-4 shrink-0" />{/if}
          </button>
        {/each}
      </DropdownMenu>
    </div>
  </Dropdown>
{/if}
