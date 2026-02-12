// Copyright (c) 2025, Finfoot Tech (Pty) Ltd and contributors
// For license information, please see license.txt

frappe.listview_settings["MRP Entry"] = {
  onload: function (listview) {
    listview.page.add_inner_button(
      __("Run MRP Processing"),
      () => {
        frappe.call({
          method: "erpnext_mrp.mrp.tasks.mrp_run.mrp_run",
          freeze: true,
          args: {
            enqueue: false,
          },
          callback: function (r) {
            frappe.show_alert(__("Processing completed"));
          },
        });
      },
      __("Actions"),
    );
  },
};
