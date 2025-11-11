import frappe


def execute():
	"""
	Set MRP Settings > item_lead_time_field to a default
	Set MRP Settings > po_item_delivery_date_field to a default
	"""
	mrp_settings = frappe.get_single("MRP Settings")
	mrp_settings.item_lead_time_field = "lead_time_days | Lead Time in days"
	mrp_settings.po_item_delivery_date_field = "schedule_date | Required By"
	mrp_settings.save()
