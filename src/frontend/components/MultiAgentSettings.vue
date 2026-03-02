<template>
  <div class="flex flex-col gap-4">
    <!-- Help Banner -->
    <div class="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-800">
      {{ t('multiagentCredentialsInfo') }}
    </div>

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
        :max="10"
      />
    </SettingCard>

    <!-- Experts Section -->
    <div class="mt-4 flex items-center justify-between">
      <h3 class="text-base font-semibold">{{ t('multiagentExpertsLabel') }}</h3>
    </div>

    <SettingCard v-for="expert in config.experts" :key="expert.id">
      <h4 class="mb-3 text-sm font-semibold">{{ expert.name }}</h4>

      <div class="flex flex-col gap-3">
        <CustomInput v-model="expert.name" :title="t('multiagentExpertNameLabel')" />

        <div class="flex flex-col gap-2">
          <label class="text-sm">{{ t('apiProvider') }}</label>
          <select v-model="expert.provider" class="rounded-md border px-3 py-2">
            <option value="official">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="gemini">Google Gemini</option>
            <option value="groq">Groq</option>
            <option value="ollama">Ollama</option>
            <option value="lmstudio">LM Studio</option>
            <option value="azure">Azure</option>
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
          <CustomInput v-else v-model="expert.model" :title="''" />
        </div>

        <CustomInput
          v-model.number="expert.temperature"
          :title="t('temperature')"
          type="number"
          :min="0"
          :max="2"
          :step="0.1"
        />
      </div>
    </SettingCard>

    <!-- Overseer/Synthesizer Section -->
    <h3 class="mt-6 text-base font-semibold">Overseer/Synthesizer Model</h3>
    <SettingCard>
      <div class="flex flex-col gap-3">
        <div class="flex flex-col gap-2">
          <label class="text-sm">{{ t('apiProvider') }}</label>
          <select v-model="config.overseer.provider" class="rounded-md border px-3 py-2">
            <option value="official">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="gemini">Google Gemini</option>
            <option value="groq">Groq</option>
            <option value="ollama">Ollama</option>
            <option value="lmstudio">LM Studio</option>
            <option value="azure">Azure</option>
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
          <CustomInput v-else v-model="config.overseer.model" :title="''" />
        </div>
        <CustomInput
          v-model.number="config.overseer.temperature"
          :title="t('temperature')"
          type="number"
          :min="0"
          :max="2"
          :step="0.1"
        />
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
              <option value="official">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="gemini">Google Gemini</option>
              <option value="groq">Groq</option>
              <option value="ollama">Ollama</option>
              <option value="lmstudio">LM Studio</option>
              <option value="azure">Azure</option>
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
            <CustomInput v-else v-model="formatterModel" :title="''" />
          </div>
          <CustomInput
            v-model.number="formatterTemperature"
            :title="t('temperature')"
            type="number"
            :min="0"
            :max="2"
            :step="0.1"
          />
        </div>
      </SettingCard>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { MultiAgentConfig, supportedProviders } from '@/api/types'
import {
  availableModels,
  availableModelsForAnthropic,
  availableModelsForAzure,
  availableModelsForGemini,
  availableModelsForGroq,
  availableModelsForOllama,
} from '@/utils/constant'

import CustomInput from './CustomInput.vue'
import SettingCard from './SettingCard.vue'

const { t } = useI18n()

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
        temperature: 0,
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

const formatterTemperature = computed({
  get: () => config.value.formatter?.temperature ?? 0,
  set: (val: number) => {
    ensureFormatter()
    config.value.formatter!.temperature = val
  },
})

const getModelsForProvider = (provider: string): string[] => {
  switch (provider) {
    case 'official':
      return availableModels
    case 'anthropic':
      return availableModelsForAnthropic
    case 'gemini':
      return availableModelsForGemini
    case 'groq':
      return availableModelsForGroq
    case 'ollama':
      return availableModelsForOllama
    case 'azure': {
      const azureStored = localStorage.getItem('azureCustomModels')
      const azureCustom: string[] = azureStored ? JSON.parse(azureStored) : []
      return [...availableModelsForAzure, ...azureCustom]
    }
    case 'lmstudio': {
      const lmStored = localStorage.getItem('lmstudioCustomModels')
      return lmStored ? JSON.parse(lmStored) : []
    }
    default:
      return []
  }
}
</script>
