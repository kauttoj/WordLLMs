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
  official: 'official',
  anthropic: 'anthropic',
  azure: 'azure',
  gemini: 'gemini',
  ollama: 'ollama',
  groq: 'groq',
  lmstudio: 'lmstudio',
}

// official API 可用的模型
export const availableModels: string[] = ['gpt-5.2-pro', 'gpt-5.2', 'gpt-5.1', 'gpt-5-mini', 'gpt-5-nano', 'gpt-4.1']

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
  systemPrompt: string
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
    systemPrompt:
      'You are an expert polyglot translator. Your task is to provide professional, context-aware translations into ${language}.\n      Maintain formatting, keep the original tone, and ensure the output is idiomatic and elegant.',
    userPrompt:
      'Translate my text into ${language}.\n      Constraints:\n      1. Provide a natural-sounding translation suitable for native speakers.\n      2. If the text is technical, use appropriate terminology.\n      3. OUTPUT ONLY the translated text. Do not include "Here is the translation" or any explanations.',
    icon: 'Globe',
    enabled: true,
  },
  {
    id: 'slot_2',
    name: 'Polish',
    systemPrompt:
      'You are a professional editor and stylist. Your goal is to make the text more professional, engaging, and clear in ${language}.',
    userPrompt:
      'Polish my text for better flow and impact.\n      Improvements:\n      - Correct grammar, spelling, and punctuation.\n      - Enhance vocabulary while maintaining the original meaning.\n      - Improve sentence structure and eliminate redundancy.\n      - Ensure the tone is consistent and professional.\n      Constraints:\n      1. Respond in ${language}.\n      2. OUTPUT ONLY the polished text without any commentary.',
    icon: 'Sparkle',
    enabled: true,
  },
  {
    id: 'slot_3',
    name: 'Academic',
    systemPrompt:
      'You are a senior academic editor for high-impact journals (e.g., Nature, Science). You specialize in formal, precise, and objective scholarly writing in ${language}.',
    userPrompt:
      'Rewrite my text to meet professional academic standards.\n      Requirements:\n      - Use formal, objective language and avoid colloquialisms.\n      - Ensure logical transitions and precise scientific terminology.\n      - Maintain a third-person perspective unless the context requires otherwise.\n      - Optimize for clarity and conciseness as per peer-review expectations.\n      Constraints:\n      1. Respond in ${language}.\n      2. OUTPUT ONLY the revised text. No pre-amble or meta-talk.',
    icon: 'BookOpen',
    enabled: true,
  },
  {
    id: 'slot_4',
    name: 'Summary',
    systemPrompt:
      'You are an expert document analyst. You excel at distilling complex information into clear, actionable summaries in ${language}.',
    userPrompt:
      'Summarize my text.\n      Structure:\n      - Capture the core message and primary supporting points.\n      - Aim for approximately 100 words (or 3-5 key bullet points).\n      - Ensure the summary is self-contained and easy to understand.\n      Constraints:\n      1. Respond in ${language}.\n      2. OUTPUT ONLY the summary.',
    icon: 'FileCheck',
    enabled: true,
  },
  {
    id: 'slot_5',
    name: 'Grammar',
    systemPrompt:
      'You are a meticulous proofreader. Your sole focus is linguistic accuracy, including syntax, morphology, and orthography in ${language}.',
    userPrompt:
      'Check and correct the grammar of my text.\n      Focus:\n      - Fix all spelling and punctuation errors.\n      - Correct subject-verb agreement and tense inconsistencies.\n      - Ensure proper sentence structure.\n      Constraints:\n      1. If the text is already perfect, respond exactly with: "No grammatical issues found."\n      2. Otherwise, provide ONLY the corrected text without explaining the changes.\n      3. Respond in ${language}.',
    icon: 'CheckCircle',
    enabled: true,
  },
  { id: 'slot_6', name: '', systemPrompt: '', userPrompt: '', icon: 'Lightbulb', enabled: false },
  { id: 'slot_7', name: '', systemPrompt: '', userPrompt: '', icon: 'PenTool', enabled: false },
  { id: 'slot_8', name: '', systemPrompt: '', userPrompt: '', icon: 'Star', enabled: false },
]

function makeEmptySlot(index: number): QuickActionSlot {
  return { id: `slot_${index}`, name: '', systemPrompt: '', userPrompt: '', icon: 'Sparkle', enabled: false }
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
          defaults[i].systemPrompt = custom[key].system
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

  return []
}

// --- Legacy built-in prompts (kept for backward compatibility) ---

export const buildInPrompt = {
  translate: {
    system: (language: string) =>
      `You are an expert polyglot translator. Your task is to provide professional, context-aware translations into ${language}.
      Maintain formatting, keep the original tone, and ensure the output is idiomatic and elegant.`,
    user: (language: string) =>
      `Translate my text into ${language}.
      Constraints:
      1. Provide a natural-sounding translation suitable for native speakers.
      2. If the text is technical, use appropriate terminology.
      3. OUTPUT ONLY the translated text. Do not include "Here is the translation" or any explanations.`,
  },

  polish: {
    system: (language: string) =>
      `You are a professional editor and stylist. Your goal is to make the text more professional, engaging, and clear in ${language}.`,
    user: (language: string) =>
      `Polish my text for better flow and impact.
      Improvements:
      - Correct grammar, spelling, and punctuation.
      - Enhance vocabulary while maintaining the original meaning.
      - Improve sentence structure and eliminate redundancy.
      - Ensure the tone is consistent and professional.
      Constraints:
      1. Respond in ${language}.
      2. OUTPUT ONLY the polished text without any commentary.`,
  },

  academic: {
    system: (language: string) =>
      `You are a senior academic editor for high-impact journals (e.g., Nature, Science). You specialize in formal, precise, and objective scholarly writing in ${language}.`,
    user: (language: string) =>
      `Rewrite my text to meet professional academic standards.
      Requirements:
      - Use formal, objective language and avoid colloquialisms.
      - Ensure logical transitions and precise scientific terminology.
      - Maintain a third-person perspective unless the context requires otherwise.
      - Optimize for clarity and conciseness as per peer-review expectations.
      Constraints:
      1. Respond in ${language}.
      2. OUTPUT ONLY the revised text. No pre-amble or meta-talk.`,
  },

  summary: {
    system: (language: string) =>
      `You are an expert document analyst. You excel at distilling complex information into clear, actionable summaries in ${language}.`,
    user: (language: string) =>
      `Summarize my text.
      Structure:
      - Capture the core message and primary supporting points.
      - Aim for approximately 100 words (or 3-5 key bullet points).
      - Ensure the summary is self-contained and easy to understand.
      Constraints:
      1. Respond in ${language}.
      2. OUTPUT ONLY the summary.`,
  },

  grammar: {
    system: (language: string) =>
      `You are a meticulous proofreader. Your sole focus is linguistic accuracy, including syntax, morphology, and orthography in ${language}.`,
    user: (language: string) =>
      `Check and correct the grammar of my text.
      Focus:
      - Fix all spelling and punctuation errors.
      - Correct subject-verb agreement and tense inconsistencies.
      - Ensure proper sentence structure.
      Constraints:
      1. If the text is already perfect, respond exactly with: "No grammatical issues found."
      2. Otherwise, provide ONLY the corrected text without explaining the changes.
      3. Respond in ${language}.`,
  },
}

export const getBuiltInPrompt = () => {
  const stored = localStorage.getItem('customBuiltInPrompts')
  if (!stored) {
    return buildInPrompt
  }

  try {
    const customPrompts = JSON.parse(stored)
    const result = { ...buildInPrompt }

    Object.keys(customPrompts).forEach(key => {
      const typedKey = key as keyof typeof buildInPrompt
      if (result[typedKey]) {
        result[typedKey] = {
          system: (language: string) => customPrompts[key].system.replace(/\$\{language\}/g, language),
          user: (language: string) => customPrompts[key].user.replace(/\$\{language\}/g, language),
        }
      }
    })

    return result
  } catch (error) {
    console.error('Error loading custom built-in prompts:', error)
    return buildInPrompt
  }
}
