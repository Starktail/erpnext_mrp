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
      template: `<Button @click="onButtonClick">Open Dialog</Button>`,
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
        { field: 'name', headerName: 'Name', sortable: true, filter: true, flex: 1 },
        { field: 'transaction_date', headerName: 'Transaction Date', sortable: true, filter: true, flex: 1 },
        { field: 'status', headerName: 'Status', sortable: true, filter: true, flex: 1 },
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
        doctype: 'Material Request',
        fields: ['name', 'title', 'status', 'transaction_date'],
        orderBy: 'creation desc',
        start: 0,
        pageLength: 5,
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
