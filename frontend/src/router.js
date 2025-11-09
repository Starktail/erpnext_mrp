import { createRouter, createWebHistory } from 'vue-router'

const routes = [
	{
		path: '/',
		name: 'Home',
		component: () => import('@/pages/Home.vue'),
	},
	{
		path: '/forecast',
		name: 'Forecast',
		component: () => import('@/pages/Forecast.vue'),
	},
]

let router = createRouter({
	history: createWebHistory('/erpnext_mrp'),
	routes,
})

export default router
