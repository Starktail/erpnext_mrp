<template>
  <ag-grid-vue
    style="height: 500px;"
    class="ag-theme-alpine mt-8 w-full"
    theme="legacy"
    :columnDefs="columnDefs"
    :rowData="materialRequestRows"
    :pagination="true"
    :paginationPageSize="10"
    :getRowId="getRowId"
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
      showDialog: false, // New data property
      columnDefs: [
        { field: 'item_code', headerName: 'Item Code', sortable: true, filter: true, flex: 1 },
        { field: 'item_name', headerName: 'Item Name', sortable: true, filter: true, flex: 1 },
        { field: 'item_group', headerName: 'Item Group', sortable: true, filter: true, flex: 1 },
        { field: 'bom_levels', headerName: 'Bom Levels', sortable: true, filter: true, flex: 1 },
        { field: 'uom', headerName: 'Uom', sortable: true, filter: true, flex: 1 },
        { field: 'gross_requirement', headerName: 'Gross Requirement', sortable: true, filter: true, flex: 1 },
        { field: 'customer_orders', headerName: 'Customer Orders', sortable: true, filter: true, flex: 1 },
        { field: 'forecasted_demand', headerName: 'Forecasted Demand', sortable: true, filter: true, flex: 1 },
        { field: 'document_reference', headerName: 'Document Reference', sortable: true, filter: true, flex: 1 },
        { field: 'on_hand_inventory', headerName: 'On Hand Inventory', sortable: true, filter: true, flex: 1 },
        { field: 'scheduled_receipts', headerName: 'Scheduled Receipts', sortable: true, filter: true, flex: 1 },
        { field: 'planned_orders', headerName: 'Planned Orders', sortable: true, filter: true, flex: 1 },
        { field: 'suppliersource', headerName: 'Suppliersource', sortable: true, filter: true, flex: 1 },
        { field: 'net_requirements', headerName: 'Net Requirements', sortable: true, filter: true, flex: 1 },
        { field: 'safety_stock', headerName: 'Safety Stock', sortable: true, filter: true, flex: 1 },
        { field: 'reorder_level', headerName: 'Reorder Level', sortable: true, filter: true, flex: 1 },
        { field: 'order_quantity', headerName: 'Order Quantity', sortable: true, filter: true, flex: 1 },
        { field: 'lead_time', headerName: 'Lead Time', sortable: true, filter: true, flex: 1 },
        { // New column for actions
          headerName: 'Actions',
          cellRenderer: 'buttonCellRenderer', // Use the locally registered component
          cellRendererParams: {
            onOpenDialog: this.handleOpenDialog // Pass the method to the cell renderer
          },
          flex: 1, // Adjust width as needed
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
        doctype: 'MRP Demo Record',
        fields: [  "item_code",
          "item_name",
          "item_group",
          "bom_levels",
          "uom",
          "gross_requirement",
          "customer_orders",
          "forecasted_demand",
          "document_reference",
          "on_hand_inventory",
          "scheduled_receipts",
          "planned_orders",
          "suppliersource",
          "net_requirements",
          "safety_stock",
          "reorder_level",
          "order_quantity",
          "lead_time"
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
