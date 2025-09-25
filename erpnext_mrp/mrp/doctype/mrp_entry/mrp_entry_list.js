// Copyright (c) 2025, Finfoot Tech (Pty) Ltd and contributors
// For license information, please see license.txt

frappe.listview_settings["MRP Entry"] = {
    onload: function (listview) {
        listview.page.add_inner_button(
            __("Get master list of items"),
            () => {
                frappe.call({
                    method: "erpnext_mrp.mrp.tasks.mrp_run.update_mrp_item_entries",
                    freeze: true,
                    args: {},
                    callback: function(r) {
                        frappe.show_alert(__('Pre-process completed'));
                    }
                });
            },
            __("Actions")
        );
    }
    }
