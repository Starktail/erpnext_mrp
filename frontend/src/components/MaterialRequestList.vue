<template>
  <ag-grid-vue
    style="height: 500px;"
    class="ag-theme-alpine mt-8 w-full"
    :columnDefs="columnDefs"
    :rowData="materialRequestRows"
    :pagination="true"
    :paginationPageSize="10"
    :getRowId="getRowId"
  />
</template>

<script>
import { AgGridVue } from "ag-grid-vue3";
// AG Grid CSS is now imported in main.js
import { computed } from 'vue';

export default {
  name: 'MaterialRequestList',
  components: {
    AgGridVue,
  },
  data() {
    return {
      columnDefs: [
        { field: 'name', headerName: 'Name', sortable: true, filter: true, flex: 1 },
        { field: 'transaction_date', headerName: 'Transaction Date', sortable: true, filter: true, flex: 1 },
        { field: 'status', headerName: 'Status', sortable: true, filter: true, flex: 1 },
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
    getRowId(params) {
      return params.data.name;
    }
  }
};
</script>
