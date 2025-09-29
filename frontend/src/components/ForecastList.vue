<template>
  <ag-grid-vue
    style="height: 500px;"
    class="ag-theme-alpine mt-8 w-full"
    theme="legacy"
    :columnDefs="columnDefs"
    :rowData="forecastRows"
    :pagination="true"
    :paginationPageSize="10"
    :getRowId="getRowId"
    :defaultColDef="{
      wrapHeaderText: true,
      autoHeaderHeight: true,
      resizable: true
    }"
  />
</template>

<script>
import { AgGridVue } from "ag-grid-vue3";
import { computed } from 'vue';

export default {
  name: 'ForecastList',
  components: {
    AgGridVue,
  },
  data() {
    return {
      columnDefs: [],
    };
  },
  resources: {
    forecast_data: {
      type: 'list',
      doctype: 'MRP Forecast',
      fields: ["name", "item_code", "forecast_quantity", "forecast_date"],
      orderBy: 'creation desc',
      limit: 1000, // Fetch a larger dataset to pivot
      auto: true,
    },
  },
  computed: {
    forecastRows() {
      if (this.$resources.forecast_data.loading || !this.$resources.forecast_data.data) {
        return null; // AG Grid will show its loading overlay
      }
      
      const pivotData = {};
      const months = new Set();

      this.$resources.forecast_data.data.forEach(row => {
        if (!pivotData[row.item_code]) {
          pivotData[row.item_code] = { item_code: row.item_code };
        }
        const month = row.forecast_date.substring(0, 7); // YYYY-MM
        pivotData[row.item_code][month] = row.forecast_quantity;
        months.add(month);
      });

      const sortedMonths = Array.from(months).sort();

      this.columnDefs = [
        { field: 'item_code', headerName: 'Item Code', sortable: true, filter: true, flex: 1 },
        ...sortedMonths.map(month => ({
          field: month,
          headerName: month,
          sortable: true,
          filter: true,
          flex: 1,
        }))
      ];

      return Object.values(pivotData);
    },
    isLoading() {
      return this.$resources.forecast_data.loading;
    }
  },
  methods: {
    getRowId(params) {
      return params.data.item_code;
    }
  }
};
</script>
