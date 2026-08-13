import datetime
import json
import os
from unittest.mock import patch

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date

from erpnext_mrp.mrp.tasks import mrp_run as mrp_run_module
from erpnext_mrp.mrp.tasks.mrp_run import (
	_NO_REORDER_SENTINEL,
	create_mrp_item_entries,
	get_forecast_coverage_status,
	process_mrp_item_entries,
)

test_data_file_items = os.path.join(
	os.path.dirname(__file__), "..", "..", "tests", "test_mrp_data_items.json"
)
test_data_file_boms = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "test_mrp_data_boms.json")
test_data_file_forecast = os.path.join(
	os.path.dirname(__file__), "..", "..", "tests", "test_mrp_data_forecast.json"
)


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
		frappe.db.delete("Item Default")
		frappe.db.delete("UOM Conversion Detail")
		frappe.db.delete("MRP Forecast")
		frappe.db.delete("Sales Order")
		frappe.db.delete("Purchase Order")
		frappe.db.delete("Work Order")
		frappe.db.delete("Item Price")
		frappe.db.delete("Stock Entry")
		frappe.db.delete("Stock Ledger Entry")

		# Load and create test items
		with open(test_data_file_items) as f:  # nosemgrep
			test_data_items = json.load(f)
			for item in test_data_items:
				create_item(**item)

		# Load and create test BOMs
		with open(test_data_file_boms) as f:  # nosemgrep
			test_data_boms = json.load(f)
			for bom in test_data_boms:
				make_bom(**bom)

		# Load and create test MRP Forecast records
		with open(test_data_file_forecast) as f:  # nosemgrep
			test_data_forecasts = json.load(f)
			for fc in test_data_forecasts:
				create_mrp_forecast(fc)

		# Set up MRP Settings
		if not frappe.db.exists("MRP Settings", "MRP Settings"):
			mrp_settings = frappe.new_doc("MRP Settings")
		else:
			mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")

		mrp_settings.look_ahead = 11
		mrp_settings.periods_type = "Calendar Week"
		mrp_settings.requirement_based_on = "Open Orders + Forecast"
		mrp_settings.item_lead_time_field = "lead_time_days | Lead Time in days"
		mrp_settings.item_additional_lead_time_field = ""
		mrp_settings.save()
		self.mrp_settings = mrp_settings

		# Create Payment Terms
		create_payment_terms_templates()

		# Create custom field for additional shipping time on Item
		create_custom_field(
			"Item",
			dict(fieldname="additional_shipping_days", label="Additional Shipping Days", fieldtype="Data"),
		)

		self._original_buying_price_list = frappe.db.get_single_value("Buying Settings", "buying_price_list")
		frappe.db.set_single_value("Buying Settings", "buying_price_list", "Standard Buying")

	def tearDown(self):
		if frappe.db.exists("Custom Field", "Item-custom_additional_lead_time"):
			frappe.delete_doc("Custom Field", "Item-custom_additional_lead_time", force=True)

		# Reset MRP Settings item_condition
		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.item_condition = ""
		mrp_settings.save()

		frappe.db.set_single_value(
			"Buying Settings", "buying_price_list", self._original_buying_price_list or ""
		)

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
			fields=["name", "item_code", "target_date", "bom_list", "is_manufactured"],
			order_by="target_date asc",
		)

		# Expect 12 items as per erpnext_mrp/tests/test_mrp_data_items.json
		unique_items = set([entry.item_code for entry in all_mrp_entries])
		self.assertEqual(len(unique_items), 12)

		# Expect 121 MRP Entry records (12 items x 11 weeks look-ahead)
		self.assertEqual(len(all_mrp_entries), 132)

		# Expect first MRP Entry record should be for current calendar week, in format [item]-[year]CW[calendar week], e.g. AAA-2025CW02
		calendar_date = test_start_day.isocalendar()
		expected_cw_string = str(calendar_date.week).zfill(2)
		self.assertEqual(
			all_mrp_entries[0].name,
			f"{all_mrp_entries[0].item_code}-{calendar_date.year}CW{expected_cw_string}",
		)
		# Expect first MRP Entry to have a BOM List
		self.assertEqual(all_mrp_entries[0].bom_list, "BOM-SR04820-001")

		# Expect last MRP Entry records should be for current calendar week + 70 days
		last_date = add_to_date(test_start_day, days=70)
		calendar_date = last_date.isocalendar()
		expected_cw_string = str(calendar_date.week).zfill(2)
		self.assertEqual(
			all_mrp_entries[-1].name,
			f"{all_mrp_entries[-1].item_code}-{calendar_date.year}CW{expected_cw_string}",
		)
		# Expect last MRP Entry to have no BOM List (we only store the BOM list in first period MRP Entry)
		self.assertIsNone(all_mrp_entries[-1].bom_list)

		# Expect is_manufactured to be 1 for items with BOM's (assemblies and sub-assemblies), and 0 for items without
		# As per erpnext_mrp/tests/test_mrp_data_boms.json, SRZ00967, SRZ00963 and SR04820 have BOM's
		bom_items = ["SRZ00967", "SRZ00963", "SR04820"]
		for item in bom_items:
			is_manufactured = [entry.is_manufactured for entry in all_mrp_entries if entry.item_code == item]
			self.assertListEqual(
				is_manufactured, [1] * 11
			)  # 11 records because that is our weeks look-ahead setting
		# The rest should have is_manufactured = 0
		is_manufactured = [
			entry.is_manufactured for entry in all_mrp_entries if entry.item_code not in bom_items
		]
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
		Test that MRP Entry records have correct upstream net demand (via forecast-driven explosion)
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Zero out safety stock and MOQ on manufactured items so suggested_receipts == raw demand
		for item_code in ("SR04820", "SRZ00963", "SRZ00967"):
			frappe.db.set_value("Item", item_code, {"safety_stock": 0, "min_order_qty": 1})

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

		# Meaning, upstream demand for sub-items below should be 14 days before the forecast date for the final item
		# ==============================================================================================================
		forecast_date = add_to_date(final_item_forecast_date, days=-14)

		# Expect an upstream net demand for "SRZ00963 - MRP Test Sub-Assembly"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00963", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream net demand for "SRZ00962 - MRP Test BOM Item 3"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00962", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 10)  # Qty of 10, as per BOM

		# Expect an upstream net demand for "SRZ00961 - MRP Test BOM Item 2"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00961", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 4)  # Qty of 4, as per BOM

		# Expect an upstream net demand for "SRZ00960 - MRP Test BOM Item 1" (level-1 path)
		mrp_entry = get_mrp_entry_by_item_week("SRZ00960", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 1)  # Qty of 1, as per BOM
		# ==============================================================================================================

		# ==============================================================================================================
		# Validate items that are consumed by "SRZ00963 - MRP Test Sub-Assembly"
		# This manufactured item has a lead time of 21 days, as per erpnext_mrp/tests/test_mrp_data_items.json

		# Meaning, upstream demand for sub-items below should be 21 + 14 days before the forecast date
		# ==============================================================================================================
		forecast_date = add_to_date(final_item_forecast_date, days=-35)

		# Expect an upstream net demand for "SRZ00967 - MRP Test Sub-Sub-Assembly"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00967", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream net demand for "SRZ00964 - MRP Test SA BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00964", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 2)  # Qty of 2, as per BOM

		# Expect an upstream net demand for "SRZ00966 - MRP Test SA BOM Item 3"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00966", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 2)  # Qty of 2, as per BOM

		# Expect an upstream net demand for "SRZ00965 - MRP Test SA BOM Item 2"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00965", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 2)  # Qty of 2, as per BOM
		# ==============================================================================================================

		# ==============================================================================================================
		# Validate items that are consumed by "SRZ00967 - MRP Test Sub-Sub-Assembly"
		# This manufactured item has a lead time of 7 days, as per erpnext_mrp/tests/test_mrp_data_items.json

		# Meaning, upstream demand for sub-items below should be 7 + 21 + 14 days before the forecast date
		# ==============================================================================================================
		forecast_date = add_to_date(final_item_forecast_date, days=-42)

		# Expect an upstream net demand for "SRZ00968 - MRP Test SSA BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00968", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream net demand for "SRZ00960 - MRP Test BOM Item 1" (level-3 path)
		mrp_entry = get_mrp_entry_by_item_week("SRZ00960", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 4)  # Qty of 4, as per BOM
		# ==============================================================================================================

	def test_process_mrp_item_entries_with_additional_lead_time(self, mock_date):
		"""
		Test that MRP Entry records have correct upstream net demand when using an additional lead time field
		"""
		# Create a custom field to use as additional lead time
		if not frappe.db.exists("Custom Field", "Item-custom_additional_lead_time"):
			frappe.get_doc(
				{
					"doctype": "Custom Field",
					"dt": "Item",
					"fieldname": "custom_additional_lead_time",
					"label": "Custom Additional Lead Time",
					"fieldtype": "Data",
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

		# Zero out safety stock and MOQ on manufactured items so suggested_receipts == raw demand
		for item_code in ("SR04820", "SRZ00963", "SRZ00967"):
			frappe.db.set_value("Item", item_code, {"safety_stock": 0, "min_order_qty": 1})

		# Update MRP Settings to use the custom field
		self.mrp_settings.item_additional_lead_time_field = (
			"custom_additional_lead_time | Custom Additional Lead Time"
		)
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

		# Expect an upstream net demand for "SRZ00963 - MRP Test Sub-Assembly"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00963", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream net demand for "SRZ00962 - MRP Test BOM Item 3"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00962", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 10)  # Qty of 10, as per BOM

		# Expect an upstream net demand for "SRZ00961 - MRP Test BOM Item 2"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00961", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 4)  # Qty of 4, as per BOM

		# Expect an upstream net demand for "SRZ00960 - MRP Test BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00960", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 1)  # Qty of 1, as per BOM
		# ==============================================================================================================

		# ==============================================================================================================
		# Validate items that are consumed by "SRZ00963 - MRP Test Sub-Assembly"
		# This manufactured item has a lead time of 21 + 2 = 23 days
		# Meaning, upstream demand for sub-items below should be 23 + 15 days before the forecast date
		# ==============================================================================================================
		forecast_date = add_to_date(final_item_forecast_date, days=-(15 + 23))

		# Expect an upstream net demand for "SRZ00967 - MRP Test Sub-Sub-Assembly"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00967", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream net demand for "SRZ00964 - MRP Test SA BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00964", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 2)  # Qty of 2, as per BOM

		# Expect an upstream net demand for "SRZ00966 - MRP Test SA BOM Item 3"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00966", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 2)  # Qty of 2, as per BOM

		# Expect an upstream net demand for "SRZ00965 - MRP Test SA BOM Item 2"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00965", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 2)  # Qty of 2, as per BOM
		# ==============================================================================================================

		# ==============================================================================================================
		# Validate items that are consumed by "SRZ00967 - MRP Test Sub-Sub-Assembly"
		# This manufactured item has a lead time of 7 + 3 = 10 days
		# The net explosion anchors on target_date (today + 4 weeks = 2025-12-02), not the conceptual
		# demand date (Jan 13 - 38 = Dec 6). So: target_date(CW49) - 10 = Dec 2 - 10 = Nov 22 = CW47.
		# ==============================================================================================================
		szr967_target_date = add_to_date(test_start_day, days=4 * 7)  # today + 4 weeks = CW49 target_date
		forecast_date = add_to_date(szr967_target_date, days=-10)  # CW49 target_date - lead_time = CW47

		# Expect an upstream net demand for "SRZ00968 - MRP Test SSA BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00968", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream net demand for "SRZ00960 - MRP Test BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00960", forecast_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 4)  # Qty of 4, as per BOM
		# ==============================================================================================================

	def test_process_mrp_item_entries_have_correct_upstream_sales_order_demand(self, mock_date):
		"""
		Test that MRP Entry records have correct upstream net demand (via SO-driven explosion)
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Zero out safety stock and MOQ on manufactured items so suggested_receipts == raw demand
		for item_code in ("SR04820", "SRZ00963", "SRZ00967"):
			frappe.db.set_value("Item", item_code, {"safety_stock": 0, "min_order_qty": 1})

		# Create Sales Order due ~70 days (compound lead time for our test item) from now
		final_item_so_date = add_to_date(test_start_day, days=70)
		create_sales_order(
			item_code="SR04820", qty=1, delivery_date=final_item_so_date, transaction_date=test_start_day
		)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Expect a Reserved Qty value for the "SR04820 - MRP Test Sales Item (Assembly)" in the correct period
		mrp_entry = get_mrp_entry_by_item_week("SR04820", final_item_so_date)
		self.assertEqual(mrp_entry.reserved_qty, 1)

		# ==============================================================================================================
		# Validate items that are consumed by "SR04820 - MRP Test Sales Item (Assembly)"
		# This manufactured item has a lead time of 14 days, as per erpnext_mrp/tests/test_mrp_data_items.json

		# Meaning, upstream demand for sub-items below should be 14 days before the SO date
		# ==============================================================================================================
		so_demand_date = add_to_date(final_item_so_date, days=-14)

		# Expect an upstream net demand for "SRZ00963 - MRP Test Sub-Assembly"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00963", so_demand_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream net demand for "SRZ00962 - MRP Test BOM Item 3"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00962", so_demand_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 10)  # Qty of 10, as per BOM

		# Expect an upstream net demand for "SRZ00961 - MRP Test BOM Item 2"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00961", so_demand_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 4)  # Qty of 4, as per BOM

		# Expect an upstream net demand for "SRZ00960 - MRP Test BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00960", so_demand_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 1)  # Qty of 1, as per BOM
		# ==============================================================================================================

		# ==============================================================================================================
		# Validate items that are consumed by "SRZ00963 - MRP Test Sub-Assembly"
		# This manufactured item has a lead time of 21 days, as per erpnext_mrp/tests/test_mrp_data_items.json

		# Meaning, upstream demand for sub-items below should be 21 + 14 days before the SO date
		# ==============================================================================================================
		so_demand_date = add_to_date(final_item_so_date, days=-35)

		# Expect an upstream net demand for "SRZ00967 - MRP Test Sub-Sub-Assembly"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00967", so_demand_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream net demand for "SRZ00964 - MRP Test SA BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00964", so_demand_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 2)  # Qty of 2, as per BOM

		# Expect an upstream net demand for "SRZ00966 - MRP Test SA BOM Item 3"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00966", so_demand_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 2)  # Qty of 2, as per BOM

		# Expect an upstream net demand for "SRZ00965 - MRP Test SA BOM Item 2"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00965", so_demand_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 2)  # Qty of 2, as per BOM
		# ==============================================================================================================

		# ==============================================================================================================
		# Validate items that are consumed by "SRZ00967 - MRP Test Sub-Sub-Assembly"
		# This manufactured item has a lead time of 7 days, as per erpnext_mrp/tests/test_mrp_data_items.json

		# Meaning, upstream demand for sub-items below should be 7 + 21 + 14 days before the SO date
		# ==============================================================================================================
		so_demand_date = add_to_date(final_item_so_date, days=-42)

		# Expect an upstream net demand for "SRZ00968 - MRP Test SSA BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00968", so_demand_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 1)  # Qty of 1, as per BOM

		# Expect an upstream net demand for "SRZ00960 - MRP Test BOM Item 1"
		mrp_entry = get_mrp_entry_by_item_week("SRZ00960", so_demand_date)
		self.assertEqual(mrp_entry.upstream_net_demand, 4)  # Qty of 4, as per BOM
		# ==============================================================================================================

	def test_item_with_long_lead_time(self, mock_date):
		"""
		Test that MRP Entry records are calculated correctly for item with long lead time.
		Using SRZLONG123 (see test_mrp_data_items.json and test_mrp_data_forecast.json)
		Run only for a single item to keep it simple.
		"""
		test_start_day = datetime.date(2026, 1, 22)
		mock_date.today.return_value = test_start_day

		# Set MRP Settings item_condition and look_ahead
		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.item_condition = "doc.item_code == 'SRZLONG123'"
		mrp_settings.look_ahead = 26
		mrp_settings.periods_type = "Calendar Week"
		mrp_settings.requirement_based_on = "Forecast only"
		mrp_settings.save()

		# Create starting stock level for item
		make_stock_entry(
			item_code="SRZLONG123",
			posting_date=add_days(test_start_day, -1),
			qty=130,
			to_warehouse="_Test Warehouse - _TC",
			rate=1,
			purpose="Material Receipt",
		)

		# Run MRP
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Expect an unchanged Projected On Hand Inventory Qty for "SRZLONG123" in the first two weeks (forecast of 0)
		mrp_entries = frappe.get_all(
			"MRP Entry",
			fields=[
				"name",
				"on_hand_inventory",
				"suggested_receipts",
				"suggested_orders",
				"projected_on_hand_inventory",
			],
			filters={"item_code": "SRZLONG123"},
			order_by="name asc",
		)
		self.assertEqual(mrp_entries[0].projected_on_hand_inventory, 130)
		self.assertEqual(mrp_entries[1].projected_on_hand_inventory, 130)

		# Expect a Projected On Hand Inventory Qty for "SRZLONG123" dropping by 16 per week (that's the forecast that consumes it) thereafter
		self.assertEqual(mrp_entries[2].projected_on_hand_inventory, 114)
		self.assertEqual(mrp_entries[3].projected_on_hand_inventory, 98)
		self.assertEqual(mrp_entries[4].projected_on_hand_inventory, 82)
		self.assertEqual(mrp_entries[5].projected_on_hand_inventory, 66)
		self.assertEqual(mrp_entries[6].projected_on_hand_inventory, 50)
		self.assertEqual(mrp_entries[7].projected_on_hand_inventory, 34)

		# In the next week, we will reach below the re-order level (of 30), so we expect a Suggested Receipt here
		self.assertEqual(mrp_entries[8].suggested_receipts, 100)
		self.assertEqual(mrp_entries[8].projected_on_hand_inventory, 118)

		# Expect a Projected On Hand Inventory Qty dropping by 16 per week thereafter
		self.assertEqual(mrp_entries[9].projected_on_hand_inventory, 102)
		self.assertEqual(mrp_entries[10].projected_on_hand_inventory, 86)
		self.assertEqual(mrp_entries[11].projected_on_hand_inventory, 70)
		self.assertEqual(mrp_entries[12].projected_on_hand_inventory, 54)
		self.assertEqual(mrp_entries[13].projected_on_hand_inventory, 38)

		# In the next week, we will reach below the re-order level (of 30), so we expect a Suggested Receipt here
		self.assertEqual(mrp_entries[14].suggested_receipts, 100)
		self.assertEqual(mrp_entries[14].projected_on_hand_inventory, 122)

		# Expect a Projected On Hand Inventory Qty dropping by 16 per week thereafter
		self.assertEqual(mrp_entries[15].projected_on_hand_inventory, 106)
		self.assertEqual(mrp_entries[16].projected_on_hand_inventory, 90)
		self.assertEqual(mrp_entries[17].projected_on_hand_inventory, 74)
		self.assertEqual(mrp_entries[18].projected_on_hand_inventory, 58)
		self.assertEqual(mrp_entries[19].projected_on_hand_inventory, 42)

		# In the next week, we will reach below the re-order level (of 30), so we expect a Suggested Receipt here
		self.assertEqual(mrp_entries[20].suggested_receipts, 100)
		self.assertEqual(mrp_entries[20].projected_on_hand_inventory, 126)

		# Expect a Projected On Hand Inventory Qty dropping by 16 per week thereafter
		self.assertEqual(mrp_entries[21].projected_on_hand_inventory, 110)
		self.assertEqual(mrp_entries[22].projected_on_hand_inventory, 94)
		self.assertEqual(mrp_entries[23].projected_on_hand_inventory, 78)
		self.assertEqual(mrp_entries[24].projected_on_hand_inventory, 62)
		self.assertEqual(mrp_entries[25].projected_on_hand_inventory, 46)

		# Now to check the Suggested Orders
		# Working backwards, we have a Suggested Receipts in period 20.
		# With a lead time of 112 days, we expect a Suggested Order in period 4
		self.assertEqual(mrp_entries[4].suggested_orders, 100)

		# We have a Suggested Receipts in periods 14 and 8.
		# As the lead time of 112 days is longer than this, we expect an URGENT (p1) Suggested Order for this in period 0
		self.assertEqual(mrp_entries[0].suggested_orders, 200)

		# TODO: change assert to stock level check
		# self.assertEqual(mrp_entries[0].urgency_level, 1, "Expected an urgency_level of 1")

		# Now, add an actual receipt in period 14
		# In total we'll have enough to meet demand, but the receipts are late, hence a p2 scenario
		create_purchase_order(
			item_code="SRZLONG123", qty=260, delivery_date="2026-04-29", transaction_date=test_start_day
		)
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)
		# mrp_entries = frappe.get_all(
		# 	"MRP Entry", fields=["urgency_level"], filters={"item_code": "SRZLONG123"}, order_by="name asc"
		# )

		# # TODO: change assert to stock level check
		# self.assertEqual(mrp_entries[0].urgency_level, 2, "Expected an urgency_level of 2")

		# Now, add an another receipt in period 3
		# This will avoid a shortage, but still bring the stock level to below the safety stock level, hence a p3 scenario
		create_purchase_order(
			item_code="SRZLONG123", qty=70, delivery_date="2026-02-11", transaction_date=test_start_day
		)
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)
		# mrp_entries = frappe.get_all(
		# 	"MRP Entry", fields=["urgency_level"], filters={"item_code": "SRZLONG123"}, order_by="name asc"
		# )

		# TODO: change assert to stock level check
		# self.assertEqual(mrp_entries[0].urgency_level, 3, "Expected an urgency_level of 3")

		# Now, add an another receipt in period 2
		# This ensure the projected stock level is always above the safety stock level, hence a p0 scenario
		create_purchase_order(
			item_code="SRZLONG123", qty=30, delivery_date="2026-02-04", transaction_date=test_start_day
		)
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)
		mrp_entries = frappe.get_all(
			"MRP Entry",
			fields=[
				"name",
				"on_hand_inventory",
				"suggested_receipts",
				"suggested_orders",
				"projected_on_hand_inventory",
				# "urgency_level",
			],
			filters={"item_code": "SRZLONG123"},
			order_by="name asc",
		)

		# TODO: change assert to stock level check
		# self.assertEqual(mrp_entries[0].urgency_level, 0, "Expected an urgency_level of 0")

	def test_finalise_does_not_clobber_on_hand(self, mock_date):
		"""
		Regression for the batch race that left in-stock items showing 0 on hand.
		"""
		test_start_day = datetime.date(2026, 1, 22)
		mock_date.today.return_value = test_start_day

		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.item_condition = "doc.item_code == 'SRZLONG123'"
		mrp_settings.look_ahead = 4
		mrp_settings.requirement_based_on = "Forecast only"
		mrp_settings.save()

		# Starting stock of 130 - the receipts phase should persist this as on_hand.
		make_stock_entry(
			item_code="SRZLONG123",
			posting_date=add_days(test_start_day, -1),
			qty=130,
			to_warehouse="_Test Warehouse - _TC",
			rate=1,
			purpose="Material Receipt",
		)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		header = frappe.get_all(
			"MRP Entry", filters={"item_code": "SRZLONG123", "is_header": 1}, pluck="name"
		)[0]
		self.assertEqual(
			frappe.db.get_value("MRP Entry", header, "on_hand_inventory"),
			130,
			"receipts phase should have written the current stock as on_hand",
		)

		# Simulate a finalise worker that loaded its rows before the receipts commit:
		# the DB has 130 but every MRP Entry it reads still shows the stale 0.
		real_get_doc = mrp_run_module.frappe.get_doc

		def stale_get_doc(*args, **kwargs):
			doc = real_get_doc(*args, **kwargs)
			if args and args[0] == "MRP Entry":
				doc.on_hand_inventory = 0
				doc.on_hand_inventory_excl_reorder_level = 0
				doc.on_hand_inventory_no_action = 0
			return doc

		item_details_map = mrp_run_module._get_all_item_details()
		with patch.object(mrp_run_module.frappe, "get_doc", side_effect=stale_get_doc):
			mrp_run_module._finalise_suggestions(
				stock_levels=[], item_details_map=item_details_map, enqueue=False
			)

		self.assertEqual(
			frappe.db.get_value("MRP Entry", header, "on_hand_inventory"),
			130,
			"finalise must not overwrite on_hand_inventory written by the receipts phase",
		)

	def test_finalise_batches_enqueued_after_commit(self, mock_date):
		"""
		The finalise batches must be enqueued with enqueue_after_commit=True.
		"""
		test_start_day = datetime.date(2026, 1, 22)
		mock_date.today.return_value = test_start_day

		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.item_condition = "doc.item_code == 'SRZLONG123'"
		mrp_settings.look_ahead = 4
		mrp_settings.requirement_based_on = "Forecast only"
		mrp_settings.save()

		make_stock_entry(
			item_code="SRZLONG123",
			posting_date=add_days(test_start_day, -1),
			qty=130,
			to_warehouse="_Test Warehouse - _TC",
			rate=1,
			purpose="Material Receipt",
		)

		create_mrp_item_entries()
		with patch.object(mrp_run_module.frappe, "enqueue") as mock_enqueue:
			process_mrp_item_entries(enqueue=True)

		finalise_calls = [
			call
			for call in mock_enqueue.call_args_list
			if call.args and "_finalise_item_batch" in call.args[0]
		]
		self.assertTrue(finalise_calls, "expected the finalise batches to be enqueued")
		for call in finalise_calls:
			self.assertTrue(
				call.kwargs.get("enqueue_after_commit"),
				"finalise batches must be enqueued with enqueue_after_commit=True",
			)

	def test_process_mrp_item_entry_has_correct_suggested_orders_value_payable(self, mock_date):
		"""
		Test that MRP Entry record has correct Suggested Orders Value Payable.
		Run only for a single item to keep it simple.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Set MRP Settings item_condition
		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		mrp_settings.save()

		# Set up a default Supplier and Payment Term
		frappe.db.set_value("Supplier", "_Test Supplier", "payment_terms", "_Test 0 days after invoice")
		item = frappe.get_doc("Item", "SRZ11111")
		item.lead_time_days = 0
		item.additional_shipping_days = 0
		item.item_defaults = []
		item.uoms = []
		row = item.append("item_defaults")
		row.default_supplier = "_Test Supplier"
		row.company = "_Test Company"
		row.default_warehouse = "_Test Warehouse - _TC"
		item.save()

		# Set up an Item Price
		price = frappe.new_doc("Item Price")
		price.item_code = "SRZ11111"
		price.price_list_rate = 2
		price.price_list = "Standard Buying"
		price.valid_from = test_start_day
		price.save()

		# Create Sales Order due ~21 days from now
		final_item_so_date = add_to_date(test_start_day, days=21)
		create_sales_order(
			item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day
		)

		# Run MRP
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Expect a Reserved Qty value for the "SRZ11111" in the correct period
		mrp_entry = get_mrp_entry_by_item_week("SRZ11111", final_item_so_date)
		self.assertEqual(mrp_entry.reserved_qty, 10)

		# Expect a Suggested Orders of the same amount as the order (this item has no lead times/min order qty)
		self.assertEqual(mrp_entry.suggested_orders, 10)

		# Expect a Suggested Orders Value
		self.assertEqual(mrp_entry.suggested_orders_value, 20)

		# Expect a Suggested Orders Value Payable
		# We used a Payment Terms Template with 0 days, so payable amount should fall in the same period
		self.assertEqual(mrp_entry.suggested_orders_value_payable, 20)

	def test_fallback_valuation_rate_is_quantity_weighted(self, mock_date):
		"""
		Without an Item Price, the suggested orders value falls back to the stock valuation rate.
		That fallback must be weighted by the quantity in each warehouse.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		mrp_settings.save()

		item = frappe.get_doc("Item", "SRZ11111")
		item.lead_time_days = 0
		item.additional_shipping_days = 0
		item.item_defaults = []
		item.uoms = []
		row = item.append("item_defaults")
		row.company = "_Test Company"
		row.default_warehouse = "_Test Warehouse - _TC"
		item.save()

		# Bulk stock at the real price, plus one prototype sample at a wildly higher rate.
		make_stock_entry(
			item_code="SRZ11111",
			posting_date=add_days(test_start_day, -1),
			qty=151,
			to_warehouse="_Test Warehouse - _TC",
			rate=20.92,
			purpose="Material Receipt",
		)
		make_stock_entry(
			item_code="SRZ11111",
			posting_date=add_days(test_start_day, -1),
			qty=1,
			to_warehouse="_Test Warehouse 1 - _TC",
			rate=671.03,
			purpose="Material Receipt",
		)

		# Demand of 252 against 152 on hand leaves a shortage of 100.
		so_date = add_to_date(test_start_day, days=21)
		create_sales_order(
			item_code="SRZ11111", qty=252, delivery_date=so_date, transaction_date=test_start_day
		)

		# No Item Price exists (setUp clears them), so the valuation fallback is used.
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		mrp_entry = get_mrp_entry_by_item_week("SRZ11111", so_date)
		self.assertEqual(mrp_entry.suggested_orders, 100)

		# Quantity weighted: (151 * 20.92 + 1 * 671.03) / 152 = 25.1970...
		expected_rate = (151 * 20.92 + 1 * 671.03) / 152
		self.assertAlmostEqual(mrp_entry.suggested_orders_value, 100 * expected_rate, places=2)

	def test_process_mrp_item_entry_has_correct_suggested_orders_value_payable_14_days(self, mock_date):
		"""
		Test that MRP Entry record has correct Suggested Orders Value Payable for a Payment Term with > 0 days
		Run only for a single item to keep it simple.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Set MRP Settings item_condition
		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		mrp_settings.save()

		# Set up a default Supplier and 14-days Payment Term
		frappe.db.set_value("Supplier", "_Test Supplier", "payment_terms", "_Test 14 days after invoice")
		item = frappe.get_doc("Item", "SRZ11111")
		item.lead_time_days = 0
		item.additional_shipping_days = 0
		item.item_defaults = []
		item.uoms = []
		row = item.append("item_defaults")
		row.default_supplier = "_Test Supplier"
		row.company = "_Test Company"
		row.default_warehouse = "_Test Warehouse - _TC"
		item.save()

		# Set up an Item Price
		price = frappe.new_doc("Item Price")
		price.item_code = "SRZ11111"
		price.price_list_rate = 2
		price.price_list = "Standard Buying"
		price.valid_from = test_start_day
		price.save()

		# Create Sales Order due ~21 days from now
		final_item_so_date = add_to_date(test_start_day, days=21)
		create_sales_order(
			item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day
		)

		# Run MRP
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Expect a Reserved Qty value for the "SRZ11111" in the correct period
		mrp_entry_of_so = get_mrp_entry_by_item_week("SRZ11111", final_item_so_date)
		self.assertEqual(mrp_entry_of_so.reserved_qty, 10)

		# Expect a Suggested Orders Value Payable for "SRZ11111"
		# We used a Payment Terms Template with 14 days, so payable amount should fall in a period 14 days later
		item_payable_date = add_to_date(final_item_so_date, days=14)
		mrp_entry_of_payable = get_mrp_entry_by_item_week("SRZ11111", item_payable_date)
		self.assertEqual(mrp_entry_of_payable.suggested_orders_value_payable, 20)

	def test_process_mrp_item_entry_has_correct_suggested_orders_value_payable_split_terms(self, mock_date):
		"""
		Test that MRP Entry record has correct Suggested Orders Value Payable for a Payment Term Template with split terms
		Run only for a single item to keep it simple.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Set MRP Settings item_condition
		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		mrp_settings.save()

		# Set up a default Supplier and 14-days Payment Term
		frappe.db.set_value(
			"Supplier", "_Test Supplier", "payment_terms", "_Test Split 0 and 14 days after invoice"
		)
		item = frappe.get_doc("Item", "SRZ11111")
		item.lead_time_days = 0
		item.additional_shipping_days = 0
		item.item_defaults = []
		item.uoms = []
		row = item.append("item_defaults")
		row.default_supplier = "_Test Supplier"
		row.company = "_Test Company"
		row.default_warehouse = "_Test Warehouse - _TC"
		item.save()

		# Set up an Item Price
		price = frappe.new_doc("Item Price")
		price.item_code = "SRZ11111"
		price.price_list_rate = 2
		price.price_list = "Standard Buying"
		price.valid_from = test_start_day
		price.save()

		# Create Sales Order due ~21 days from now
		final_item_so_date = add_to_date(test_start_day, days=21)
		create_sales_order(
			item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day
		)

		# Run MRP
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Expect a Reserved Qty value for the "SRZ11111" in the correct period
		mrp_entry_of_so = get_mrp_entry_by_item_week("SRZ11111", final_item_so_date)
		self.assertEqual(mrp_entry_of_so.reserved_qty, 10)

		# Expect a Suggested Orders Value Payable for "SRZ11111"
		# We used a Payment Terms Template with two terms, 50% at 0 days, and 50% @ 14 days,
		# so payable amounts should be split in current period and in a period 14 days later
		item_payable_date_first_payment = final_item_so_date
		item_payable_date_second_payment = add_to_date(final_item_so_date, days=14)
		mrp_entry_of_payable_first_payment = get_mrp_entry_by_item_week(
			"SRZ11111", item_payable_date_first_payment
		)
		self.assertEqual(mrp_entry_of_payable_first_payment.suggested_orders_value_payable, 10)
		mrp_entry_of_payable_second_payment = get_mrp_entry_by_item_week(
			"SRZ11111", item_payable_date_second_payment
		)
		self.assertEqual(mrp_entry_of_payable_second_payment.suggested_orders_value_payable, 10)

	def test_process_mrp_item_entry_has_correct_suggested_orders_value_payable_with_shipment_date(
		self, mock_date
	):
		"""
		Test that MRP Entry record has correct Suggested Orders Value Payable when Custom Due Date is set on "Shipment Date"
		Run only for a single item to keep it simple.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Set MRP Settings item_condition and custom lead time fields
		self.mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		self.mrp_settings.item_lead_time_field = "lead_time_days | Lead Time in days"
		# mrp_settings.item_additional_lead_time_field = ""
		self.mrp_settings.save()

		# Set up a default Supplier and Payment Term and set lead time, so that we can take this into account when calculating payable amount date
		frappe.db.set_value(
			"Supplier", "_Test Supplier", "payment_terms", "_Test Payment Term based on Shipment Date"
		)
		item = frappe.get_doc("Item", "SRZ11111")
		item.lead_time_days = 21
		item.additional_shipping_days = 0
		item.item_defaults = []
		item.uoms = []
		row = item.append("item_defaults")
		row.default_supplier = "_Test Supplier"
		row.company = "_Test Company"
		row.default_warehouse = "_Test Warehouse - _TC"
		item.save()

		# Set up an Item Price
		price = frappe.new_doc("Item Price")
		price.item_code = "SRZ11111"
		price.price_list_rate = 2
		price.price_list = "Standard Buying"
		price.valid_from = test_start_day
		price.save()

		# Create Sales Order due ~7 days from now
		final_item_so_date = add_to_date(test_start_day, days=7)
		create_sales_order(
			item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day
		)

		# Run MRP
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Expect a Reserved Qty value for the "SRZ11111" in the correct period
		mrp_entry = get_mrp_entry_by_item_week("SRZ11111", final_item_so_date)
		self.assertEqual(mrp_entry.reserved_qty, 10)

		# Expect a Suggested Orders Value on the start week (due to 21 days lead time)
		mrp_entry_order = get_mrp_entry_by_item_week("SRZ11111", test_start_day)
		self.assertEqual(mrp_entry_order.suggested_orders_value, 20)

		# Expect a Suggested Orders Value Payable
		# We used a Payment Terms Template that's due on "Shipment date"
		# Order Date (Week 45) + Shipment Lead Time (21 days) = Week 48
		final_item_payable_date = add_to_date(test_start_day, days=21)
		mrp_entry_payable = get_mrp_entry_by_item_week("SRZ11111", final_item_payable_date)
		self.assertEqual(mrp_entry_payable.suggested_orders_value_payable, 20)

	def test_process_mrp_item_entry_has_correct_suggested_orders_value_payable_with_arrival_date(
		self, mock_date
	):
		"""
		Test that MRP Entry record has correct Suggested Orders Value Payable when Custom Due Date is set on "Arrival Date"
		Run only for a single item to keep it simple.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Set MRP Settings item_condition and custom lead time fields
		self.mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		self.mrp_settings.item_lead_time_field = "lead_time_days | Lead Time in days"
		self.mrp_settings.item_additional_lead_time_field = (
			"additional_shipping_days | Additional Shipping Days"
		)
		# mrp_settings.item_additional_lead_time_field = ""
		self.mrp_settings.save()

		# Set up a default Supplier and Payment Term and set lead time, so that we can take this into account when calculating payable amount date
		frappe.db.set_value(
			"Supplier", "_Test Supplier", "payment_terms", "_Test Payment Term based on Arrival Date"
		)
		item = frappe.get_doc("Item", "SRZ11111")
		item.lead_time_days = 21
		item.additional_shipping_days = 7
		item.item_defaults = []
		item.uoms = []
		row = item.append("item_defaults")
		row.default_supplier = "_Test Supplier"
		row.company = "_Test Company"
		row.default_warehouse = "_Test Warehouse - _TC"
		item.save()

		# Set up an Item Price
		price = frappe.new_doc("Item Price")
		price.item_code = "SRZ11111"
		price.price_list_rate = 2
		price.price_list = "Standard Buying"
		price.valid_from = test_start_day
		price.save()

		# Create Sales Order due ~7 days from now
		final_item_so_date = add_to_date(test_start_day, days=7)
		create_sales_order(
			item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day
		)

		# Run MRP
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Expect a Reserved Qty value for the "SRZ11111" in the correct period
		mrp_entry = get_mrp_entry_by_item_week("SRZ11111", final_item_so_date)
		self.assertEqual(mrp_entry.reserved_qty, 10)

		# Expect a Suggested Orders Value on the start week
		mrp_entry_order = get_mrp_entry_by_item_week("SRZ11111", test_start_day)
		self.assertEqual(mrp_entry_order.suggested_orders_value, 20)

		# Expect a Suggested Orders Value Payable
		# We used a Payment Terms Template that's due on "Arrival date"
		# Order Date (Week 45) + Total Lead Time (21+7 days) = Week 49
		final_item_payable_date = add_to_date(test_start_day, days=21 + 7)
		mrp_entry_payable = get_mrp_entry_by_item_week("SRZ11111", final_item_payable_date)
		self.assertEqual(mrp_entry_payable.suggested_orders_value_payable, 20)

	def test_process_mrp_item_entry_has_correct_suggested_orders_value_payable_split_shipment_arrival_date(
		self, mock_date
	):
		"""
		Test that MRP Entry record has correct Suggested Orders Value Payable when a split Payment Terms Template is used,
		40% Payable on "Shipment Date" and 60% Payable on "Arrival Date"
		Run only for a single item to keep it simple.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Set MRP Settings item_condition and custom lead time fields
		self.mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		self.mrp_settings.item_lead_time_field = "lead_time_days | Lead Time in days"
		self.mrp_settings.item_additional_lead_time_field = (
			"additional_shipping_days | Additional Shipping Days"
		)
		# mrp_settings.item_additional_lead_time_field = ""
		self.mrp_settings.save()

		# Set up a default Supplier and Payment Term and set lead time, so that we can take this into account when calculating payable amount date
		frappe.db.set_value(
			"Supplier",
			"_Test Supplier",
			"payment_terms",
			"_Test Split Payment Term based on Shipment + Arrival Date",
		)
		item = frappe.get_doc("Item", "SRZ11111")
		item.lead_time_days = 21
		item.additional_shipping_days = 7
		item.item_defaults = []
		item.uoms = []
		row = item.append("item_defaults")
		row.default_supplier = "_Test Supplier"
		row.company = "_Test Company"
		row.default_warehouse = "_Test Warehouse - _TC"
		item.save()

		# Set up an Item Price
		price = frappe.new_doc("Item Price")
		price.item_code = "SRZ11111"
		price.price_list_rate = 2
		price.price_list = "Standard Buying"
		price.valid_from = test_start_day
		price.save()

		# Create Sales Order due ~7 days from now
		final_item_so_date = add_to_date(test_start_day, days=7)
		create_sales_order(
			item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day
		)

		# Run MRP
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Expect a Reserved Qty value for the "SRZ11111" in the correct period
		mrp_entry = get_mrp_entry_by_item_week("SRZ11111", final_item_so_date)
		self.assertEqual(mrp_entry.reserved_qty, 10)

		# Expect a Suggested Orders Value on the start week
		mrp_entry_order = get_mrp_entry_by_item_week("SRZ11111", test_start_day)
		self.assertEqual(mrp_entry_order.suggested_orders_value, 20)

		# Expect a Suggested Orders Value Payable
		# 40% on Shipment Date (Order Date + 21) = Week 48
		item_shipment_payable_date = add_to_date(test_start_day, days=21)
		mrp_entry_shipment_payable = get_mrp_entry_by_item_week("SRZ11111", item_shipment_payable_date)
		self.assertEqual(mrp_entry_shipment_payable.suggested_orders_value_payable, 20 * 0.4)

		# 60% on Arrival Date (Order Date + 21 + 7) = Week 49
		item_arrival_payable_date = add_to_date(test_start_day, days=21 + 7)
		mrp_entry_arrival_payable = get_mrp_entry_by_item_week("SRZ11111", item_arrival_payable_date)
		self.assertEqual(mrp_entry_arrival_payable.suggested_orders_value_payable, 20 * 0.6)

	def test_process_mrp_item_entry_has_correct_suggested_orders_value_payable_with_no_supplier(
		self, mock_date
	):
		"""
		Test that MRP Entry record has correct Suggested Orders Value Payable with no default supplier.
		Run only for a single item to keep it simple.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Set MRP Settings item_condition
		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		mrp_settings.save()

		# item = frappe.get_doc("Item", "SRZ11111")
		# item.lead_time_days = 0
		# item.additional_shipping_days = 0
		# item.item_defaults = []
		# item.uoms = []

		# Set up an Item Price
		price = frappe.new_doc("Item Price")
		price.item_code = "SRZ11111"
		price.price_list_rate = 2
		price.price_list = "Standard Buying"
		price.valid_from = test_start_day
		price.save()

		# Create Sales Order due ~21 days from now
		final_item_so_date = add_to_date(test_start_day, days=21)
		create_sales_order(
			item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day
		)

		# Run MRP
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Expect a Reserved Qty value for the "SRZ11111" in the correct period
		mrp_entry = get_mrp_entry_by_item_week("SRZ11111", final_item_so_date)
		self.assertEqual(mrp_entry.reserved_qty, 10)

		# Expect a Suggested Orders of the same amount as the order (this item has no lead times/min order qty)
		self.assertEqual(mrp_entry.suggested_orders, 10)

		# Expect a Suggested Orders Value
		self.assertEqual(mrp_entry.suggested_orders_value, 20)

		# Expect a Suggested Orders Value Payable
		# With no default supplier, payable date should default to the order date
		self.assertEqual(mrp_entry.suggested_orders_value_payable, 20)

	def test_days_to_reorder_calculation(self, mock_date):
		"""
		Test that days_to_reorder is calculated correctly.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# 1. Test Future Order (Positive days_to_reorder)
		# Create Item with 10 days lead time
		create_item("TEST-DTR-01", "Test DTR Item 1", "Raw Material", lead_time_days=10)

		# Create demand due in 20 days (CW 48).
		# T (Nov 4) is Week 45.
		# T+20 (Nov 24) is Week 48.
		# Bucket for Week 48 has target_date = Nov 4 + 21 days = Nov 25.
		# Receipt Date = Nov 25.
		# Order Date = Nov 25 - 10 days = Nov 15.
		# Days to reorder = Nov 15 - Nov 4 = 11 days.
		due_date_future = add_days(test_start_day, 20)
		create_sales_order("TEST-DTR-01", 10, due_date_future, test_start_day)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		mrp_entries = frappe.get_all(
			"MRP Entry",
			filters={"item_code": "TEST-DTR-01"},
			fields=["days_to_reorder", "needs_reorder", "target_date"],
			order_by="target_date asc",
		)
		self.assertEqual(mrp_entries[0].days_to_reorder, 11)
		self.assertEqual(mrp_entries[0].needs_reorder, 1)

		# 2. Test Late Order (Negative days_to_reorder)
		# Create Item with 10 days lead time
		create_item("TEST-DTR-02", "Test DTR Item 2", "Raw Material", lead_time_days=10)

		# Create demand due in 5 days (CW 45).
		# T+5 (Nov 9) is Week 45.
		# Bucket for Week 45 has target_date = Nov 4.
		# Receipt Date = Nov 4.
		# Order Date = Nov 4 - 10 = Oct 25.
		# Days to reorder = Oct 25 - Nov 4 = -10.
		due_date_late = add_days(test_start_day, 5)
		create_sales_order("TEST-DTR-02", 10, due_date_late, test_start_day)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		mrp_entries_2 = frappe.get_all(
			"MRP Entry",
			filters={"item_code": "TEST-DTR-02"},
			fields=["days_to_reorder", "needs_reorder", "target_date"],
			order_by="target_date asc",
		)
		self.assertEqual(mrp_entries_2[0].days_to_reorder, -10)
		self.assertEqual(mrp_entries_2[0].needs_reorder, 1)

	def test_days_to_reorder_null_when_fully_covered(self, mock_date):
		"""
		When scheduled_receipts cover all demand for the MRP horizon,
		suggested_receipts = 0 for all periods. needs_reorder must be 0
		and days_to_reorder must be the sentinel value, not a real value.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		create_item("TEST-DTR-COVERED", "DTR Covered Item", "Raw Material", lead_time_days=10)

		due_date = add_days(test_start_day, 20)
		create_sales_order("TEST-DTR-COVERED", 10, due_date, test_start_day)
		create_purchase_order("TEST-DTR-COVERED", 10, due_date, test_start_day)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		header = frappe.get_all(
			"MRP Entry",
			filters={"item_code": "TEST-DTR-COVERED", "is_header": 1},
			fields=["needs_reorder", "needs_reorder_excl_reorder_level", "days_to_reorder"],
		)

		self.assertEqual(len(header), 1)
		self.assertEqual(header[0].needs_reorder, 0)
		self.assertEqual(header[0].needs_reorder_excl_reorder_level, 0)
		self.assertEqual(header[0].days_to_reorder, _NO_REORDER_SENTINEL)

	def test_days_to_reorder_split_safety_vs_no_safety(self, mock_date):
		"""
		When a PO covers demand exactly (scheduled_receipts == demand), there is no true
		shortage (excl safety stock), but safety stock is still unmet.
		Expected: needs_reorder=1, needs_reorder_excl_reorder_level=0.

		on_hand=0, scheduled_receipts=10, demand=10, safety_stock=20
		  excl: 0 - 10 + 10 = 0        → no shortage → needs_reorder_excl = 0
		  incl: 0 - 10 + 10 - 20 = -20 → shortage    → needs_reorder = 1
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		create_item(
			"TEST-DTR-SPLIT",
			"DTR Split Item",
			"Raw Material",
			lead_time_days=7,
			safety_stock=20,
		)

		due_date = add_days(test_start_day, 14)
		create_sales_order("TEST-DTR-SPLIT", 10, due_date, test_start_day)
		create_purchase_order("TEST-DTR-SPLIT", 10, due_date, test_start_day)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		header = frappe.get_all(
			"MRP Entry",
			filters={"item_code": "TEST-DTR-SPLIT", "is_header": 1},
			fields=["needs_reorder", "needs_reorder_excl_reorder_level", "days_to_reorder"],
		)

		self.assertEqual(len(header), 1)
		self.assertEqual(header[0].needs_reorder, 1)
		self.assertNotEqual(header[0].days_to_reorder, _NO_REORDER_SENTINEL)
		self.assertEqual(header[0].needs_reorder_excl_reorder_level, 0)

	def test_scheduled_receipts_value_populated_from_open_po(self, mock_date):
		"""
		scheduled_receipts_value must equal (qty - received_qty) * base_rate for an open PO.
		With no payment terms on the supplier the payable must default to the same period.
		total_payable must equal suggested_orders_value_payable + scheduled_receipts_value_payable.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		frappe.db.set_value("Supplier", "_Test Supplier", "payment_terms", "")

		create_item("TEST-SRV-01", "Scheduled Receipts Value Item", "Raw Material", lead_time_days=0)

		po_delivery_date = add_days(test_start_day, 14)
		# create_purchase_order uses rate=10 per unit; base_rate == rate in the test environment
		create_purchase_order("TEST-SRV-01", 5, po_delivery_date, test_start_day)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		po_item = frappe.db.get_value(
			"Purchase Order Item",
			{"item_code": "TEST-SRV-01"},
			["qty", "received_qty", "base_rate"],
			as_dict=True,
		)
		expected_value = (po_item.qty - (po_item.received_qty or 0)) * po_item.base_rate

		po_entry = get_mrp_entry_by_item_week("TEST-SRV-01", po_delivery_date)
		self.assertEqual(po_entry.scheduled_receipts_value, expected_value)
		# No payment terms → payable equals value in same period
		self.assertEqual(po_entry.scheduled_receipts_value_payable, expected_value)
		# No suggested orders (PO covers all demand) → total_payable == scheduled payable
		self.assertEqual(po_entry.total_payable, expected_value)

	def test_scheduled_receipts_value_zero_when_no_open_po(self, mock_date):
		"""
		Items with no open POs must have scheduled_receipts_value == 0 and
		scheduled_receipts_value_payable == 0; total_payable must equal
		suggested_orders_value_payable only.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		frappe.db.set_value("Supplier", "_Test Supplier", "payment_terms", "")

		create_item("TEST-SRV-02", "No PO Item", "Raw Material", lead_time_days=0)

		so_date = add_days(test_start_day, 14)
		create_sales_order("TEST-SRV-02", 10, so_date, test_start_day)

		# Set up an item price so suggested_orders_value is non-zero
		price = frappe.new_doc("Item Price")
		price.item_code = "TEST-SRV-02"
		price.price_list_rate = 3
		price.price_list = "Standard Buying"
		price.valid_from = test_start_day
		price.save()

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		so_entry = get_mrp_entry_by_item_week("TEST-SRV-02", so_date)
		self.assertEqual(so_entry.scheduled_receipts_value or 0, 0)
		self.assertEqual(so_entry.scheduled_receipts_value_payable or 0, 0)
		# total_payable must match suggested_orders_value_payable exactly
		self.assertEqual(so_entry.total_payable, so_entry.suggested_orders_value_payable)

	def test_total_payable_is_sum_of_both_payables(self, mock_date):
		"""
		When a week has both a suggested order and an open PO, total_payable must equal
		the sum of suggested_orders_value_payable and scheduled_receipts_value_payable.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		frappe.db.set_value("Supplier", "_Test Supplier", "payment_terms", "_Test 0 days after invoice")

		create_item("TEST-SRV-03", "Combined Payable Item", "Raw Material", lead_time_days=0)

		item = frappe.get_doc("Item", "TEST-SRV-03")
		item.item_defaults = []
		item.uoms = []
		row = item.append("item_defaults")
		row.default_supplier = "_Test Supplier"
		row.company = "_Test Company"
		row.default_warehouse = "_Test Warehouse - _TC"
		item.save()

		price = frappe.new_doc("Item Price")
		price.item_code = "TEST-SRV-03"
		price.price_list_rate = 4
		price.price_list = "Standard Buying"
		price.valid_from = test_start_day
		price.save()

		target_date = add_days(test_start_day, 21)
		# PO: 3 units x base_rate 10 = 30 scheduled value
		create_purchase_order("TEST-SRV-03", 3, target_date, test_start_day)
		# SO: 10 units demand, no stock: suggested_orders=10, value=40
		create_sales_order("TEST-SRV-03", 10, target_date, test_start_day)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		entry = get_mrp_entry_by_item_week("TEST-SRV-03", target_date)
		self.assertEqual(
			entry.total_payable,
			(entry.suggested_orders_value_payable or 0) + (entry.scheduled_receipts_value_payable or 0),
		)
		# Both components must be non-zero to make this test meaningful
		self.assertGreater(entry.suggested_orders_value_payable or 0, 0)
		self.assertGreater(entry.scheduled_receipts_value_payable or 0, 0)

	def test_net_explosion_suppressed_when_parent_has_stock(self, mock_date):
		"""
		When a parent's stock fully covers its demand, suggested_receipts = 0 and children
		receive zero upstream_net_demand. Primary regression test for the gross→net change.
		"""
		test_start_day = datetime.date(2026, 1, 5)
		mock_date.today.return_value = test_start_day

		create_item("TEST-NET-PARENT", "Net Parent", "Raw Material", lead_time_days=7)
		create_item("TEST-NET-CHILD", "Net Child", "Raw Material", lead_time_days=0)
		make_bom("TEST-NET-PARENT", [{"item_code": "TEST-NET-CHILD", "qty": 2}])

		make_stock_entry(
			item_code="TEST-NET-PARENT",
			posting_date=add_days(test_start_day, -1),
			qty=20,
			to_warehouse="_Test Warehouse - _TC",
			rate=1,
			purpose="Material Receipt",
		)

		self.mrp_settings.item_condition = "doc.item_code in ['TEST-NET-PARENT', 'TEST-NET-CHILD']"
		self.mrp_settings.save()

		create_mrp_forecast(
			{"item_code": "TEST-NET-PARENT", "forecast_date": test_start_day, "forecast_quantity": 10}
		)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		parent_entry = get_mrp_entry_by_item_week("TEST-NET-PARENT", test_start_day)
		self.assertEqual(parent_entry.suggested_receipts, 0)

		child_entries = frappe.get_all(
			"MRP Entry",
			filters={"item_code": "TEST-NET-CHILD"},
			fields=["upstream_net_demand", "suggested_receipts"],
		)
		for entry in child_entries:
			self.assertEqual(entry.upstream_net_demand or 0, 0)
			self.assertEqual(entry.suggested_receipts or 0, 0)

	def test_net_explosion_fires_when_parent_has_shortage(self, mock_date):
		"""
		When a parent has a shortage, upstream_net_demand is written to the child in the correct
		week, scaled by BOM quantity.
		"""
		test_start_day = datetime.date(2026, 1, 5)
		mock_date.today.return_value = test_start_day

		create_item("TEST-NET-PARENT", "Net Parent", "Raw Material", lead_time_days=7)
		create_item("TEST-NET-CHILD", "Net Child", "Raw Material", lead_time_days=0)
		make_bom("TEST-NET-PARENT", [{"item_code": "TEST-NET-CHILD", "qty": 2}])

		self.mrp_settings.item_condition = "doc.item_code in ['TEST-NET-PARENT', 'TEST-NET-CHILD']"
		self.mrp_settings.save()

		create_mrp_forecast(
			{"item_code": "TEST-NET-PARENT", "forecast_date": test_start_day, "forecast_quantity": 10}
		)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Parent has no stock → shortage → suggested_receipts = 10
		parent_entry = get_mrp_entry_by_item_week("TEST-NET-PARENT", test_start_day)
		self.assertEqual(parent_entry.suggested_receipts, 10)

		# Child demand snaps to current week (lead_time=7d would push to previous week, GREATEST snaps forward)
		child_entry = get_mrp_entry_by_item_week("TEST-NET-CHILD", test_start_day)
		self.assertEqual(child_entry.upstream_net_demand, 20)  # 10 x 2 BOM qty
		self.assertGreater(child_entry.suggested_receipts, 0)

	def test_net_explosion_selective_by_week(self, mock_date):
		"""
		The explosion is week-selective: only weeks where the parent has a genuine production
		shortage cascade to children.
		"""
		test_start_day = datetime.date(2026, 1, 5)
		mock_date.today.return_value = test_start_day

		create_item("TEST-NET-PARENT", "Net Parent", "Raw Material", lead_time_days=7)
		create_item("TEST-NET-CHILD", "Net Child", "Raw Material", lead_time_days=0)
		make_bom("TEST-NET-PARENT", [{"item_code": "TEST-NET-CHILD", "qty": 2}])

		make_stock_entry(
			item_code="TEST-NET-PARENT",
			posting_date=add_days(test_start_day, -1),
			qty=20,
			to_warehouse="_Test Warehouse - _TC",
			rate=1,
			purpose="Material Receipt",
		)

		self.mrp_settings.item_condition = "doc.item_code in ['TEST-NET-PARENT', 'TEST-NET-CHILD']"
		self.mrp_settings.save()

		# Three weeks of demand: stock covers weeks 0 and 1, shortage only in week 2
		for offset in (0, 7, 14):
			create_mrp_forecast(
				{
					"item_code": "TEST-NET-PARENT",
					"forecast_date": add_days(test_start_day, offset),
					"forecast_quantity": 10,
				}
			)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Parent: only week 2 has a production need
		parent_w0 = get_mrp_entry_by_item_week("TEST-NET-PARENT", test_start_day)
		parent_w2 = get_mrp_entry_by_item_week("TEST-NET-PARENT", add_days(test_start_day, 14))
		self.assertEqual(parent_w0.suggested_receipts or 0, 0)
		self.assertEqual(parent_w2.suggested_receipts, 10)

		# Child: upstream demand only in week 1 (week 2 target_date - 7d lead time = week 1)
		child_w0 = get_mrp_entry_by_item_week("TEST-NET-CHILD", test_start_day)
		child_w1 = get_mrp_entry_by_item_week("TEST-NET-CHILD", add_days(test_start_day, 7))
		child_w2 = get_mrp_entry_by_item_week("TEST-NET-CHILD", add_days(test_start_day, 14))
		self.assertEqual(child_w0.upstream_net_demand or 0, 0)
		self.assertEqual(child_w1.upstream_net_demand, 20)  # 10 x 2 BOM qty
		self.assertEqual(child_w2.upstream_net_demand or 0, 0)

	def test_net_explosion_moq_rounding_propagates_to_child(self, mock_date):
		"""
		The child receives demand based on the MOQ-rounded suggested_receipts of the parent,
		not the raw shortage quantity.
		"""
		test_start_day = datetime.date(2026, 1, 5)
		mock_date.today.return_value = test_start_day

		create_item("TEST-NET-MOQ-PARENT", "MOQ Parent", "Raw Material", lead_time_days=0, min_order_qty=10)
		create_item("TEST-NET-MOQ-CHILD", "MOQ Child", "Raw Material", lead_time_days=0)
		make_bom("TEST-NET-MOQ-PARENT", [{"item_code": "TEST-NET-MOQ-CHILD", "qty": 3}])

		self.mrp_settings.item_condition = "doc.item_code in ['TEST-NET-MOQ-PARENT', 'TEST-NET-MOQ-CHILD']"
		self.mrp_settings.save()

		# Forecast 7 units in week 1; MOQ=10 → suggested_receipts rounds up to 10
		create_mrp_forecast(
			{
				"item_code": "TEST-NET-MOQ-PARENT",
				"forecast_date": add_days(test_start_day, 7),
				"forecast_quantity": 7,
			}
		)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		parent_entry = get_mrp_entry_by_item_week("TEST-NET-MOQ-PARENT", add_days(test_start_day, 7))
		self.assertEqual(parent_entry.suggested_receipts, 10)

		child_entry = get_mrp_entry_by_item_week("TEST-NET-MOQ-CHILD", add_days(test_start_day, 7))
		self.assertEqual(child_entry.upstream_net_demand, 30)  # 10 (MOQ-rounded) x 3 BOM qty
		self.assertNotEqual(child_entry.upstream_net_demand, 21)  # gross behaviour would give 7 x 3

	def test_net_explosion_accumulates_from_multiple_parents(self, mock_date):
		"""
		When a shared component receives upstream_net_demand from two different parents at the
		same BOM level, the quantities are correctly accumulated, not overwritten.
		"""
		test_start_day = datetime.date(2026, 1, 5)
		mock_date.today.return_value = test_start_day

		create_item("TEST-SHARED-A", "Shared Parent A", "Raw Material", lead_time_days=0)
		create_item("TEST-SHARED-B", "Shared Parent B", "Raw Material", lead_time_days=0)
		create_item("TEST-SHARED-COMP", "Shared Component", "Raw Material", lead_time_days=0)
		make_bom("TEST-SHARED-A", [{"item_code": "TEST-SHARED-COMP", "qty": 3}])
		make_bom("TEST-SHARED-B", [{"item_code": "TEST-SHARED-COMP", "qty": 5}])

		self.mrp_settings.item_condition = (
			"doc.item_code in ['TEST-SHARED-A', 'TEST-SHARED-B', 'TEST-SHARED-COMP']"
		)
		self.mrp_settings.save()

		week1 = add_days(test_start_day, 7)
		create_mrp_forecast({"item_code": "TEST-SHARED-A", "forecast_date": week1, "forecast_quantity": 10})
		create_mrp_forecast({"item_code": "TEST-SHARED-B", "forecast_date": week1, "forecast_quantity": 10})

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		comp_entry = get_mrp_entry_by_item_week("TEST-SHARED-COMP", week1)
		# From A: 10 x 3 = 30; from B: 10 x 5 = 50; total = 80
		self.assertEqual(comp_entry.upstream_net_demand, 80)
		self.assertNotEqual(comp_entry.upstream_net_demand, 30)  # A-only
		self.assertNotEqual(comp_entry.upstream_net_demand, 50)  # B-only

	def test_net_explosion_date_shift_uses_combined_lead_time(self, mock_date):
		"""
		The child's demand date is shifted by the parent's combined lead time (primary +
		additional), which is already stored in MRP Entry.lead_time at scaffold time.
		"""
		test_start_day = datetime.date(2026, 1, 5)
		mock_date.today.return_value = test_start_day

		if not frappe.db.exists("Custom Field", "Item-custom_additional_lead_time"):
			frappe.get_doc(
				{
					"doctype": "Custom Field",
					"dt": "Item",
					"fieldname": "custom_additional_lead_time",
					"label": "Custom Additional Lead Time",
					"fieldtype": "Data",
					"insert_after": "lead_time_days",
				}
			).insert()

		create_item("TEST-NET-COMBINED-PARENT", "Combined LT Parent", "Raw Material", lead_time_days=7)
		create_item("TEST-NET-COMBINED-CHILD", "Combined LT Child", "Raw Material", lead_time_days=0)
		make_bom("TEST-NET-COMBINED-PARENT", [{"item_code": "TEST-NET-COMBINED-CHILD", "qty": 1}])

		frappe.db.set_value("Item", "TEST-NET-COMBINED-PARENT", "custom_additional_lead_time", 7)

		self.mrp_settings.item_condition = (
			"doc.item_code in ['TEST-NET-COMBINED-PARENT', 'TEST-NET-COMBINED-CHILD']"
		)
		self.mrp_settings.item_additional_lead_time_field = (
			"custom_additional_lead_time | Custom Additional Lead Time"
		)
		self.mrp_settings.save()

		# Forecast in week 2 (day 14). Combined lead_time = 7 + 7 = 14d → child demand lands in week 0
		create_mrp_forecast(
			{
				"item_code": "TEST-NET-COMBINED-PARENT",
				"forecast_date": add_days(test_start_day, 14),
				"forecast_quantity": 10,
			}
		)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		# Child demand must land in week 0 (14d shift), NOT week 1 (7d shift)
		child_w0 = get_mrp_entry_by_item_week("TEST-NET-COMBINED-CHILD", test_start_day)
		child_w1 = get_mrp_entry_by_item_week("TEST-NET-COMBINED-CHILD", add_days(test_start_day, 7))
		self.assertEqual(child_w0.upstream_net_demand, 10)
		self.assertEqual(child_w1.upstream_net_demand or 0, 0)

	def test_forecast_only_mode_children_receive_upstream_demand(self, mock_date):
		"""
		Under requirement_based_on = "Forecast only", upstream_net_demand is added to demand
		unconditionally regardless of mode. A child with no direct forecast still receives
		suggested_receipts driven by the parent's production need.
		"""
		test_start_day = datetime.date(2026, 1, 5)
		mock_date.today.return_value = test_start_day

		create_item("TEST-NET-PARENT", "Net Parent", "Raw Material", lead_time_days=7)
		create_item("TEST-NET-CHILD", "Net Child", "Raw Material", lead_time_days=0)
		make_bom("TEST-NET-PARENT", [{"item_code": "TEST-NET-CHILD", "qty": 2}])

		self.mrp_settings.item_condition = "doc.item_code in ['TEST-NET-PARENT', 'TEST-NET-CHILD']"
		self.mrp_settings.requirement_based_on = "Forecast only"
		self.mrp_settings.save()

		create_mrp_forecast(
			{"item_code": "TEST-NET-PARENT", "forecast_date": test_start_day, "forecast_quantity": 10}
		)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		child_entry = get_mrp_entry_by_item_week("TEST-NET-CHILD", test_start_day)
		self.assertEqual(child_entry.upstream_net_demand, 20)  # explosion wrote 10 x 2
		self.assertEqual(child_entry.open_orders or 0, 0)  # not in open_orders
		self.assertEqual(child_entry.forecast_demand or 0, 0)  # no direct forecast
		self.assertEqual(
			child_entry.total_forecast_demand, 20
		)  # forecast_demand(0) + upstream_net_demand(20)
		self.assertEqual(child_entry.suggested_receipts, 20)  # demand = 0 + 20 → shortage → receipts

	def test_open_orders_only_mode_children_receive_upstream_demand(self, mock_date):
		"""
		Under requirement_based_on = "Open Orders only", upstream_net_demand is still added to
		demand unconditionally. A child with no direct SO or WO demand still receives
		suggested_receipts when its parent has a production need driven by a Sales Order.
		"""
		test_start_day = datetime.date(2026, 1, 5)
		mock_date.today.return_value = test_start_day

		create_item("TEST-NET-PARENT", "Net Parent", "Raw Material", lead_time_days=7)
		create_item("TEST-NET-CHILD", "Net Child", "Raw Material", lead_time_days=0)
		make_bom("TEST-NET-PARENT", [{"item_code": "TEST-NET-CHILD", "qty": 2}])

		self.mrp_settings.item_condition = "doc.item_code in ['TEST-NET-PARENT', 'TEST-NET-CHILD']"
		self.mrp_settings.requirement_based_on = "Open Orders only"
		self.mrp_settings.save()

		create_sales_order(
			item_code="TEST-NET-PARENT",
			qty=10,
			delivery_date=test_start_day,
			transaction_date=test_start_day,
		)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		parent_entry = get_mrp_entry_by_item_week("TEST-NET-PARENT", test_start_day)
		self.assertGreater(parent_entry.suggested_receipts, 0)

		child_entry = get_mrp_entry_by_item_week("TEST-NET-CHILD", test_start_day)
		self.assertEqual(child_entry.upstream_net_demand, parent_entry.suggested_receipts * 2)
		self.assertEqual(child_entry.open_orders or 0, 0)  # not in open_orders
		self.assertGreater(child_entry.suggested_receipts, 0)

	def test_on_hand_inventory_wrong_when_stock_transaction_on_today(self, mock_date):
		"""
		Regression: on_hand_inventory, on_hand_inventory_excl_reorder_level, and
		on_hand_inventory_no_action were all sourced from opening_qty of the stock balance
		report (from_date = to_date = today).
		This test demonstrates the bug: 50 units are received on today's date, so the MRP
		opening stock for the item should be 50.
		"""
		test_start_day = datetime.date(2026, 1, 5)
		mock_date.today.return_value = test_start_day

		create_item("TEST-SOH-TODAY", "SOH Today Item", "Raw Material", lead_time_days=0)

		self.mrp_settings.item_condition = "doc.item_code == 'TEST-SOH-TODAY'"
		self.mrp_settings.save()

		# Stock entry posted ON today (not yesterday)
		make_stock_entry(
			item_code="TEST-SOH-TODAY",
			posting_date=test_start_day,
			qty=50,
			to_warehouse="_Test Warehouse - _TC",
			rate=1,
			purpose="Material Receipt",
		)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		header = frappe.get_all(
			"MRP Entry",
			filters={"item_code": "TEST-SOH-TODAY", "is_header": 1},
			fields=[
				"on_hand_inventory",
				"on_hand_inventory_excl_reorder_level",
				"on_hand_inventory_no_action",
			],
		)
		self.assertEqual(len(header), 1)

		# All three fields should reflect the 50 units received today.
		self.assertEqual(header[0].on_hand_inventory, 50)
		self.assertEqual(header[0].on_hand_inventory_excl_reorder_level, 50)
		self.assertEqual(header[0].on_hand_inventory_no_action, 50)

	def test_rejected_warehouse_stock_excluded_from_on_hand(self, mock_date):
		"""Stock held in a rejected warehouse must not count toward on_hand_inventory."""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		create_item("TEST-REJ-MRP", "Rejected WH Test Item", "Raw Material", lead_time_days=0)

		self.mrp_settings.item_condition = "doc.item_code == 'TEST-REJ-MRP'"
		self.mrp_settings.save()

		if not frappe.db.exists("Warehouse", "_Test Rejected WH - _TC"):
			frappe.get_doc(
				{
					"doctype": "Warehouse",
					"warehouse_name": "_Test Rejected WH",
					"is_rejected_warehouse": 1,
					"company": "_Test Company",
				}
			).insert(ignore_permissions=True)
		else:
			frappe.db.set_value("Warehouse", "_Test Rejected WH - _TC", "is_rejected_warehouse", 1)

		make_stock_entry(
			item_code="TEST-REJ-MRP",
			posting_date=test_start_day,
			qty=100,
			to_warehouse="_Test Rejected WH - _TC",
			rate=1,
			purpose="Material Receipt",
		)

		create_sales_order(
			item_code="TEST-REJ-MRP",
			qty=10,
			delivery_date=add_to_date(test_start_day, days=7),
			transaction_date=test_start_day,
		)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		header = frappe.get_all(
			"MRP Entry",
			filters={"item_code": "TEST-REJ-MRP", "is_header": 1},
			fields=["on_hand_inventory"],
		)
		self.assertEqual(len(header), 1)
		self.assertEqual(header[0].on_hand_inventory, 0)

	def test_item_price_uses_buying_price_list(self, mock_date):
		"""Price from Buying Settings buying_price_list is used when no supplier-specific price exists."""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		self.mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		self.mrp_settings.save()

		price = frappe.new_doc("Item Price")
		price.item_code = "SRZ11111"
		price.price_list = "Standard Buying"
		price.price_list_rate = 5.0
		price.valid_from = test_start_day
		price.save()

		create_sales_order(
			item_code="SRZ11111",
			qty=10,
			delivery_date=add_to_date(test_start_day, days=7),
			transaction_date=test_start_day,
		)
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		entry = get_mrp_entry_by_item_week("SRZ11111", add_to_date(test_start_day, days=7))
		self.assertEqual(entry.suggested_orders_value, 50.0)

	def test_item_price_supplier_specific_takes_priority(self, mock_date):
		"""Supplier-specific Item Price beats the buying price list price."""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		self.mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		self.mrp_settings.save()

		item = frappe.get_doc("Item", "SRZ11111")
		item.item_defaults = []
		item.uoms = []
		row = item.append("item_defaults")
		row.default_supplier = "_Test Supplier"
		row.company = "_Test Company"
		row.default_warehouse = "_Test Warehouse - _TC"
		item.save()

		pl_currency = frappe.db.get_value("Price List", "Standard Buying", "currency")

		p1 = frappe.new_doc("Item Price")
		p1.item_code = "SRZ11111"
		p1.price_list = "Standard Buying"
		p1.price_list_rate = 5.0
		p1.valid_from = test_start_day
		p1.save()

		p2 = frappe.new_doc("Item Price")
		p2.item_code = "SRZ11111"
		p2.price_list = "Standard Buying"
		p2.supplier = "_Test Supplier"
		p2.price_list_rate = 8.0
		p2.buying = 1
		p2.currency = pl_currency
		p2.valid_from = test_start_day
		p2.save()

		create_sales_order(
			item_code="SRZ11111",
			qty=10,
			delivery_date=add_to_date(test_start_day, days=7),
			transaction_date=test_start_day,
		)
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		entry = get_mrp_entry_by_item_week("SRZ11111", add_to_date(test_start_day, days=7))
		self.assertEqual(entry.suggested_orders_value, 80.0)

	def test_item_price_wrong_price_list_ignored(self, mock_date):
		"""An Item Price on a different buying price list (different currency) is ignored; valuation_rate is used."""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		self.mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		self.mrp_settings.save()

		if not frappe.db.exists("Price List", "_Test USD Buying"):
			pl = frappe.new_doc("Price List")
			pl.price_list_name = "_Test USD Buying"
			pl.currency = "USD"
			pl.buying = 1
			pl.insert(ignore_permissions=True)

		p = frappe.new_doc("Item Price")
		p.item_code = "SRZ11111"
		p.price_list = "_Test USD Buying"
		p.price_list_rate = 999.0
		p.valid_from = test_start_day
		p.save()

		create_sales_order(
			item_code="SRZ11111",
			qty=10,
			delivery_date=add_to_date(test_start_day, days=7),
			transaction_date=test_start_day,
		)
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		entry = get_mrp_entry_by_item_week("SRZ11111", add_to_date(test_start_day, days=7))
		# No price on Standard Buying; valuation_rate = 10 (set in create_item); 10 x 10 = 100
		self.assertEqual(entry.suggested_orders_value, 100.0)

	def test_item_price_expired_is_ignored(self, mock_date):
		"""An Item Price whose valid_upto is in the past is not used."""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		self.mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		self.mrp_settings.save()

		yesterday = add_to_date(test_start_day, days=-1)

		p_expired = frappe.new_doc("Item Price")
		p_expired.item_code = "SRZ11111"
		p_expired.price_list = "Standard Buying"
		p_expired.price_list_rate = 999.0
		p_expired.valid_from = add_to_date(test_start_day, days=-30)
		p_expired.valid_upto = yesterday
		p_expired.save()

		p_valid = frappe.new_doc("Item Price")
		p_valid.item_code = "SRZ11111"
		p_valid.price_list = "Standard Buying"
		p_valid.price_list_rate = 7.0
		p_valid.valid_from = test_start_day
		p_valid.save()

		create_sales_order(
			item_code="SRZ11111",
			qty=10,
			delivery_date=add_to_date(test_start_day, days=7),
			transaction_date=test_start_day,
		)
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		entry = get_mrp_entry_by_item_week("SRZ11111", add_to_date(test_start_day, days=7))
		self.assertEqual(entry.suggested_orders_value, 70.0)

	def test_item_price_uom_conversion(self, mock_date):
		"""A price in a non-stock UoM is converted to price-per-stock-UoM before use."""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		self.mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		self.mrp_settings.save()

		if not frappe.db.exists("UOM", "Test Box"):
			frappe.get_doc({"doctype": "UOM", "uom_name": "Test Box"}).insert()

		item = frappe.get_doc("Item", "SRZ11111")
		item.uoms = []
		row = item.append("uoms")
		row.uom = "Test Box"
		row.conversion_factor = 100  # 1 Test Box = 100 Nos
		item.save()

		p = frappe.new_doc("Item Price")
		p.item_code = "SRZ11111"
		p.price_list = "Standard Buying"
		p.price_list_rate = 500.0
		p.uom = "Test Box"
		p.valid_from = test_start_day
		p.save()

		create_sales_order(
			item_code="SRZ11111",
			qty=10,
			delivery_date=add_to_date(test_start_day, days=7),
			transaction_date=test_start_day,
		)
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		entry = get_mrp_entry_by_item_week("SRZ11111", add_to_date(test_start_day, days=7))
		# 500 / 100 = 5 per Nos; 10 x 5 = 50
		self.assertEqual(entry.suggested_orders_value, 50.0)


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
	safety_stock: int = 0,
	min_order_qty: int = 0,
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
		item.safety_stock = safety_stock
		item.min_order_qty = min_order_qty
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


def create_sales_order(
	item_code: str, qty: int, delivery_date: datetime.datetime, transaction_date: datetime.datetime
):
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
			"rate": 10,
		},
	)

	so.delivery_date = delivery_date
	so.transaction_date = transaction_date

	so.insert()
	so.submit()

	return so


def create_purchase_order(
	item_code: str, qty: int, delivery_date: datetime.datetime, transaction_date: datetime.datetime
):
	def dont_validate_minimum_order_qty(**args):
		pass

	po = frappe.new_doc("Purchase Order")
	po.set_warehouse = ""
	po.company = "_Test Company"
	po.supplier = "_Test Supplier"
	po.currency = "ZAR"
	po.po_no = ""
	po.append(
		"items",
		{
			"item_code": item_code,
			"warehouse": "_Test Warehouse - _TC",
			"schedule_date": delivery_date,
			"qty": qty,
			"rate": 10,
		},
	)

	po.schedule_date = delivery_date
	po.transaction_date = transaction_date

	po.validate_minimum_order_qty = dont_validate_minimum_order_qty

	po.insert()
	po.submit()

	return po


def create_payment_terms_templates():
	from erpnext.accounts.doctype.payment_entry.test_payment_entry import create_payment_term

	create_payment_term("_Test Payment Term 0 days after invoice")

	if not frappe.db.exists("Payment Terms Template", "_Test 0 days after invoice"):
		frappe.get_doc(
			{
				"doctype": "Payment Terms Template",
				"template_name": "_Test 0 days after invoice",
				"terms": [
					{
						"doctype": "Payment Terms Template Detail",
						"payment_term": "_Test 0 days after invoice",
						"invoice_portion": 100.00,
						"credit_days_based_on": "Day(s) after invoice date",
						"credit_days": 0,
					},
				],
			}
		).insert()

	create_payment_term("_Test Payment Term 14 days after invoice")

	if not frappe.db.exists("Payment Terms Template", "_Test 14 days after invoice"):
		frappe.get_doc(
			{
				"doctype": "Payment Terms Template",
				"template_name": "_Test 14 days after invoice",
				"terms": [
					{
						"doctype": "Payment Terms Template Detail",
						"payment_term": "_Test 14 days after invoice",
						"invoice_portion": 100.00,
						"credit_days_based_on": "Day(s) after invoice date",
						"credit_days": 14,
					},
				],
			}
		).insert()

	if not frappe.db.exists("Payment Terms Template", "_Test Split 0 and 14 days after invoice"):
		frappe.get_doc(
			{
				"doctype": "Payment Terms Template",
				"template_name": "_Test Split 0 and 14 days after invoice",
				"terms": [
					{
						"doctype": "Payment Terms Template Detail",
						"payment_term": "_Test 0 days after invoice",
						"invoice_portion": 50.00,
						"credit_days_based_on": "Day(s) after invoice date",
						"credit_days": 0,
					},
					{
						"doctype": "Payment Terms Template Detail",
						"payment_term": "_Test 14 days after invoice",
						"invoice_portion": 50.00,
						"credit_days_based_on": "Day(s) after invoice date",
						"credit_days": 14,
					},
				],
			}
		).insert()

	create_payment_term("_Test Payment Term based on Shipment Date")
	frappe.db.set_value(
		"Payment Term", "_Test Payment Term based on Shipment Date", "custom_due_date", "Shipment date"
	)

	if not frappe.db.exists("Payment Terms Template", "_Test Payment Term based on Shipment Date"):
		frappe.get_doc(
			{
				"doctype": "Payment Terms Template",
				"template_name": "_Test Payment Term based on Shipment Date",
				"terms": [
					{
						"doctype": "Payment Terms Template Detail",
						"payment_term": "_Test Payment Term based on Shipment Date",
						"invoice_portion": 100.00,
						"credit_days_based_on": "Day(s) after invoice date",
						"credit_days": 0,
					},
				],
			}
		).insert()

	create_payment_term("_Test Payment Term based on Arrival Date")
	frappe.db.set_value(
		"Payment Term", "_Test Payment Term based on Arrival Date", "custom_due_date", "Arrival date"
	)

	if not frappe.db.exists("Payment Terms Template", "_Test Payment Term based on Arrival Date"):
		frappe.get_doc(
			{
				"doctype": "Payment Terms Template",
				"template_name": "_Test Payment Term based on Arrival Date",
				"terms": [
					{
						"doctype": "Payment Terms Template Detail",
						"payment_term": "_Test Payment Term based on Arrival Date",
						"invoice_portion": 100.00,
						"credit_days_based_on": "Day(s) after invoice date",
						"credit_days": 0,
					},
				],
			}
		).insert()

	if not frappe.db.exists(
		"Payment Terms Template", "_Test Split Payment Term based on Shipment + Arrival Date"
	):
		frappe.get_doc(
			{
				"doctype": "Payment Terms Template",
				"template_name": "_Test Split Payment Term based on Shipment + Arrival Date",
				"terms": [
					{
						"doctype": "Payment Terms Template Detail",
						"payment_term": "_Test Payment Term based on Shipment Date",
						"invoice_portion": 40.00,
						"credit_days_based_on": "Day(s) after invoice date",
						"credit_days": 0,
					},
					{
						"doctype": "Payment Terms Template Detail",
						"payment_term": "_Test Payment Term based on Arrival Date",
						"invoice_portion": 60.00,
						"credit_days_based_on": "Day(s) after invoice date",
						"credit_days": 0,
					},
				],
			}
		).insert()


@patch("erpnext_mrp.mrp.tasks.mrp_run.date")
class TestGetForecastCoverageStatus(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("MRP Forecast")

		if not frappe.db.exists("MRP Settings", "MRP Settings"):
			mrp_settings = frappe.new_doc("MRP Settings")
		else:
			mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.look_ahead = 6
		mrp_settings.requirement_based_on = "Open Orders + Forecast"
		mrp_settings.save()

	def tearDown(self):
		frappe.db.delete("MRP Forecast")
		super().tearDown()

	def test_no_forecasts_returns_uncovered(self, mock_date):
		mock_date.today.return_value = datetime.date(2025, 11, 4)

		result = get_forecast_coverage_status()

		self.assertFalse(result["covered"])
		self.assertIsNone(result["max_forecast_date"])
		self.assertEqual(result["weeks_short"], 6)

	def test_forecast_fully_covers_horizon(self, mock_date):
		today = datetime.date(2025, 11, 4)
		mock_date.today.return_value = today

		frappe.get_doc(
			{
				"doctype": "MRP Forecast",
				"forecast_date": add_days(today, 6 * 7),
				"forecast_quantity": 10,
			}
		).insert(ignore_permissions=True, ignore_links=True, ignore_mandatory=True)

		result = get_forecast_coverage_status()

		self.assertTrue(result["covered"])
		self.assertEqual(result["weeks_short"], 0)

	def test_forecast_partially_covers_horizon(self, mock_date):
		today = datetime.date(2025, 11, 4)
		mock_date.today.return_value = today

		frappe.get_doc(
			{
				"doctype": "MRP Forecast",
				"forecast_date": add_days(today, 3 * 7),
				"forecast_quantity": 10,
			}
		).insert(ignore_permissions=True, ignore_links=True, ignore_mandatory=True)

		result = get_forecast_coverage_status()

		self.assertFalse(result["covered"])
		self.assertGreater(result["weeks_short"], 0)
		self.assertLessEqual(result["weeks_short"], 3)

	def test_open_orders_only_skips_check(self, mock_date):
		mock_date.today.return_value = datetime.date(2025, 11, 4)

		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.requirement_based_on = "Open Orders only"
		mrp_settings.save()

		result = get_forecast_coverage_status()

		self.assertTrue(result["covered"])
		self.assertEqual(result["weeks_short"], 0)


@patch("erpnext_mrp.mrp.tasks.mrp_run.date")
class TestScheduledReceiptsPayableWithActualPODates(FrappeTestCase):
	"""
	Verifies that scheduled_receipts_value_payable uses actual PO dates instead of
	lead-time back-calculation when payment term custom_due_date is set.
	"""

	ITEM_CODE = "TEST-SRPD-01"
	SUPPLIER_NAME = "_Test Supplier SRPD"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_custom_field(
			"Purchase Order Item",
			dict(
				fieldname="custom_expected_arrival_date",
				label="Expected Arrival Date",
				fieldtype="Date",
			),
		)

	@classmethod
	def tearDownClass(cls):
		if frappe.db.exists("Custom Field", "Purchase Order Item-custom_expected_arrival_date"):
			frappe.delete_doc("Custom Field", "Purchase Order Item-custom_expected_arrival_date", force=True)
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		frappe.db.delete("MRP Entry")
		frappe.db.delete("Purchase Order")
		frappe.db.delete("Item", {"name": self.ITEM_CODE})

		_ensure_payment_terms_for_actual_dates()

		if not frappe.db.exists("Supplier", self.SUPPLIER_NAME):
			supplier = frappe.new_doc("Supplier")
			supplier.supplier_name = self.SUPPLIER_NAME
			supplier.supplier_type = "Company"
			supplier.insert(ignore_permissions=True)

		if not frappe.db.exists("MRP Settings", "MRP Settings"):
			mrp_settings = frappe.new_doc("MRP Settings")
		else:
			mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.look_ahead = 11
		mrp_settings.periods_type = "Calendar Week"
		mrp_settings.requirement_based_on = "Open Orders + Forecast"
		mrp_settings.item_lead_time_field = "lead_time_days | Lead Time in days"
		mrp_settings.item_additional_lead_time_field = ""
		mrp_settings.po_item_delivery_date_field = "custom_expected_arrival_date | Expected Arrival Date"
		mrp_settings.assume_remaining_qty = 1
		mrp_settings.save()

		item = create_item(self.ITEM_CODE, "SRPD Test Item", "Raw Material", lead_time_days=0)
		item.item_defaults = []
		item.uoms = []
		row = item.append("item_defaults")
		row.default_supplier = self.SUPPLIER_NAME
		row.company = "_Test Company"
		row.default_warehouse = "_Test Warehouse - _TC"
		item.save()

	def tearDown(self):
		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.po_item_delivery_date_field = ""
		mrp_settings.po_item_shipment_date_field = ""
		mrp_settings.po_item_arrival_date_field = ""
		mrp_settings.assume_remaining_qty = 0
		mrp_settings.save()
		super().tearDown()

	def _make_supplier(self, payment_terms_template: str) -> None:
		frappe.db.set_value("Supplier", self.SUPPLIER_NAME, "payment_terms", payment_terms_template)

	def _set_payment_anchor_fields(self, shipment: str = "", arrival: str = "") -> None:
		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.po_item_shipment_date_field = shipment
		mrp_settings.po_item_arrival_date_field = arrival
		mrp_settings.save()

	def _make_po(
		self,
		transaction_date: datetime.date,
		schedule_date: datetime.date,
		custom_expected_arrival_date: datetime.date | None,
		expected_delivery_date: datetime.date | None = None,
		qty: int = 10,
		rate: float = 100.0,
	):
		po = frappe.new_doc("Purchase Order")
		po.company = "_Test Company"
		po.supplier = self.SUPPLIER_NAME
		po.currency = "ZAR"
		po.transaction_date = transaction_date
		po.schedule_date = schedule_date
		po.append(
			"items",
			{
				"item_code": self.ITEM_CODE,
				"warehouse": "_Test Warehouse - _TC",
				"schedule_date": schedule_date,
				"qty": qty,
				"rate": rate,
				"custom_expected_arrival_date": custom_expected_arrival_date,
				"expected_delivery_date": expected_delivery_date,
			},
		)
		po.insert(ignore_permissions=True)
		po.submit()
		return po

	def test_order_date_term_uses_po_transaction_date(self, mock_date):
		"""
		When custom_due_date == "Order date", the payment due date must be calculated
		from the actual po.transaction_date, not from the arrival-week bucket.

		PO transaction_date = W1, schedule_date = W3, arrival = W5, term = "Order date" + 0 days.
		Expected: payable lands in W1, not W5.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start

		w1 = test_start
		w3 = test_start + datetime.timedelta(weeks=2)
		w5 = test_start + datetime.timedelta(weeks=4)

		self._make_supplier("_Test Payment Term based on Order Date")
		self._make_po(transaction_date=w1, schedule_date=w3, custom_expected_arrival_date=w5)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		w1_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w1)
		w5_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w5)

		self.assertGreater(
			w1_entry.scheduled_receipts_value_payable or 0,
			0,
			"Payment obligation must appear in the order-date week (W1)",
		)
		self.assertEqual(
			w5_entry.scheduled_receipts_value_payable or 0,
			0,
			"Arrival week must carry no payable when term is 'Order date'",
		)

	def test_shipment_date_term_uses_po_schedule_date(self, mock_date):
		"""
		When custom_due_date == "Shipment date", the payment due date must be calculated
		from the actual po_item.schedule_date (ETD), not lead-time back-calculation.

		PO transaction_date = W1, schedule_date = W3, arrival = W5, term = "Shipment date" + 0 days.
		Expected: payable lands in W3.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start

		w1 = test_start
		w3 = test_start + datetime.timedelta(weeks=2)
		w5 = test_start + datetime.timedelta(weeks=4)

		self._make_supplier("_Test Payment Term based on Shipment Date")
		self._make_po(transaction_date=w1, schedule_date=w3, custom_expected_arrival_date=w5)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		w1_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w1)
		w3_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w3)
		w5_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w5)

		self.assertGreater(
			w3_entry.scheduled_receipts_value_payable or 0,
			0,
			"Payment obligation must appear in the shipment-date week (W3)",
		)
		self.assertEqual(w1_entry.scheduled_receipts_value_payable or 0, 0)
		self.assertEqual(w5_entry.scheduled_receipts_value_payable or 0, 0)

	def test_arrival_date_term_uses_po_custom_expected_arrival_date(self, mock_date):
		"""
		When custom_due_date == "Arrival date", the payment due date must be calculated
		from po_item.custom_expected_arrival_date.

		PO transaction_date = W1, schedule_date = W3, arrival = W5, term = "Arrival date" + 0 days.
		Expected: payable lands in W5.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start

		w1 = test_start
		w3 = test_start + datetime.timedelta(weeks=2)
		w5 = test_start + datetime.timedelta(weeks=4)

		self._make_supplier("_Test Payment Term based on Arrival Date")
		self._make_po(transaction_date=w1, schedule_date=w3, custom_expected_arrival_date=w5)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		w1_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w1)
		w3_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w3)
		w5_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w5)

		self.assertGreater(
			w5_entry.scheduled_receipts_value_payable or 0,
			0,
			"Payment obligation must appear in the arrival-date week (W5)",
		)
		self.assertEqual(w1_entry.scheduled_receipts_value_payable or 0, 0)
		self.assertEqual(w3_entry.scheduled_receipts_value_payable or 0, 0)

	def test_missing_eta_falls_back_to_etd(self, mock_date):
		"""
		When custom_expected_arrival_date is NULL and the term is "Arrival date",
		the code falls back to schedule_date (ETD). Payable must land in the ETD week.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start

		w1 = test_start
		w3 = test_start + datetime.timedelta(weeks=2)

		self._make_supplier("_Test Payment Term based on Arrival Date")
		self._make_po(transaction_date=w1, schedule_date=w3, custom_expected_arrival_date=None)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		w1_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w1)
		w3_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w3)

		self.assertGreater(
			w3_entry.scheduled_receipts_value_payable or 0,
			0,
			"When ETA is absent, payable must fall back to the ETD week (W3)",
		)
		self.assertEqual(w1_entry.scheduled_receipts_value_payable or 0, 0)

	def test_shipment_date_term_uses_configured_field_on_delayed_po(self, mock_date):
		"""
		A delayed order keeps its original schedule_date and tracks the new date on
		expected_delivery_date. With that field configured as the shipment date anchor,
		the instalment must follow the delay.

		PO schedule_date = W1 (overdue), expected_delivery_date = W4, term = "Shipment date" + 0 days.
		Expected: payable lands in W4, not W1.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start

		w1 = test_start
		w4 = test_start + datetime.timedelta(weeks=3)

		self._set_payment_anchor_fields(shipment="expected_delivery_date | Expected Delivery Date")
		self._make_supplier("_Test Payment Term based on Shipment Date")
		self._make_po(
			transaction_date=w1,
			schedule_date=w1,
			custom_expected_arrival_date=None,
			expected_delivery_date=w4,
		)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		w1_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w1)
		w4_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w4)

		self.assertGreater(
			w4_entry.scheduled_receipts_value_payable or 0,
			0,
			"Payable must follow the configured shipment date field (W4)",
		)
		self.assertEqual(
			w1_entry.scheduled_receipts_value_payable or 0,
			0,
			"Payable must not stay on the original schedule_date week (W1)",
		)

	def test_configured_shipment_field_empty_falls_back_to_schedule_date(self, mock_date):
		"""
		The configured shipment date field is optional and blank on most existing PO lines.
		Those lines must keep using schedule_date instead of collapsing to the order date.

		PO transaction_date = W1, schedule_date = W3, expected_delivery_date empty.
		Expected: payable stays in W3.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start

		w1 = test_start
		w3 = test_start + datetime.timedelta(weeks=2)

		self._set_payment_anchor_fields(shipment="expected_delivery_date | Expected Delivery Date")
		self._make_supplier("_Test Payment Term based on Shipment Date")
		self._make_po(
			transaction_date=w1,
			schedule_date=w3,
			custom_expected_arrival_date=None,
			expected_delivery_date=None,
		)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		w1_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w1)
		w3_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w3)

		self.assertGreater(
			w3_entry.scheduled_receipts_value_payable or 0,
			0,
			"An empty shipment date field must fall back to schedule_date (W3)",
		)
		self.assertEqual(
			w1_entry.scheduled_receipts_value_payable or 0,
			0,
			"An empty shipment date field must not push the payable onto the order date (W1)",
		)

	def test_arrival_date_term_uses_configured_field(self, mock_date):
		"""
		The arrival date anchor is configurable too. With custom_expected_arrival_date empty,
		the term must still resolve through the configured field rather than falling back
		to the shipment date.

		PO schedule_date = W3, expected_delivery_date = W5, term = "Arrival date" + 0 days.
		Expected: payable lands in W5, not the shipment week W3.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start

		w1 = test_start
		w3 = test_start + datetime.timedelta(weeks=2)
		w5 = test_start + datetime.timedelta(weeks=4)

		self._set_payment_anchor_fields(arrival="expected_delivery_date | Expected Delivery Date")
		self._make_supplier("_Test Payment Term based on Arrival Date")
		self._make_po(
			transaction_date=w1,
			schedule_date=w3,
			custom_expected_arrival_date=None,
			expected_delivery_date=w5,
		)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		w3_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w3)
		w5_entry = get_mrp_entry_by_item_week(self.ITEM_CODE, w5)

		self.assertGreater(
			w5_entry.scheduled_receipts_value_payable or 0,
			0,
			"Payable must follow the configured arrival date field (W5)",
		)
		self.assertEqual(
			w3_entry.scheduled_receipts_value_payable or 0,
			0,
			"Payable must not fall back to the shipment week (W3) when the arrival field is set",
		)


def _ensure_payment_terms_for_actual_dates():
	from erpnext.accounts.doctype.payment_entry.test_payment_entry import create_payment_term

	create_payment_term("_Test Payment Term based on Order Date")
	frappe.db.set_value(
		"Payment Term", "_Test Payment Term based on Order Date", "custom_due_date", "Order date"
	)

	if not frappe.db.exists("Payment Terms Template", "_Test Payment Term based on Order Date"):
		frappe.get_doc(
			{
				"doctype": "Payment Terms Template",
				"template_name": "_Test Payment Term based on Order Date",
				"terms": [
					{
						"doctype": "Payment Terms Template Detail",
						"payment_term": "_Test Payment Term based on Order Date",
						"invoice_portion": 100.00,
						"credit_days_based_on": "Day(s) after invoice date",
						"credit_days": 0,
					},
				],
			}
		).insert()

	create_payment_term("_Test Payment Term based on Shipment Date")
	frappe.db.set_value(
		"Payment Term", "_Test Payment Term based on Shipment Date", "custom_due_date", "Shipment date"
	)

	if not frappe.db.exists("Payment Terms Template", "_Test Payment Term based on Shipment Date"):
		frappe.get_doc(
			{
				"doctype": "Payment Terms Template",
				"template_name": "_Test Payment Term based on Shipment Date",
				"terms": [
					{
						"doctype": "Payment Terms Template Detail",
						"payment_term": "_Test Payment Term based on Shipment Date",
						"invoice_portion": 100.00,
						"credit_days_based_on": "Day(s) after invoice date",
						"credit_days": 0,
					},
				],
			}
		).insert()

	create_payment_term("_Test Payment Term based on Arrival Date")
	frappe.db.set_value(
		"Payment Term", "_Test Payment Term based on Arrival Date", "custom_due_date", "Arrival date"
	)

	if not frappe.db.exists("Payment Terms Template", "_Test Payment Term based on Arrival Date"):
		frappe.get_doc(
			{
				"doctype": "Payment Terms Template",
				"template_name": "_Test Payment Term based on Arrival Date",
				"terms": [
					{
						"doctype": "Payment Terms Template Detail",
						"payment_term": "_Test Payment Term based on Arrival Date",
						"invoice_portion": 100.00,
						"credit_days_based_on": "Day(s) after invoice date",
						"credit_days": 0,
					},
				],
			}
		).insert()


class TestMRPFinaliseGuard(FrappeTestCase):
	"""
	Unit tests for _finalise_in_progress(): the stateless, age-filtered, fail-open run guard.
	The queue read (_get_batch_jobs) and the tz conversion are patched so the decision logic is
	tested deterministically without a live RQ worker.
	"""

	JOB_NAME = "erpnext_mrp.mrp.tasks.mrp_run._finalise_item_batch"

	def setUp(self):
		super().setUp()
		# Remove any pre-existing logs so the "most recent run" is the one we set up.
		frappe.db.delete("Scheduled Job Log", {"scheduled_job_type": "mrp_run.mrp_run"})

	def _set_last_run(self, when):
		log = frappe.get_doc(
			{"doctype": "Scheduled Job Log", "scheduled_job_type": "mrp_run.mrp_run", "status": "Complete"}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Scheduled Job Log", log.name, "creation", when, update_modified=False)

	def _job(self, status, creation):
		return frappe._dict(
			{"name": "job1", "job_name": self.JOB_NAME, "status": status, "creation": creation}
		)

	def test_no_previous_run_is_not_in_progress(self):
		with patch.object(mrp_run_module, "_get_batch_jobs", return_value=[]):
			self.assertEqual(mrp_run_module._finalise_in_progress(), (False, False))

	def test_live_recent_batch_is_in_progress(self):
		now = frappe.utils.now_datetime()
		self._set_last_run(now - datetime.timedelta(minutes=10))
		jobs = [self._job("started", now - datetime.timedelta(minutes=5))]
		with (
			patch.object(mrp_run_module, "convert_utc_to_system_timezone", side_effect=lambda dt: dt),
			patch.object(mrp_run_module, "_get_batch_jobs", return_value=jobs),
		):
			self.assertEqual(mrp_run_module._finalise_in_progress(), (True, False))

	def test_ancient_phantom_job_is_ignored(self):
		# A queued job created BEFORE the most recent run must not block it (the original deadlock).
		now = frappe.utils.now_datetime()
		self._set_last_run(now - datetime.timedelta(minutes=10))
		jobs = [self._job("queued", now - datetime.timedelta(minutes=100))]
		with (
			patch.object(mrp_run_module, "convert_utc_to_system_timezone", side_effect=lambda dt: dt),
			patch.object(mrp_run_module, "_get_batch_jobs", return_value=jobs),
		):
			self.assertEqual(mrp_run_module._finalise_in_progress(), (False, False))

	def test_wedged_job_past_ceiling_is_stale(self):
		# In-progress but older than the ceiling -> (True, True): proceed anyway + alert.
		now = frappe.utils.now_datetime()
		self._set_last_run(now - datetime.timedelta(minutes=200))
		age = mrp_run_module.MRP_FINALISE_CEILING_MINUTES + 30
		jobs = [self._job("started", now - datetime.timedelta(minutes=age))]
		with (
			patch.object(mrp_run_module, "convert_utc_to_system_timezone", side_effect=lambda dt: dt),
			patch.object(mrp_run_module, "_get_batch_jobs", return_value=jobs),
		):
			self.assertEqual(mrp_run_module._finalise_in_progress(), (True, True))

	def test_finished_jobs_do_not_count(self):
		now = frappe.utils.now_datetime()
		self._set_last_run(now - datetime.timedelta(minutes=10))
		jobs = [self._job("finished", now - datetime.timedelta(minutes=5))]
		with (
			patch.object(mrp_run_module, "convert_utc_to_system_timezone", side_effect=lambda dt: dt),
			patch.object(mrp_run_module, "_get_batch_jobs", return_value=jobs),
		):
			self.assertEqual(mrp_run_module._finalise_in_progress(), (False, False))


@patch("erpnext_mrp.mrp.tasks.mrp_run.date")
class TestSuggestionsWithinLeadTime(FrappeTestCase):
	"""
	A suggested receipt is only useful if an order placed now could actually arrive in time.
	When the lead time is longer than the distance to the shortage, the suggestion is placed in
	a period it can never serve, and by the time it could arrive the inbound Purchase Orders have
	already covered the gap -- leaving permanent surplus stock and inflated near-term cash.
	"""

	WAREHOUSE = "_Test Warehouse - _TC"

	def setUp(self):
		super().setUp()
		frappe.db.delete("MRP Entry")
		frappe.db.delete("MRP Forecast")
		frappe.db.delete("Purchase Order")
		frappe.db.delete("Stock Entry")
		frappe.db.delete("Stock Ledger Entry")

		if not frappe.db.exists("MRP Settings", "MRP Settings"):
			mrp_settings = frappe.new_doc("MRP Settings")
		else:
			mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.look_ahead = 12
		mrp_settings.periods_type = "Calendar Week"
		mrp_settings.requirement_based_on = "Forecast only"
		mrp_settings.item_lead_time_field = "lead_time_days | Lead Time in days"
		mrp_settings.item_additional_lead_time_field = ""
		mrp_settings.defer_suggestions_within_lead_time = 1
		mrp_settings.save()
		self.mrp_settings = mrp_settings

	def tearDown(self):
		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.item_condition = ""
		mrp_settings.defer_suggestions_within_lead_time = 0
		mrp_settings.save()
		super().tearDown()

	def _setup_item(self, item_code: str, lead_time_days: int, on_hand: int, test_start):
		item = create_item(item_code, item_code, "_Test Item Group A", lead_time_days=lead_time_days)
		item.lead_time_days = lead_time_days
		item.save()

		self.mrp_settings.item_condition = f"doc.item_code == '{item_code}'"
		self.mrp_settings.save()

		if on_hand:
			make_stock_entry(
				item_code=item_code,
				posting_date=add_days(test_start, -1),
				qty=on_hand,
				to_warehouse=self.WAREHOUSE,
				rate=10,
				purpose="Material Receipt",
			)
		return item

	def _entries(self, item_code: str) -> list:
		return frappe.get_all(
			"MRP Entry",
			filters={"item_code": item_code},
			fields=[
				"name",
				"target_date",
				"suggested_receipts",
				"suggested_orders",
				"suggested_orders_value",
				"scheduled_receipts",
				"projected_on_hand_inventory",
				"projected_on_hand_inventory_no_action",
			],
			order_by="target_date asc",
		)

	def test_no_suggestion_when_inbound_po_arrives_before_lead_time_allows(self, mock_date):
		"""
		Lead time 56 days (8 weeks). Shortage in W2, open PO for 200 landing in W4.
		Nothing ordered today can arrive before W8, and by W8 the PO has already covered
		the gap, so no order should be suggested and no surplus should be left behind.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start
		item_code = "LT-FENCE-COVERED"

		w2 = test_start + datetime.timedelta(weeks=2)
		w4 = test_start + datetime.timedelta(weeks=4)

		self._setup_item(item_code, lead_time_days=56, on_hand=100, test_start=test_start)
		create_mrp_forecast({"item_code": item_code, "forecast_date": w2, "forecast_quantity": 150})
		create_purchase_order(item_code=item_code, qty=200, delivery_date=w4, transaction_date=test_start)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		entries = self._entries(item_code)
		total_suggested_orders = sum(e.suggested_orders or 0 for e in entries)
		total_suggested_value = sum(e.suggested_orders_value or 0 for e in entries)

		self.assertEqual(
			total_suggested_orders,
			0,
			"No order can arrive before the inbound PO, so none should be suggested",
		)
		self.assertEqual(
			total_suggested_value,
			0,
			"Unachievable suggestions must not inflate near-term suggested order cash",
		)
		self.assertEqual(
			entries[-1].projected_on_hand_inventory,
			entries[-1].projected_on_hand_inventory_no_action,
			"Suggesting an order the pipeline already covers leaves permanent surplus stock",
		)

	def test_suggestion_is_netted_against_a_partially_covering_po(self, mock_date):
		"""
		Lead time 56 days. Shortage of 200 in W2, but only 50 is inbound in W4.
		A suggestion is still required, but it must be netted against the inbound 50 rather
		than repeating the full W2 shortage.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start
		item_code = "LT-FENCE-PARTIAL"

		w2 = test_start + datetime.timedelta(weeks=2)
		w4 = test_start + datetime.timedelta(weeks=4)

		self._setup_item(item_code, lead_time_days=56, on_hand=100, test_start=test_start)
		create_mrp_forecast({"item_code": item_code, "forecast_date": w2, "forecast_quantity": 300})
		create_purchase_order(item_code=item_code, qty=50, delivery_date=w4, transaction_date=test_start)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		entries = self._entries(item_code)
		total_suggested_orders = sum(e.suggested_orders or 0 for e in entries)

		self.assertGreater(
			total_suggested_orders,
			0,
			"The inbound PO only covers part of the shortage, so a suggestion is still required",
		)
		self.assertEqual(
			total_suggested_orders,
			150,
			"The suggestion must net off the 50 already inbound, not repeat the full 200 shortage",
		)

	def test_short_lead_time_shortage_is_still_suggested(self, mock_date):
		"""
		Guard against over-suppression: with a 7 day lead time, a W2 shortage can be fixed by
		ordering in W1, so the suggestion must survive even though a PO exists later in W6.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start
		item_code = "LT-FENCE-SHORT"

		w1 = test_start + datetime.timedelta(weeks=1)
		w2 = test_start + datetime.timedelta(weeks=2)
		w6 = test_start + datetime.timedelta(weeks=6)

		self._setup_item(item_code, lead_time_days=7, on_hand=100, test_start=test_start)
		create_mrp_forecast({"item_code": item_code, "forecast_date": w2, "forecast_quantity": 150})
		create_purchase_order(item_code=item_code, qty=200, delivery_date=w6, transaction_date=test_start)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		w1_entry = get_mrp_entry_by_item_week(item_code, w1)
		w2_entry = get_mrp_entry_by_item_week(item_code, w2)

		self.assertEqual(
			w2_entry.suggested_receipts, 50, "An achievable shortage must still be flagged in W2"
		)
		self.assertEqual(
			w1_entry.suggested_orders,
			50,
			"The order must be suggested one week ahead of the W2 receipt",
		)

	def test_long_lead_time_shortage_without_any_po_is_still_suggested(self, mock_date):
		"""
		Guard against suppressing real demand: the same long lead time with nothing inbound
		must still raise a suggestion, because no pipeline supply exists to cover the gap.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start
		item_code = "LT-FENCE-UNCOVERED"

		w2 = test_start + datetime.timedelta(weeks=2)

		self._setup_item(item_code, lead_time_days=56, on_hand=100, test_start=test_start)
		create_mrp_forecast({"item_code": item_code, "forecast_date": w2, "forecast_quantity": 150})

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		entries = self._entries(item_code)
		total_suggested_orders = sum(e.suggested_orders or 0 for e in entries)

		self.assertEqual(
			total_suggested_orders,
			50,
			"With nothing inbound the shortage is real and must still be ordered",
		)

	def test_setting_disabled_leaves_behaviour_unchanged(self, mock_date):
		"""
		With the setting off, the shortage is suggested in the period it occurs even though
		the lead time makes that delivery impossible -- the behaviour before the setting existed.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start
		item_code = "LT-FENCE-DISABLED"

		w2 = test_start + datetime.timedelta(weeks=2)
		w4 = test_start + datetime.timedelta(weeks=4)

		self.mrp_settings.defer_suggestions_within_lead_time = 0
		self.mrp_settings.save()

		self._setup_item(item_code, lead_time_days=56, on_hand=100, test_start=test_start)
		create_mrp_forecast({"item_code": item_code, "forecast_date": w2, "forecast_quantity": 150})
		create_purchase_order(item_code=item_code, qty=200, delivery_date=w4, transaction_date=test_start)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		w2_entry = get_mrp_entry_by_item_week(item_code, w2)
		entries = self._entries(item_code)

		self.assertEqual(
			w2_entry.suggested_receipts, 50, "With the setting off the W2 shortage is still suggested"
		)
		self.assertEqual(
			sum(e.suggested_orders or 0 for e in entries),
			50,
			"With the setting off the unachievable order is still raised",
		)

	def test_lead_time_beyond_horizon_still_surfaces_netted_requirement(self, mock_date):
		"""
		A lead time longer than the look-ahead horizon has no fillable period inside it. The
		requirement must be clamped to the last period rather than disappearing, and it must
		still be netted against the inbound Purchase Order.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start
		item_code = "LT-FENCE-BEYOND"

		w2 = test_start + datetime.timedelta(weeks=2)
		w4 = test_start + datetime.timedelta(weeks=4)

		# 154 days is 22 weeks, well past the 12 week look-ahead configured in setUp.
		self._setup_item(item_code, lead_time_days=154, on_hand=100, test_start=test_start)
		create_mrp_forecast({"item_code": item_code, "forecast_date": w2, "forecast_quantity": 300})
		create_purchase_order(item_code=item_code, qty=50, delivery_date=w4, transaction_date=test_start)

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		entries = self._entries(item_code)

		self.assertEqual(
			sum(e.suggested_orders or 0 for e in entries),
			150,
			"A lead time past the horizon must still raise the netted requirement, not nothing",
		)
		self.assertEqual(
			entries[-1].suggested_receipts,
			150,
			"The requirement belongs in the last period of the horizon",
		)

		# The receipt is booked in the last period, but the demand exists in W2, so urgency must
		# be measured from W2: 14 days out, less the 154 day lead time.
		header = get_mrp_entry_by_item_week(item_code, test_start)
		self.assertEqual(
			header.days_to_reorder,
			-140,
			"Urgency must be measured from the demand, not from the deferred receipt period",
		)

	def test_deferral_does_not_change_urgency_for_a_fillable_shortage(self, mock_date):
		"""
		When the shortage is far enough out for the lead time to be met, the receipt is not
		deferred and the reported urgency must match the un-deferred calculation exactly.
		"""
		test_start = datetime.date(2025, 11, 3)
		mock_date.today.return_value = test_start
		item_code = "LT-FENCE-URGENCY"

		w4 = test_start + datetime.timedelta(weeks=4)

		self._setup_item(item_code, lead_time_days=7, on_hand=100, test_start=test_start)
		create_mrp_forecast({"item_code": item_code, "forecast_date": w4, "forecast_quantity": 150})

		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)

		header = get_mrp_entry_by_item_week(item_code, test_start)
		self.assertEqual(
			header.days_to_reorder,
			21,
			"An achievable shortage 28 days out with a 7 day lead time must report 21 days",
		)
