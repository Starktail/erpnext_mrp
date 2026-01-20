import './index.css'

// Import AG Grid styles globally
import 'ag-grid-community/styles/ag-grid.css'
import 'ag-grid-community/styles/ag-theme-alpine.css'

import { createApp } from 'vue'
import router from './router'
import App from './App.vue'

import { Button, setConfig, frappeRequest, resourcesPlugin } from 'frappe-ui'
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community'

ModuleRegistry.registerModules([AllCommunityModule])

let app = createApp(App)

setConfig('resourceFetcher', frappeRequest)

app.use(router)
app.use(resourcesPlugin)

app.component('Button', Button)

if (import.meta.env.DEV) {
	frappeRequest({ url: '/api/method/erpnext_mrp.www.erpnext_mrp.get_context_for_dev' }).then((values) => {
		for (let key in values) {
			window[key] = values[key]
		}
		app.mount('#app')
	})
} else {
	// In production, jinjaBootData likely sets window.frappe_boot
	if (window.frappe_boot) {
		window.sysdefaults = window.frappe_boot.sysdefaults
	}
	app.mount('#app')
}
