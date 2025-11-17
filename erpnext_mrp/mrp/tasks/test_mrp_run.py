import datetime
import json
import os
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date

from erpnext_mrp.mrp.tasks.mrp_run import create_mrp_item_entries, process_mrp_item_entries

test_data_file_items = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "test_mrp_data_items.json")
test_data_file_boms = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "test_mrp_data_boms.json")
test_data_file_forecast = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "test_mrp_data_forecast.json")


@patch("erpnext_mrp.mrp.tasks.mrp_run.date")
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

		mrp_settings.look_ahead = 11
		mrp_settings.periods_type = "Calendar Week"
		mrp_settings.requirement_based_on = "Open Orders + Forecast"
		mrp_settings.item_lead_time_field = "lead_time_days | Lead Time in days"
		mrp_settings.save()
		self.mrp_settings = mrp_settings

	def tearDown(self):
		if frappe.db.exists("Custom Field", "Item-custom_additional_lead_time"):
			frappe.delete_doc("Custom Field", "Item-custom_additional_lead_time", force=True)
		super().tearDown()

	def test_create_mrp_item_entries(self, mock_date):
		"""
		Test that MRP Entry records are created successfully
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Create an MRP Forecast for ~70 days (compound lead time for our test item) from now
		mrp_forecast = {
			"item_code": "SR04820",
			"forecast_date": add_days(test_start_day, 70),
			"forecast_quantity": 1,
		}
		create_mrp_forecast(mrp_forecast)

		create_mrp_item_entries()

		# Assert that MRP Entries are created for all items.
		all_mrp_entries = frappe.get_all(
			"MRP Entry",
			fields=["name", "item_code", "target_date", "is_manufactured"],
			order_by="target_date asc",
		)

		# Expect 10 items as per erpnext_mrp/tests/test_mrp_data_items.json
		unique_items = set([entry.item_code for entry in all_mrp_entries])
		self.assertEqual(len(unique_items), 10)

		# Expect 110 MRP Entry records (10 items x 11 weeks look-ahead)
		self.assertEqual(len(all_mrp_entries), 110)

		# Expect first MRP Entry record should be for current calendar week, in format [item]-[year]CW[calendar week], e.g. AAA-2025CW02
		calendar_date = test_start_day.isocalendar()
		expected_cw_string = str(calendar_date.week).zfill(2)
		self.assertEqual(
			all_mrp_entries[0].name,
			f"{all_mrp_entries[0].item_code}-{calendar_date.year}CW{expected_cw_string}",
		)

		# Expect last MRP Entry records should be for current calendar week + 70 days
		last_date = add_to_date(test_start_day, days=70)
		calendar_date = last_date.isocalendar()
		expected_cw_string = str(calendar_date.week).zfill(2)
		self.assertEqual(
			all_mrp_entries[-1].name,
			f"{all_mrp_entries[-1].item_code}-{calendar_date.year}CW{expected_cw_string}",
		)

		# Expect is_manufactured to be 1 for items with BOM's (assemblies and sub-assemblies), and 0 for items without
		# As per erpnext_mrp/tests/test_mrp_data_boms.json, SRZ00967, SRZ00963 and SR04820 have BOM's
		bom_items = ["SRZ00967", "SRZ00963", "SR04820"]
		for item in bom_items:
			is_manufactured = [entry.is_manufactured for entry in all_mrp_entries if entry.item_code == item]
			self.assertListEqual(is_manufactured, [1] * 11)  # 11 records because that is our weeks look-ahead setting
		# The rest should have is_manufactured = 0
		is_manufactured = [entry.is_manufactured for entry in all_mrp_entries if entry.item_code not in bom_items]
		self.assertFalse(any(is_manufactured))

	# Gantt chart of test BOM with lead times

	# Items
	# SR04820 - MRP Test Sales Item (Assembly) |                                                        [===== 14 =====]
	#   SRZ00960 - MRP Test BOM Item 1         |                          [============= 28 =============]
	#   SRZ00961 - MRP Test BOM Item 2         |                                               [=== 7 ===]
	#   SRZ00962 - MRP Test BOM Item 3         |                                                     [=3=]
	#   SRZ00963 - MRP Test Sub-Assembly       |                                   [========= 21 ========]
	#     SRZ00964 - MRP Test SA BOM Item 1    |                            [-- 7 --]
	#     SRZ00966 - MRP Test SA BOM Item 3    |       [------------ 28 ------------]
	#     SRZ00967 - MRP Test Sub-Sub-Assembly |                            [-- 7 --]
	#       SRZ00968 - MRP Test SSA BOM Item 1 |[oooooooooooo 28 oooooooooooo]
	#       SRZ00960 - MRP Test BOM Item 1     |[oooooooooooo 28 oooooooooooo]
	#     SRZ00965 - MRP Test SA BOM Item 2    |                   [------ 14 ------]
	#                                          |+----+----+----+----+----+----+----+----+----+----+----+----+----+----+----|
	#                                           0    5   10   15   20   25   30   35   40   45   50   55   60   65   70   75
	#                                                            Start on Day

	def test_process_mrp_item_entries_have_correct_upstream_forecast(self, mock_date):
		"""
		Test that MRP Entry records have correct upstream forecast
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Create an MRP Forecast for ~70 days (compound lead time for our test item) from now
		final_item_forecast_date = add_to_date(test_start_day, days=70)
		mrp_forecast = {
			"item_code": "SR04820",
			"forecast_date": final_item_forecast_date,
			"forecast_quantity": 1,
		}
		create_mrp_forecast(mrp_forecast)
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Expect a forecast demand for the "SR04820 - MRP Test Sales Item (Assembly)" in the correct period
		mrp_entry = get_mrp_entry_by_item_week("SR04820", final_item_forecast_date)
		self.assertEqual(mrp_entry.forecast_demand, 1)

		# ==============================================================================================================
		# Validate items that are consumed by "SR04820 - MRP Test Sales Item (Assembly)"
		# This manufactured item has a lead time of 14 days, as per erpnext_mrp/tests/test_mrp_data_items.json

		# Meaning, forecast for the sub-items below should be 14 days before the forecast date for the final item
		# ==============================================================================================================
		forecast_date = add_to_date(final_item_forecast_date, days=-14)

		# Expect an upstream forecast demand for "SRZ00963 - MRP Test Sub-Assembly"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00963", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream forecast demand for "SRZ00962 - MRP Test BOM Item 3"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00962", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 10)  # Qty of 10, as per BOM

		# Expect an upstream forecast demand for "SRZ00961 - MRP Test BOM Item 2"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00961", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 4)  # Qty of 4, as per BOM

		# Expect an upstream forecast demand for "SRZ00960 - MRP Test BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00960", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 1)  # Qty of 1, as per BOM
		# ==============================================================================================================

		# ==============================================================================================================
		# Validate items that are consumed by "SRZ00963 - MRP Test Sub-Assembly"
		# This manufactured item has a lead time of 21 days, as per erpnext_mrp/tests/test_mrp_data_items.json

		# Meaning, forecast for the sub-items below should be 21 + 14 days before the forecast date for the final item
		# ==============================================================================================================
		forecast_date = add_to_date(final_item_forecast_date, days=-35)

		# Expect an upstream forecast demand for "SRZ00967 - MRP Test Sub-Sub-Assembly"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00967", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream forecast demand for "SRZ00964 - MRP Test SA BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00964", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 2)  # Qty of 2, as per BOM

		# Expect an upstream forecast demand for "SRZ00966 - MRP Test SA BOM Item 3"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00966", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 2)  # Qty of 2, as per BOM

		# Expect an upstream forecast demand for "SRZ00965 - MRP Test SA BOM Item 2"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00965", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 2)  # Qty of 2, as per BOM
		# ==============================================================================================================

		# ==============================================================================================================
		# Validate items that are consumed by "SRZ00967 - MRP Test Sub-Sub-Assembly"
		# This manufactured item has a lead time of 7 days, as per erpnext_mrp/tests/test_mrp_data_items.json

		# Meaning, forecast for the sub-items below should be 7 + 21 + 14 days before the forecast date for the final item
		# ==============================================================================================================
		forecast_date = add_to_date(final_item_forecast_date, days=-42)

		# Expect an upstream forecast demand for "SRZ00968 - MRP Test SSA BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00968", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream forecast demand for "SRZ00960 - MRP Test BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00960", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 4)  # Qty of 4, as per BOM
		# ==============================================================================================================

	def test_process_mrp_item_entries_with_additional_lead_time(self, mock_date):
		"""
		Test that MRP Entry records have correct upstream forecast when using an additional lead time field
		"""
		# Create a custom field to use as additional lead time
		if not frappe.db.exists("Custom Field", "Item-custom_additional_lead_time"):
			frappe.get_doc(
				{
					"doctype": "Custom Field",
					"dt": "Item",
					"fieldname": "custom_additional_lead_time",
					"label": "Custom Additional Lead Time",
					"fieldtype": "Int",
					"insert_after": "lead_time_days",
				}
			).insert()

		# Update a few items with values for the custom field
		# Original lead_time_days is 14. Total is now 15.
		frappe.db.set_value("Item", "SR04820", "custom_additional_lead_time", 1)
		# Original lead_time_days is 21. Total is now 23.
		frappe.db.set_value("Item", "SRZ00963", "custom_additional_lead_time", 2)
		# Original lead_time_days is 7. Total is now 10.
		frappe.db.set_value("Item", "SRZ00967", "custom_additional_lead_time", 3)

		# Update MRP Settings to use the custom field
		self.mrp_settings.item_additional_lead_time_field = "custom_additional_lead_time | Custom Additional Lead Time"
		self.mrp_settings.save()

		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Create an MRP Forecast for ~70 days (compound lead time for our test item) from now
		final_item_forecast_date = add_to_date(test_start_day, days=70)
		mrp_forecast = {
			"item_code": "SR04820",
			"forecast_date": final_item_forecast_date,
			"forecast_quantity": 1,
		}
		create_mrp_forecast(mrp_forecast)
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Expect a forecast demand for the "SR04820 - MRP Test Sales Item (Assembly)" in the correct period
		mrp_entry = get_mrp_entry_by_item_week("SR04820", final_item_forecast_date)
		self.assertEqual(mrp_entry.forecast_demand, 1)

		# ==============================================================================================================
		# Validate items that are consumed by "SR04820 - MRP Test Sales Item (Assembly)"
		# This manufactured item has a lead time of 14 + 1 = 15 days
		# ==============================================================================================================
		forecast_date = add_to_date(final_item_forecast_date, days=-15)

		# Expect an upstream forecast demand for "SRZ00963 - MRP Test Sub-Assembly"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00963", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream forecast demand for "SRZ00962 - MRP Test BOM Item 3"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00962", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 10)  # Qty of 10, as per BOM

		# Expect an upstream forecast demand for "SRZ00961 - MRP Test BOM Item 2"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00961", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 4)  # Qty of 4, as per BOM

		# Expect an upstream forecast demand for "SRZ00960 - MRP Test BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00960", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 1)  # Qty of 1, as per BOM
		# ==============================================================================================================

		# ==============================================================================================================
		# Validate items that are consumed by "SRZ00963 - MRP Test Sub-Assembly"
		# This manufactured item has a lead time of 21 + 2 = 23 days
		# Meaning, forecast for the sub-items below should be 23 + 15 days before the forecast date for the final item
		# ==============================================================================================================
		forecast_date = add_to_date(final_item_forecast_date, days=-(15 + 23))

		# Expect an upstream forecast demand for "SRZ00967 - MRP Test Sub-Sub-Assembly"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00967", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream forecast demand for "SRZ00964 - MRP Test SA BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00964", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 2)  # Qty of 2, as per BOM

		# Expect an upstream forecast demand for "SRZ00966 - MRP Test SA BOM Item 3"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00966", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 2)  # Qty of 2, as per BOM

		# Expect an upstream forecast demand for "SRZ00965 - MRP Test SA BOM Item 2"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00965", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 2)  # Qty of 2, as per BOM
		# ==============================================================================================================

		# ==============================================================================================================
		# Validate items that are consumed by "SRZ00967 - MRP Test Sub-Sub-Assembly"
		# This manufactured item has a lead time of 7 + 3 = 10 days
		# Meaning, forecast for the sub-items below should be 10 + 23 + 15 days before the forecast date for the final item
		# ==============================================================================================================
		forecast_date = add_to_date(final_item_forecast_date, days=-(15 + 23 + 10))

		# Expect an upstream forecast demand for "SRZ00968 - MRP Test SSA BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00968", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream forecast demand for "SRZ00960 - MRP Test BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00960", forecast_date)
		self.assertEqual(mrp_entry.upstream_forecast_demand, 4)  # Qty of 4, as per BOM
		# ==============================================================================================================

	def test_process_mrp_item_entries_have_correct_upstream_sales_order_demand(self, mock_date):
		"""
		Test that MRP Entry records have correct upstream Sales Order-based demand
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Create Sales Order due ~70 days (compound lead time for our test item) from now
		final_item_so_date = add_to_date(test_start_day, days=70)
		create_sales_order(item_code="SR04820", qty=1, delivery_date=final_item_so_date)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Expect a Reserved Qty value for the "SR04820 - MRP Test Sales Item (Assembly)" in the correct period
		mrp_entry = get_mrp_entry_by_item_week("SR04820", final_item_so_date)
		self.assertEqual(mrp_entry.reserved_qty, 1)

		# ==============================================================================================================
		# Validate items that are consumed by "SR04820 - MRP Test Sales Item (Assembly)"
		# This manufactured item has a lead time of 14 days, as per erpnext_mrp/tests/test_mrp_data_items.json

		# Meaning, forecast for the sub-items below should be 14 days before the forecast date for the final item
		# ==============================================================================================================
		so_demand_date = add_to_date(final_item_so_date, days=-14)

		# Expect an upstream forecast demand for "SRZ00963 - MRP Test Sub-Assembly"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00963", so_demand_date)
		self.assertEqual(mrp_entry.upstream_so_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream forecast demand for "SRZ00962 - MRP Test BOM Item 3"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00962", so_demand_date)
		self.assertEqual(mrp_entry.upstream_so_demand, 10)  # Qty of 10, as per BOM

		# Expect an upstream forecast demand for "SRZ00961 - MRP Test BOM Item 2"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00961", so_demand_date)
		self.assertEqual(mrp_entry.upstream_so_demand, 4)  # Qty of 4, as per BOM

		# Expect an upstream forecast demand for "SRZ00960 - MRP Test BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00960", so_demand_date)
		self.assertEqual(mrp_entry.upstream_so_demand, 1)  # Qty of 1, as per BOM
		# ==============================================================================================================

		# ==============================================================================================================
		# Validate items that are consumed by "SRZ00963 - MRP Test Sub-Assembly"
		# This manufactured item has a lead time of 21 days, as per erpnext_mrp/tests/test_mrp_data_items.json

		# Meaning, forecast for the sub-items below should be 21 + 14 days before the forecast date for the final item
		# ==============================================================================================================
		so_demand_date = add_to_date(final_item_so_date, days=-35)

		# Expect an upstream forecast demand for "SRZ00967 - MRP Test Sub-Sub-Assembly"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00967", so_demand_date)
		self.assertEqual(mrp_entry.upstream_so_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream forecast demand for "SRZ00964 - MRP Test SA BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00964", so_demand_date)
		self.assertEqual(mrp_entry.upstream_so_demand, 2)  # Qty of 2, as per BOM

		# Expect an upstream forecast demand for "SRZ00966 - MRP Test SA BOM Item 3"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00966", so_demand_date)
		self.assertEqual(mrp_entry.upstream_so_demand, 2)  # Qty of 2, as per BOM

		# Expect an upstream forecast demand for "SRZ00965 - MRP Test SA BOM Item 2"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00965", so_demand_date)
		self.assertEqual(mrp_entry.upstream_so_demand, 2)  # Qty of 2, as per BOM
		# ==============================================================================================================

		# ==============================================================================================================
		# Validate items that are consumed by "SRZ00967 - MRP Test Sub-Sub-Assembly"
		# This manufactured item has a lead time of 7 days, as per erpnext_mrp/tests/test_mrp_data_items.json

		# Meaning, forecast for the sub-items below should be 7 + 21 + 14 days before the forecast date for the final item
		# ==============================================================================================================
		so_demand_date = add_to_date(final_item_so_date, days=-42)

		# Expect an upstream forecast demand for "SRZ00968 - MRP Test SSA BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00968", so_demand_date)
		self.assertEqual(mrp_entry.upstream_so_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream forecast demand for "SRZ00960 - MRP Test BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00960", so_demand_date)
		self.assertEqual(mrp_entry.upstream_so_demand, 4)  # Qty of 4, as per BOM
		# ==============================================================================================================


def get_mrp_entry_by_item_week(item_code: str, demand_date: datetime.datetime):
	isodate = demand_date.isocalendar()
	week_string = str(isodate.week).zfill(2)
	mrp_entry_name = f"{item_code}-{isodate.year}CW{week_string}"
	return frappe.get_doc("MRP Entry", mrp_entry_name)


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
			{"default_warehouse": "_Test Warehouse - _TC", "company": "_Test Company"},
		)
		item.save()
	else:
		item = frappe.get_doc("Item", item_code)
	return item


def make_bom(item: str, raw_materials: list):
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


def create_mrp_forecast(mrp_forecast: dict):
	mrp_forecast["doctype"] = "MRP Forecast"
	forecast = frappe.get_doc(mrp_forecast)
	forecast.insert(ignore_permissions=True)
	return forecast


def create_sales_order(item_code: str, qty: int, delivery_date: datetime.datetime):
	so = frappe.new_doc("Sales Order")
	so.set_warehouse = ""
	so.company = "_Test Company"
	so.customer = "_Test Customer"
	so.currency = "ZAR"
	so.po_no = ""
	so.append(
		"items",
		{
			"item_code": item_code,
			"warehouse": "_Test Warehouse - _TC",
			"qty": qty,
			# "uom": None,
			# "price_list_rate": args.price_list_rate or None,
			# "discount_percentage": args.discount_percentage or None,
			"rate": 10,
		},
	)

	so.delivery_date = delivery_date

	so.insert()
	so.submit()

	return so
