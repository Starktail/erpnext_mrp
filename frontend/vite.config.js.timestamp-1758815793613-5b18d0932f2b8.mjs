// vite.config.js
import { defineConfig } from "file:///workspace/development/frappe-bench-v15/apps/erpnext_mrp/frontend/node_modules/vite/dist/node/index.js";
import vue from "file:///workspace/development/frappe-bench-v15/apps/erpnext_mrp/frontend/node_modules/@vitejs/plugin-vue/dist/index.mjs";
import path from "path";
import frappeui from "file:///workspace/development/frappe-bench-v15/apps/erpnext_mrp/frontend/node_modules/frappe-ui/vite/index.js";
var __vite_injected_original_dirname = "/workspace/development/frappe-bench-v15/apps/erpnext_mrp/frontend";
var vite_config_default = defineConfig({
  plugins: [
    frappeui({
      frappeProxy: true,
      lucideIcons: true,
      jinjaBootData: true,
      buildConfig: {
        indexHtmlPath: "../erpnext_mrp/www/erpnext_mrp.html",
        emptyOutDir: true,
        sourcemap: true
      }
    }),
    vue()
  ],
  resolve: {
    alias: {
      "@": path.resolve(__vite_injected_original_dirname, "src"),
      "vue": "vue/dist/vue.esm-bundler.js"
      // Add this line
    }
  },
  optimizeDeps: {
    include: [
      "feather-icons",
      "showdown",
      "tailwind.config.js",
      "prosemirror-state",
      "prosemirror-view",
      "lowlight"
    ]
  }
});
export {
  vite_config_default as default
};
//# sourceMappingURL=data:application/json;base64,ewogICJ2ZXJzaW9uIjogMywKICAic291cmNlcyI6IFsidml0ZS5jb25maWcuanMiXSwKICAic291cmNlc0NvbnRlbnQiOiBbImNvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9kaXJuYW1lID0gXCIvd29ya3NwYWNlL2RldmVsb3BtZW50L2ZyYXBwZS1iZW5jaC12MTUvYXBwcy9lcnBuZXh0X21ycC9mcm9udGVuZFwiO2NvbnN0IF9fdml0ZV9pbmplY3RlZF9vcmlnaW5hbF9maWxlbmFtZSA9IFwiL3dvcmtzcGFjZS9kZXZlbG9wbWVudC9mcmFwcGUtYmVuY2gtdjE1L2FwcHMvZXJwbmV4dF9tcnAvZnJvbnRlbmQvdml0ZS5jb25maWcuanNcIjtjb25zdCBfX3ZpdGVfaW5qZWN0ZWRfb3JpZ2luYWxfaW1wb3J0X21ldGFfdXJsID0gXCJmaWxlOi8vL3dvcmtzcGFjZS9kZXZlbG9wbWVudC9mcmFwcGUtYmVuY2gtdjE1L2FwcHMvZXJwbmV4dF9tcnAvZnJvbnRlbmQvdml0ZS5jb25maWcuanNcIjtpbXBvcnQgeyBkZWZpbmVDb25maWcgfSBmcm9tICd2aXRlJ1xuaW1wb3J0IHZ1ZSBmcm9tICdAdml0ZWpzL3BsdWdpbi12dWUnXG5pbXBvcnQgcGF0aCBmcm9tICdwYXRoJ1xuaW1wb3J0IGZyYXBwZXVpIGZyb20gJ2ZyYXBwZS11aS92aXRlJ1xuXG4vLyBodHRwczovL3ZpdGVqcy5kZXYvY29uZmlnL1xuZXhwb3J0IGRlZmF1bHQgZGVmaW5lQ29uZmlnKHtcbiAgcGx1Z2luczogW1xuICAgIGZyYXBwZXVpKHtcbiAgICAgIGZyYXBwZVByb3h5OiB0cnVlLFxuICAgICAgbHVjaWRlSWNvbnM6IHRydWUsXG4gICAgICBqaW5qYUJvb3REYXRhOiB0cnVlLFxuICAgICAgYnVpbGRDb25maWc6IHtcbiAgICAgICAgaW5kZXhIdG1sUGF0aDogJy4uL2VycG5leHRfbXJwL3d3dy9lcnBuZXh0X21ycC5odG1sJyxcbiAgICAgICAgZW1wdHlPdXREaXI6IHRydWUsXG4gICAgICAgIHNvdXJjZW1hcDogdHJ1ZSxcbiAgICAgIH0sXG4gICAgfSksXG4gICAgdnVlKClcbiAgXSxcbiAgcmVzb2x2ZToge1xuICAgIGFsaWFzOiB7XG4gICAgICAnQCc6IHBhdGgucmVzb2x2ZShfX2Rpcm5hbWUsICdzcmMnKSxcbiAgICAgICd2dWUnOiAndnVlL2Rpc3QvdnVlLmVzbS1idW5kbGVyLmpzJywgLy8gQWRkIHRoaXMgbGluZVxuICAgIH0sXG4gIH0sXG4gIG9wdGltaXplRGVwczoge1xuICAgIGluY2x1ZGU6IFtcbiAgICAgICdmZWF0aGVyLWljb25zJyxcbiAgICAgICdzaG93ZG93bicsXG4gICAgICAndGFpbHdpbmQuY29uZmlnLmpzJyxcbiAgICAgICdwcm9zZW1pcnJvci1zdGF0ZScsXG4gICAgICAncHJvc2VtaXJyb3ItdmlldycsXG4gICAgICAnbG93bGlnaHQnLFxuICAgIF0sXG4gIH0sXG59KVxuIl0sCiAgIm1hcHBpbmdzIjogIjtBQUFxWCxTQUFTLG9CQUFvQjtBQUNsWixPQUFPLFNBQVM7QUFDaEIsT0FBTyxVQUFVO0FBQ2pCLE9BQU8sY0FBYztBQUhyQixJQUFNLG1DQUFtQztBQU16QyxJQUFPLHNCQUFRLGFBQWE7QUFBQSxFQUMxQixTQUFTO0FBQUEsSUFDUCxTQUFTO0FBQUEsTUFDUCxhQUFhO0FBQUEsTUFDYixhQUFhO0FBQUEsTUFDYixlQUFlO0FBQUEsTUFDZixhQUFhO0FBQUEsUUFDWCxlQUFlO0FBQUEsUUFDZixhQUFhO0FBQUEsUUFDYixXQUFXO0FBQUEsTUFDYjtBQUFBLElBQ0YsQ0FBQztBQUFBLElBQ0QsSUFBSTtBQUFBLEVBQ047QUFBQSxFQUNBLFNBQVM7QUFBQSxJQUNQLE9BQU87QUFBQSxNQUNMLEtBQUssS0FBSyxRQUFRLGtDQUFXLEtBQUs7QUFBQSxNQUNsQyxPQUFPO0FBQUE7QUFBQSxJQUNUO0FBQUEsRUFDRjtBQUFBLEVBQ0EsY0FBYztBQUFBLElBQ1osU0FBUztBQUFBLE1BQ1A7QUFBQSxNQUNBO0FBQUEsTUFDQTtBQUFBLE1BQ0E7QUFBQSxNQUNBO0FBQUEsTUFDQTtBQUFBLElBQ0Y7QUFBQSxFQUNGO0FBQ0YsQ0FBQzsiLAogICJuYW1lcyI6IFtdCn0K
