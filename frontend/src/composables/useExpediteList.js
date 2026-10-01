import { ref, readonly } from 'vue'
import { call } from 'frappe-ui'

// Module-level state so the sidebar, the MRP Workbench and the Expedite List share one status
const enabled = ref(false)
const count = ref(0)
const needsRerun = ref(false)
const loaded = ref(false)

async function refresh() {
  try {
    const status = await call(
      'erpnext_mrp.mrp.tasks.mrp_run.get_expedite_status',
    )
    enabled.value = status.enabled
    count.value = status.count
    needsRerun.value = status.needs_rerun
    loaded.value = true
  } catch (e) {
    console.warn('Expedite List status failed:', e)
  }
}

export function useExpediteList() {
  return {
    enabled: readonly(enabled),
    count: readonly(count),
    needsRerun: readonly(needsRerun),
    loaded: readonly(loaded),
    refresh,
  }
}
