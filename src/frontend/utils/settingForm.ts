import { Ref, ref } from 'vue'

import { localStorageKey } from './enum'
import { Setting_Names, SettingNames, settingPreset } from './settingPreset'

type SettingForm = {
  [K in SettingNames]: (typeof settingPreset)[K]['defaultValue']
}

type SettingValue = string | number | string[]

function initializeSettings(): Record<string, SettingValue> {
  const settings: Record<string, SettingValue> = {}

  for (const key of Setting_Names) {
    const preset = settingPreset[key]

    if (preset.getFunc) {
      settings[key] = preset.getFunc()
    } else {
      const storageKey = preset.saveKey || key
      const storedValue = localStorage.getItem(storageKey)
      settings[key] = storedValue ?? preset.defaultValue
    }
  }

  // Auto-select migrated Azure deployment
  if (
    !settings.azureModelSelect &&
    Array.isArray(settings.azureCustomModels) &&
    (settings.azureCustomModels as string[]).length > 0
  ) {
    settings.azureModelSelect = (settings.azureCustomModels as string[])[0]
    localStorage.setItem(localStorageKey.azureModel, settings.azureModelSelect as string)
  }

  return settings
}

// Module-level singleton so both HomePage and SettingsPage share the same ref.
// Without this, each call creates an isolated ref — settings saved in SettingsPage
// never propagate to HomePage until the add-in restarts.
const _settingForm = ref(initializeSettings()) as Ref<SettingForm>

function useSettingForm() {
  return _settingForm
}

export default useSettingForm
