<template>
	<div class="h-full flex flex-col">
		<div class="mb-4 flex justify-between items-center">
			<div class="flex gap-2 items-center">
				<Button @click="clearFilters">Clear Filters</Button>
				<Button @click="rerunMrp">Rerun MRP Calculations</Button>
				<Button @click="exportToCsv">Export to CSV</Button>
				<Combobox :options="quantityFields" v-model="closed_column_field" placeholder="Select a field" />
				<Checkbox v-model="onlyShowSuggested" label="Only show items with suggested orders"></Checkbox>
			</div>
			<!-- Colour Legend -->
			<div class="flex items-center gap-4">
				<div class="text-sm text-gray-600">{{ lastMrpRunTime }}</div>
				<div class="flex items-center gap-2 text-sm cursor-pointer" @click="showUrgencyLegend = true">
					<div class="w-4 h-4 rounded" style="background-color: #ffdddd"></div>
					<div class="w-4 h-4 rounded" style="background-color: #eab26eff"></div>
					<span class="text-gray-600 hover:underline">Urgency Legend</span>
				</div>
				<div class="flex items-center gap-2 text-sm">
					<div class="w-4 h-4 rounded" style="background-color: #ddeeff"></div>
					<span class="text-gray-600">Suggested Order</span>
				</div>
				<Button @click="openCreateRequestDialog" :disabled="selectedRows.length === 0">Create Material Request</Button>
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
			@grid-ready="onGridReady"
			rowSelection="multiple"
			@selection-changed="onSelectionChanged"
		/>
		<Dialog v-model="showRerunDialog" @hide="showRerunDialog = false">
			<template #body-title>
				<h3 class="text-2xl font-semibold text-ink-gray-9">MRP Calculations Started</h3>
			</template>
			<template #body-content>
				<div>
					<p>The MRP calculations have been started in the background.</p>
					<p>
						You can monitor the progress of the job here:
						<a href="/app/rq-job" target="_blank" class="text-blue-600 hover:underline">View Background Jobs</a>
					</p>
					<p>Once the job is complete, you can reload this page to see the updated results.</p>
				</div>
			</template>
			<template #actions>
				<Button @click="showRerunDialog = false">Close</Button>
			</template>
		</Dialog>
		<Dialog v-model="showDialog" @hide="showDialog = false">
			<template #body-title>
				<h3 class="text-2xl font-semibold text-ink-gray-9">Material Request Details</h3>
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
				<h3 class="text-2xl font-semibold text-ink-gray-9">Create Material Request</h3>
			</template>
			<template #body-content>
				<div>
					<p>You are about to create Material Requests for the following items:</p>
					<ul v-if="selectedItemsSummary.length > 0" class="list-disc list-inside my-4">
						<li v-for="(item, index) in selectedItemsSummary" :key="index">
							Item: {{ item.item_code }}, Qty: {{ item.quantity }}, Week: {{ item.week }}, Supplier: {{ item.supplier || 'N/A' }}
						</li>
					</ul>
					<p v-else class="my-4">No items with suggested orders selected.</p>
				</div>
			</template>
			<template #actions>
				<Button @click="showCreateDialog = false">Cancel</Button>
				<Button @click="confirmCreateMaterialRequest" variant="solid" :disabled="selectedItemsSummary.length === 0">Confirm</Button>
			</template>
		</Dialog>
		<Dialog v-model="showSuccessDialog" @hide="showSuccessDialog = false">
			<template #body-title>
				<h3 class="text-2xl font-semibold text-ink-gray-9">Material Requests Created</h3>
			</template>
			<template #body-content>
				<div>
					<p>The following Material Requests have been created successfully:</p>
					<ul v-if="newlyCreatedDocs.length" class="list-disc list-inside my-4">
						<li v-for="doc in newlyCreatedDocs" :key="doc.name">
							<a :href="`/app/material-request/${doc.name}`" target="_blank" class="text-blue-600 hover:underline">{{ doc.name }}</a>
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
				<h3 class="text-2xl font-semibold text-ink-gray-9">Urgency Level Legend</h3>
			</template>
			<template #body-content>
				<div>
					<p>The urgency level highlights items that require attention:</p>
					<ul class="list-disc list-inside my-4 space-y-2">
						<li class="flex items-start gap-2">
							<div class="w-4 h-4 rounded mt-1 flex-shrink-0" style="background-color: #ffdddd"></div>
							<span><b>P1 - Critical:</b> Required and not enough quantity on order (excl safety stock).</span>
						</li>
						<li class="flex items-start gap-2">
							<div class="w-4 h-4 rounded mt-1 flex-shrink-0" style="background-color: #eab26eff"></div>
							<span><b>P2 - Attention:</b> Enough quantity on order, but scheduled to arrive late (excl safety stock).</span>
						</li>
						<li class="flex items-start gap-2">
							<div class="w-4 h-4 rounded mt-1 flex-shrink-0" style="background-color: #888888ff"></div>
							<span><b>P3 - Optional:</b> On order, but the stock level will drop below the safety stock (no row highlight)</span>
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
					'uom',
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
			if (!this.$resources.last_mrp_run.data || this.$resources.last_mrp_run.data.length === 0) {
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
			if (this.$resources.mrp_entries.loading || !this.$resources.mrp_entries.data) {
				return null // AG Grid will show its loading overlay
			}

			const mrpEntries = this.$resources.mrp_entries.data
			const items = {}

			mrpEntries.forEach((entry) => {
				if (!entry.item_code) return

				if (!items[entry.item_code]) {
					items[entry.item_code] = {
						name: entry.item_code, // for getRowId
						item_code: entry.item_code,
						item_name: entry.item_name,
						item_group: entry.item_group,
						uom: entry.uom,
						reorder_level: entry.reorder_level,
						reorder_quantity: entry.reorder_quantity,
						lead_time: entry.lead_time,
						default_supplier: entry.default_supplier,
						_urgency_levels: [],
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
					'projected_on_hand_inventory',
				]

				fieldsToPivot.forEach((field) => {
					items[entry.item_code][`${weekKey}_${field}`] = entry[field]
				})
			})

			Object.values(items).forEach((item) => {
				const positiveUrgencies = item._urgency_levels.filter((u) => u > 0)
				item.urgency_level = positiveUrgencies.length > 0 ? Math.min(...positiveUrgencies) : 0
				delete item._urgency_levels
			})

			let item_rows = Object.values(items)

			if (this.onlyShowSuggested) {
				item_rows = item_rows.filter((row) => {
					return Object.keys(row).some((key) => key.endsWith('_suggested_orders') && row[key] > 0)
				})
			}

			return item_rows
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
					headerName: 'Item Code',
					sortable: true,
					filter: true,
					width: 120,
					pinned: 'left',
					cellRenderer: (params) => {
						if (params.value) {
							return `<a href="/app/item/${params.value}" target="_blank" class="text-blue-600 hover:underline">${params.value}</a>`
						}
						return null
					},
				},
				{
					field: 'item_name',
					headerName: 'Item Name',
					sortable: true,
					filter: true,
					pinned: 'left',
				},
				{
					field: 'item_group',
					headerName: 'Item Group',
					sortable: true,
					filter: true,
					width: 120,
				},
				{ field: 'uom', headerName: 'Uom', sortable: true, filter: true, width: 100 },
				{
					field: 'reorder_level',
					headerName: 'Reorder Level',
					sortable: true,
					filter: true,
					width: 110,
					cellStyle: { textAlign: 'right' },
					headerClass: 'ag-right-aligned-header',
				},
				{
					field: 'reorder_quantity',
					headerName: 'Re-order Quantity',
					sortable: true,
					filter: true,
					width: 110,
					cellStyle: { textAlign: 'right' },
					headerClass: 'ag-right-aligned-header',
				},
				{
					field: 'lead_time',
					headerName: 'Lead Time',
					sortable: true,
					filter: true,
					width: 100,
					cellStyle: { textAlign: 'right' },
					headerClass: 'ag-right-aligned-header',
				},
				{
					field: 'default_supplier',
					headerName: 'Supplier',
					sortable: true,
					filter: true,
					width: 120,
				},
				{
					field: 'urgency_level',
					headerName: 'Urgency Level',
					sortable: true,
					filter: true,
					width: 120,
					cellStyle: { textAlign: 'center' },
					sort: 'desc',
					cellRenderer: (params) => {
						return params.value !== 0 ? `⚠️ <b>P${params.value}</b>` : params.value
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
			}

			if (this.$resources.mrp_entries.loading || !this.$resources.mrp_entries.data) {
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
				const openChildren = this.quantityFields.map((qField) => ({
					...qField,
					field: `${weekKey}_${qField.value}`,
					headerName: qField.label,
					columnGroupShow: 'open',
					sortable: true,
					filter: true,
					width: 120,
					cellStyle: qField.cellStyle || { textAlign: 'right' },
					headerClass: 'ag-right-aligned-header',
				}))

				const closedField = this.quantityFields.find((f) => f.value === this.closed_column_field)

				const closedChild = {
					field: `${weekKey}_${closedField.value}`,
					headerName: closedField.label,
					columnGroupShow: 'closed',
					sortable: true,
					filter: true,
					width: 120,
					cellStyle: closedField.cellStyle || { textAlign: 'right' },
					valueFormatter: closedField.valueFormatter,
					headerClass: 'ag-right-aligned-header',
				}

				return {
					headerName: weekKey,
					groupId: weekKey,
					children: [closedChild, ...openChildren],
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
					cellStyle: (params) => (params.value > 0 ? { background: '#ddeeff', textAlign: 'right' } : { textAlign: 'right' }),
				},
				{
					value: 'suggested_orders_value',
					label: 'Suggested Orders Value',
					cellStyle: { textAlign: 'right' },
					valueFormatter: (params) => this.formatCurrency(params.value),
				},
				{ value: 'projected_on_hand_inventory', label: 'Projected On Hand Inventory' },
			]
		},
		isLoading() {
			return this.$resources.mrp_entries.loading
		},
	},
	methods: {
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
			// New method to be called by the button in the cell
			this.showDialog = true
			console.log('MaterialRequestList: showDialog is now true') // For verification
		},
		getRowId(params) {
			return params.data.name
		},
		getRowStyle(params) {
			if (params.data && params.data.urgency_level === 1) {
				return { background: '#ffdddd' }
			} else if (params.data && params.data.urgency_level === 2) {
				return { background: '#eab26eff' }
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
			this.selectedRows.forEach((row) => {
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
			})
			this.selectedItemsSummary = summary

			await nextTick()

			this.showCreateDialog = true
		},
		async confirmCreateMaterialRequest() {
			try {
				const createdDocs = await this.createMaterialRequest(this.selectedItemsSummary)
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
				if (supplierItems[0].supplier && supplierItems[0].supplier !== 'No Supplier') {
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
