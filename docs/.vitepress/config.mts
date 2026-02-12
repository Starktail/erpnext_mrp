import { defineConfig } from 'vitepress'

// https://vitepress.dev/reference/site-config
export default defineConfig({
  title: "MRP Tools for ERPNext Documentation",
  description: "MRP Tools for ERPNext Documentation",
  outDir: '../erpnext_mrp/www',
  assetsDir: 'assets/erpnext_mrp',
  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    nav: [
      { text: 'Desk', link: '/' },
      { text: 'Documentation Home', link: '/erpnext_mrp_introduction' },
      { text: 'Starktail', link: 'https://starktail.com' }
    ],

    sidebar: [
      { text: 'Introduction', link: '/erpnext_mrp_introduction' },
      { text: 'MRP Calculations', link: '/erpnext_mrp_run' },
      { text: 'MRP Workbench', link: '/erpnext_mrp_workbench' },
    ],

    socialLinks: [
      { icon: 'mailgun', link: 'mailto:support@starktail.com'},
      { icon: 'github', link: 'https://github.com/Starktail/erpnext_mrp' }
    ],

    editLink: {
      pattern: 'https://github.com/Starktail/erpnext_mrp/edit/version-15/docs/:path'
    }
  },
  // Set metaChunk to avoid having window.__VP_HASH_MAP__ in the generated HTML, 
  // as this blocks jinja template rendering for frappe portal pages
  metaChunk: true,
  ignoreDeadLinks: [
    // ignore all links starting with /app/ (these point to doctypes or other resources
    //  hosted on the frappe site, and won't be alive at build time)
    /^\/app\//
  ],
  // Links that point to pages outside our vitepress docs, like Doctype links should not
  // be appended with .html
  transformHtml: (code) => {
    return code.replace(/href="(\/app\/[^"]*)\.html"/g, 'href="$1"');
  },
  // Vite config
  vite: {
    build: {
      // Inline ALL images to avoid having images in the public directory
      assetsInlineLimit: 52428800, // 50 MB,
      chunkSizeWarningLimit: 2000, // 2000 KB
      // Don't clear out www, as we have files there for /frontend
      emptyOutDir: false
    },
  },
})