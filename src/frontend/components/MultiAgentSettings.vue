<template>
  <div class="flex flex-col gap-4">
    <!-- Help Banner -->
    <div class="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
      {{ t('multiagentCredentialsInfo') }}
    </div>

    <!-- Experts Section -->
    <div class="mt-4 flex items-center justify-between">
      <h3 class="text-base font-semibold">{{ t('multiagentExpertsLabel') }}</h3>
    </div>
    <p class="mt-1 text-xs text-secondary/70">{{ t('multiagentExpertsOrderHelp') }}</p>

    <SettingCard v-for="expert in config.experts" :key="expert.id">
      <h4 class="mb-3 text-sm font-semibold">{{ expert.name }}</h4>

      <div class="flex flex-col gap-3">
        <CustomInput v-model="expert.name" :title="t('multiagentExpertNameLabel')" />

        <div class="flex flex-col gap-2">
          <label class="text-sm">{{ t('apiProvider') }}</label>
          <select v-model="expert.provider" class="rounded-md border px-3 py-2">
            <option v-for="(internalId, displayName) in availableAPIs" :key="internalId" :value="internalId">{{ displayName }}</option>
          </select>
        </div>

        <div class="flex flex-col gap-2">
          <label class="text-sm">{{ t('modelLabel') }}</label>
          <select
            v-if="getModelsForProvider(expert.provider).length > 0"
            v-model="expert.model"
            class="rounded-md border px-3 py-2"
          >
            <option v-for="model in getModelsForProvider(expert.provider)" :key="model" :value="model">
              {{ model }}
            </option>
          </select>
          <select v-else disabled class="cursor-not-allowed rounded-md border px-3 py-2 opacity-50">
            <option value="">{{ t('noModelsConfigured') }}</option>
          </select>
        </div>

        <div v-if="!isEffortHidden(expert)" class="flex flex-col gap-2">
          <label class="text-sm">{{ t('multiagentReasoningEffortLabel') }}</label>
          <select
            :value="expert.reasoningEffort || ''"
            class="rounded-md border px-3 py-2"
            @change="setEffort(expert, ($event.target as HTMLSelectElement).value)"
          >
            <option value="">{{ t('multiagentInheritEffort') }}</option>
            <option v-for="tier in effortOptions(expert)" :key="tier" :value="tier">{{ tier }}</option>
          </select>
          <div
            v-if="effortNotice(expert)"
            class="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-700 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-400"
          >
            {{ effortNotice(expert) }}
          </div>
        </div>
      </div>
    </SettingCard>

    <!-- Overseer/Synthesizer Section -->
    <h3 class="mt-6 text-base font-semibold">Overseer/Synthesizer Model</h3>
    <SettingCard>
      <div class="flex flex-col gap-3">
        <div class="flex flex-col gap-2">
          <label class="text-sm">{{ t('apiProvider') }}</label>
          <select v-model="config.overseer.provider" class="rounded-md border px-3 py-2">
            <option v-for="(internalId, displayName) in availableAPIs" :key="internalId" :value="internalId">{{ displayName }}</option>
          </select>
        </div>

        <div class="flex flex-col gap-2">
          <label class="text-sm">{{ t('modelLabel') }}</label>
          <select
            v-if="getModelsForProvider(config.overseer.provider).length > 0"
            v-model="config.overseer.model"
            class="rounded-md border px-3 py-2"
          >
            <option v-for="model in getModelsForProvider(config.overseer.provider)" :key="model" :value="model">
              {{ model }}
            </option>
          </select>
          <select v-else disabled class="cursor-not-allowed rounded-md border px-3 py-2 opacity-50">
            <option value="">{{ t('noModelsConfigured') }}</option>
          </select>
        </div>

        <div v-if="!isEffortHidden(config.overseer)" class="flex flex-col gap-2">
          <label class="text-sm">{{ t('multiagentReasoningEffortLabel') }}</label>
          <select
            :value="config.overseer.reasoningEffort || ''"
            class="rounded-md border px-3 py-2"
            @change="setEffort(config.overseer, ($event.target as HTMLSelectElement).value)"
          >
            <option value="">{{ t('multiagentInheritEffort') }}</option>
            <option v-for="tier in effortOptions(config.overseer)" :key="tier" :value="tier">{{ tier }}</option>
          </select>
          <div
            v-if="effortNotice(config.overseer)"
            class="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-700 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-400"
          >
            {{ effortNotice(config.overseer) }}
          </div>
        </div>
      </div>
    </SettingCard>

    <!-- Formatter Model (Legacy mode only) -->
    <template v-if="config.operatingMode === 'legacy'">
      <h3 class="mt-6 text-base font-semibold">{{ t('multiagentFormatterModelLabel') }}</h3>
      <p class="text-xs text-gray-500">{{ t('multiagentFormatterModelHelp') }}</p>
      <SettingCard>
        <div class="flex flex-col gap-3">
          <div class="flex flex-col gap-2">
            <label class="text-sm">{{ t('apiProvider') }}</label>
            <select v-model="formatterProvider" class="rounded-md border px-3 py-2">
              <option v-for="(internalId, displayName) in availableAPIs" :key="internalId" :value="internalId">{{ displayName }}</option>
            </select>
          </div>

          <div class="flex flex-col gap-2">
            <label class="text-sm">{{ t('modelLabel') }}</label>
            <select
              v-if="getModelsForProvider(formatterProvider).length > 0"
              v-model="formatterModel"
              class="rounded-md border px-3 py-2"
            >
              <option v-for="model in getModelsForProvider(formatterProvider)" :key="model" :value="model">
                {{ model }}
              </option>
            </select>
            <select v-else disabled class="cursor-not-allowed rounded-md border px-3 py-2 opacity-50">
            <option value="">{{ t('noModelsConfigured') }}</option>
          </select>
          </div>

          <div v-if="config.formatter && !isEffortHidden(config.formatter)" class="flex flex-col gap-2">
            <label class="text-sm">{{ t('multiagentReasoningEffortLabel') }}</label>
            <select v-model="formatterEffort" class="rounded-md border px-3 py-2">
              <option value="">{{ t('multiagentInheritEffort') }}</option>
              <option v-for="tier in effortOptions(config.formatter)" :key="tier" :value="tier">{{ tier }}</option>
            </select>
            <div
              v-if="effortNotice(config.formatter)"
              class="rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-700 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-400"
            >
              {{ effortNotice(config.formatter) }}
            </div>
          </div>
        </div>
      </SettingCard>
    </template>

    <!-- Advanced Options -->
    <h3 class="mt-6 text-base font-semibold">Advanced Options</h3>

    <!-- Operating Mode -->
    <SettingCard>
      <div class="flex flex-col gap-2">
        <label class="text-sm">{{ t('multiagentOperatingModeLabel') }}</label>
        <select v-model="config.operatingMode" class="rounded-md border px-3 py-2">
          <option value="combined">{{ t('multiagentOperatingModeCombined') }}</option>
          <option value="legacy">{{ t('multiagentOperatingModeLegacy') }}</option>
        </select>
        <p class="text-xs text-gray-500">{{ t('multiagentOperatingModeHelp') }}</p>
      </div>
    </SettingCard>

    <!-- Max Rounds -->
    <SettingCard>
      <CustomInput
        v-model.number="config.maxRounds"
        :title="t('multiagentMaxRoundsLabel')"
        type="number"
        :min="1"
        :max="50"
      />
    </SettingCard>

    <!-- Expert Full History -->
    <SettingCard>
      <label class="flex items-center gap-2 text-sm">
        <input v-model="config.expertFullHistory" type="checkbox" class="rounded" />
        {{ t('multiagentExpertFullHistoryLabel') }}
      </label>
      <p class="mt-1 text-xs text-gray-500">{{ t('multiagentExpertFullHistoryHelp') }}</p>
    </SettingCard>

    <!-- Expert Parallelization -->
    <SettingCard>
      <label class="flex items-center gap-2 text-sm">
        <input v-model="config.useExpertParallelization" type="checkbox" class="rounded" />
        {{ t('useExpertParallelizationLabel') }}
      </label>
      <p class="mt-1 text-xs text-gray-500">{{ t('useExpertParallelizationPlaceholder') }}</p>
    </SettingCard>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { CONSERVATIVE_EFFORTS, fetchEffortCapability, type ModelCapability } from '@/api/modelCapabilities'
import type { MultiAgentConfig, supportedProviders } from '@/api/types'
import {
  availableAPIs,
  availableModels,
  availableModelsForAnthropic,
  availableModelsForAzure,
  availableModelsForGemini,
  availableModelsForGroq,
  availableModelsForOllama,
  availableModelsForTogetherAI,
} from '@/utils/constant'
import useSettingForm from '@/utils/settingForm'

import CustomInput from './CustomInput.vue'
import SettingCard from './SettingCard.vue'

const { t } = useI18n()
const settingForm = useSettingForm()

const props = defineProps<{
  modelValue: MultiAgentConfig
}>()

const emit = defineEmits<(e: 'update:modelValue', value: MultiAgentConfig) => void>()

const config = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})

const ensureFormatter = () => {
  if (!config.value.formatter) {
    config.value = {
      ...config.value,
      formatter: {
        id: 'formatter',
        provider: 'anthropic',
        model: 'claude-haiku-4-5',
      },
    }
  }
}

const formatterProvider = computed({
  get: () => (config.value.formatter?.provider ?? 'anthropic') as string,
  set: (val: string) => {
    ensureFormatter()
    config.value.formatter!.provider = val as supportedProviders
  },
})

const formatterModel = computed({
  get: () => config.value.formatter?.model ?? '',
  set: (val: string) => {
    ensureFormatter()
    config.value.formatter!.model = val
  },
})

const formatterEffort = computed({
  get: () => config.value.formatter?.reasoningEffort ?? '',
  set: (val: string) => {
    ensureFormatter()
    config.value.formatter!.reasoningEffort = val
  },
})

// ---------------------------------------------------------------------------
// Per-role reasoning effort
//
// Each role's effort defaults to '' = inherit whatever the provider's own
// settings sheet holds. An explicit tier overrides it, which is the point: the
// supported tiers are a property of the *model*, not the provider, so a role
// running a different model than the provider sheet's needs its own value.
// The offered ladder therefore comes from the same live per-model endpoint the
// provider sheet uses, so the two cannot disagree.
// ---------------------------------------------------------------------------

interface EffortRole {
  provider: supportedProviders
  model: string
  reasoningEffort?: string
}

const EFFORT_TIER_ORDER = ['none', 'low', 'medium', 'high', 'xhigh', 'max']

// Keyed `${provider}:${model}` rather than by role, so two roles on the same
// model share one entry. `null` means the fetch failed; a missing entry just
// means "not fetched yet", which shows the conservative ladder without a notice.
const capabilities = ref<Record<string, ModelCapability | null>>({})

const capabilityFor = (role: EffortRole): ModelCapability | null | undefined =>
  role.model ? capabilities.value[`${role.provider}:${role.model}`] : undefined

const effortOptions = (role: EffortRole): string[] => {
  const capability = capabilityFor(role)
  return capability?.supported_efforts.length ? capability.supported_efforts : CONSERVATIVE_EFFORTS
}

// Hidden only when the model is confirmed to have no reasoning tiers at all
// (e.g. gpt-4.1) — an unfetched or failed lookup still shows the control.
const isEffortHidden = (role: EffortRole): boolean => capabilityFor(role)?.supported_efforts.length === 0

const effortNotice = (role: EffortRole): string => {
  const capability = capabilityFor(role)
  if (capability === null) return t('modelCapabilitiesNotice')
  if (!capability) return ''
  if (capability.warnings.length) return capability.warnings.join(' ')
  if (capability.source === 'inferred' || capability.source === 'fallback') return t('modelCapabilitiesNotice')
  return ''
}

const setEffort = (role: EffortRole, value: string) => {
  role.reasoningEffort = value
}

// Snap a stale override (e.g. `max` saved against Sonnet, model switched to a
// model capping at `high`) to the nearest tier the new ladder supports, so the
// form never holds a value its own dropdown can't render. Mirrors the backend
// clamp in providers/effort.py — nearest LOWER tier first.
const coerceEffort = (role: EffortRole, capability: ModelCapability) => {
  const current = role.reasoningEffort
  if (!current) return // inheriting; the provider sheet's value is clamped backend-side
  const ladder = capability.supported_efforts
  if (ladder.length === 0) {
    role.reasoningEffort = '' // control is hidden — don't keep invisible state
    return
  }
  if (ladder.includes(current)) return

  const idx = EFFORT_TIER_ORDER.indexOf(current)
  let next = ''
  if (idx !== -1) {
    for (let i = idx - 1; i >= 0 && !next; i--) {
      if (ladder.includes(EFFORT_TIER_ORDER[i])) next = EFFORT_TIER_ORDER[i]
    }
    for (let i = idx + 1; i < EFFORT_TIER_ORDER.length && !next; i++) {
      if (ladder.includes(EFFORT_TIER_ORDER[i])) next = EFFORT_TIER_ORDER[i]
    }
  }
  if (!next) next = ladder.includes(capability.default_effort) ? capability.default_effort : ladder[0]
  role.reasoningEffort = next
}

// A failed fetch must degrade to the conservative ladder + a notice, never
// throw out of the watcher and break the rest of the settings sheet.
const loadCapability = async (role: EffortRole) => {
  if (!role.model) return
  const key = `${role.provider}:${role.model}`
  try {
    const capability = await fetchEffortCapability(role.provider, role.model)
    capabilities.value[key] = capability
    coerceEffort(role, capability)
  } catch (error) {
    console.error(`[MultiAgentSettings] Failed to load model capabilities for ${key}:`, error)
    capabilities.value[key] = null
  }
}

const effortRoles = computed<EffortRole[]>(() => {
  const roles: EffortRole[] = [...config.value.experts, config.value.overseer]
  if (config.value.formatter) roles.push(config.value.formatter)
  return roles
})

// Deep so a provider/model change on any role refetches. Unrelated edits (e.g.
// renaming an expert) also fire it, but fetchEffortCapability is memoized per
// provider:model, so those never reach the network.
watch(effortRoles, roles => roles.forEach(role => void loadCapability(role)), { deep: true, immediate: true })

// Preset (built-in) models per provider. Custom models are appended reactively
// from the shared settingForm singleton (key `${provider}CustomModels`), so models
// added/removed in Settings update these dropdowns live without a restart.
const presetModelsForProvider = (provider: string): string[] => {
  switch (provider) {
    case 'openai':
      return availableModels
    case 'anthropic':
      return availableModelsForAnthropic
    case 'gemini':
      return availableModelsForGemini
    case 'groq':
      return availableModelsForGroq
    case 'ollama':
      return availableModelsForOllama
    case 'azure':
      return availableModelsForAzure
    case 'togetherai':
      return availableModelsForTogetherAI
    case 'lmstudio':
      return []
    default:
      return []
  }
}

const getModelsForProvider = (provider: string): string[] => {
  const custom = ((settingForm.value as Record<string, unknown>)[`${provider}CustomModels`] as string[]) ?? []
  return [...presetModelsForProvider(provider), ...custom]
}
</script>
