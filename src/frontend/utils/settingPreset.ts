import { i18n } from '@/i18n'

import { forceNumber, optionLists } from './common'
import {
  availableModels,
  availableModelsForAnthropic,
  availableModelsForAzure,
  availableModelsForGemini,
  availableModelsForGroq,
  availableModelsForOllama,
  availableModelsForTogetherAI,
} from './constant'
import { localStorageKey } from './enum'

type componentType = 'input' | 'select' | 'inputNum' | 'checkbox'

const getCustomModels = (key: string, oldKey: string): string[] => {
  const stored = localStorage.getItem(key)
  if (stored) {
    try {
      return JSON.parse(stored)
    } catch {
      return []
    }
  }
  const oldModel = localStorage.getItem(oldKey)
  if (oldModel?.trim()) {
    const models = [oldModel]
    localStorage.setItem(key, JSON.stringify(models))
    return models
  }
  return []
}

const saveCustomModels = (key: string, models: string[]) => localStorage.setItem(key, JSON.stringify(models))

interface ISettingOption<T> {
  defaultValue: T
  saveKey?: string
  type?: componentType
  stepStyle?: 'temperature' | 'maxTokens'
  optionObj?: { label: string; value: string }[]
  optionList?: string[]
  saveFunc?: (value: T) => void
  getFunc?: () => T
}

export const Setting_Names = [
  'api',
  'localLanguage',
  'replyLanguage',
  'openaiAPIKey',
  'openaiBasePath',
  'openaiCustomModel',
  'openaiCustomModels',
  'openaiTemperature',
  'openaiMaxContextTokens',
  'openaiModelSelect',
  'anthropicAPIKey',
  'anthropicCustomModel',
  'anthropicCustomModels',
  'anthropicModelSelect',
  'anthropicTemperature',
  'anthropicMaxContextTokens',
  'azureAPIKey',
  'azureAPIEndpoint',
  'azureAPIVersion',
  'azureCustomModels',
  'azureModelSelect',
  'azureTemperature',
  'azureMaxContextTokens',
  'geminiAPIKey',
  'geminiCustomModel',
  'geminiCustomModels',
  'geminiModelSelect',
  'geminiTemperature',
  'geminiMaxContextTokens',
  'ollamaEndpoint',
  'ollamaCustomModel',
  'ollamaCustomModels',
  'ollamaModelSelect',
  'ollamaTemperature',
  'ollamaMaxContextTokens',
  'groqAPIKey',
  'groqTemperature',
  'groqMaxContextTokens',
  'groqModelSelect',
  'groqCustomModel',
  'groqCustomModels',
  'lmstudioEndpoint',
  'lmstudioFilterThinking',
  'lmstudioCustomModels',
  'lmstudioModelSelect',
  'lmstudioMaxContextTokens',
  'lmstudioTemperature',
  'togetheraiAPIKey',
  'togetheraiCustomModel',
  'togetheraiCustomModels',
  'togetheraiModelSelect',
  'togetheraiTemperature',
  'togetheraiMaxContextTokens',
  'systemPrompt',
  'userPrompt',
  'agentMaxIterations',
  'enableMarkdown',
  'horizontalToolCalls',
  'attachmentCharLimit',
  'llmTimeout',
  'historyDbPath',
  'tavilyApiKey',
] as const

export type SettingNames = (typeof Setting_Names)[number]

type keyOfLocalStorageKey = keyof typeof localStorageKey

// Helper functions
const createStorageFuncs = (key: string, defaultValue: number) => ({
  getFunc: () => forceNumber(localStorage.getItem(key)) || defaultValue,
  saveFunc: (value: number) => localStorage.setItem(key, value.toString()),
})

const inputSetting = (defaultValue: string, saveKey?: keyOfLocalStorageKey): ISettingOption<string> => ({
  defaultValue,
  saveKey,
  type: 'input',
})

const inputNumSetting = (
  defaultValue: number,
  saveKey: keyOfLocalStorageKey,
  stepStyle: 'temperature' | 'maxTokens',
): ISettingOption<number> => ({
  defaultValue,
  saveKey,
  type: 'inputNum',
  stepStyle,
  ...createStorageFuncs(localStorageKey[saveKey], defaultValue),
})

const selectSetting = (
  defaultValue: string,
  saveKey: keyOfLocalStorageKey,
  optionList: string[],
): ISettingOption<string> => ({
  defaultValue,
  saveKey,
  type: 'select',
  optionList,
  getFunc: () => localStorage.getItem(localStorageKey[saveKey]) || defaultValue,
})

const checkboxSetting = (defaultValue: boolean, saveKey: keyOfLocalStorageKey): ISettingOption<boolean> => ({
  defaultValue,
  saveKey,
  type: 'checkbox',
  getFunc: () => {
    const stored = localStorage.getItem(localStorageKey[saveKey])
    return stored !== null ? stored === 'true' : defaultValue
  },
  saveFunc: (value: boolean) => {
    localStorage.setItem(localStorageKey[saveKey], String(value))
  },
})

const customModelsetting = (saveKey: keyOfLocalStorageKey, oldKey: keyOfLocalStorageKey): ISettingOption<string[]> => ({
  defaultValue: [],
  saveKey,
  getFunc: () => getCustomModels(localStorageKey[saveKey], localStorageKey[oldKey]),
  saveFunc: (value: string[]) => saveCustomModels(localStorageKey[saveKey], value),
})

export const settingPreset = {
  api: {
    ...inputSetting('openai'),
    type: 'select',
    optionObj: optionLists.apiList,
  },
  localLanguage: {
    ...inputSetting('en'),
    type: 'select',
    optionObj: optionLists.localLanguageList,
    saveFunc: (value: string) => {
      i18n.global.locale.value = value as 'en' | 'zh-cn'
      localStorage.setItem(localStorageKey.localLanguage, value)
    },
  },
  replyLanguage: {
    ...inputSetting('English'),
    type: 'select',
    optionObj: optionLists.replyLanguageList,
  },
  openaiAPIKey: inputSetting('', 'apiKey'),
  openaiBasePath: inputSetting('', 'basePath'),
  openaiCustomModel: inputSetting('', 'customModel'),
  openaiCustomModels: customModelsetting('customModels', 'customModel'),
  openaiTemperature: inputNumSetting(1.0, 'temperature', 'temperature'),
  openaiMaxContextTokens: inputNumSetting(128000, 'maxContextTokens', 'maxTokens'),
  openaiModelSelect: selectSetting('gpt-5', 'model', availableModels),
  anthropicAPIKey: inputSetting('', 'anthropicAPIKey'),
  anthropicCustomModel: inputSetting('', 'anthropicCustomModel'),
  anthropicCustomModels: customModelsetting('anthropicCustomModels', 'anthropicCustomModel'),
  anthropicModelSelect: selectSetting('claude-opus-4-5', 'anthropicModel', availableModelsForAnthropic),
  anthropicTemperature: inputNumSetting(1.0, 'anthropicTemperature', 'temperature'),
  anthropicMaxContextTokens: inputNumSetting(128000, 'anthropicMaxContextTokens', 'maxTokens'),
  azureAPIKey: inputSetting(''),
  azureAPIEndpoint: inputSetting(''),
  azureAPIVersion: inputSetting(''),
  azureCustomModels: customModelsetting('azureCustomModels', 'azureDeploymentName'),
  azureModelSelect: selectSetting('', 'azureModel', availableModelsForAzure),
  azureTemperature: inputNumSetting(1.0, 'azureTemperature', 'temperature'),
  azureMaxContextTokens: inputNumSetting(128000, 'azureMaxContextTokens', 'maxTokens'),
  geminiAPIKey: inputSetting(''),
  geminiCustomModel: inputSetting(''),
  geminiCustomModels: customModelsetting('geminiCustomModels', 'geminiCustomModel'),
  geminiModelSelect: selectSetting('gemini-3-pro-preview', 'geminiModel', availableModelsForGemini),
  geminiTemperature: inputNumSetting(1.0, 'geminiTemperature', 'temperature'),
  geminiMaxContextTokens: inputNumSetting(128000, 'geminiMaxContextTokens', 'maxTokens'),
  ollamaEndpoint: inputSetting(''),
  ollamaCustomModel: inputSetting(''),
  ollamaCustomModels: customModelsetting('ollamaCustomModels', 'ollamaCustomModel'),
  ollamaModelSelect: selectSetting('qwen3:latest', 'ollamaModel', availableModelsForOllama),
  ollamaTemperature: inputNumSetting(1.0, 'ollamaTemperature', 'temperature'),
  ollamaMaxContextTokens: inputNumSetting(128000, 'ollamaMaxContextTokens', 'maxTokens'),
  groqAPIKey: inputSetting(''),
  groqTemperature: inputNumSetting(1.0, 'groqTemperature', 'temperature'),
  groqMaxContextTokens: inputNumSetting(128000, 'groqMaxContextTokens', 'maxTokens'),
  groqModelSelect: selectSetting('qwen/qwen3-32b', 'groqModel', availableModelsForGroq),
  groqCustomModel: inputSetting(''),
  groqCustomModels: customModelsetting('groqCustomModels', 'groqCustomModel'),
  lmstudioEndpoint: inputSetting('http://localhost:1234/v1', 'lmstudioEndpoint'),
  lmstudioFilterThinking: checkboxSetting(true, 'lmstudioFilterThinking'),
  lmstudioCustomModels: customModelsetting('lmstudioCustomModels', 'lmstudioCustomModel'),
  lmstudioModelSelect: selectSetting('', 'lmstudioModel', []),
  lmstudioMaxContextTokens: inputNumSetting(128000, 'lmstudioMaxContextTokens', 'maxTokens'),
  lmstudioTemperature: inputNumSetting(1.0, 'lmstudioTemperature', 'temperature'),
  togetheraiAPIKey: inputSetting(''),
  togetheraiCustomModel: inputSetting(''),
  togetheraiCustomModels: customModelsetting('togetheraiCustomModels', 'togetheraiCustomModel'),
  togetheraiModelSelect: selectSetting('meta-llama/Llama-3.3-70B-Instruct-Turbo', 'togetheraiModel', availableModelsForTogetherAI),
  togetheraiTemperature: inputNumSetting(1.0, 'togetheraiTemperature', 'temperature'),
  togetheraiMaxContextTokens: inputNumSetting(128000, 'togetheraiMaxContextTokens', 'maxTokens'),
  systemPrompt: inputSetting('', 'defaultSystemPrompt'),
  userPrompt: inputSetting('', 'defaultPrompt'),
  agentMaxIterations: inputNumSetting(120, 'agentMaxIterations', 'maxTokens'),
  enableMarkdown: checkboxSetting(true, 'enableMarkdown'),
  horizontalToolCalls: checkboxSetting(true, 'horizontalToolCalls'),
  attachmentCharLimit: inputNumSetting(100000, 'attachmentCharLimit', 'maxTokens'),
  llmTimeout: inputNumSetting(90, 'llmTimeout', 'maxTokens'),
  historyDbPath: inputSetting('', 'historyDbPath'),
  tavilyApiKey: inputSetting('', 'tavilyApiKey'),
} as const satisfies Record<SettingNames, ISettingOption<any>>
