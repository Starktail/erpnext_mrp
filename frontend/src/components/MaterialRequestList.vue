<template>
  <div class="h-full flex flex-col">
    <div class="mb-4 flex justify-between items-center shrink-0">
      <div class="flex gap-2 items-center">
        <Button @click="clearFilters">Clear Filters</Button>
        <NDropdown
          trigger="click"
          :options="presetDropdownOptions"
          @select="handlePresetDropdownSelect"
        >
          <span>
            <Button
              :class="activePresetName ? 'font-semibold text-blue-700' : ''"
            >
              {{ activePresetName ?? 'Filters ▾' }}
            </Button>
          </span>
        </NDropdown>
        <Button @click="rerunMrp">Rerun MRP Calculations</Button>
        <Combobox
          :options="quantityFields"
          v-model="closed_column_field"
          placeholder="Select a field"
        />
      </div>
      <!-- Colour Legend -->
      <div class="flex items-center gap-4">
        <div class="text-sm text-gray-600">{{ lastMrpRunTime }}</div>
        <div class="flex items-center gap-2 text-sm">
          <div class="w-4 h-4 rounded" style="background-color: #ddeeff"></div>
          <span class="text-gray-600">Suggested Order</span>
        </div>
        <div class="flex items-center gap-2 text-sm">
          <div class="w-4 h-4 rounded" style="background-color: #fed7d7"></div>
          <span class="text-gray-600">Shortage</span>
        </div>
        <div class="flex items-center gap-2 text-sm">
          <div class="w-4 h-4 rounded" style="background-color: #fff2cc"></div>
          <span class="text-gray-600">Below Safety Stock</span>
        </div>
        <Button
          @click="openCreateRequestDialog"
          :disabled="selectedRowKeys.length === 0"
          >Create Material Request</Button
        >
      </div>
    </div>

    <div class="w-full flex-grow">
      <n-data-table
        ref="tableRef"
        remote
        :columns="columns"
        :data="treeData"
        :row-key="rowKey"
        :loading="loadingRef"
        :bordered="true"
        :single-line="false"
        size="small"
        :pagination="paginationReactive"
        :checked-row-keys="selectedRowKeys"
        :row-class-name="rowClassName"
        @update:checked-row-keys="handleCheck"
        @update:filters="handleFiltersChange"
        @update:sorter="handleSorterChange"
        @update:page="handlePageChange"
        @update:page-size="handlePageSizeChange"
        @load="onLoad"
        :cascade="false"
        allow-checking-not-loaded
        :scroll-x="scrollX"
        virtual-scroll
        flex-height
        striped
        class="h-full"
      />
    </div>

    <Dialog v-model="showRerunDialog" @hide="showRerunDialog = false">
      <template #body-title>
        <h3 class="text-2xl font-semibold text-ink-gray-9">
          MRP Calculations Started
        </h3>
      </template>
      <template #body-content>
        <div>
          <p>The MRP calculations have been started in the background.</p>
          <p>
            You can monitor the progress of the job here:
            <a
              href="/app/rq-job"
              target="_blank"
              class="text-blue-600 hover:underline"
              >View Background Jobs</a
            >
          </p>
          <p>
            This page will automatically refresh when the calculations are
            complete.
          </p>
        </div>
      </template>
      <template #actions>
        <Button @click="showRerunDialog = false">Close</Button>
      </template>
    </Dialog>
    <Dialog v-model="showForecastWarning" @hide="showForecastWarning = false">
      <template #body-title>
        <h3 class="text-2xl font-semibold text-ink-gray-9">
          Insufficient Forecast Data
        </h3>
      </template>
      <template #body-content>
        <div class="space-y-3">
          <p>
            Your MRP look-ahead window is
            <strong>{{ forecastWarningData.look_ahead_weeks }} weeks</strong>
            (until
            <strong>{{ forecastWarningData.look_ahead_end_date }}</strong
            >), but forecast data only extends to
            <strong>{{
              forecastWarningData.max_forecast_date ?? 'no forecasts found'
            }}</strong
            >.
          </p>
          <p>
            The last
            <strong
              >{{ forecastWarningData.weeks_short }} week{{
                forecastWarningData.weeks_short !== 1 ? 's' : ''
              }}</strong
            >
            of the planning horizon have no forecast demand. Suggested orders
            and projected stock for those weeks may be understated.
          </p>
          <p>
            To resolve this, extend your
            <a
              href="/app/mrp-forecast"
              target="_blank"
              class="text-blue-600 hover:underline"
              >MRP Forecast</a
            >
            records to cover at least
            <strong>{{ forecastWarningData.look_ahead_end_date }}</strong
            >.
          </p>
        </div>
      </template>
      <template #actions>
        <Button @click="showForecastWarning = false">Dismiss</Button>
      </template>
    </Dialog>
    <Dialog v-model="showDialog" @hide="showDialog = false">
      <template #body-title>
        <h3 class="text-2xl font-semibold text-ink-gray-9">
          Material Request Details
        </h3>
      </template>
      <template #body-content>
        <div>
          <p>Dialog content will go here.</p>
          <p>For now, this confirms the dialog is working.</p>
        </div>
      </template>
      <template #actions>
        <Button @click="showDialog = false">Close</Button>
      </template>
    </Dialog>
    <Dialog
      v-model="showBreakdownDialog"
      @hide="showBreakdownDialog = false"
      :options="{ size: 'xl' }"
    >
      <template #body-title>
        <div class="flex items-center gap-1 flex-wrap">
          <span
            v-for="(frame, idx) in breakdownStack"
            :key="idx"
            class="flex items-center gap-1"
          >
            <span v-if="idx > 0" class="text-gray-400">›</span>
            <button
              v-if="idx < breakdownStack.length - 1"
              class="text-blue-500 hover:underline text-sm font-normal"
              @click="breakdownStack.splice(idx + 1)"
            >
              {{ frame.item_code }}
            </button>
            <span v-else class="text-lg font-semibold text-ink-gray-9">
              {{ frame.item_code }}
            </span>
            <span class="text-xs text-gray-400">{{ frame.week_key }}</span>
          </span>
        </div>
      </template>
      <template #body-content>
        <div v-if="breakdownLoading" class="py-8 text-center text-gray-400">
          Loading…
        </div>
        <div v-else-if="breakdownData" class="space-y-6 text-sm">
          <div class="flex gap-6 p-3 bg-gray-50 rounded font-mono text-xs">
            <span
              >Direct forecast:
              <b>{{ breakdownData.stored.forecast_demand }}</b></span
            >
            <span>+</span>
            <span
              >Upstream net demand:
              <b>{{ breakdownData.stored.upstream_net_demand }}</b></span
            >
            <span>=</span>
            <span
              >Total:
              <b>{{ breakdownData.stored.total_forecast_demand }}</b></span
            >
          </div>
          <div
            v-if="breakdownReconciliationWarning"
            class="text-xs text-orange-600 bg-orange-50 border border-orange-200 rounded p-2"
          >
            ⚠ Calculated values differ from stored values. BOMs or forecasts
            may have changed since the last MRP run ({{
              breakdownData.last_mrp_run ?? 'unknown'
            }}).
          </div>
          <div>
            <h4 class="font-semibold text-gray-700 mb-2">
              Direct Forecasts
              <span class="font-normal text-gray-400"
                >({{ breakdownData.direct_forecasts.length }} entries)</span
              >
            </h4>
            <p
              v-if="breakdownData.direct_forecasts.length === 0"
              class="text-gray-400 italic text-xs"
            >
              No MRP Forecast entries for this item in this week.
            </p>
            <table v-else class="w-full text-xs border-collapse">
              <thead>
                <tr class="border-b text-left text-gray-500">
                  <th class="py-1 pr-4">Forecast Date</th>
                  <th class="py-1 pr-4 text-right">Quantity</th>
                  <th class="py-1">Document</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="f in breakdownData.direct_forecasts"
                  :key="f.name"
                  class="border-b border-gray-100"
                >
                  <td class="py-1 pr-4">{{ f.forecast_date }}</td>
                  <td class="py-1 pr-4 text-right font-mono">
                    {{ f.forecast_quantity }}
                  </td>
                  <td class="py-1">
                    <a
                      :href="`/app/mrp-forecast/${f.name}`"
                      target="_blank"
                      class="text-blue-500 hover:underline"
                      >{{ f.name }}</a
                    >
                  </td>
                </tr>
                <tr class="font-semibold text-gray-700 border-t">
                  <td class="py-1 pr-4">Total</td>
                  <td class="py-1 pr-4 text-right font-mono">
                    {{ directForecastTotal }}
                  </td>
                  <td></td>
                </tr>
              </tbody>
            </table>
          </div>
          <div>
            <h4 class="font-semibold text-gray-700 mb-2">
              Upstream Net Demand
              <span class="font-normal text-gray-400">
                (exploded from
                {{ breakdownData.parent_contributions.length }} parent item(s))
              </span>
            </h4>
            <p
              v-if="breakdownData.parent_contributions.length === 0"
              class="text-gray-400 italic text-xs"
            >
              No parent items contributed upstream demand in this week.
            </p>
            <table v-else class="w-full text-xs border-collapse">
              <thead>
                <tr class="border-b text-left text-gray-500">
                  <th class="py-1 pr-4">Parent Item</th>
                  <th class="py-1 pr-4 text-right">Suggestions</th>
                  <th class="py-1 pr-4 text-right">BOM Ratio</th>
                  <th class="py-1 pr-4 text-right">Contribution</th>
                  <th class="py-1 pr-4">Parent Week</th>
                  <th class="py-1"></th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="p in breakdownData.parent_contributions"
                  :key="`${p.parent_item_code}-${p.parent_target_date}`"
                  class="border-b border-gray-100"
                >
                  <td class="py-1 pr-4">
                    <a
                      :href="`/app/item/${p.parent_item_code}`"
                      target="_blank"
                      class="text-blue-500 hover:underline"
                      >{{ p.parent_item_code }}</a
                    >
                    <span class="text-gray-400 ml-1">{{
                      p.parent_item_name
                    }}</span>
                  </td>
                  <td class="py-1 pr-4 text-right font-mono">
                    {{ p.parent_suggested_receipts }}
                  </td>
                  <td class="py-1 pr-4 text-right font-mono">
                    {{ p.component_qty_per_bom }}/{{ p.bom_output_qty }} =
                    {{
                      (p.component_qty_per_bom / p.bom_output_qty).toFixed(4)
                    }}
                  </td>
                  <td class="py-1 pr-4 text-right font-mono">
                    {{ p.contribution }}
                  </td>
                  <td class="py-1 pr-4 text-gray-500">
                    {{ p.parent_target_date }}
                  </td>
                  <td class="py-1">
                    <button
                      v-if="
                        p.parent_bom_level > 0 &&
                        !isAlreadyInBreakdownStack(p.parent_item_code)
                      "
                      class="text-xs text-blue-500 hover:underline whitespace-nowrap"
                      @click="
                        drillUpToParent(
                          p.parent_item_code,
                          p.parent_item_name,
                          p.parent_target_date,
                        )
                      "
                    >
                      Explain ↑
                    </button>
                  </td>
                </tr>
                <tr class="font-semibold text-gray-700 border-t">
                  <td class="py-1 pr-4" colspan="3">Total</td>
                  <td class="py-1 pr-4 text-right font-mono">
                    {{ upstreamTotal.toFixed(3) }}
                  </td>
                  <td colspan="2"></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="text-xs text-gray-400">
            MRP last run: {{ breakdownData.last_mrp_run ?? 'unknown' }}
          </p>
        </div>
      </template>
      <template #actions>
        <Button
          v-if="breakdownStack.length > 1"
          variant="subtle"
          @click="breakdownGoBack"
        >
          ← Back
        </Button>
        <Button @click="showBreakdownDialog = false">Close</Button>
      </template>
    </Dialog>
    <Dialog v-model="showCreateDialog" @hide="showCreateDialog = false">
      <template #body-title>
        <h3 class="text-2xl font-semibold text-ink-gray-9">
          Create Material Request
        </h3>
      </template>
      <template #body-content>
        <div>
          <p>
            You are about to create Material Requests for the following items:
          </p>
          <ul
            v-if="selectedItemsSummary.length > 0"
            class="list-disc list-inside my-4"
          >
            <li v-for="(item, index) in selectedItemsSummary" :key="index">
              Item: {{ item.item_code }}, Qty: {{ item.quantity }}, Week:
              {{ item.week }}, Supplier: {{ item.supplier || 'N/A' }}
            </li>
          </ul>
          <p v-else class="my-4">No items with suggested orders selected.</p>
        </div>
      </template>
      <template #actions>
        <Button @click="showCreateDialog = false">Cancel</Button>
        <Button
          @click="confirmCreateMaterialRequest"
          variant="solid"
          :disabled="selectedItemsSummary.length === 0"
          >Confirm</Button
        >
      </template>
    </Dialog>
    <Dialog v-model="showSavePresetModal" @hide="showSavePresetModal = false">
      <template #body-title>
        <h3 class="text-2xl font-semibold text-ink-gray-9">
          Save Filter Preset
        </h3>
      </template>
      <template #body-content>
        <div class="space-y-2">
          <NInput
            v-model:value="presetNameInput"
            placeholder="Preset name…"
            autofocus
            @keydown.enter="confirmSavePreset"
          />
          <p v-if="presetNameConflict" class="text-sm text-orange-600">
            A preset with this name already exists and will be overwritten.
          </p>
        </div>
      </template>
      <template #actions>
        <Button @click="showSavePresetModal = false">Cancel</Button>
        <Button
          variant="solid"
          :disabled="!presetNameInput.trim()"
          @click="confirmSavePreset"
          >Save</Button
        >
      </template>
    </Dialog>
    <Dialog v-model="showSuccessDialog" @hide="showSuccessDialog = false">
      <template #body-title>
        <h3 class="text-2xl font-semibold text-ink-gray-9">
          Material Requests Created
        </h3>
      </template>
      <template #body-content>
        <div>
          <p>The following Material Requests have been created successfully:</p>
          <ul v-if="newlyCreatedDocs.length" class="list-disc list-inside my-4">
            <li v-for="doc in newlyCreatedDocs" :key="doc.name">
              <a
                :href="`/app/material-request/${doc.name}`"
                target="_blank"
                class="text-blue-600 hover:underline"
                >{{ doc.name }}</a
              >
            </li>
          </ul>
        </div>
      </template>
      <template #actions>
        <Button @click="showSuccessDialog = false">Close</Button>
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import {
  ref,
  reactive,
  computed,
  watch,
  nextTick,
  h,
  onMounted,
  onUnmounted,
} from 'vue'
import { NDataTable, NInput, NInputNumber, NSpace, NDropdown } from 'naive-ui'
import { useFilterPresets } from '../composables/useFilterPresets'
import {
  Button,
  Dialog,
  Combobox,
  Checkbox,
  call,
  toast,
  createListResource,
  createResource,
  createDocumentResource,
} from 'frappe-ui'
import { formatCurrency as formatCurrencyUtil } from '../utils/numberFormat'

const {
  presets,
  save: savePreset,
  remove: removePreset,
  load: loadPreset,
} = useFilterPresets()
const showSavePresetModal = ref(false)
const presetNameInput = ref('')

const showDialog = ref(false)
const closed_column_field = ref('suggested_orders')
const selectedRowKeys = ref([])
const showCreateDialog = ref(false)
const selectedItemsSummary = ref([])
const showSuccessDialog = ref(false)
const newlyCreatedDocs = ref([])
const showRerunDialog = ref(false)
const showForecastWarning = ref(false)
const showBreakdownDialog = ref(false)
const breakdownStack = ref([])
const currentStockLevels = ref({})
const stockSyncLoading = ref(false)
const SYNC_EPSILON = 0.001
const forecastWarningData = reactive({
  weeks_short: 0,
  max_forecast_date: null,
  look_ahead_end_date: null,
  look_ahead_weeks: 0,
})

const textFilters = reactive({
  item_code: '',
  item_name: '',
  item_group: '',
  bom_list: '',
  default_supplier: '',
})

const appliedTextFilters = reactive({
  item_code: '',
  item_name: '',
  item_group: '',
  bom_list: '',
  default_supplier: '',
})

const excludeFilters = reactive({
  item_code: '',
  item_name: '',
  item_group: '',
  bom_list: '',
  default_supplier: '',
})

const appliedExcludeFilters = reactive({
  item_code: '',
  item_name: '',
  item_group: '',
  bom_list: '',
  default_supplier: '',
})

const numberFilters = reactive({
  reorder_level: { min: null, max: null },
  reorder_quantity: { min: null, max: null },
  lead_time: { min: null, max: null },
  days_to_reorder: { min: null, max: null },
  days_to_reorder_excl_reorder_level: { min: null, max: null },
})

const appliedNumberFilters = reactive({
  reorder_level: { min: null, max: null },
  reorder_quantity: { min: null, max: null },
  lead_time: { min: null, max: null },
  days_to_reorder: { min: null, max: null },
  days_to_reorder_excl_reorder_level: { min: null, max: null },
})

const LABEL_STYLE = { marginBottom: '4px', fontSize: '11px', color: '#888' }

function commitTextFilter(columnKey, hide) {
  appliedTextFilters[columnKey] = textFilters[columnKey]
  appliedExcludeFilters[columnKey] = excludeFilters[columnKey]
  paginationReactive.page = 1
  executeAsyncQuery()
  hide()
}

function clearTextFilter(columnKey, hide) {
  textFilters[columnKey] = ''
  appliedTextFilters[columnKey] = ''
  excludeFilters[columnKey] = ''
  appliedExcludeFilters[columnKey] = ''
  paginationReactive.page = 1
  executeAsyncQuery()
  hide()
}

function renderTextFilter(columnKey, placeholder) {
  return ({ hide }) => {
    return h('div', { style: { padding: '8px', width: '280px' } }, [
      h('div', { style: LABEL_STYLE }, 'Include (contains)'),
      h(NInput, {
        value: textFilters[columnKey],
        'onUpdate:value': (v) => {
          textFilters[columnKey] = v
        },
        placeholder,
        size: 'small',
        style: { marginBottom: '8px' },
        onKeyup: (e) => {
          if (e.key === 'Enter') commitTextFilter(columnKey, hide)
        },
      }),
      h('div', { style: LABEL_STYLE }, 'Exclude (not contains)'),
      h(NInput, {
        value: excludeFilters[columnKey],
        'onUpdate:value': (v) => {
          excludeFilters[columnKey] = v
        },
        placeholder: `Exclude ${placeholder.replace('Search ', '')}`,
        size: 'small',
        style: { marginBottom: '8px' },
        onKeyup: (e) => {
          if (e.key === 'Enter') commitTextFilter(columnKey, hide)
        },
      }),
      h(NSpace, { justify: 'end' }, () => [
        h(
          Button,
          { size: 'sm', onClick: () => clearTextFilter(columnKey, hide) },
          () => 'Clear',
        ),
        h(
          Button,
          {
            size: 'sm',
            variant: 'solid',
            onClick: () => commitTextFilter(columnKey, hide),
          },
          () => 'Search',
        ),
      ]),
    ])
  }
}

function renderNumberFilter(columnKey) {
  return ({ hide }) => {
    return h('div', { style: { padding: '8px', width: '250px' } }, [
      h(NSpace, { vertical: true, style: { marginBottom: '8px' } }, () => [
        h(NInputNumber, {
          value: numberFilters[columnKey].min,
          'onUpdate:value': (v) => {
            numberFilters[columnKey].min = v
          },
          placeholder: 'Min',
          size: 'small',
          clearable: true,
        }),
        h(NInputNumber, {
          value: numberFilters[columnKey].max,
          'onUpdate:value': (v) => {
            numberFilters[columnKey].max = v
          },
          placeholder: 'Max',
          size: 'small',
          clearable: true,
        }),
      ]),
      h(NSpace, { justify: 'end' }, () => [
        h(
          Button,
          {
            size: 'sm',
            onClick: () => {
              numberFilters[columnKey].min = null
              numberFilters[columnKey].max = null
              appliedNumberFilters[columnKey].min = null
              appliedNumberFilters[columnKey].max = null
              paginationReactive.page = 1
              executeAsyncQuery()
              hide()
            },
          },
          () => 'Clear',
        ),
        h(
          Button,
          {
            size: 'sm',
            variant: 'solid',
            onClick: () => {
              appliedNumberFilters[columnKey].min = numberFilters[columnKey].min
              appliedNumberFilters[columnKey].max = numberFilters[columnKey].max
              paginationReactive.page = 1
              executeAsyncQuery()
              hide()
            },
          },
          () => 'Filter',
        ),
      ]),
    ])
  }
}

async function checkStockSync(itemCodes) {
  if (!itemCodes.length) return
  stockSyncLoading.value = true
  try {
    currentStockLevels.value = await call(
      'erpnext_mrp.api.get_current_stock_levels',
      { item_codes: JSON.stringify(itemCodes) },
    )
  } catch (e) {
    console.warn('Stock sync check failed:', e)
  }
  stockSyncLoading.value = false
}

function isOutOfSync(row) {
  if (row.type !== 'HEADER') return false
  const current = currentStockLevels.value[row.item_code]
  if (current === undefined) return false
  return Math.abs(current - (row.on_hand_inventory ?? 0)) > SYNC_EPSILON
}

function syncDelta(row) {
  const current = currentStockLevels.value[row.item_code] ?? 0
  return current - (row.on_hand_inventory ?? 0)
}

function isBomParent(row) {
  if (!row.bom_list) return false
  const prefix = `BOM-${row.item_code}-`
  return row.bom_list.split(',').some((bom) => bom.trim().startsWith(prefix))
}

const EXCLUDE_CHIP_STYLE = {
  color: '#c0392b',
  fontSize: '10px',
  marginLeft: '4px',
  fontWeight: 'normal',
}

function renderColumnTitle(label, columnKey) {
  return h('span', {}, [
    label,
    appliedExcludeFilters[columnKey]
      ? h('span', { style: EXCLUDE_CHIP_STYLE }, 'x excl')
      : null,
  ])
}

const sorterRef = ref({ columnKey: 'days_to_reorder', order: 'ascend' })

const paginationReactive = reactive({
  page: 1,
  pageSize: 50,
  showSizePicker: true,
  pageSizes: [10, 20, 50, 100],
  itemCount: 0,
})

const treeData = ref([])
const scrollX = ref(2500)
const loadingRef = ref(true)

const mrpRunCompleteHandler = () => {
  currentStockLevels.value = {}
  toast.success('MRP data refreshed')
  executeAsyncQuery()
  last_mrp_run.reload()
}

onMounted(async () => {
  const params = new URLSearchParams(window.location.search)
  const presetParam = params.get('preset')
  let presetLoaded = false
  if (presetParam) {
    const preset = loadPreset(presetParam)
    if (preset) {
      applyPreset(preset)
      presetLoaded = true
    }
  }
  if (!presetLoaded) executeAsyncQuery()
  checkForecastCoverage()
  window.frappe?.realtime?.on('mrp_run_complete', mrpRunCompleteHandler)
})

onUnmounted(() => {
  window.frappe?.realtime?.off('mrp_run_complete', mrpRunCompleteHandler)
})

const mrp_settings = createDocumentResource({
  doctype: 'MRP Settings',
  name: 'MRP Settings',
  auto: true,
})

const defaultTimeUnit = computed(
  () => mrp_settings.doc?.default_time_unit || 'Days',
)

const last_mrp_run = createListResource({
  doctype: 'Scheduled Job Log',
  fields: ['creation'],
  filters: {
    scheduled_job_type: 'mrp_run.mrp_run',
  },
  orderBy: 'creation desc',
  pageLength: 1,
  auto: true,
})

const lastMrpRunTime = computed(() => {
  if (last_mrp_run.list.loading) {
    return 'Loading...'
  }
  if (!last_mrp_run.data || last_mrp_run.data.length === 0) {
    return 'MRP has not run yet.'
  }
  const lastRun = last_mrp_run.data[0]
  if (lastRun) {
    const d = new Date(lastRun.creation)
    return `Last MRP Run: ${d.toLocaleString()}`
  }
  return 'MRP has not run yet.'
})

const material_request_creator = createResource({
  url: 'frappe.client.insert',
})

function formatQuantity(value) {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value !== 'number') return value
  const absVal = Math.abs(value)
  if (absVal >= 1000) {
    const kVal = value / 1000
    return (kVal % 1 === 0 ? kVal.toString() : kVal.toFixed(1)) + 'k'
  }
  return value
}

function formatTime(value) {
  if (value === null || value === undefined || value === '') return ''
  let val = value
  if (defaultTimeUnit.value === 'Weeks') {
    val = val / 7
    val = Math.round(val * 10) / 10
  }
  return formatQuantity(val)
}

function formatCurrency(value) {
  if (value === null || value === undefined || value === '') return ''
  if (Math.abs(value) >= 1000) {
    const kVal = value / 1000
    const formattedK = kVal % 1 === 0 ? kVal.toString() : kVal.toFixed(1)
    const currency = window.sysdefaults?.currency || 'USD'
    const sample = formatCurrencyUtil(1, null, currency, 0)
    return sample.replace('1', `${formattedK}k`).replace(/\s/g, '')
  }
  const currency = window.sysdefaults?.currency
  return formatCurrencyUtil(value, null, currency, 0)
}

const ALL_QUANTITY_FIELDS = [
  {
    value: 'projected_on_hand_inventory_no_action',
    label: 'Projected On Hand (without Suggested Orders)',
    formatter: (val) => (val < 0 ? '<0' : formatQuantity(val)),
    cellClass: (val, data) => {
      if (val < 0) return 'shortage'
      if (val < data.reorder_level) return 'below-safety'
      return ''
    },
  },
  { value: 'scheduled_receipts', label: 'Scheduled Receipts' },
  { value: 'suggested_receipts', label: 'Suggested Receipts' },
  {
    value: 'projected_on_hand_inventory_excl_reorder_level',
    label: 'Projected On Hand (with Suggested Orders, excl Safety Stock)',
  },
  {
    value: 'projected_on_hand_inventory',
    label: 'Projected On Hand (with Suggested Orders, incl Safety Stock)',
  },
  { value: 'open_orders', label: 'Open Sales/Work Orders' },
  { value: 'total_forecast_demand', label: 'Total Forecast Demand' },
  {
    value: 'suggested_orders',
    label: 'Suggested Orders',
    cellClass: (val) => (val > 0 ? 'suggested-order' : ''),
  },
  {
    value: 'suggested_orders_value',
    label: 'Suggested Orders Value',
    formatter: (val) => (val > 0 ? formatCurrency(val) : ''),
  },
  {
    value: 'suggested_orders_value_payable',
    label: 'Suggested Orders Payable',
    formatter: (val) => (val > 0 ? formatCurrency(val) : ''),
  },
  {
    value: 'scheduled_receipts_value',
    label: 'Scheduled Orders Value',
    formatter: (val) => (val > 0 ? formatCurrency(val) : ''),
  },
  {
    value: 'scheduled_receipts_value_payable',
    label: 'Scheduled Orders Payable',
    formatter: (val) => (val > 0 ? formatCurrency(val) : ''),
  },
  {
    value: 'total_payable',
    label: 'Total Orders Payable',
    formatter: (val) => (val > 0 ? formatCurrency(val) : ''),
  },
  {
    value: 'on_hand_inventory_no_action',
    label: 'On Hand (without Suggested Orders)',
  },
  {
    value: 'on_hand_inventory_excl_reorder_level',
    label: 'On Hand (with Suggested Orders, excl Safety Stock)',
  },
  {
    value: 'on_hand_inventory',
    label: 'On Hand (with Suggested Orders, incl Safety Stock)',
  },
]

const quantityFields = computed(() => {
  const settings = mrp_settings.doc
  if (!settings) return ALL_QUANTITY_FIELDS
  return ALL_QUANTITY_FIELDS.filter((f) => settings[f.value] !== 0)
})

const breakdownCurrent = computed(
  () => breakdownStack.value[breakdownStack.value.length - 1] ?? null,
)
const breakdownLoading = computed(
  () => breakdownCurrent.value?.loading ?? false,
)
const breakdownData = computed(() => breakdownCurrent.value?.data ?? null)

const directForecastTotal = computed(() =>
  (breakdownData.value?.direct_forecasts ?? []).reduce(
    (s, f) => s + (f.forecast_quantity || 0),
    0,
  ),
)

const upstreamTotal = computed(() =>
  (breakdownData.value?.parent_contributions ?? []).reduce(
    (s, p) => s + (p.contribution || 0),
    0,
  ),
)

const breakdownReconciliationWarning = computed(() => {
  if (!breakdownData.value) return false
  const { forecast_demand, upstream_net_demand } = breakdownData.value.stored
  return (
    Math.abs(directForecastTotal.value - forecast_demand) > 0.01 ||
    Math.abs(upstreamTotal.value - upstream_net_demand) > 0.01
  )
})

function getWeekNumber(d) {
  d = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7))
  var yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1))
  var weekNo = Math.ceil(((d - yearStart) / 86400000 + 1) / 7)
  return [d.getUTCFullYear(), weekNo]
}

function getDateFromWeek(weekStr) {
  if (!weekStr) return null
  const [year, week] = weekStr.split('-W').map(Number)
  const d = new Date(Date.UTC(year, 0, 4))
  d.setUTCDate(d.getUTCDate() + (week - 1) * 7)
  d.setUTCDate(d.getUTCDate() - (d.getUTCDay() || 7) + 1)
  return d.toISOString().split('T')[0]
}

function getFormattedWeekHeader(weekKey) {
  const [year, weekNum] = weekKey.split('-W').map(Number)
  const mondayDateStr = getDateFromWeek(weekKey)
  if (!mondayDateStr) return weekKey
  const [y, m, d] = mondayDateStr.split('-')
  return `CW ${weekNum} | ${d}-${m}-${y.slice(-2)}`
}

function getWeekKeys() {
  const look_ahead = mrp_settings.doc?.look_ahead || 6

  let targetDateStr = null
  if (treeData.value.length > 0) {
    targetDateStr = treeData.value[0].target_date
  }

  let targetDate
  if (targetDateStr) {
    targetDate = new Date(targetDateStr)
  } else if (last_mrp_run.data && last_mrp_run.data.length > 0) {
    targetDate = new Date(last_mrp_run.data[0].creation)
  } else {
    targetDate = new Date()
  }

  const weeks = []
  for (let i = 0; i < look_ahead; i++) {
    const d = new Date(targetDate)
    d.setDate(d.getDate() + i * 7)
    const [year, week] = getWeekNumber(d)
    weeks.push(`${year}-W${String(week).padStart(2, '0')}`)
  }
  return weeks
}

const columns = computed(() => {
  const staticCols = [
    {
      type: 'selection',
      fixed: 'left',
    },
    {
      title: () => renderColumnTitle('Item Code / Measure', 'item_code'),
      key: 'item_code',
      filter: true,
      filterOptionValue:
        appliedTextFilters.item_code || appliedExcludeFilters.item_code || null,
      renderFilterMenu: renderTextFilter('item_code', 'Search Item Code'),
      fixed: 'left',
      width: 400,
      sorter: 'default',
      sortOrder:
        sorterRef.value.columnKey === 'item_code'
          ? sorterRef.value.order
          : false,
      className: 'item-code-column',
      render: (row) => {
        if (row.type === 'HEADER') {
          const link = h(
            'a',
            {
              href: `/app/item/${row.item_code}`,
              target: '_blank',
              class: 'text-blue-600 hover:underline',
            },
            row.item_code,
          )
          const badges = []
          if (isBomParent(row)) {
            badges.push(
              h(
                'span',
                {
                  title: 'This is the Parent Item of this BOM',
                  style: {
                    color: '#7f8c8d',
                    cursor: 'default',
                    fontSize: '13px',
                  },
                },
                '⚙',
              ),
            )
          }
          if (isOutOfSync(row)) {
            const delta = syncDelta(row)
            const sign = delta > 0 ? '+' : ''
            const stored = row.on_hand_inventory ?? 0
            const current = currentStockLevels.value[row.item_code]
            badges.push(
              h(
                'span',
                {
                  title: `Stock changed since last MRP run: was ${stored}, now ${current} (${sign}${delta.toFixed(
                    2,
                  )})`,
                  style: {
                    color: '#e67e22',
                    cursor: 'default',
                    fontSize: '13px',
                  },
                },
                '⚠',
              ),
            )
          }
          if (badges.length === 0) return link
          return h(
            'span',
            {
              style: {
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
              },
            },
            [link, ...badges],
          )
        }
        const isSelected = row.measure_key === closed_column_field.value
        return h(
          'span',
          { class: ['text-gray-600', isSelected ? 'font-bold' : ''] },
          row.item_code_display,
        )
      },
    },
    {
      title: () => renderColumnTitle('Item Name', 'item_name'),
      key: 'item_name',
      filter: true,
      filterOptionValue:
        appliedTextFilters.item_name || appliedExcludeFilters.item_name || null,
      renderFilterMenu: renderTextFilter('item_name', 'Search Item Name'),
      fixed: 'left',
      width: 200,
      ellipsis: {
        tooltip: true,
      },
      sorter: 'default',
      sortOrder:
        sorterRef.value.columnKey === 'item_name'
          ? sorterRef.value.order
          : false,
      render: (row) => (row.type === 'HEADER' ? row.item_name : ''),
    },
    {
      title: () => renderColumnTitle('Item Group', 'item_group'),
      key: 'item_group',
      filter: true,
      filterOptionValue:
        appliedTextFilters.item_group ||
        appliedExcludeFilters.item_group ||
        null,
      renderFilterMenu: renderTextFilter('item_group', 'Search Item Group'),
      width: 120,
      ellipsis: {
        tooltip: true,
      },
      sorter: 'default',
      sortOrder:
        sorterRef.value.columnKey === 'item_group'
          ? sorterRef.value.order
          : false,

      render: (row) => (row.type === 'HEADER' ? row.item_group : ''),
    },
    {
      title: 'UoM',
      key: 'uom',
      width: 80,
      ellipsis: {
        tooltip: true,
      },
      sorter: 'default',
      sortOrder:
        sorterRef.value.columnKey === 'uom' ? sorterRef.value.order : false,
      render: (row) => (row.type === 'HEADER' ? row.uom : ''),
    },
    {
      title: () => renderColumnTitle('Top-Level BOM', 'bom_list'),
      key: 'bom_list',
      filter: true,
      filterOptionValue:
        appliedTextFilters.bom_list || appliedExcludeFilters.bom_list || null,
      renderFilterMenu: renderTextFilter('bom_list', 'Search BOM'),
      width: 150,
      ellipsis: {
        tooltip: true,
      },
      render: (row) => (row.type === 'HEADER' ? row.bom_list : ''),
    },
    {
      title: 'Safety Stock',
      key: 'reorder_level',
      filter: true,
      filterOptionValue:
        appliedNumberFilters.reorder_level.min !== null ||
        appliedNumberFilters.reorder_level.max !== null ||
        null,
      renderFilterMenu: renderNumberFilter('reorder_level'),
      width: 100,
      ellipsis: {
        tooltip: true,
      },
      align: 'right',
      sorter: 'default',
      sortOrder:
        sorterRef.value.columnKey === 'reorder_level'
          ? sorterRef.value.order
          : false,
      render: (row) =>
        row.type === 'HEADER' ? formatQuantity(row.reorder_level) : '',
    },
    {
      title: 'Re-order Qty',
      key: 'reorder_quantity',
      filter: true,
      filterOptionValue:
        appliedNumberFilters.reorder_quantity.min !== null ||
        appliedNumberFilters.reorder_quantity.max !== null ||
        null,
      renderFilterMenu: renderNumberFilter('reorder_quantity'),
      width: 110,
      ellipsis: {
        tooltip: true,
      },
      align: 'right',
      sorter: 'default',
      sortOrder:
        sorterRef.value.columnKey === 'reorder_quantity'
          ? sorterRef.value.order
          : false,
      render: (row) =>
        row.type === 'HEADER' ? formatQuantity(row.reorder_quantity) : '',
    },
    {
      title: `Lead Time (${defaultTimeUnit.value})`,
      key: 'lead_time',
      filter: true,
      filterOptionValue:
        appliedNumberFilters.lead_time.min !== null ||
        appliedNumberFilters.lead_time.max !== null ||
        null,
      renderFilterMenu: renderNumberFilter('lead_time'),
      width: 110,
      ellipsis: {
        tooltip: true,
      },
      align: 'right',
      sorter: 'default',
      sortOrder:
        sorterRef.value.columnKey === 'lead_time'
          ? sorterRef.value.order
          : false,
      render: (row) => (row.type === 'HEADER' ? formatTime(row.lead_time) : ''),
    },
    {
      title: () => renderColumnTitle('Supplier', 'default_supplier'),
      key: 'default_supplier',
      filter: true,
      filterOptionValue:
        appliedTextFilters.default_supplier ||
        appliedExcludeFilters.default_supplier ||
        null,
      renderFilterMenu: renderTextFilter('default_supplier', 'Search Supplier'),
      width: 120,
      ellipsis: {
        tooltip: true,
      },
      sorter: 'default',
      sortOrder:
        sorterRef.value.columnKey === 'default_supplier'
          ? sorterRef.value.order
          : false,

      render: (row) => {
        if (row.type !== 'HEADER') return ''
        return mrp_settings.doc?.render_supplier_name
          ? row.default_supplier_name
          : row.default_supplier
      },
    },
    {
      title: `${defaultTimeUnit.value} to Reorder (incl Safety)`,
      key: 'days_to_reorder',
      filter: true,
      filterOptionValue:
        appliedNumberFilters.days_to_reorder.min !== null ||
        appliedNumberFilters.days_to_reorder.max !== null ||
        null,
      renderFilterMenu: renderNumberFilter('days_to_reorder'),
      width: 120,
      ellipsis: {
        tooltip: true,
      },
      align: 'right',
      sorter: 'default',
      sortOrder:
        sorterRef.value.columnKey === 'days_to_reorder'
          ? sorterRef.value.order
          : false,
      render: (row) => {
        if (row.type !== 'HEADER') return ''
        return row.needs_reorder ? formatTime(row.days_to_reorder) : '—'
      },
    },
    {
      title: `${defaultTimeUnit.value} to Reorder`,
      key: 'days_to_reorder_excl_reorder_level',
      filter: true,
      filterOptionValue:
        appliedNumberFilters.days_to_reorder_excl_reorder_level.min !== null ||
        appliedNumberFilters.days_to_reorder_excl_reorder_level.max !== null ||
        null,
      renderFilterMenu: renderNumberFilter(
        'days_to_reorder_excl_reorder_level',
      ),
      width: 120,
      ellipsis: {
        tooltip: true,
      },
      align: 'right',
      sorter: 'default',
      sortOrder:
        sorterRef.value.columnKey === 'days_to_reorder_excl_reorder_level'
          ? sorterRef.value.order
          : false,
      render: (row) => {
        if (row.type !== 'HEADER') return ''
        return row.needs_reorder_excl_reorder_level
          ? formatTime(row.days_to_reorder_excl_reorder_level)
          : '—'
      },
    },
  ]

  const weekCols = getWeekKeys().map((weekKey) => {
    return {
      title: () => {
        return h(
          'div',
          { class: 'rotated-header-naive' },
          getFormattedWeekHeader(weekKey),
        )
      },
      key: weekKey,
      width: 60,
      ellipsis: {
        tooltip: true,
      },
      align: 'right',
      className: 'week-column',
      cellProps: (row) => {
        const val = row[weekKey]
        let measure_key =
          row.type === 'DETAIL' ? row.measure_key : closed_column_field.value
        const qField = quantityFields.value.find((f) => f.value === measure_key)
        if (qField && qField.cellClass) {
          return { class: qField.cellClass(val, row) }
        }
        return {}
      },
      render: (row) => {
        const val = row[weekKey]
        let measure_key =
          row.type === 'DETAIL' ? row.measure_key : closed_column_field.value
        const qField = quantityFields.value.find((f) => f.value === measure_key)

        let formattedVal = formatQuantity(val)
        if (
          val === 0 &&
          ![
            'on_hand_inventory_no_action',
            'on_hand_inventory',
            'on_hand_inventory_excl_reorder_level',
            'projected_on_hand_inventory_no_action',
            'projected_on_hand_inventory',
            'projected_on_hand_inventory_excl_reorder_level',
          ].includes(measure_key)
        ) {
          formattedVal = ''
        } else if (qField && qField.formatter) {
          formattedVal = qField.formatter(val)
        }

        if (
          row.type === 'DETAIL' &&
          row.measure_key === 'total_forecast_demand' &&
          val > 0
        ) {
          return h(
            'span',
            {
              style: {
                cursor: 'pointer',
                textDecoration: 'underline dotted',
                textUnderlineOffset: '3px',
              },
              title: 'Click to explain',
              onClick: () =>
                openBreakdownDialog(row.item_code, weekKey, row.item_name),
            },
            formattedVal,
          )
        }

        return formattedVal
      },
    }
  })

  const actionsCol = {
    title: 'Actions',
    key: 'actions',
    width: 120,
    render: (row) => {
      if (row.type === 'HEADER') {
        return h(
          Button,
          { size: 'sm', onClick: () => handleOpenDialog() },
          { default: () => 'Planning Detail' },
        )
      }
      return ''
    },
  }

  scrollX.value =
    staticCols.reduce((acc, c) => acc + (c.width || 100), 0) +
    weekCols.reduce((acc, c) => acc + (c.width || 60), 0) +
    actionsCol.width

  return staticCols.concat(weekCols, actionsCol)
})

async function executeAsyncQuery() {
  loadingRef.value = true

  let itemCodeFilter = null
  const backendFilters = [['MRP Entry', 'is_header', '=', 1]]
  const backendOrFilters = []

  if (itemCodeFilter) {
    backendFilters.push(['MRP Entry', 'item_code', 'in', itemCodeFilter[1]])
  }

  Object.keys(appliedTextFilters).forEach((key) => {
    if (appliedTextFilters[key]) {
      if (key === 'default_supplier') {
        backendOrFilters.push([
          'MRP Entry',
          'default_supplier',
          'like',
          `%${appliedTextFilters[key]}%`,
        ])
        backendOrFilters.push([
          'MRP Entry',
          'default_supplier_name',
          'like',
          `%${appliedTextFilters[key]}%`,
        ])
      } else {
        backendFilters.push([
          'MRP Entry',
          key,
          'like',
          `%${appliedTextFilters[key]}%`,
        ])
      }
    }
  })

  Object.keys(appliedExcludeFilters).forEach((key) => {
    if (appliedExcludeFilters[key]) {
      if (key === 'default_supplier') {
        backendFilters.push([
          'MRP Entry',
          'default_supplier',
          'not like',
          `%${appliedExcludeFilters[key]}%`,
        ])
        backendFilters.push([
          'MRP Entry',
          'default_supplier_name',
          'not like',
          `%${appliedExcludeFilters[key]}%`,
        ])
      } else {
        backendFilters.push([
          'MRP Entry',
          key,
          'not like',
          `%${appliedExcludeFilters[key]}%`,
        ])
      }
    }
  })

  Object.keys(appliedNumberFilters).forEach((key) => {
    if (appliedNumberFilters[key].min !== null) {
      backendFilters.push([
        'MRP Entry',
        key,
        '>=',
        appliedNumberFilters[key].min,
      ])
    }
    if (appliedNumberFilters[key].max !== null) {
      backendFilters.push([
        'MRP Entry',
        key,
        '<=',
        appliedNumberFilters[key].max,
      ])
    }
  })

  if (
    appliedNumberFilters.days_to_reorder.min !== null ||
    appliedNumberFilters.days_to_reorder.max !== null
  ) {
    backendFilters.push(['MRP Entry', 'needs_reorder', '=', 1])
  }
  if (
    appliedNumberFilters.days_to_reorder_excl_reorder_level.min !== null ||
    appliedNumberFilters.days_to_reorder_excl_reorder_level.max !== null
  ) {
    backendFilters.push([
      'MRP Entry',
      'needs_reorder_excl_reorder_level',
      '=',
      1,
    ])
  }

  try {
    const count = await call('frappe.client.get_count', {
      doctype: 'MRP Entry',
      filters: backendFilters,
      or_filters: backendOrFilters.length > 0 ? backendOrFilters : null,
    })

    paginationReactive.itemCount = count

    let orderBy = 'item_code asc'
    if (sorterRef.value && sorterRef.value.order) {
      const sortOrder = sorterRef.value.order === 'ascend' ? 'asc' : 'desc'
      const columnKey = sorterRef.value.columnKey
      if (
        [
          'item_code',
          'item_name',
          'item_group',
          'uom',
          'reorder_level',
          'reorder_quantity',
          'lead_time',
          'default_supplier',
          'days_to_reorder',
          'days_to_reorder_excl_reorder_level',
        ].includes(columnKey)
      ) {
        orderBy = `${columnKey} ${sortOrder}`
      }
    }

    const items = await call('frappe.client.get_list', {
      doctype: 'MRP Entry',
      filters: backendFilters,
      or_filters: backendOrFilters.length > 0 ? backendOrFilters : null,
      fields: ['*'],
      limit_start: (paginationReactive.page - 1) * paginationReactive.pageSize,
      limit_page_length: paginationReactive.pageSize,
      order_by: orderBy,
    })

    const itemCodes = items.map((item) => item.item_code)
    let details = []
    if (itemCodes.length > 0) {
      details = await call('frappe.client.get_list', {
        doctype: 'MRP Entry',
        filters: [['item_code', 'in', itemCodes]],
        fields: [
          'item_code',
          'target_date',
          'on_hand_inventory_no_action',
          'on_hand_inventory',
          'on_hand_inventory_excl_reorder_level',
          'open_orders',
          'total_forecast_demand',
          'scheduled_receipts',
          'suggested_receipts',
          'suggested_orders',
          'suggested_orders_value',
          'suggested_orders_value_payable',
          'scheduled_receipts_value',
          'scheduled_receipts_value_payable',
          'total_payable',
          'projected_on_hand_inventory_no_action',
          'projected_on_hand_inventory',
          'projected_on_hand_inventory_excl_reorder_level',
        ],
        limit_page_length: 0,
      })
    }

    const pivotedDataByItem = {}
    itemCodes.forEach((code) => {
      pivotedDataByItem[code] = {}
    })

    const fieldsToPivot = [
      'on_hand_inventory_no_action',
      'on_hand_inventory',
      'on_hand_inventory_excl_reorder_level',
      'open_orders',
      'total_forecast_demand',
      'scheduled_receipts',
      'suggested_receipts',
      'suggested_orders',
      'suggested_orders_value',
      'suggested_orders_value_payable',
      'scheduled_receipts_value',
      'scheduled_receipts_value_payable',
      'total_payable',
      'projected_on_hand_inventory_no_action',
      'projected_on_hand_inventory',
      'projected_on_hand_inventory_excl_reorder_level',
    ]

    details.forEach((entry) => {
      if (!entry.target_date) return
      const [year, week] = getWeekNumber(new Date(entry.target_date))
      const weekKey = `${year}-W${String(week).padStart(2, '0')}`
      if (!pivotedDataByItem[entry.item_code]) {
        pivotedDataByItem[entry.item_code] = {}
      }
      fieldsToPivot.forEach((field) => {
        pivotedDataByItem[entry.item_code][`${weekKey}_${field}`] = entry[field]
      })
    })

    const weeks = getWeekKeys()

    treeData.value = items.map((item) => {
      const row = {
        ...item,
        id: item.item_code,
        type: 'HEADER',
        isLeaf: false,
        _itemPivot: pivotedDataByItem[item.item_code] || {},
      }
      weeks.forEach((weekKey) => {
        row[weekKey] = row._itemPivot[`${weekKey}_${closed_column_field.value}`]
      })
      return row
    })
    checkStockSync(items.map((i) => i.item_code))
  } catch (e) {
    console.error(e)
    toast.error('Failed to fetch MRP entries')
  }

  loadingRef.value = false
}

function onLoad(row) {
  return new Promise((resolve) => {
    const weeks = getWeekKeys()
    const children = []

    quantityFields.value.forEach((qField) => {
      const detailRow = {
        ...row,
        id: `${row.item_code}_${qField.value}`,
        type: 'DETAIL',
        measure_key: qField.value,
        item_code_display: qField.label,
        isLeaf: true,
      }
      weeks.forEach((weekKey) => {
        detailRow[weekKey] = row._itemPivot[`${weekKey}_${qField.value}`]
      })
      children.push(detailRow)
    })

    row.children = children
    resolve()
  })
}

function rowKey(rowData) {
  return rowData.id
}

function rowClassName(row) {
  if (row.type === 'HEADER') return 'row-header'
  if (row.type === 'DETAIL') return 'row-detail'
  return ''
}

function handleCheck(keys) {
  selectedRowKeys.value = keys
}

function handleFiltersChange() {
  // handled locally by custom filter renderers now
}

function handleSorterChange(sorter) {
  if (!loadingRef.value) {
    loadingRef.value = true
    sorterRef.value = sorter
    paginationReactive.page = 1
    executeAsyncQuery()
  }
}

function handlePageChange(currentPage) {
  if (!loadingRef.value) {
    loadingRef.value = true
    paginationReactive.page = currentPage
    executeAsyncQuery()
  }
}

function handlePageSizeChange(pageSize) {
  if (!loadingRef.value) {
    loadingRef.value = true
    paginationReactive.pageSize = pageSize
    paginationReactive.page = 1
    executeAsyncQuery()
  }
}

watch(closed_column_field, (newVal) => {
  const weeks = getWeekKeys()
  treeData.value.forEach((row) => {
    if (row._itemPivot) {
      weeks.forEach((weekKey) => {
        row[weekKey] = row._itemPivot[`${weekKey}_${newVal}`]
      })
    }
  })
})

watch(quantityFields, (newFields) => {
  const validValues = newFields.map((f) => f.value)
  if (!validValues.includes(closed_column_field.value)) {
    closed_column_field.value = validValues.includes('suggested_orders')
      ? 'suggested_orders'
      : validValues[0] ?? 'suggested_orders'
  }
})

watch(
  () => mrp_settings.doc,
  (newSettings, oldSettings) => {
    if (!oldSettings && newSettings) {
      treeData.value.forEach((row) => {
        if (row.children) {
          delete row.children
          row.isLeaf = false
        }
      })
    }
  },
)

const presetNameConflict = computed(() =>
  presets.value.some((p) => p.name === presetNameInput.value.trim()),
)

const activePresetName = computed(() => {
  const currentState = JSON.stringify({
    appliedTextFilters: { ...appliedTextFilters },
    appliedExcludeFilters: { ...appliedExcludeFilters },
    appliedNumberFilters: JSON.parse(JSON.stringify(appliedNumberFilters)),
    sorterRef: sorterRef.value,
    closed_column_field: closed_column_field.value,
  })
  return (
    presets.value.find((p) => {
      const storedState = JSON.stringify({
        appliedTextFilters: p.appliedTextFilters,
        appliedExcludeFilters: p.appliedExcludeFilters,
        appliedNumberFilters: p.appliedNumberFilters,
        sorterRef: p.sorterRef,
        closed_column_field: p.closed_column_field,
      })
      return storedState === currentState
    })?.name ?? null
  )
})

const presetDropdownOptions = computed(() => {
  const opts = [
    { label: 'Save current filters…', key: '__save__' },
    { type: 'divider', key: 'div1' },
  ]
  if (presets.value.length === 0) {
    opts.push({ label: 'No saved presets', key: '__empty__', disabled: true })
  } else {
    presets.value.forEach((p) => {
      opts.push({
        key: `load:${p.name}`,
        label: () =>
          h(
            'div',
            {
              style:
                'display:flex; justify-content:space-between; align-items:center; gap:16px; min-width:160px',
            },
            [
              h('span', p.name),
              h(
                'span',
                {
                  style:
                    'color:#c0392b; cursor:pointer; font-size:12px; padding:0 4px',
                  onClick: (e) => {
                    e.stopPropagation()
                    removePreset(p.name)
                  },
                },
                '✕',
              ),
            ],
          ),
      })
    })
  }
  return opts
})

function confirmSavePreset() {
  if (!presetNameInput.value.trim()) return
  savePreset({
    name: presetNameInput.value.trim(),
    appliedTextFilters: { ...appliedTextFilters },
    appliedExcludeFilters: { ...appliedExcludeFilters },
    appliedNumberFilters: JSON.parse(JSON.stringify(appliedNumberFilters)),
    sorterRef: { ...sorterRef.value },
    closed_column_field: closed_column_field.value,
  })
  showSavePresetModal.value = false
  presetNameInput.value = ''
}

function applyPreset(preset) {
  Object.assign(appliedTextFilters, preset.appliedTextFilters)
  Object.assign(textFilters, preset.appliedTextFilters)
  Object.assign(appliedExcludeFilters, preset.appliedExcludeFilters ?? {})
  Object.assign(excludeFilters, preset.appliedExcludeFilters ?? {})
  Object.keys(preset.appliedNumberFilters).forEach((k) => {
    if (appliedNumberFilters[k]) {
      appliedNumberFilters[k].min = preset.appliedNumberFilters[k].min
      appliedNumberFilters[k].max = preset.appliedNumberFilters[k].max
      numberFilters[k].min = preset.appliedNumberFilters[k].min
      numberFilters[k].max = preset.appliedNumberFilters[k].max
    }
  })
  sorterRef.value = { ...preset.sorterRef }
  closed_column_field.value = preset.closed_column_field
  paginationReactive.page = 1
  executeAsyncQuery()
}

function handlePresetDropdownSelect(key) {
  if (key === '__empty__' || key === 'div1') return
  if (key === '__save__') {
    presetNameInput.value = ''
    showSavePresetModal.value = true
    return
  }
  if (key.startsWith('load:')) {
    const preset = loadPreset(key.slice(5))
    if (preset) applyPreset(preset)
  }
}

function clearFilters() {
  Object.keys(textFilters).forEach((k) => {
    textFilters[k] = ''
    appliedTextFilters[k] = ''
    excludeFilters[k] = ''
    appliedExcludeFilters[k] = ''
  })
  Object.keys(numberFilters).forEach((k) => {
    numberFilters[k].min = null
    numberFilters[k].max = null
    appliedNumberFilters[k].min = null
    appliedNumberFilters[k].max = null
  })
  paginationReactive.page = 1
  executeAsyncQuery()
}

function rerunMrp() {
  call('erpnext_mrp.mrp.tasks.mrp_run.trigger_mrp_run').then(() => {
    toast.success('MRP Calculation Started')
    showRerunDialog.value = true
  })
}

async function checkForecastCoverage() {
  try {
    const status = await call(
      'erpnext_mrp.mrp.tasks.mrp_run.get_forecast_coverage_status',
    )
    if (!status.covered) {
      forecastWarningData.weeks_short = status.weeks_short
      forecastWarningData.max_forecast_date = status.max_forecast_date
      forecastWarningData.look_ahead_end_date = status.look_ahead_end_date
      forecastWarningData.look_ahead_weeks = status.look_ahead_weeks
      showForecastWarning.value = true
    }
  } catch (e) {
    console.warn('Forecast coverage check failed:', e)
  }
}

function handleOpenDialog() {
  showDialog.value = true
}

function _dateToWeekKey(dateStr) {
  const d = new Date(dateStr + 'T00:00:00Z')
  const [year, week] = getWeekNumber(d)
  return `${year}-W${String(week).padStart(2, '0')}`
}

function isAlreadyInBreakdownStack(item_code) {
  return breakdownStack.value.some((frame) => frame.item_code === item_code)
}

async function _loadBreakdownFrame(idx, item_code, week_key) {
  try {
    const result = await call(
      'erpnext_mrp.mrp.tasks.mrp_run.get_forecast_demand_breakdown',
      { item_code, week_key },
    )
    breakdownStack.value[idx] = {
      ...breakdownStack.value[idx],
      data: result,
      loading: false,
    }
  } catch (e) {
    breakdownStack.value[idx] = { ...breakdownStack.value[idx], loading: false }
    toast({
      title: 'Error loading breakdown',
      text: e.message,
      variant: 'error',
    })
  }
}

async function openBreakdownDialog(item_code, week_key, item_name) {
  breakdownStack.value = [
    { item_code, week_key, item_name, data: null, loading: true },
  ]
  showBreakdownDialog.value = true
  await _loadBreakdownFrame(0, item_code, week_key)
}

async function drillUpToParent(
  parent_item_code,
  parent_item_name,
  parent_target_date,
) {
  const week_key = _dateToWeekKey(parent_target_date)
  const idx = breakdownStack.value.length
  breakdownStack.value.push({
    item_code: parent_item_code,
    week_key,
    item_name: parent_item_name,
    data: null,
    loading: true,
  })
  await _loadBreakdownFrame(idx, parent_item_code, week_key)
}

function breakdownGoBack() {
  if (breakdownStack.value.length > 1) breakdownStack.value.pop()
}

async function openCreateRequestDialog() {
  const summary = []

  for (const row of treeData.value) {
    if (selectedRowKeys.value.includes(row.id) && !row._itemPivot) {
      await onLoad(row)
    }
  }

  const flatData = []
  treeData.value.forEach((node) => {
    flatData.push(node)
    if (node.children) {
      flatData.push(...node.children)
    }
  })

  const selectedRowObjects = flatData.filter((r) =>
    selectedRowKeys.value.includes(r.id),
  )

  selectedRowObjects.forEach((row) => {
    if (row.type === 'DETAIL' && row.measure_key !== 'suggested_orders') return

    if (row.type === 'DETAIL') {
      Object.keys(row).forEach((key) => {
        if (key.match(/^\d{4}-W\d{2}$/) && row[key] > 0) {
          summary.push({
            item_code: row.item_code,
            quantity: row[key],
            week: key,
            supplier: null,
          })
        }
      })
    }

    if (row.type === 'HEADER') {
      if (row._itemPivot) {
        Object.keys(row._itemPivot).forEach((key) => {
          if (key.endsWith('_suggested_orders') && row._itemPivot[key] > 0) {
            const week = key.split('_suggested_orders')[0]
            summary.push({
              item_code: row.item_code,
              quantity: row._itemPivot[key],
              week: week,
              supplier: row.default_supplier,
            })
          }
        })
      }
    }
  })

  const uniqueSummary = {}
  summary.forEach((s) => {
    const key = `${s.item_code}_${s.week}`
    uniqueSummary[key] = s
  })
  selectedItemsSummary.value = Object.values(uniqueSummary)

  await nextTick()
  showCreateDialog.value = true
}

async function createMaterialRequest(items) {
  const itemsBySupplier = items.reduce((acc, item) => {
    const supplier = item.supplier || 'No Supplier'
    if (!acc[supplier]) {
      acc[supplier] = []
    }
    acc[supplier].push(item)
    return acc
  }, {})

  const createdDocs = []
  for (const supplierItems of Object.values(itemsBySupplier)) {
    const materialRequestDoc = {
      doctype: 'Material Request',
      material_request_type: 'Purchase',
      schedule_date: getDateFromWeek(supplierItems[0].week),
      items: supplierItems.map((item) => ({
        item_code: item.item_code,
        qty: item.quantity,
        schedule_date: getDateFromWeek(item.week),
      })),
    }
    if (
      supplierItems[0].supplier &&
      supplierItems[0].supplier !== 'No Supplier'
    ) {
      materialRequestDoc.supplier = supplierItems[0].supplier
    }

    const newDoc = await material_request_creator.submit({
      doc: materialRequestDoc,
    })
    if (newDoc) {
      createdDocs.push(newDoc)
    }
  }
  return createdDocs
}

async function confirmCreateMaterialRequest() {
  try {
    const createdDocs = await createMaterialRequest(selectedItemsSummary.value)
    newlyCreatedDocs.value = createdDocs
    showSuccessDialog.value = true
    showCreateDialog.value = false
    selectedRowKeys.value = []
  } catch (error) {
    console.error('Failed to create Material Request:', error)
  }
}
</script>

<style>
.bom-clip {
  font-size: 11px;
  line-height: 1.2;
}

.rotated-header-naive {
  transform: rotate(-90deg);
  white-space: nowrap;
  width: 30px;
  height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-left: -5px;
}

.n-data-table-th {
  vertical-align: bottom !important;
}

/* Fix table header height for rotation */
.n-data-table-thead {
  height: 140px;
}

/* Fix for Naive UI tree table ellipsis wrapping causing double height and offset */
.n-data-table-td {
  white-space: nowrap;
}

/* Reduce whitespace */
.n-data-table-td {
  padding: 4px !important;
}
</style>

<style scoped>
/* Cell Coloring Rules */
:deep(.suggested-order) {
  background-color: #ddeeff !important;
}
:deep(.shortage) {
  background-color: #fed7d7 !important;
}
:deep(.below-safety) {
  background-color: #fff2cc !important;
}

/* Header vs Detail Row Styling */
:deep(.row-header .item-code-column) {
  font-weight: 600;
}
:deep(.row-detail .item-code-column) {
  padding-left: 24px !important;
}

/* Label at top, icons at bottom for sortable/filterable headers */
:deep(.n-data-table-th--filterable),
:deep(.n-data-table-th--sortable) {
  padding-top: 6px !important;
  padding-bottom: 28px !important;
  align-items: flex-start !important;
}

/* Non-fixed columns need position:relative as the containing block for absolute icons.
   Fixed columns already have position:sticky (set by Naive UI) which serves the same
   purpose — overriding it with relative breaks their horizontal alignment. */
:deep(
    .n-data-table-th--filterable:not(.n-data-table-th--fixed-left):not(
        .n-data-table-th--fixed-right
      )
  ),
:deep(
    .n-data-table-th--sortable:not(.n-data-table-th--fixed-left):not(
        .n-data-table-th--fixed-right
      )
  ) {
  position: relative !important;
}

:deep(.n-data-table-th--filterable .n-data-table-th__title-wrapper),
:deep(.n-data-table-th--sortable .n-data-table-th__title-wrapper) {
  width: 100% !important;
  overflow: visible !important;
}

:deep(.n-data-table-th--filterable .n-data-table-th__title),
:deep(.n-data-table-th--sortable .n-data-table-th__title) {
  overflow: visible !important;
  white-space: normal !important;
}

/* Override Naive UI's inline style="text-overflow: ellipsis" on the header span */
:deep(.n-data-table-th--filterable .n-ellipsis),
:deep(.n-data-table-th--sortable .n-ellipsis) {
  overflow: visible !important;
  white-space: normal !important;
  text-overflow: unset !important;
}

/* Sorter icon pinned to bottom-right (shift left when filter also present) */
:deep(.n-data-table-th--sortable .n-data-table-sorter) {
  position: absolute !important;
  bottom: 4px !important;
  right: 4px !important;
}

:deep(
    .n-data-table-th--sortable.n-data-table-th--filterable .n-data-table-sorter
  ) {
  right: 24px !important;
}

/* Filter icon pinned to bottom-right */
:deep(.n-data-table-th--filterable .n-data-table-filter) {
  position: absolute !important;
  bottom: 4px !important;
  right: 4px !important;
}

/* Active Filter Icon Indication */
:deep(.n-data-table-filter--active) {
  color: #18a058 !important; /* Naive UI success color (green) */
}
:deep(.n-data-table-filter--active .n-base-icon) {
  color: #18a058 !important;
}

/* Table header should also be greyed out behind dialog modals */
:deep(.n-data-table .n-data-table-base-table-header) {
  z-index: 0;
}
</style>
