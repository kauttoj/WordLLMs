export const languageMap: IStringKeyMap = {
  en: 'English',
  es: 'Español',
  fr: 'Français',
  de: 'Deutsch',
  it: 'Italiano',
  pt: 'Português',
  hi: 'हिन्दी',
  ar: 'العربية',
  'zh-cn': '简体中文',
  'zh-tw': '繁體中文',
  ja: '日本語',
  ko: '한국어',
  ru: 'Русский',
  nl: 'Nederlands',
  sv: 'Svenska',
  fi: 'Suomi',
  no: 'Norsk',
  da: 'Dansk',
  pl: 'Polski',
  tr: 'Türkçe',
  el: 'Ελληνικά',
  he: 'עברית',
  hu: 'Magyar',
  id: 'Bahasa Indonesia',
  ms: 'Bahasa Melayu',
  th: 'ไทย',
  vi: 'Tiếng Việt',
  uk: 'Українська',
  bg: 'Български',
  cs: 'Čeština',
  ro: 'Română',
  sk: 'Slovenčina',
  sl: 'Slovenščina',
  hr: 'Hrvatski',
  sr: 'Српски',
  bn: 'বাংলা',
  gu: 'ગુજરાતી',
  kn: 'ಕನ್ನಡ',
  mr: 'मराठी',
  ta: 'தமிழ்',
  te: 'తెలుగు',
  ur: 'اردو',
}

export const availableAPIs: IStringKeyMap = {
  OpenAI: 'official',
  Anthropic: 'anthropic',
  Azure: 'azure',
  Gemini: 'gemini',
  Ollama: 'ollama',
  Groq: 'groq',
  LMStudio: 'lmstudio',
}

// official API 可用的模型
export const availableModels: string[] = [
  'gpt-5.4',
  'gpt-5.2-pro',
  'gpt-5.2',
  'gpt-5.1',
  'gpt-5-mini',
  'gpt-5-nano',
  'gpt-4.1',
]

// Gemini API 可用的模型
export const availableModelsForGemini: string[] = [
  'gemini-3.1-pro-preview',
  'gemini-3-pro-preview',
  'gemini-3-flash-preview',
  'gemini-2.5-pro',
  'gemini-2.5-flash',
]

// Ollama API 可用的模型
export const availableModelsForOllama: string[] = [
  'qwen3:latest',
  'llama4:latest',
  'deepseek-r1:latest',
  'gpt-oss:latest',
  'kimi-k2:1t-cloud',
  'gemini-3-flash-preview:latest',
  'ministral-3:latest',
]

export const availableModelsForGroq: string[] = [
  'llama-3.1-8b-instant',
  'llama-3.3-70b-versatile',
  'meta-llama/llama-guard-4-12b',
  'openai/gpt-oss-120b',
  'openai/gpt-oss-20b',
  'whisper-large-v3',
  'whisper-large-v3-turbo',
  'meta-llama/llama-4-maverick-17b-128e-instruct',
  'meta-llama/llama-4-scout-17b-16e-instruct',
  'meta-llama/llama-prompt-guard-2-22m',
  'meta-llama/llama-prompt-guard-2-86m',
  'moonshotai/kimi-k2-instruct-0905',
  'qwen/qwen3-32b',
]

// Anthropic API available models
export const availableModelsForAnthropic: string[] = [
  'claude-opus-4-6',
  'claude-opus-4-5',
  'claude-sonnet-4-6',
  'claude-sonnet-4-5',
  'claude-haiku-4-5',
]

// Azure: combined OpenAI + Anthropic models (custom AI Services models added by user)
export const availableModelsForAzure: string[] = [...availableModels, ...availableModelsForAnthropic]

import {
  BookOpen,
  CheckCircle,
  FileCheck,
  Globe,
  Lightbulb,
  PenTool,
  Search,
  Sparkle,
  Star,
  Zap,
} from 'lucide-vue-next'
import type { Component } from 'vue'

// --- Quick Action Slots ---

export interface QuickActionSlot {
  id: string
  name: string
  userPrompt: string
  icon: string
  enabled: boolean
}

export interface SystemPromptPreset {
  id: string
  name: string
  systemPrompt: string
}

export const ICON_OPTIONS: Record<string, Component> = {
  Globe,
  Sparkle,
  BookOpen,
  FileCheck,
  CheckCircle,
  Lightbulb,
  PenTool,
  Search,
  Zap,
  Star,
}

export const DEFAULT_QUICK_ACTION_SLOTS: QuickActionSlot[] = [
  {
    id: 'slot_1',
    name: 'Translate',
    userPrompt:
      'Translate my text into ${language}.\n      Constraints:\n      1. Provide a natural-sounding translation suitable for native speakers.\n      2. If the text is technical, use appropriate terminology.\n      3. OUTPUT ONLY the translated text. Do not include "Here is the translation" or any explanations.',
    icon: 'Globe',
    enabled: true,
  },
  {
    id: 'slot_2',
    name: 'Polish',
    userPrompt:
      'Polish my text for better flow and impact.\n      Improvements:\n      - Correct grammar, spelling, and punctuation.\n      - Enhance vocabulary while maintaining the original meaning.\n      - Improve sentence structure and eliminate redundancy.\n      - Ensure the tone is consistent and professional.\n      Constraints:\n      1. Respond in ${language}.\n      2. OUTPUT ONLY the polished text without any commentary.',
    icon: 'Sparkle',
    enabled: true,
  },
  {
    id: 'slot_3',
    name: 'Academic',
    userPrompt:
      'Rewrite my text to meet professional academic standards.\n      Requirements:\n      - Use formal, objective language and avoid colloquialisms.\n      - Ensure logical transitions and precise scientific terminology.\n      - Maintain a third-person perspective unless the context requires otherwise.\n      - Optimize for clarity and conciseness as per peer-review expectations.\n      Constraints:\n      1. Respond in ${language}.\n      2. OUTPUT ONLY the revised text. No pre-amble or meta-talk.',
    icon: 'BookOpen',
    enabled: true,
  },
  {
    id: 'slot_4',
    name: 'Summary',
    userPrompt:
      'Summarize my text.\n      Structure:\n      - Capture the core message and primary supporting points.\n      - Aim for approximately 100 words (or 3-5 key bullet points).\n      - Ensure the summary is self-contained and easy to understand.\n      Constraints:\n      1. Respond in ${language}.\n      2. OUTPUT ONLY the summary.',
    icon: 'FileCheck',
    enabled: true,
  },
  {
    id: 'slot_5',
    name: 'Grammar',
    userPrompt:
      'Check and correct the grammar of my text.\n      Focus:\n      - Fix all spelling and punctuation errors.\n      - Correct subject-verb agreement and tense inconsistencies.\n      - Ensure proper sentence structure.\n      Constraints:\n      1. If the text is already perfect, respond exactly with: "No grammatical issues found."\n      2. Otherwise, provide ONLY the corrected text without explaining the changes.\n      3. Respond in ${language}.',
    icon: 'CheckCircle',
    enabled: true,
  },
  { id: 'slot_6', name: '', userPrompt: '', icon: 'Lightbulb', enabled: false },
  { id: 'slot_7', name: '', userPrompt: '', icon: 'PenTool', enabled: false },
  { id: 'slot_8', name: '', userPrompt: '', icon: 'Star', enabled: false },
]

function makeEmptySlot(index: number): QuickActionSlot {
  return { id: `slot_${index}`, name: '', userPrompt: '', icon: 'Sparkle', enabled: false }
}

export function getQuickActionSlots(): QuickActionSlot[] {
  const stored = localStorage.getItem('quickActionSlots')
  if (stored) {
    try {
      const parsed = JSON.parse(stored) as QuickActionSlot[]
      while (parsed.length < 8) parsed.push(makeEmptySlot(parsed.length + 1))
      return parsed.slice(0, 8)
    } catch {
      // Corrupted — fall through to defaults
    }
  }

  // Migration from customBuiltInPrompts
  const customStored = localStorage.getItem('customBuiltInPrompts')
  if (customStored) {
    try {
      const custom = JSON.parse(customStored)
      const defaults = DEFAULT_QUICK_ACTION_SLOTS.map(s => ({ ...s }))
      const keyMap = ['translate', 'polish', 'academic', 'summary', 'grammar']
      keyMap.forEach((key, i) => {
        if (custom[key]) {
          defaults[i].userPrompt = custom[key].user
        }
      })
      localStorage.setItem('quickActionSlots', JSON.stringify(defaults))
      return defaults
    } catch {
      // Corrupted migration data — fall through
    }
  }

  return DEFAULT_QUICK_ACTION_SLOTS.map(s => ({ ...s }))
}

export const DEFAULT_SYSTEM_PROMPT_PRESETS: SystemPromptPreset[] = [
  {
    id: 'preset_data_scientist',
    name: 'Data Scientist',
    systemPrompt:
      "Act as a professional quantitative researcher and data scientist. You respect data, facts, logic and reasoning. Never flatter or patronize the user unnecessarily. Be skeptical and use rigorous, scientific thinking. Base all responses on facts and never fabricate information. If you don't know something and cannot find information, acknowledge it immediately.",
  },
  {
    id: 'preset_academic_writer',
    name: 'Academic Writer',
    systemPrompt:
      'Act as an experienced academic writer. Use formal, precise language appropriate for scholarly publications. Structure arguments logically with clear thesis statements and supporting evidence. Cite claims carefully and distinguish between established facts and interpretations. Maintain objectivity and acknowledge limitations or alternative viewpoints.',
  },
  {
    id: 'preset_marketing_assistant',
    name: 'Marketing Assistant',
    systemPrompt:
      'Act as a skilled marketing professional. Focus on clear, persuasive communication tailored to the target audience. Prioritize measurable outcomes and data-driven strategies. Write compelling copy that balances creativity with brand consistency. Be direct about trade-offs between reach, engagement, and conversion.',
  },
]

export function getSystemPromptPresets(): SystemPromptPreset[] {
  const stored = localStorage.getItem('systemPromptPresets')
  if (stored) {
    try {
      return JSON.parse(stored) as SystemPromptPreset[]
    } catch {
      // Corrupted — fall through
    }
  }

  // Migration from savedPrompts
  const oldStored = localStorage.getItem('savedPrompts')
  if (oldStored) {
    try {
      const old = JSON.parse(oldStored) as { id: string; name: string; systemPrompt: string; userPrompt: string }[]
      const migrated: SystemPromptPreset[] = old
        .filter(p => p.systemPrompt.trim())
        .map(p => ({ id: p.id, name: p.name, systemPrompt: p.systemPrompt }))
      localStorage.setItem('systemPromptPresets', JSON.stringify(migrated))
      return migrated
    } catch {
      // Corrupted migration data — fall through
    }
  }

  return DEFAULT_SYSTEM_PROMPT_PRESETS.map(p => ({ ...p }))
}