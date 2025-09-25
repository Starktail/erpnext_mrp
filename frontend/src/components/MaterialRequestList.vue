<template>
  <div>
    <div class="mb-4 flex gap-2">
      <Button @click="expandAll">Expand All</Button>
      <Button @click="collapseAll">Collapse All</Button>
    </div>
    <ag-grid-vue
      style="height: 500px;"
      class="ag-theme-alpine w-full"
      theme="legacy"
      :columnDefs="columnDefs"
      :rowData="materialRequestRows"
      :pagination="true"
      :paginationPageSize="10"
      :getRowId="getRowId"
      :defaultColDef="{
        wrapHeaderText: true,
        autoHeaderHeight: true,
        resizable: true
      }"
      @grid-ready="onGridReady"
    />
    <Dialog v-model="showDialog" title="Material Request Details" @hide="showDialog = false">
      <div>
        <p>Dialog content will go here.</p>
        <p>For now, this confirms the dialog is working.</p>
      </div>
      <template #actions>
        <Button @click="showDialog = false">Close</Button>
      </template>
    </Dialog>
  </div>
</template>

<script>
import { AgGridVue } from "ag-grid-vue3";
// AG Grid CSS is now imported in main.js
import { computed } from 'vue';
import { Button, Dialog } from 'frappe-ui'; // Import Button and Dialog components

export default {
  name: 'MaterialRequestList',
  components: {
    AgGridVue,
    Dialog, // Register the Dialog component
    buttonCellRenderer: { 
      name: 'ButtonCellRenderer',
      template: `<Button @click="onButtonClick">Planning Detail</Button>`,
      components: { // Explicitly register Button for this local component
        Button,
      },
      props: {
        params: { // AG Grid passes params via a prop named 'params'
          type: Object,
          required: true
        }
      },
      methods: {
        onButtonClick() {
          // Call the method passed in cellRendererParams from the parent component
          this.params.onOpenDialog();
        }
      }
    }
  },
  data() {
    return {
      gridApi: null,
      columnApi: null,
      showDialog: false, // New data property
      columnDefs: [
        { field: 'item_code', headerName: 'Item Code', sortable: true, filter: true, width: 120, pinned: 'left' },
        { field: 'item_name', headerName: 'Item Name', sortable: true, filter: true },
        { field: 'item_group', headerName: 'Item Group', sortable: true, filter: true, width: 120 },
        { field: 'uom', headerName: 'Uom', sortable: true, filter: true, width: 100 },
        { field: 'safety_stock', headerName: 'Safety Stock', sortable: true, filter: true, width: 100 },
        { field: 'reorder_level', headerName: 'Reorder Level', sortable: true, filter: true, width: 100 },
        { field: 'reorder_quantity', headerName: 'Re-order Quantity', sortable: true, filter: true, width: 100 },
        { field: 'lead_time', headerName: 'Lead Time', sortable: true, filter: true, width: 100 },
        { field: 'is_urgent', headerName: 'Urgent', sortable: true, filter: true, width: 100 },
        {
          headerName: '2025-09',
          groupId: '2025-09',
          children: [
            { field: 'on_hand_inventory', headerName: 'On Hand Inventory', sortable: true, filter: true, width: 120 },
            { field: 'open_orders', headerName: 'Open Orders', sortable: true, filter: true, width: 120 },
            { field: 'forecast_demand', headerName: 'Forecast Demand', sortable: true, filter: true, width: 120 },
            { field: 'scheduled_receipts', headerName: 'Scheduled Receipts', sortable: true, filter: true, width: 120 },
            { field: 'suggested_receipts', headerName: 'Suggested Receipts', sortable: true, filter: true, width: 120 },
            { field: 'suggested_orders', headerName: 'Suggested Orders', sortable: true, filter: true, width: 120 },
            { field: 'projected_on_hand_inventory', headerName: 'Projected On Hand Inventory', sortable: true, filter: true, width: 120 },
          ]
        },
        {
          headerName: '2025-10',
          groupId: '2025-10',
          children: [
            { field: 'gross_requirement', headerName: 'Gross Requirement', sortable: true, filter: true, width: 120 },
            { field: 'customer_orders', headerName: 'Customer Orders', sortable: true, filter: true, width: 120 },
            { field: 'forecasted_demand', headerName: 'Forecasted Demand', sortable: true, filter: true, width: 120 },
            { field: 'document_reference', headerName: 'Document Reference', sortable: true, filter: true, width: 120 },
            { field: 'on_hand_inventory', headerName: 'On Hand Inventory', sortable: true, filter: true, width: 120 },
            { field: 'scheduled_receipts', headerName: 'Scheduled Receipts', sortable: true, filter: true, width: 120 },
            { field: 'planned_orders', headerName: 'Planned Orders', sortable: true, filter: true, width: 120 },
            { field: 'suppliersource', headerName: 'Suppliersource', sortable: true, filter: true, width: 120 },
          ]
        },
        { // New column for actions
          headerName: 'Actions',
          cellRenderer: 'buttonCellRenderer', // Use the locally registered component
          cellRendererParams: {
            onOpenDialog: this.handleOpenDialog // Pass the method to the cell renderer
          },
          sortable: false,
          filter: false,
        }
      ],
    };
  },
  resources: {
    material_requests() {
      return {
        type: 'list',
        doctype: 'MRP Entry',
        fields: [
          "item_code",
          "item_name",
          "item_group",
          "uom",
          "reorder_level",
          "reorder_quantity",
          "lead_time",
          "is_urgent",
          "on_hand_inventory",
          "open_orders",
          "forecast_demand",
          "scheduled_receipts",
          "suggested_receipts",
          "suggested_orders",
          "projected_on_hand_inventory"
        ],
        orderBy: 'creation desc',
        start: 0,
        pageLength: 15,
        auto: true,
      }
    },
  },
  computed: {
    materialRequestRows() {
      if (this.$resources.material_requests.loading) {
        return null; // AG Grid will show its loading overlay
      }
      return this.$resources.material_requests.data || [];
    },
    isLoading() {
      return this.$resources.material_requests.loading;
    }
  },
  methods: {
    onGridReady(params) {
      this.gridApi = params.api;
      this.columnApi = params.columnApi;
    },
    expandAll() {
      this.columnApi.setColumnGroupOpened(null, true);
    },
    collapseAll() {
      this.columnApi.setColumnGroupOpened(null, false);
    },
    handleOpenDialog() { // New method to be called by the button in the cell
      this.showDialog = true;
      console.log('MaterialRequestList: showDialog is now true'); // For verification
    },
    getRowId(params) {
      return params.data.name;
    }
  }
};
</script>