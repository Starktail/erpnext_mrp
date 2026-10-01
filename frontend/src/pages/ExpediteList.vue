<template>
  <div class="flex flex-col h-screen w-full px-4 py-12">
    <h1 class="text-2xl font-bold mb-2">Expedite List</h1>
    <p class="text-sm text-gray-600 max-w-3xl">
      Items that run out of stock before an order placed today could arrive.
    </p>
    <p class="text-sm text-gray-600 max-w-3xl">
      Because <b>"Only Suggest Orders That Can Arrive In Time"</b> is enabled,
      MRP does not suggest a new order for these shortages.
    </p>
    <p class="text-sm text-gray-600 max-w-3xl">
      It is necessary to expedite the open Purchase Orders or Work Orders below.
    </p>
    <ExpediteListTable class="mt-6 flex-grow" />
  </div>
</template>

<script>
import ExpediteListTable from '@/components/ExpediteListTable.vue'

export default {
  name: 'ExpediteList',
  components: {
    ExpediteListTable,
  },
}
</script>
