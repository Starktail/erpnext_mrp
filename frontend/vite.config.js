import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import frappeui from 'frappe-ui/vite'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    frappeui({
      frappeProxy: true,
      lucideIcons: true,
      jinjaBootData: true,
      buildConfig: {
        indexHtmlPath: '../erpnext_mrp/www/erpnext_mrp.html',
			  outDir: "../erpnext_mrp/public/erpnext_mrp",
        emptyOutDir: true,
        sourcemap: true,
      },
    }),
    vue()
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      'vue': 'vue/dist/vue.esm-bundler.js', // Add this line
    },
  },
  optimizeDeps: {
    include: [
      'feather-icons',
      'showdown',
      'tailwind.config.js',
      'prosemirror-state',
      'prosemirror-view',
      'lowlight',
    ],
  },
})
