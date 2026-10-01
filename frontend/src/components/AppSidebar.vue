<script setup>
import { ref, computed, h, inject, onMounted } from 'vue'
import { Sidebar } from 'frappe-ui'
import LayoutList from '~icons/lucide/layout-list'
import BarChart2 from '~icons/lucide/bar-chart-2'
import AlarmClock from '~icons/lucide/alarm-clock'
import { useExpediteList } from '@/composables/useExpediteList'

const isCollapsed = ref(true)

const {
  enabled: expediteEnabled,
  count: expediteCount,
  refresh: refreshExpediteList,
} = useExpediteList()

// frappe-ui's Sidebar has no nested items, so a sub-item is indented through its icon.
// The indent is dropped when collapsed, where only icons show and must stay aligned.
function indented(icon) {
  return {
    inheritAttrs: false,
    setup() {
      const isSidebarCollapsed = inject('isSidebarCollapsed', ref(false))
      return () =>
        h('span', { class: isSidebarCollapsed.value ? '' : 'pl-4' }, [
          h(icon, { class: 'size-4 text-ink-gray-6' }),
        ])
    },
  }
}
const IndentedAlarmClock = indented(AlarmClock)

const header = {
  title: 'ERPNext MRP',
  logo: '/assets/erpnext_mrp/mrp-logo.png',
  menuItems: [
    {
      label: 'Toggle Theme',
      icon: 'moon',
      onClick: toggleTheme,
    },
    {
      label: 'Documentation',
      icon: 'book',
      onClick: () => open('/erpnext_mrp_introduction', '_blank'),
    },
    {
      label: 'Logout',
      icon: 'log-out',
      onClick: () => alert('Logging out...'),
    },
  ],
}

const sections = computed(() => [
  {
    label: 'Planning Tools',
    items: [
      {
        label: 'Forecast',
        icon: BarChart2,
        to: '/forecast',
      },
      {
        label: 'MRP Workbench',
        icon: LayoutList,
        to: '/',
      },
      ...(expediteEnabled.value
        ? [
            {
              label: 'Expedite List',
              icon: IndentedAlarmClock,
              to: '/expedite',
              suffix: expediteCount.value ? String(expediteCount.value) : '',
            },
          ]
        : []),
    ],
  },
])

onMounted(refreshExpediteList)

function toggleTheme() {
  const currentTheme = document.documentElement.getAttribute('data-theme')
  const newTheme = currentTheme === 'dark' ? 'light' : 'dark'
  document.documentElement.setAttribute('data-theme', newTheme)
}
</script>

<template>
  <Sidebar
    :header="header"
    :sections="sections"
    v-model:collapsed="isCollapsed"
  />
</template>
