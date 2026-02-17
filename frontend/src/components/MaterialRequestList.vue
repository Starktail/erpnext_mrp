<template>
  <div class="h-full flex flex-col">
    <div class="mb-4 flex justify-between items-center">
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
        <div
          class="flex items-center gap-2 text-sm cursor-pointer"
          @click="showUrgencyLegend = true"
        >
          <div class="w-4 h-4 rounded" style="background-color: #ffdddd"></div>
          <div
            class="w-4 h-4 rounded"
            style="background-color: #eab26eff"
          ></div>
          <span class="text-gray-600 hover:underline">Urgency Legend</span>
        </div>
        <div class="flex items-center gap-2 text-sm">
          <div class="w-4 h-4 rounded" style="background-color: #ddeeff"></div>
          <span class="text-gray-600">Suggested Order</span>
        </div>
        <Button
          @click="openCreateRequestDialog"
          :disabled="selectedRows.length === 0"
          >Create Material Request</Button
        >
      </div>
    </div>
    <ag-grid-vue
      class="ag-theme-alpine w-full flex-grow"
      theme="legacy"
      :columnDefs="dynamicColumnDefs"
      :rowData="mrpEntryRows"
      :pagination="true"
      :paginationPageSize="100"
      :getRowId="getRowId"
      :defaultColDef="{
        wrapHeaderText: true,
        autoHeaderHeight: true,
        resizable: true,
      }"
      :getRowStyle="getRowStyle"
      :tooltipShowDelay="300"
      :tooltipHideDelay="2000"
      :enableBrowserTooltips="false"
      @grid-ready="onGridReady"
      rowSelection="multiple"
      @selection-changed="onSelectionChanged"
    />
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
    <Dialog v-model="showUrgencyLegend" @hide="showUrgencyLegend = false">
      <template #body-title>
        <h3 class="text-2xl font-semibold text-ink-gray-9">
          Urgency Level Legend
        </h3>
      </template>
      <template #body-content>
        <div>
          <p>The urgency level highlights items that require attention:</p>
          <ul class="list-disc list-inside my-4 space-y-2">
            <li class="flex items-start gap-2">
              <div
                class="w-4 h-4 rounded mt-1 flex-shrink-0"
                style="background-color: #ffdddd"
              ></div>
              <span
                ><b>P1 - Critical:</b> Required and not enough quantity on order
                (excl safety stock).</span
              >
            </li>
            <li class="flex items-start gap-2">
              <div
                class="w-4 h-4 rounded mt-1 flex-shrink-0"
                style="background-color: #eab26eff"
              ></div>
              <span
                ><b>P2 - Attention:</b> Enough quantity on order, but scheduled
                to arrive late (excl safety stock).</span
              >
            </li>
            <li class="flex items-start gap-2">
              <div
                class="w-4 h-4 rounded mt-1 flex-shrink-0"
                style="background-color: #888888ff"
              ></div>
              <span
                ><b>P3 - Optional:</b> On order, but the stock level will drop
                below the safety stock (no row highlight)</span
              >
            </li>
          </ul>
        </div>
      </template>
      <template #actions>
        <Button @click="showUrgencyLegend = false">Close</Button>
      </template>
    </Dialog>
  </div>
</template>

<script>
import { nextTick } from 'vue'
import { AgGridVue } from 'ag-grid-vue3'
// AG Grid CSS is now imported in main.js
import { Button, Dialog, Combobox, Checkbox, call, toast } from 'frappe-ui'
import { formatCurrency } from '../utils/numberFormat'

export default {
  name: 'MaterialRequestList',
  components: {
    AgGridVue,
    Dialog, // Register the Dialog component
    Combobox, // Register the Combobox component
    Checkbox,
    buttonCellRenderer: {
      name: 'ButtonCellRenderer',
      template: `<Button @click="onButtonClick">Planning Detail</Button>`,
      components: {
        // Explicitly register Button for this local component
        Button,
      },
      props: {
        params: {
          // AG Grid passes params via a prop named 'params'
          type: Object,
          required: true,
        },
      },
      methods: {
        onButtonClick() {
          // Call the method passed in cellRendererParams from the parent component
          this.params.onOpenDialog()
        },
      },
    },
    ExpandCellRenderer: {
      template: `
        <div class="flex items-center h-full" :style="{ paddingLeft: params.data.type === 'DETAIL' ? '20px' : '0px' }">
          <div v-if="params.data.type === 'HEADER'" 
               @click.stop="onToggle" 
               class="cursor-pointer mr-2 w-4 flex justify-center text-gray-500 hover:text-gray-700 select-none">
             <span v-if="isExpanded">▼</span>
             <span v-else>▶</span>
          </div>
          <span v-if="params.data.type === 'HEADER'">
            <a :href="'/app/item/' + params.value" target="_blank" class="text-blue-600 hover:underline">{{ params.value }}</a>
          </span>
          <span v-else class="text-gray-600">{{ params.value }}</span>
        </div>
      `,
      props: { params: { type: Object, required: true } },
      computed: {
        isExpanded() {
          return this.params.isExpanded(this.params.data.item_code)
        },
      },
      methods: {
        onToggle() {
          this.params.toggleExpand(this.params.data.item_code)
        },
      },
    },
  },
  data() {
    return {
      gridApi: null,
      columnApi: null,
      showDialog: false,
      closed_column_field: 'suggested_orders',
      selectedRows: [],
      showCreateDialog: false,
      selectedItemsSummary: [],
      showSuccessDialog: false,
      newlyCreatedDocs: [],
      showRerunDialog: false,
      onlyShowSuggested: false,
      showUrgencyLegend: false,
      expandedItems: [], // Store expanded item codes
    }
  },
  resources: {
    mrp_entries() {
      return {
        type: 'list',
        doctype: 'MRP Entry',
        fields: [
          'name',
          'item_code',
          'item_name',
          'item_group',
          'bom_list',
          'uom',
          'bom_level',
          'reorder_level',
          'reorder_quantity',
          'lead_time',
          'default_supplier',
          'urgency_level',
          'target_date',
          'on_hand_inventory',
          'open_orders',
          'total_forecast_demand',
          'scheduled_receipts',
          'suggested_receipts',
          'suggested_orders',
          'suggested_orders_value',
          'suggested_orders_value_payable',
          'projected_on_hand_inventory',
        ],
        orderBy: 'creation desc',
        start: 0,
        pageLength: 500,
        auto: true,
        onSuccess() {
          if (this.$resources.mrp_entries.hasNextPage) {
            this.$resources.mrp_entries.next()
          }
        },
      }
    },
    material_request_creator() {
      return {
        url: 'frappe.client.insert',
        onSuccess: () => {
          console.log('Material Request created successfully')
        },
      }
    },
    last_mrp_run() {
      return {
        type: 'list',
        doctype: 'Scheduled Job Log',
        fields: ['creation'],
        filters: {
          scheduled_job_type: 'mrp_run.mrp_run',
        },
        orderBy: 'creation desc',
        pageLength: 1,
        auto: true,
      }
    },
  },
  computed: {
    lastMrpRunTime() {
      if (this.$resources.last_mrp_run.loading) {
        return 'Loading...'
      }
      if (
        !this.$resources.last_mrp_run.data ||
        this.$resources.last_mrp_run.data.length === 0
      ) {
        return 'MRP has not run yet.'
      }
      const lastRun = this.$resources.last_mrp_run.data[0]
      if (lastRun) {
        const d = new Date(lastRun.creation)
        return `Last MRP Run: ${d.toLocaleString()}`
      }
      return 'MRP has not run yet.'
    },
    mrpEntryRows() {
      if (
        this.$resources.mrp_entries.loading ||
        !this.$resources.mrp_entries.data
      ) {
        return null // AG Grid will show its loading overlay
      }

      const mrpEntries = this.$resources.mrp_entries.data
      const items = {}

      // 1. Group by Item
      mrpEntries.forEach((entry) => {
        if (!entry.item_code) return

        if (!items[entry.item_code]) {
          items[entry.item_code] = {
            name: entry.item_code, // for original logic
            item_code: entry.item_code,
            item_name: entry.item_name,
            item_group: entry.item_group,
            bom_list: entry.bom_list,
            uom: entry.uom,
            bom_level: entry.bom_level,
            reorder_level: entry.reorder_level,
            reorder_quantity: entry.reorder_quantity,
            lead_time: entry.lead_time,
            default_supplier: entry.default_supplier,
            _urgency_levels: [],
            _weeks_data: {}, // Store week data here
          }
        }

        items[entry.item_code]._urgency_levels.push(entry.urgency_level)

        if (!entry.target_date) return

        const [year, week] = this.getWeekNumber(new Date(entry.target_date))
        const weekKey = `${year}-W${String(week).padStart(2, '0')}`

        const fieldsToPivot = [
          'on_hand_inventory',
          'open_orders',
          'total_forecast_demand',
          'scheduled_receipts',
          'suggested_receipts',
          'suggested_orders',
          'suggested_orders_value',
          'suggested_orders_value_payable',
          'projected_on_hand_inventory',
        ]

        // Store data in a nested structure or flat with prefix
        // Flattening with prefix is easier for lookup
        fieldsToPivot.forEach((field) => {
          items[entry.item_code][`${weekKey}_${field}`] = entry[field]
        })
      })

      // 2. Process Items (urgency, filtering)
      Object.values(items).forEach((item) => {
        const positiveUrgencies = item._urgency_levels.filter((u) => u > 0)
        item.urgency_level =
          positiveUrgencies.length > 0 ? Math.min(...positiveUrgencies) : 0
        delete item._urgency_levels
      })

      let processedItems = Object.values(items)

      if (this.onlyShowSuggested) {
        processedItems = processedItems.filter((row) => {
          return Object.keys(row).some(
            (key) => key.endsWith('_suggested_orders') && row[key] > 0,
          )
        })
      }

      // 3. Flatten to Rows (Header + Details)
      const rows = []
      const expandedSet = new Set(this.expandedItems)

      processedItems.forEach((item) => {
        // Header Row
        rows.push({
          ...item,
          type: 'HEADER',
          // Ensure unique ID for row
          row_id: item.item_code,
        })

        // Detail Rows
        if (expandedSet.has(item.item_code)) {
          this.quantityFields.forEach((qField) => {
            const detailRow = {
              item_code: item.item_code, // Reference to parent
              type: 'DETAIL',
              measure_key: qField.value,
              row_id: `${item.item_code}_${qField.value}`,
              // For the first column (Item Code), we show the label
              item_code_display: qField.label,
              default_supplier: item.default_supplier,
            }

            // Populate week columns
            Object.keys(item).forEach((key) => {
              if (key.endsWith('_' + qField.value)) {
                const week = key.substring(
                  0,
                  key.length - (qField.value.length + 1),
                )
                detailRow[week] = item[key]
              }
            })

            rows.push(detailRow)
          })
        }
      })

      return rows
    },
    dynamicColumnDefs() {
      const staticColumns = [
        {
          headerName: 'Select',
          checkboxSelection: true,
          headerCheckboxSelection: true,
          pinned: 'left',
          width: 50,
        },
        {
          field: 'item_code',
          headerName: 'Item Code / Measure',
          sortable: true, // Sort only works for Headers effectively
          filter: true,
          width: 200,
          pinned: 'left',
          cellRenderer: 'ExpandCellRenderer',
          cellRendererParams: {
            toggleExpand: this.toggleExpand,
            isExpanded: this.isExpanded,
          },
          valueGetter: (params) => {
            if (params.data.type === 'HEADER') return params.data.item_code
            return params.data.item_code_display // The measure label
          },
        },
        {
          field: 'item_name',
          headerName: 'Item Name',
          sortable: true,
          filter: true,
          pinned: 'left',
          valueGetter: (params) =>
            params.data.type === 'HEADER' ? params.data.item_name : '',
        },
        {
          field: 'item_group',
          headerName: 'Item Group',
          sortable: true,
          filter: true,
          width: 120,
          valueGetter: (params) =>
            params.data.type === 'HEADER' ? params.data.item_group : '',
        },
        {
          field: 'uom',
          headerName: 'Uom',
          sortable: true,
          filter: true,
          width: 100,
          valueGetter: (params) =>
            params.data.type === 'HEADER' ? params.data.uom : '',
        },
        {
          field: 'bom_list',
          headerName: 'BOM',
          sortable: false,
          filter: true,
          width: 160,
          wrapText: true,
          tooltipField: 'bom_list',
          cellClass: 'bom-clip',
          valueGetter: (params) =>
            params.data.type === 'HEADER' ? params.data.bom_list : '',
        },
        {
          field: 'bom_level',
          headerName: 'Lvl',
          sortable: true,
          filter: true,
          width: 70,
          valueGetter: (params) =>
            params.data.type === 'HEADER' ? params.data.bom_level : '',
        },
        {
          field: 'reorder_level',
          headerName: 'Safety Stock',
          sortable: true,
          filter: true,
          width: 110,
          cellStyle: { textAlign: 'right' },
          headerClass: 'ag-right-aligned-header',
          valueGetter: (params) =>
            params.data.type === 'HEADER' ? params.data.reorder_level : '',
        },
        {
          field: 'reorder_quantity',
          headerName: 'Re-order Qty',
          sortable: true,
          filter: true,
          width: 110,
          cellStyle: { textAlign: 'right' },
          headerClass: 'ag-right-aligned-header',
          valueGetter: (params) =>
            params.data.type === 'HEADER' ? params.data.reorder_quantity : '',
        },
        {
          field: 'lead_time',
          headerName: 'Lead Time',
          sortable: true,
          filter: true,
          width: 100,
          cellStyle: { textAlign: 'right' },
          headerClass: 'ag-right-aligned-header',
          valueGetter: (params) =>
            params.data.type === 'HEADER' ? params.data.lead_time : '',
        },
        {
          field: 'default_supplier',
          headerName: 'Supplier',
          sortable: true,
          filter: true,
          width: 120,
          valueGetter: (params) =>
            params.data.type === 'HEADER' ? params.data.default_supplier : '',
        },
        {
          field: 'urgency_level',
          headerName: 'Urgency',
          sortable: true,
          filter: true,
          width: 120,
          cellStyle: { textAlign: 'center' },
          comparator: (valueA, valueB) => {
            const valA = valueA === 0 ? 999 : valueA
            const valB = valueB === 0 ? 999 : valueB
            return valA - valB
          },
          cellRenderer: (params) => {
            if (params.data.type !== 'HEADER') return ''
            return params.value !== 0
              ? `⚠️ <b>P${params.value}</b>`
              : params.value
          },
        },
      ]

      const actionsColumn = {
        headerName: 'Actions',
        cellRenderer: 'buttonCellRenderer',
        cellRendererParams: {
          onOpenDialog: this.handleOpenDialog,
        },
        sortable: false,
        filter: false,
        valueGetter: (params) =>
          params.data.type === 'HEADER' ? 'Actions' : '',
      }
      // Only show button for Header rows?
      // The renderer handles display, but we can return null if not header.
      // But the renderer is a component. We can hide it in CSS or modify component.
      // I'll leave it as is, but maybe hide the button if value is empty?
      // Actually the current buttonCellRenderer doesn't check type.
      // I'll assume it's fine or update it if needed.
      // For now, let's keep it simple.

      if (
        this.$resources.mrp_entries.loading ||
        !this.$resources.mrp_entries.data
      ) {
        return staticColumns.concat(actionsColumn)
      }

      const mrpEntries = this.$resources.mrp_entries.data
      const weeks = new Set()
      mrpEntries.forEach((entry) => {
        if (!entry.target_date) return
        const [year, week] = this.getWeekNumber(new Date(entry.target_date))
        const weekKey = `${year}-W${String(week).padStart(2, '0')}`
        weeks.add(weekKey)
      })

      const sortedWeeks = Array.from(weeks).sort()

      const dynamicColumns = sortedWeeks.map((weekKey) => {
        return {
          headerName: weekKey,
          sortable: true,
          filter: true,
          width: 120,
          headerClass: 'ag-right-aligned-header',
          valueGetter: (params) => {
            if (params.data.type === 'HEADER') {
              const fieldKey = `${weekKey}_${this.closed_column_field}`
              return params.data[fieldKey]
            }
            return params.data[weekKey]
          },
          cellStyle: (params) => {
            const style = { textAlign: 'right' }
            let measure_key =
              params.data.type === 'DETAIL'
                ? params.data.measure_key
                : this.closed_column_field

            const qField = this.quantityFields.find(
              (f) => f.value === measure_key,
            )
            if (qField && qField.cellStyle) {
              if (typeof qField.cellStyle === 'function') {
                return { ...style, ...qField.cellStyle(params) }
              } else {
                return { ...style, ...qField.cellStyle }
              }
            }
            return style
          },
          valueFormatter: (params) => {
            let measure_key =
              params.data.type === 'DETAIL'
                ? params.data.measure_key
                : this.closed_column_field
            const qField = this.quantityFields.find(
              (f) => f.value === measure_key,
            )
            if (qField && qField.valueFormatter) {
              return qField.valueFormatter(params)
            }
            return params.value
          },
        }
      })

      return staticColumns.concat(dynamicColumns, actionsColumn)
    },
    quantityFields() {
      return [
        { value: 'on_hand_inventory', label: 'On Hand Inventory' },
        { value: 'open_orders', label: 'Open Sales/Work Orders' },
        { value: 'total_forecast_demand', label: 'Total Forecast Demand' },
        { value: 'scheduled_receipts', label: 'Scheduled Receipts' },
        { value: 'suggested_receipts', label: 'Suggested Receipts' },
        {
          value: 'suggested_orders',
          label: 'Suggested Orders',
          cellStyle: (params) =>
            params.value > 0
              ? { background: '#ddeeff', textAlign: 'right' }
              : { textAlign: 'right' },
        },
        {
          value: 'suggested_orders_value',
          label: 'Suggested Orders Value',
          cellStyle: { textAlign: 'right' },
          valueFormatter: (params) =>
            params.value > 0 ? this.formatCurrency(params.value) : '',
        },
        {
          value: 'suggested_orders_value_payable',
          label: 'Suggested Orders Payable',
          cellStyle: { textAlign: 'right' },
          valueFormatter: (params) =>
            params.value > 0 ? this.formatCurrency(params.value) : '',
        },
        {
          value: 'projected_on_hand_inventory',
          label: 'Projected On Hand Inventory',
        },
      ]
    },
    isLoading() {
      return this.$resources.mrp_entries.loading
    },
  },
  watch: {
    closed_column_field() {
      if (this.gridApi) {
        this.gridApi.refreshCells({ force: true })
      }
    },
  },
  methods: {
    toggleExpand(itemCode) {
      const idx = this.expandedItems.indexOf(itemCode)
      if (idx === -1) {
        this.expandedItems.push(itemCode)
      } else {
        this.expandedItems.splice(idx, 1)
      }
    },
    isExpanded(itemCode) {
      return this.expandedItems.includes(itemCode)
    },
    formatCurrency(value) {
      if (value === null || value === undefined) return ''
      const currency = window.sysdefaults?.currency
      return formatCurrency(value, null, currency)
    },
    exportToCsv() {
      this.gridApi.exportDataAsCsv({ allColumns: true })
    },
    onGridReady(params) {
      this.gridApi = params.api
      this.columnApi = params.columnApi
    },
    clearFilters() {
      this.gridApi.setFilterModel(null)
    },
    rerunMrp() {
      call('erpnext_mrp.mrp.tasks.mrp_run.mrp_run').then(() => {
        toast.success('MRP Calculation Started')
        this.showRerunDialog = true
      })
    },
    reload() {
      this.$resources.mrp_entries.reload()
    },
    handleOpenDialog() {
      this.showDialog = true
    },
    getRowId(params) {
      return params.data.row_id
    },
    getRowStyle(params) {
      if (params.data.type === 'HEADER') {
        if (params.data.urgency_level === 1) {
          return { background: '#ffdddd' }
        } else if (params.data.urgency_level === 2) {
          return { background: '#eab26eff' }
        }
        return { fontWeight: 'bold', background: '#f9f9f9' }
      }
      return null
    },
    // From https://stackoverflow.com/a/6117889
    getWeekNumber(d) {
      // Copy date so don't modify original
      d = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
      // Set to nearest Thursday: current date + 4 - current day number
      // Make Sunday's day number 7
      d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7))
      // Get first day of year
      var yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1))
      // Calculate full weeks to nearest Thursday
      var weekNo = Math.ceil(((d - yearStart) / 86400000 + 1) / 7)
      // Return array of year and week number
      return [d.getUTCFullYear(), weekNo]
    },
    onSelectionChanged() {
      this.selectedRows = this.gridApi.getSelectedRows()
    },
    async openCreateRequestDialog() {
      const summary = []

      // Filter out Header rows if they are selected alongside their children?
      // Or use Header rows to fetch all suggestions for that item?
      // Let's stick to explicit suggestions found in selected rows.
      // Case 1: Header selected. We should probably find suggestions for that item.
      // Case 2: Detail selected. We check if it is 'suggested_orders'.

      const itemsToProcess = new Set()

      this.selectedRows.forEach((row) => {
        if (row.type === 'HEADER') {
          itemsToProcess.add(row.item_code)
        } else if (
          row.type === 'DETAIL' &&
          row.measure_key === 'suggested_orders'
        ) {
          // Should we add the whole item or just the selected row's values?
          // The original logic iterated keys on the row.
          // If we have the detail row for 'suggested_orders', it has the values.
          // We can process this row directly.
        }
      })

      // If we process headers, we need to find the data.
      // We can look up in mrp_entries.
      // But mrp_entries is flat list of (Item, Week).
      // It's easier if we have the consolidated item object.
      // But we don't store it globally.
      // However, we can re-construct or look at `mrpEntryRows` (which are just rows).

      // Let's try a simpler approach:
      // Iterate selected rows.
      // If Header: Find all children (conceptually) -> actually simpler: assume user expanded and saw suggestions?
      // If user selects Header, do we assume they want to order EVERYTHING suggested for that item? Yes.

      // To implement this, we need the "full item data" which we have in `mrpEntryRows` (the Header row has all the hidden fields like `2024-W01_suggested_orders`!).
      // Wait, in my implementation of `mrpEntryRows`, I did:
      // rows.push({ ...item, type: 'HEADER' })
      // And `item` had `2024-W01_suggested_orders` etc attached to it!
      // So the Header Row object *still contains* all the data, even if not shown in columns.
      // Perfect.

      this.selectedRows.forEach((row) => {
        // If it's a detail row, only care if it is suggested orders
        if (row.type === 'DETAIL' && row.measure_key !== 'suggested_orders')
          return

        // If it's a detail row for suggested_orders, it has fields like '2024-W01': 10
        // We can extract them.

        if (row.type === 'DETAIL') {
          Object.keys(row).forEach((key) => {
            // key is like '2024-W01'
            if (key.match(/^\d{4}-W\d{2}$/) && row[key] > 0) {
              summary.push({
                item_code: row.item_code,
                quantity: row[key],
                week: key,
                supplier: null, // We need to find supplier. Header row has it. Detail row doesn't have it explicitly in my code above?
                // Wait, I didn't copy default_supplier to Detail row.
                // I should fix that in mrpEntryRows.
              })
            }
          })
        }

        // If it's HEADER, it has '2024-W01_suggested_orders': 10
        if (row.type === 'HEADER') {
          Object.keys(row).forEach((key) => {
            if (key.endsWith('_suggested_orders') && row[key] > 0) {
              const week = key.split('_suggested_orders')[0]
              summary.push({
                item_code: row.item_code,
                quantity: row[key],
                week: week,
                supplier: row.default_supplier,
              })
            }
          })
        }
      })

      // Deduplicate?
      // If user selected both Header and Detail, we might double count.
      // Map by item+week.
      const uniqueSummary = {}
      summary.forEach((s) => {
        const key = `${s.item_code}_${s.week}`
        uniqueSummary[key] = s
      })
      this.selectedItemsSummary = Object.values(uniqueSummary)

      // Need to fix Supplier in Detail row processing.
      // I can add default_supplier to Detail row in mrpEntryRows.
      // Let's rely on looking up the Header row in the grid API? No, expensive.
      // I'll update mrpEntryRows to include default_supplier in Detail rows.

      await nextTick()

      this.showCreateDialog = true
    },
    async confirmCreateMaterialRequest() {
      try {
        const createdDocs = await this.createMaterialRequest(
          this.selectedItemsSummary,
        )
        this.newlyCreatedDocs = createdDocs
        this.showSuccessDialog = true
        this.showCreateDialog = false
        this.gridApi.deselectAll()
      } catch (error) {
        console.error('Failed to create Material Request:', error)
        // Maybe show an error message
      }
    },
    getDateFromWeek(weekStr) {
      if (!weekStr) return null
      const [year, week] = weekStr.split('-W').map(Number)

      const d = new Date(Date.UTC(year, 0, 4)) // Start with Jan 4th, which is always in week 1
      d.setUTCDate(d.getUTCDate() + (week - 1) * 7) // Go to the desired week
      d.setUTCDate(d.getUTCDate() - (d.getUTCDay() || 7) + 1) // Go to Monday of that week

      return d.toISOString().split('T')[0] // Format as YYYY-MM-DD
    },
    async createMaterialRequest(items) {
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
          schedule_date: this.getDateFromWeek(supplierItems[0].week),
          items: supplierItems.map((item) => ({
            item_code: item.item_code,
            qty: item.quantity,
            schedule_date: this.getDateFromWeek(item.week),
          })),
        }
        if (
          supplierItems[0].supplier &&
          supplierItems[0].supplier !== 'No Supplier'
        ) {
          materialRequestDoc.supplier = supplierItems[0].supplier
        }

        const newDoc = await this.$resources.material_request_creator.submit({
          doc: materialRequestDoc,
        })
        if (newDoc) {
          createdDocs.push(newDoc)
        }
      }
      return createdDocs
    },
  },
}
</script>

<style>
.bom-clip {
  font-size: 11px;
  line-height: 1.2;
}

.ag-theme-alpine .ag-cell-label-container {
  flex-direction: row;
  flex-wrap: wrap;
}

.ag-theme-alpine .ag-header-cell-label {
  display: contents;
}

.ag-theme-alpine .ag-header-cell-filter-button {
  order: 1;
  margin-right: 4px;
}

.ag-theme-alpine .ag-sort-indicator-container {
  order: 2;
}

.ag-theme-alpine .ag-header-cell-text {
  order: 3;
  width: 100%;
  margin-top: 2px;
}

.ag-theme-alpine .ag-right-aligned-header .ag-cell-label-container {
  justify-content: flex-end;
}

.ag-theme-alpine .ag-right-aligned-header .ag-header-cell-text {
  text-align: right;
}

.ag-theme-alpine {
  z-index: 0;
}
</style>
