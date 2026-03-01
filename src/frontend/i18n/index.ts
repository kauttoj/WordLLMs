import { createI18n } from 'vue-i18n'

import { localStorageKey } from '@/utils/enum'

import en from './locales/en.json'

const messages = {
  en,
}

export const i18n = createI18n({
  legacy: false,
  locale: localStorage.getItem(localStorageKey.localLanguage) || 'en',
  fallbackLocale: 'en',
  messages,
})
