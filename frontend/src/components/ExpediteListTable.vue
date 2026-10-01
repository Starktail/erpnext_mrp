<template>
  <div class="h-full flex flex-col">
    <div v-if="loaded && !enabled" class="text-sm text-gray-600">
      The Expedite List is only available when
      <a
        href="/app/mrp-settings"
        target="_blank"
        class="text-blue-600 hover:underline"
        >Only Suggest Orders That Can Arrive In Time</a
      >
      is enabled in MRP Settings.
    </div>
    <template v-else>
      <div v-if="needsRerun" class="mb-3 text-sm text-amber-700">
        MRP Settings changed after the last MRP run, so this list may be out of
        date. Rerun MRP from the
        <router-link to="/" class="text-blue-600 hover:underline"
          >MRP Workbench</router-link
        >
        to update it.
      </div>
      <div v-if="expedite_list.error" class="text-sm text-red-600">
        Failed to load the Expedite List: {{ expedite_list.error.message }}
      </div>
      <n-data-table
        v-else
        :columns="columns"
        :data="expedite_list.data || []"
        :row-key="(row) => row.item_code"
        :loading="expedite_list.loading"
        :bordered="true"
        :single-line="false"
        size="small"
        :pagination="{ pageSize: 50 }"
        :scroll-x="1660"
        flex-height
        striped
        class="h-full"
      >
        <template #empty>
          <span class="text-sm text-gray-600">
            {{
              needsRerun
                ? 'No stockouts as of the last MRP run.'
                : 'No stockouts: all shortages can still be covered in time.'
            }}
          </span>
        </template>
      </n-data-table>
    </template>
  </div>
</template>

<script setup>
import { h, onMounted, onUnmounted } from 'vue'
import { NDataTable } from 'naive-ui'
import { createResource } from 'frappe-ui'
import { useExpediteList } from '../composables/useExpediteList'

const { enabled, needsRerun, loaded, refresh } = useExpediteList()

const expedite_list = createResource({
  url: 'erpnext_mrp.mrp.tasks.mrp_run.get_expedite_list',
  auto: true,
})

function formatDate(value) {
  if (!value) return ''
  return new Date(value).toLocaleDateString()
}

function isOverdue(value) {
  return value && new Date(value) < new Date(new Date().toDateString())
}

function docLink(doctype, name) {
  const route = doctype.toLowerCase().replace(/ /g, '-')
  return h(
    'a',
    {
      href: `/app/${route}/${name}`,
      target: '_blank',
      class: 'text-blue-600 hover:underline',
    },
    name,
  )
}

function renderInbound(row) {
  if (!row.inbound.length) {
    return h(
      'span',
      { class: 'text-red-600' },
      'Nothing inbound: order immediately',
    )
  }
  return h(
    'div',
    { class: 'flex flex-col gap-0.5' },
    row.inbound.map((line) =>
      h('div', { class: 'flex gap-2 whitespace-nowrap' }, [
        docLink(line.doctype, line.name),
        h('span', { class: 'text-gray-600' }, `${line.qty} ${row.uom || ''}`),
        h(
          'span',
          {
            class: isOverdue(line.expected_date)
              ? 'text-red-600'
              : 'text-gray-600',
          },
          line.expected_date
            ? `${
                isOverdue(line.expected_date) ? 'overdue' : 'due'
              } ${formatDate(line.expected_date)}`
            : '',
        ),
        line.supplier_name
          ? h('span', { class: 'text-gray-500' }, line.supplier_name)
          : null,
      ]),
    ),
  )
}

function supplierLabel(row) {
  return row.default_supplier_name || row.default_supplier || ''
}

const columns = [
  {
    title: 'Item Code',
    key: 'item_code',
    width: 200,
    sorter: (a, b) => a.item_code.localeCompare(b.item_code),
    render: (row) => docLink('Item', row.item_code),
  },
  {
    title: 'Item Name',
    key: 'item_name',
    width: 200,
    ellipsis: { tooltip: true },
  },
  {
    title: 'Item Group',
    key: 'item_group',
    width: 160,
    ellipsis: { tooltip: true },
    sorter: (a, b) => (a.item_group || '').localeCompare(b.item_group || ''),
  },
  {
    title: 'Type',
    key: 'is_manufactured',
    width: 120,
    sorter: (a, b) => a.is_manufactured - b.is_manufactured,
    render: (row) => (row.is_manufactured ? 'Manufactured' : 'Purchased'),
  },
  {
    title: 'Default Supplier',
    key: 'default_supplier_name',
    width: 160,
    ellipsis: { tooltip: true },
    sorter: (a, b) => supplierLabel(a).localeCompare(supplierLabel(b)),
    render: supplierLabel,
  },
  {
    title: 'Lead Time (days)',
    key: 'lead_time',
    width: 110,
    sorter: (a, b) => (a.lead_time || 0) - (b.lead_time || 0),
  },
  {
    title: 'On Hand',
    key: 'on_hand_inventory',
    width: 100,
  },
  {
    title: 'Stockout From',
    key: 'first_stockout_date',
    width: 130,
    defaultSortOrder: 'ascend',
    sorter: (a, b) =>
      new Date(a.first_stockout_date) - new Date(b.first_stockout_date),
    render: (row) =>
      h(
        'span',
        { class: 'text-red-600 font-semibold' },
        formatDate(row.first_stockout_date),
      ),
  },
  {
    title: 'Peak Shortage',
    key: 'stockout_qty',
    width: 120,
    sorter: (a, b) => a.stockout_qty - b.stockout_qty,
    render: (row) => `${row.stockout_qty} ${row.uom || ''}`,
  },
  {
    title: 'Inbound Supply to Expedite',
    key: 'inbound',
    minWidth: 360,
    render: renderInbound,
  },
]

function reload() {
  refresh()
  expedite_list.reload()
}

onMounted(() => {
  refresh()
  window.frappe?.realtime?.on('mrp_run_complete', reload)
})

onUnmounted(() => {
  window.frappe?.realtime?.off('mrp_run_complete', reload)
})
</script>
