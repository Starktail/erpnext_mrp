import frappe


def execute():
	"""
	Set MRP Settings > item_lead_time_field to a default
	"""
	mrp_settings = frappe.get_single("MRP Settings")
	mrp_settings.item_lead_time_field = "lead_time_days | Lead Time in days"
	mrp_settings.save()
