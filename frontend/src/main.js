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
app.mount('#app')
