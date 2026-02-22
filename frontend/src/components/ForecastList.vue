<template>
  <div class="h-full flex flex-col w-full mt-8">
    <n-data-table
      ref="tableRef"
      :columns="columns"
      :data="forecastRows"
      :row-key="rowKey"
      :loading="isLoading"
      :bordered="true"
      :single-line="false"
      size="small"
      :pagination="pagination"
      class="h-[500px]"
      flex-height
      striped
    />
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { NDataTable } from 'naive-ui'
import { createListResource } from 'frappe-ui'

const pagination = ref({
  pageSize: 10,
})

const forecast_data = createListResource({
  doctype: 'MRP Forecast',
  fields: ['name', 'item_code', 'forecast_quantity', 'forecast_date'],
  orderBy: 'creation desc',
  limit: 1000, // Fetch a larger dataset to pivot
  auto: true,
})

const isLoading = computed(() => forecast_data.list.loading)

const tableData = computed(() => {
  if (isLoading.value || !forecast_data.data) {
    return { rows: [], months: [] }
  }

  const pivotData = {}
  const months = new Set()

  forecast_data.data.forEach((row) => {
    if (!pivotData[row.item_code]) {
      pivotData[row.item_code] = { item_code: row.item_code }
    }
    const month = row.forecast_date.substring(0, 7) // YYYY-MM
    pivotData[row.item_code][month] = row.forecast_quantity
    months.add(month)
  })

  const sortedMonths = Array.from(months).sort()
  return {
    rows: Object.values(pivotData),
    months: sortedMonths,
  }
})

const forecastRows = computed(() => tableData.value.rows)

const columns = computed(() => {
  const cols = [
    {
      title: 'Item Code',
      key: 'item_code',
      sorter: 'default',
    },
  ]

  tableData.value.months.forEach((month) => {
    cols.push({
      title: month,
      key: month,
      sorter: 'default',
    })
  })

  return cols
})

function rowKey(rowData) {
  return rowData.item_code
}
</script>
