import './index.css'

import { createApp } from 'vue'

import App from './App.vue'
import { i18n } from './i18n'
import router from './router'

const initApp = () => {
  const app = createApp(App)
  const debounce = (fn: (...args: any[]) => void, delay?: number) => {
    let timer: number | null = null
    return function (this: unknown, ...args: any[]) {
      const context = this

      if (timer !== null) clearTimeout(timer)
      timer = window.setTimeout(() => {
        fn.apply(context, args)
      }, delay)
    }
  }

  const _ResizeObserver = window.ResizeObserver
  window.ResizeObserver = class ResizeObserver extends _ResizeObserver {
    constructor(callback: ResizeObserverCallback) {
      callback = debounce(callback, 16)
      super(callback)
    }
  }
  app.use(i18n)
  app.use(router)
  app.mount('#app')
}

// Support both browser and Word environments
if (typeof window.Office !== 'undefined') {
  window.Office.onReady(() => {
    initApp()
  })
} else {
  // Browser mode - init immediately
  console.log('[Main] Running in browser mode (Office.js not detected)')
  initApp()
}
