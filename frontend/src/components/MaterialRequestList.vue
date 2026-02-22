<template>
  <div class="h-full flex flex-col">
    <div class="mb-4 flex justify-between items-center shrink-0">
      <div class="flex gap-2 items-center">
        <Button @click="clearFilters">Clear Filters</Button>
        <Button @click="rerunMrp">Rerun MRP Calculations</Button>
        <Button @click="exportToCsv">Export to CSV</Button>
        <Combobox
          :options="quantityFields"
          v-model="closed_column_field"
          placeholder="Select a field"
        />
        <Checkbox
          v-model="onlyShowSuggested"
          label="Only show items with suggested orders"
        ></Checkbox>
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
            Once the job is complete, you can reload this page to see the
            updated results.
          </p>
        </div>
      </template>
      <template #actions>
        <Button @click="showRerunDialog = false">Close</Button>
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
import { ref, reactive, computed, watch, nextTick, h, onMounted } from 'vue'
import { NDataTable, NInput } from 'naive-ui'
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

const showDialog = ref(false)
const closed_column_field = ref('suggested_orders')
const selectedRowKeys = ref([])
const showCreateDialog = ref(false)
const selectedItemsSummary = ref([])
const showSuccessDialog = ref(false)
const newlyCreatedDocs = ref([])
const showRerunDialog = ref(false)
const onlyShowSuggested = ref(false)
const itemCodeSearch = ref('')

const filtersRef = reactive({
  item_group: null,
  default_supplier: null,
})
const sorterRef = ref(null)

const paginationReactive = reactive({
  page: 1,
  pageSize: 10,
  showSizePicker: true,
  pageSizes: [5, 10, 20, 50],
  itemCount: 0,
})

const treeData = ref([])
const scrollX = ref(2500)
const loadingRef = ref(true)

const itemGroupOptions = ref([])
const supplierOptions = ref([])

onMounted(async () => {
  call('frappe.client.get_list', {
    doctype: 'MRP Entry',
    filters: { is_header: 1 },
    fields: ['item_group'],
    distinct: 1,
    limit_page_length: 0,
  }).then((res) => {
    itemGroupOptions.value = res
      .filter((r) => r.item_group)
      .map((r) => ({ label: r.item_group, value: r.item_group }))
  })

  call('frappe.client.get_list', {
    doctype: 'MRP Entry',
    filters: { is_header: 1 },
    fields: ['default_supplier'],
    distinct: 1,
    limit_page_length: 0,
  }).then((res) => {
    supplierOptions.value = res
      .filter((r) => r.default_supplier)
      .map((r) => ({ label: r.default_supplier, value: r.default_supplier }))
  })

  executeAsyncQuery()
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

const quantityFields = computed(() => [
  {
    value: 'projected_on_hand_inventory_no_action',
    label: 'Projected On Hand [Ignore Suggested Orders]',
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
    label: 'Projected On Hand [with Suggested Orders] (excl Safety Stock)',
  },
  {
    value: 'projected_on_hand_inventory',
    label: 'Projected On Hand [with Suggested Orders] (incl Safety Stock)',
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
    value: 'on_hand_inventory_no_action',
    label: 'On Hand [Ignore Suggested Orders]',
  },
  {
    value: 'on_hand_inventory_excl_reorder_level',
    label: 'On Hand [with Suggested Orders] (excl Safety Stock)',
  },
  {
    value: 'on_hand_inventory',
    label: 'On Hand [with Suggested Orders] (incl Safety Stock)',
  },
])

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
      title: 'Item Code / Measure',
      key: 'item_code',
      fixed: 'left',
      width: 400,
      sorter: 'default',
      className: 'item-code-column',
      render: (row) => {
        if (row.type === 'HEADER') {
          return h(
            'a',
            {
              href: `/app/item/${row.item_code}`,
              target: '_blank',
              class: 'text-blue-600 hover:underline',
            },
            row.item_code,
          )
        }
        return h('span', { class: 'text-gray-600' }, row.item_code_display)
      },
    },
    {
      title: 'Item Name',
      key: 'item_name',
      fixed: 'left',
      width: 200,
      ellipsis: {
        tooltip: true,
      },
      sorter: 'default',
      render: (row) => (row.type === 'HEADER' ? row.item_name : ''),
    },
    {
      title: 'Item Group',
      key: 'item_group',
      width: 120,
      ellipsis: {
        tooltip: true,
      },
      sorter: 'default',
      filterMultiple: true,
      filterOptionValues: filtersRef.item_group,
      filterOptions: itemGroupOptions.value,
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
      render: (row) => (row.type === 'HEADER' ? row.uom : ''),
    },
    {
      title: 'BOM',
      key: 'bom_list',
      width: 120,
      render: (row) =>
        row.type === 'HEADER'
          ? h(
              'div',
              { class: 'bom-clip', title: row.bom_list || '' },
              row.bom_list || '',
            )
          : '',
    },
    {
      title: 'Lvl',
      key: 'bom_level',
      width: 60,
      ellipsis: {
        tooltip: true,
      },
      sorter: 'default',
      render: (row) => (row.type === 'HEADER' ? row.bom_level : ''),
    },
    {
      title: 'Safety Stock',
      key: 'reorder_level',
      width: 100,
      ellipsis: {
        tooltip: true,
      },
      align: 'right',
      sorter: 'default',
      render: (row) =>
        row.type === 'HEADER' ? formatQuantity(row.reorder_level) : '',
    },
    {
      title: 'Re-order Qty',
      key: 'reorder_quantity',
      width: 100,
      ellipsis: {
        tooltip: true,
      },
      align: 'right',
      sorter: 'default',
      render: (row) =>
        row.type === 'HEADER' ? formatQuantity(row.reorder_quantity) : '',
    },
    {
      title: `Lead Time (${defaultTimeUnit.value})`,
      key: 'lead_time',
      width: 100,
      ellipsis: {
        tooltip: true,
      },
      align: 'right',
      sorter: 'default',
      render: (row) => (row.type === 'HEADER' ? formatTime(row.lead_time) : ''),
    },
    {
      title: 'Supplier',
      key: 'default_supplier',
      width: 120,
      ellipsis: {
        tooltip: true,
      },
      sorter: 'default',
      filterMultiple: true,
      filterOptionValues: filtersRef.default_supplier,
      filterOptions: supplierOptions.value,
      render: (row) => (row.type === 'HEADER' ? row.default_supplier : ''),
    },
    {
      title: `${defaultTimeUnit.value} to Reorder (incl Safety)`,
      key: 'days_to_reorder',
      width: 110,
      ellipsis: {
        tooltip: true,
      },
      align: 'right',
      sorter: 'default',
      render: (row) =>
        row.type === 'HEADER' ? formatTime(row.days_to_reorder) : '',
    },
    {
      title: `${defaultTimeUnit.value} to Reorder`,
      key: 'days_to_reorder_excl_reorder_level',
      width: 110,
      ellipsis: {
        tooltip: true,
      },
      align: 'right',
      sorter: 'default',
      render: (row) =>
        row.type === 'HEADER'
          ? formatTime(row.days_to_reorder_excl_reorder_level)
          : '',
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
  if (onlyShowSuggested.value) {
    try {
      const suggestedEntries = await call('frappe.client.get_list', {
        doctype: 'MRP Entry',
        filters: { suggested_orders: ['>', 0] },
        fields: ['item_code'],
        distinct: 1,
        limit_page_length: 0,
      })
      const suggestedItemCodes = suggestedEntries.map((e) => e.item_code)
      if (suggestedItemCodes.length === 0) {
        treeData.value = []
        paginationReactive.itemCount = 0
        loadingRef.value = false
        return
      }
      itemCodeFilter = ['in', suggestedItemCodes]
    } catch (e) {
      console.error(e)
      toast.error('Failed to filter suggested orders')
      loadingRef.value = false
      return
    }
  }

  const backendFilters = { is_header: 1 }
  if (itemCodeFilter) backendFilters.item_code = itemCodeFilter
  if (filtersRef.item_group && filtersRef.item_group.length > 0)
    backendFilters.item_group = ['in', filtersRef.item_group]
  if (filtersRef.default_supplier && filtersRef.default_supplier.length > 0)
    backendFilters.default_supplier = ['in', filtersRef.default_supplier]

  try {
    const count = await call('frappe.client.get_count', {
      doctype: 'MRP Entry',
      filters: backendFilters,
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
          'bom_level',
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
      fields: ['*'],
      limit_start: (paginationReactive.page - 1) * paginationReactive.pageSize,
      limit_page_length: paginationReactive.pageSize,
      order_by: orderBy,
    })

    treeData.value = items.map((item) => ({
      ...item,
      id: item.item_code,
      type: 'HEADER',
      isLeaf: false,
    }))
  } catch (e) {
    console.error(e)
    toast.error('Failed to fetch MRP entries')
  }

  loadingRef.value = false
}

function onLoad(row) {
  return new Promise((resolve) => {
    call('frappe.client.get_list', {
      doctype: 'MRP Entry',
      filters: { item_code: row.item_code },
      fields: ['*'],
      limit_page_length: 500,
    })
      .then((entries) => {
        const itemPivot = {}
        const weeks = getWeekKeys()

        entries.forEach((entry) => {
          const [year, week] = getWeekNumber(new Date(entry.target_date))
          const weekKey = `${year}-W${String(week).padStart(2, '0')}`

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
            'projected_on_hand_inventory_no_action',
            'projected_on_hand_inventory',
            'projected_on_hand_inventory_excl_reorder_level',
          ]
          fieldsToPivot.forEach((field) => {
            itemPivot[`${weekKey}_${field}`] = entry[field]
          })
        })

        weeks.forEach((weekKey) => {
          row[weekKey] = itemPivot[`${weekKey}_${closed_column_field.value}`]
        })

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
            detailRow[weekKey] = itemPivot[`${weekKey}_${qField.value}`]
          })
          children.push(detailRow)
        })

        row.children = children
        row._itemPivot = itemPivot

        resolve()
      })
      .catch((err) => {
        console.error(err)
        toast.error('Failed to load details')
        resolve()
      })
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

function handleFiltersChange(filters) {
  if (!loadingRef.value) {
    loadingRef.value = true
    Object.keys(filters).forEach((key) => {
      filtersRef[key] = Array.isArray(filters[key]) ? filters[key] : []
    })
    paginationReactive.page = 1
    executeAsyncQuery()
  }
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

watch([onlyShowSuggested, itemCodeSearch], () => {
  paginationReactive.page = 1
  executeAsyncQuery()
})

function exportToCsv() {
  toast.error('CSV Export not currently implemented for this table view.')
}

function clearFilters() {
  toast.info('Filter clearing requires custom filter columns in Naive UI')
}

function rerunMrp() {
  call('erpnext_mrp.mrp.tasks.mrp_run.trigger_mrp_run').then(() => {
    toast.success('MRP Calculation Started')
    showRerunDialog.value = true
  })
}

function handleOpenDialog() {
  showDialog.value = true
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
</style>
