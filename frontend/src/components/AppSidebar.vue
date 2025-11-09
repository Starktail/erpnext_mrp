<script setup>
import { Sidebar } from 'frappe-ui'
import LayoutList from '~icons/lucide/layout-list'
import BarChart2 from '~icons/lucide/bar-chart-2'

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
			onClick: () => open('/erpnextmrp_introduction', '_blank'),
		},
		{
			label: 'Logout',
			icon: 'log-out',
			onClick: () => alert('Logging out...'),
		},
	],
}

const sections = [
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
		],
	},
]

function toggleTheme() {
	const currentTheme = document.documentElement.getAttribute('data-theme')
	const newTheme = currentTheme === 'dark' ? 'light' : 'dark'
	document.documentElement.setAttribute('data-theme', newTheme)
}
</script>

<template>
	<Sidebar :header="header" :sections="sections" />
</template>
