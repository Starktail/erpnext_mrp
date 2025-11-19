// Copyright (c) 2025, Finfoot Tech (Pty) Ltd and contributors
// For license information, please see license.txt

frappe.ui.form.on("MRP Settings", {
	refresh(frm) {
		// Set the Options for item_lead_time_field field
		frappe.call({
			method: "get_docfields",
			doc: frm.doc,
			args: {
				doctype: "Item",
				field_type: "Int",
			},
			callback: function (r) {
				// Sort the array of objects alphabetically by the label property
				r.message.sort((a, b) => {
					const labelA = a.label || "";
					const labelB = b.label || "";
					return labelA.localeCompare(labelB);
				});

				// Use map to create an array of strings in the desired format
				const formattedStrings = r.message.map((fields) => `${fields.fieldname} | ${fields.label}`);

				// Join the strings with newline characters to create the final string
				const options = "\n" + formattedStrings.join("\n");

				// Set the Options property
				frm.set_df_property("item_lead_time_field", "options", options);
				frm.refresh_field("item_lead_time_field");
			},
		});

		// Set the Options for item_additional_lead_time_field field
		frappe.call({
			method: "get_docfields",
			doc: frm.doc,
			args: {
				doctype: "Item",
			},
			callback: function (r) {
				// Sort the array of objects alphabetically by the label property
				r.message.sort((a, b) => {
					const labelA = a.label || "";
					const labelB = b.label || "";
					return labelA.localeCompare(labelB);
				});

				// Use map to create an array of strings in the desired format
				const formattedStrings = r.message.map((fields) => `${fields.fieldname} | ${fields.label}`);

				// Join the strings with newline characters to create the final string
				const options = "\n" + formattedStrings.join("\n");

				// Set the Options property
				frm.set_df_property("item_additional_lead_time_field", "options", options);
				frm.refresh_field("item_additional_lead_time_field");
			},
		});

		// Set the Options for the po_item_delivery_date_field field
		frappe.call({
			method: "get_docfields",
			doc: frm.doc,
			args: {
				doctype: "Purchase Order Item",
				field_type: "Date",
				mandatory_fields_only: true,
			},
			callback: function (r) {
				// Sort the array of objects alphabetically by the label property
				r.message.sort((a, b) => {
					const labelA = a.label || "";
					const labelB = b.label || "";
					return labelA.localeCompare(labelB);
				});

				// Use map to create an array of strings in the desired format
				const formattedStrings = r.message.map((fields) => `${fields.fieldname} | ${fields.label}`);

				// Join the strings with newline characters to create the final string
				const options = "\n" + formattedStrings.join("\n");

				// Set the Options property
				frm.set_df_property("po_item_delivery_date_field", "options", options);
				frm.refresh_field("po_item_delivery_date_field");
			},
		});
	},
});
