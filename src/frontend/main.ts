import './index.css'

import { createApp } from 'vue'

import { bootstrapProfile } from './api/profile'
import App from './App.vue'
import { i18n } from './i18n'
import router from './router'

function renderBackendDownError(err: unknown) {
  const root = document.getElementById('app')
  if (!root) return
  const msg = err instanceof Error ? err.message : String(err)
  root.innerHTML = `
    <div style="padding:24px;font-family:system-ui,sans-serif;color:#333;max-width:520px;margin:40px auto;">
      <h2 style="margin:0 0 12px;">Backend unreachable</h2>
      <p>WordLLMs requires the Python backend to be running. Start it and reload this pane.</p>
      <p style="color:#888;font-size:12px;">Details: ${msg}</p>
      <button onclick="window.location.reload()" style="padding:6px 16px;cursor:pointer;">Reload</button>
    </div>
  `
}

const initApp = async () => {
  try {
    await bootstrapProfile()
  } catch (err) {
    console.error('[Main] Profile bootstrap failed:', err)
    renderBackendDownError(err)
    return
  }
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
  console.log('[Main] Running outside Word (Office.js not detected)')
  initApp()
}
