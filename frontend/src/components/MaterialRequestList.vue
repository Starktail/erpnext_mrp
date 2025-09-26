<template>
  <div class="h-full flex flex-col">
    <div class="mb-4 flex gap-2 items-center">
      <Button @click="clearFilters">Clear Filters</Button>
      <Button @click="reload">Reload</Button>
      <Combobox :options="quantityFields" v-model="closed_column_field" placeholder="Select a field" />
    </div>
    <ag-grid-vue
      class="ag-theme-alpine w-full flex-grow"
      theme="legacy"
      :columnDefs="dynamicColumnDefs"
      :rowData="materialRequestRows"
      :pagination="true"
      :paginationPageSize="100"
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
import { Button, Dialog, Combobox } from 'frappe-ui'; // Import Button and Dialog components

export default {
  name: 'MaterialRequestList',
  components: {
    AgGridVue,
    Dialog, // Register the Dialog component
    Combobox, // Register the Combobox component
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
      showDialog: false,
      closed_column_field: 'suggested_orders',
    };
  },
  resources: {
    material_requests() {
      return {
        type: 'list',
        doctype: 'MRP Entry',
        fields: [
          "name",
          "item_code",
          "item_name",
          "item_group",
          "uom",
          "reorder_level",
          "reorder_quantity",
          "lead_time",
          "is_urgent",
          "target_date",
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
        pageLength: 10000,
        auto: true,
      }
    },
  },
  computed: {
    materialRequestRows() {
      if (this.$resources.material_requests.loading || !this.$resources.material_requests.data) {
        return null; // AG Grid will show its loading overlay
      }
      
      const mrpEntries = this.$resources.material_requests.data;
      const items = {};

      mrpEntries.forEach(entry => {
        if (!entry.item_code) return;

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
            is_urgent: entry.is_urgent,
          };
        }

        if (!entry.target_date) return;

        const [year, week] = this.getWeekNumber(new Date(entry.target_date));
        const weekKey = `${year}-W${String(week).padStart(2, '0')}`;

        const fieldsToPivot = [
            'on_hand_inventory',
            'open_orders',
            'forecast_demand',
            'scheduled_receipts',
            'suggested_receipts',
            'suggested_orders',
            'projected_on_hand_inventory'
        ];

        fieldsToPivot.forEach(field => {
            items[entry.item_code][`${weekKey}_${field}`] = entry[field];
        });
      });

      return Object.values(items);
    },
    dynamicColumnDefs() {
      const staticColumns = [
        { field: 'item_code', headerName: 'Item Code', sortable: true, filter: true, width: 120, pinned: 'left' },
        { field: 'item_name', headerName: 'Item Name', sortable: true, filter: true, pinned: 'left' },
        { field: 'item_group', headerName: 'Item Group', sortable: true, filter: true, width: 120 },
        { field: 'uom', headerName: 'Uom', sortable: true, filter: true, width: 100 },
        { field: 'reorder_level', headerName: 'Reorder Level', sortable: true, filter: true, width: 110 },
        { field: 'reorder_quantity', headerName: 'Re-order Quantity', sortable: true, filter: true, width: 110 },
        { field: 'lead_time', headerName: 'Lead Time', sortable: true, filter: true, width: 100 },
        { field: 'is_urgent', headerName: 'Urgent', sortable: true, filter: true, width: 100 },
      ];

      const actionsColumn = {
          headerName: 'Actions',
          cellRenderer: 'buttonCellRenderer',
          cellRendererParams: {
              onOpenDialog: this.handleOpenDialog
          },
          sortable: false,
          filter: false,
      };

      if (this.$resources.material_requests.loading || !this.$resources.material_requests.data) {
          return staticColumns.concat(actionsColumn);
      }

      const mrpEntries = this.$resources.material_requests.data;
      const weeks = new Set();
      mrpEntries.forEach(entry => {
          if (!entry.target_date) return;
          const [year, week] = this.getWeekNumber(new Date(entry.target_date));
          const weekKey = `${year}-W${String(week).padStart(2, '0')}`;
          weeks.add(weekKey);
      });

      const sortedWeeks = Array.from(weeks).sort();

      const dynamicColumns = sortedWeeks.map(weekKey => {
          const openChildren = this.quantityFields.map(qField => ({
              field: `${weekKey}_${qField.value}`,
              headerName: qField.label,
              columnGroupShow: 'open',
              sortable: true,
              filter: true,
              width: 120
          }));

          const closedField = this.quantityFields.find(f => f.value === this.closed_column_field);

          const closedChild = {
              field: `${weekKey}_${closedField.value}`,
              headerName: closedField.label,
              columnGroupShow: 'closed',
              sortable: true,
              filter: true,
              width: 120
          };

          return {
              headerName: weekKey,
              groupId: weekKey,
              children: [closedChild, ...openChildren]
          };
      });

      return staticColumns.concat(dynamicColumns, actionsColumn);
    },
    quantityFields() {
      return [
          { value: 'on_hand_inventory', label: 'On Hand Inventory' },
          { value: 'open_orders', label: 'Open Orders' },
          { value: 'forecast_demand', label: 'Forecast Demand' },
          { value: 'scheduled_receipts', label: 'Scheduled Receipts' },
          { value: 'suggested_receipts', label: 'Suggested Receipts' },
          { value: 'suggested_orders', label: 'Suggested Orders' },
          { value: 'projected_on_hand_inventory', label: 'Projected On Hand Inventory' },
      ];
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
    clearFilters() {
      this.gridApi.setFilterModel(null);
    },
    reload() {
      this.$resources.material_requests.reload();
    },
    handleOpenDialog() { // New method to be called by the button in the cell
      this.showDialog = true;
      console.log('MaterialRequestList: showDialog is now true'); // For verification
    },
    getRowId(params) {
      return params.data.name;
    },
    // From https://stackoverflow.com/a/6117889
    getWeekNumber(d) {
        // Copy date so don't modify original
        d = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
        // Set to nearest Thursday: current date + 4 - current day number
        // Make Sunday's day number 7
        d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay()||7));
        // Get first day of year
        var yearStart = new Date(Date.UTC(d.getUTCFullYear(),0,1));
        // Calculate full weeks to nearest Thursday
        var weekNo = Math.ceil(( ( (d - yearStart) / 86400000) + 1)/7);
        // Return array of year and week number
        return [d.getUTCFullYear(), weekNo];
    }
  }
};
</script>