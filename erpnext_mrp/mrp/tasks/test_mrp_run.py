import os
import json
from typing import Dict, List

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today, add_days, get_datetime, add_to_date

from erpnext_mrp.mrp.tasks.mrp_run import (
	create_mrp_item_entries,
	process_mrp_item_entries
)

test_data_file_items = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "test_mrp_data_items.json")
test_data_file_boms = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "test_mrp_data_boms.json")
test_data_file_forecast = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "test_mrp_data_forecast.json")

class TestMRPRun(FrappeTestCase):
	"""
	Integration tests for mrp_run(), using test_mrp_data.json as mock data.
	"""

	def setUp(self):
		super().setUp()
		# Clear any existing records
		frappe.db.delete("MRP Entry")
		frappe.db.delete("BOM")
		frappe.db.delete("Item")
		frappe.db.delete("MRP Forecast")
		frappe.db.delete("Sales Order")
		frappe.db.delete("Purchase Order")
		frappe.db.delete("Work Order")

		# Load and create test items
		with open(test_data_file_items) as f:
			test_data_items = json.load(f)
			for item in test_data_items:
				create_item(**item)

		# Load and create test BOMs
		with open(test_data_file_boms) as f:
			test_data_boms = json.load(f)
			for bom in test_data_boms:
				make_bom(**bom)

		# # Load and create test MRP Forecast records
		# with open(test_data_file_forecast) as f:
		# 	test_data_forecasts = json.load(f)
		# 	for fc in test_data_forecasts:
		# 		create_mrp_forecast(fc)

		# Set up MRP Settings
		if not frappe.db.exists("MRP Settings", "MRP Settings"):
			mrp_settings = frappe.new_doc("MRP Settings")
		else:
			mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")

		mrp_settings.look_ahead = 8
		mrp_settings.periods_type = "Calendar Week"
		mrp_settings.requirement_based_on = "Open Orders + Forecast"
		mrp_settings.save()
		self.mrp_settings = mrp_settings

	def test_create_mrp_item_entries(self):
		"""
		Test that MRP Entry records are created successfully
		"""

		# Create an MRP Forecast for ~52 days (compound lead time for our test item) from now
		mrp_forecast =  {
			"item_code": "SR04820",
			"forecast_date": add_days(today(), 52),
			"forecast_quantity": 1
			}
		create_mrp_forecast(mrp_forecast)

		create_mrp_item_entries()
		
		# Assert that MRP Entries are created for all items. 
		all_mrp_entries = frappe.get_all("MRP Entry", fields=["name", "item_code", "target_date", "is_manufactured"], order_by="target_date asc")

		# Expect 10 items as per erpnext_mrp/tests/test_mrp_data_items.json
		unique_items = set([entry.item_code for entry in all_mrp_entries])
		self.assertEquals(len(unique_items), 10)

		# Expect 80 MRP Entry records (10 items x 8 weeks look-ahead)
		self.assertEquals(len(all_mrp_entries), 80)

		# Expect first MRP Entry record should be for current calendar week, in format [item]-[year]CW[calendar week], e.g. AAA-2025CW02
		calendar_date = get_datetime().isocalendar()
		expected_cw_string = str(calendar_date.week).zfill(2)
		self.assertEquals(all_mrp_entries[0].name, f"{all_mrp_entries[0].item_code}-{calendar_date.year}CW{expected_cw_string}")

		# Expect last MRP Entry records should be for current calendar week + 8 weeks
		last_date = add_to_date(get_datetime(), days=52)
		calendar_date = last_date.isocalendar()
		expected_cw_string = str(calendar_date.week).zfill(2)
		self.assertEquals(all_mrp_entries[-1].name, f"{all_mrp_entries[-1].item_code}-{calendar_date.year}CW{expected_cw_string}")

		# Expect is_manufactured to be 1 for items with BOM's (assemblies and sub-assemblies), and 0 for items without
		# As per erpnext_mrp/tests/test_mrp_data_boms.json, SRZ00967, SRZ00963 and SR04820 have BOM's
		bom_items = ["SRZ00967", "SRZ00963", "SR04820"]
		for item in bom_items:
			is_manufactured = [entry.is_manufactured for entry in all_mrp_entries if entry.item_code == item]
			self.assertListEqual(is_manufactured, [1] * 8) # 8 records because that is our weeks look-ahead setting
		# The rest should have is_manufactured = 0
		is_manufactured = [entry.is_manufactured for entry in all_mrp_entries if entry.item_code not in bom_items]
		self.assertFalse(any(is_manufactured))


	def test_process_mrp_item_entries(self):
		"""
		Test that MRP Entry records are processed correctly
		"""

		# Create an MRP Forecast for ~52 days (compound lead time for our test item) from now
		forecast_date = add_to_date(get_datetime(), days=52)
		mrp_forecast =  {
			"item_code": "SR04820",
			"forecast_date": forecast_date,
			"forecast_quantity": 1
			}
		create_mrp_forecast(mrp_forecast)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)
		frappe.db.commit()

		all_mrp_entries = frappe.get_all("MRP Entry", fields=["name", "item_code", "target_date"], order_by="target_date asc")

		# Expect a forecast demand for the parent item that we created an MRP Forecast for
		relevant_mrp_entry_name = next(entry for entry in all_mrp_entries if entry.name == f"SR04820-{forecast_date.year}CW{forecast_date.isocalendar().week}").name
		relevant_mrp_entry = frappe.get_doc("MRP Entry", relevant_mrp_entry_name)
		self.assertEquals(relevant_mrp_entry.forecast_demand, 1)


def create_item(
	item_code: str,
	item_name: str,
	item_group: str,
	lead_time_days: int,
	opening_stock: int = 0,
):
	if not frappe.db.exists("Item", item_code):
		item = frappe.new_doc("Item")
		item.item_code = item_code
		item.item_name = item_name
		item.description = item_name
		item.item_group = item_group
		item.stock_uom = "Nos"
		item.is_stock_item = 1
		item.opening_stock = opening_stock
		item.valuation_rate = 10
		item.lead_time_days = lead_time_days
		item.append(
			"item_defaults",
			{
				"default_warehouse": "_Test Warehouse - _TC",
				"company": "_Test Company"
			},
		)
		item.save()
	else:
		item = frappe.get_doc("Item", item_code)
	return item


def make_bom(item: str, raw_materials: List):
	bom = frappe.get_doc(
		{
			"doctype": "BOM",
			"is_default": 1,
			"item": item,
			"currency": "ZAR",
			"quantity": 1,
			"company": "_Test Company",
			"with_operations": 0,
		}
	)

	for material in raw_materials:
		item_doc = frappe.get_doc("Item", material.get("item_code"))
		bom.append(
			"items",
			{
				"item_code": material.get("item_code"),
				"qty": material.get("qty") or 1.0,
				"uom": item_doc.stock_uom,
				"stock_uom": item_doc.stock_uom,
				"rate": item_doc.valuation_rate,
				# "source_warehouse": args.source_warehouse,
			},
		)

	bom.insert(ignore_permissions=True)

	bom.submit()

	return bom

def create_mrp_forecast(mrp_forecast: Dict):
	mrp_forecast["doctype"] = "MRP Forecast"
	forecast = frappe.get_doc(mrp_forecast)
	forecast.insert(ignore_permissions=True)
	return forecast

