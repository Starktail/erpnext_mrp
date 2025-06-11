<template>
  <ListView
    :rows="materialRequestRows"
    rowKey="name"
    :columns="columns"
    :loading="isLoading"
    class="mt-8"
  />
</template>

<script>
import { ListView, createListResource } from 'frappe-ui';
import { computed } from 'vue';

export default {
  name: 'MaterialRequestList',
  components: {
    ListView,
  },
  data() {
    return {
      columns: [
        { key: 'name', label: 'Name' },
        { key: 'transaction_date', label: 'Transaction Date' },
        { key: 'status', label: 'Status' },
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
      return this.$resources.material_requests.data || [];
    },
    isLoading() {
      return this.$resources.material_requests.loading;
    }
  },
};
</script>
