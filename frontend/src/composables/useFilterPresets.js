import { ref, readonly } from 'vue'

const STORAGE_KEY = 'mrp_workbench_filter_presets'

function readStore() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
  } catch {
    return []
  }
}

function writeStore(presets) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(presets))
  } catch {
    // localStorage unavailable (e.g. strict private browsing)
  }
}

export function useFilterPresets() {
  const presets = ref(readStore())

  function save(preset) {
    const existing = presets.value.findIndex((p) => p.name === preset.name)
    const entry = { ...preset, createdAt: new Date().toISOString() }
    if (existing >= 0) {
      presets.value.splice(existing, 1, entry)
    } else {
      presets.value.unshift(entry)
    }
    writeStore(presets.value)
  }

  function remove(name) {
    presets.value = presets.value.filter((p) => p.name !== name)
    writeStore(presets.value)
  }

  function load(name) {
    return presets.value.find((p) => p.name === name)
  }

  return { presets: readonly(presets), save, remove, load }
}
