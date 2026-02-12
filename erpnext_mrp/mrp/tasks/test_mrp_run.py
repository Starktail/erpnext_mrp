import datetime
import json
import os
from unittest.mock import patch

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry
from frappe.custom.doctype.custom_field.custom_field import create_custom_field
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
		create_custom_field("Item", dict(fieldname="additional_shipping_days", label="Additional Shipping Days", fieldtype="Data"))

	def tearDown(self):
		if frappe.db.exists("Custom Field", "Item-custom_additional_lead_time"):
			frappe.delete_doc("Custom Field", "Item-custom_additional_lead_time", force=True)

		# Reset MRP Settings item_condition
		mrp_settings = frappe.get_doc("MRP Settings", "MRP Settings")
		mrp_settings.item_condition = ""
		mrp_settings.save()

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
		create_sales_order(item_code="SR04820", qty=1, delivery_date=final_item_so_date, transaction_date=test_start_day)

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

		# TODO
		# Test that scheduled_receipts populates correctly on MRP Entries (planned_qty & ordered_qty)
		# Test that suggested_receipts populates correctly on MRP Entries
		# Test that suggested_orders populates correctly on MRP Entries
		# Test that projected_on_hand_inventory populates correctly on MRP Entries
		# Test that correct Urgency Level is calculated on MRP Entries

		# Add another demand for parent item (SR04820) with different due date, to test that qtys are aggregated

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
			fields=["name", "on_hand_inventory", "suggested_receipts", "suggested_orders", "projected_on_hand_inventory", "urgency_level"],
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
		self.assertEqual(mrp_entries[0].urgency_level, 1, "Expected an urgency_level of 1")

		# Now, add an actual receipt in period 14
		# In total we'll have enough to meet demand, but the receipts are late, hence a p2 scenario
		create_purchase_order(item_code="SRZLONG123", qty=260, delivery_date="2026-04-29", transaction_date=test_start_day)
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)
		mrp_entries = frappe.get_all("MRP Entry", fields=["urgency_level"], filters={"item_code": "SRZLONG123"}, order_by="name asc")

		self.assertEqual(mrp_entries[0].urgency_level, 2, "Expected an urgency_level of 2")

		# Now, add an another receipt in period 3
		# This will avoid a shortage, but still bring the stock level to below the safety stock level, hence a p3 scenario
		create_purchase_order(item_code="SRZLONG123", qty=70, delivery_date="2026-02-11", transaction_date=test_start_day)
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)
		mrp_entries = frappe.get_all("MRP Entry", fields=["urgency_level"], filters={"item_code": "SRZLONG123"}, order_by="name asc")

		self.assertEqual(mrp_entries[0].urgency_level, 3, "Expected an urgency_level of 3")

		# Now, add an another receipt in period 2
		# This ensure the projected stock level is always above the safety stock level, hence a p0 scenario
		create_purchase_order(item_code="SRZLONG123", qty=30, delivery_date="2026-02-04", transaction_date=test_start_day)
		create_mrp_item_entries()
		process_mrp_item_entries(enqueue=False)
		mrp_entries = frappe.get_all(
			"MRP Entry",
			fields=["name", "on_hand_inventory", "suggested_receipts", "suggested_orders", "projected_on_hand_inventory", "urgency_level"],
			filters={"item_code": "SRZLONG123"},
			order_by="name asc",
		)

		self.assertEqual(mrp_entries[0].urgency_level, 0, "Expected an urgency_level of 0")

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
		create_sales_order(item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day)

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
		create_sales_order(item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day)

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
		frappe.db.set_value("Supplier", "_Test Supplier", "payment_terms", "_Test Split 0 and 14 days after invoice")
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
		create_sales_order(item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day)

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
		mrp_entry_of_payable_first_payment = get_mrp_entry_by_item_week("SRZ11111", item_payable_date_first_payment)
		self.assertEqual(mrp_entry_of_payable_first_payment.suggested_orders_value_payable, 10)
		mrp_entry_of_payable_second_payment = get_mrp_entry_by_item_week("SRZ11111", item_payable_date_second_payment)
		self.assertEqual(mrp_entry_of_payable_second_payment.suggested_orders_value_payable, 10)

	def test_process_mrp_item_entry_has_correct_suggested_orders_value_payable_with_shipment_date(self, mock_date):
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
		frappe.db.set_value("Supplier", "_Test Supplier", "payment_terms", "_Test Payment Term based on Shipment Date")
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
		create_sales_order(item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day)

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

	def test_process_mrp_item_entry_has_correct_suggested_orders_value_payable_with_arrival_date(self, mock_date):
		"""
		Test that MRP Entry record has correct Suggested Orders Value Payable when Custom Due Date is set on "Arrival Date"
		Run only for a single item to keep it simple.
		"""
		test_start_day = datetime.date(2025, 11, 4)
		mock_date.today.return_value = test_start_day

		# Set MRP Settings item_condition and custom lead time fields
		self.mrp_settings.item_condition = "doc.item_code == 'SRZ11111'"
		self.mrp_settings.item_lead_time_field = "lead_time_days | Lead Time in days"
		self.mrp_settings.item_additional_lead_time_field = "additional_shipping_days | Additional Shipping Days"
		# mrp_settings.item_additional_lead_time_field = ""
		self.mrp_settings.save()

		# Set up a default Supplier and Payment Term and set lead time, so that we can take this into account when calculating payable amount date
		frappe.db.set_value("Supplier", "_Test Supplier", "payment_terms", "_Test Payment Term based on Arrival Date")
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
		create_sales_order(item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day)

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

	def test_process_mrp_item_entry_has_correct_suggested_orders_value_payable_split_shipment_arrival_date(self, mock_date):
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
		self.mrp_settings.item_additional_lead_time_field = "additional_shipping_days | Additional Shipping Days"
		# mrp_settings.item_additional_lead_time_field = ""
		self.mrp_settings.save()

		# Set up a default Supplier and Payment Term and set lead time, so that we can take this into account when calculating payable amount date
		frappe.db.set_value("Supplier", "_Test Supplier", "payment_terms", "_Test Split Payment Term based on Shipment + Arrival Date")
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
		create_sales_order(item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day)

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

	def test_process_mrp_item_entry_has_correct_suggested_orders_value_payable_with_no_supplier(self, mock_date):
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
		create_sales_order(item_code="SRZ11111", qty=10, delivery_date=final_item_so_date, transaction_date=test_start_day)

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


def create_sales_order(item_code: str, qty: int, delivery_date: datetime.datetime, transaction_date: datetime.datetime):
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


def create_purchase_order(item_code: str, qty: int, delivery_date: datetime.datetime, transaction_date: datetime.datetime):
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
	frappe.db.set_value("Payment Term", "_Test Payment Term based on Shipment Date", "custom_due_date", "Shipment date")

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
	frappe.db.set_value("Payment Term", "_Test Payment Term based on Arrival Date", "custom_due_date", "Arrival date")

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

	if not frappe.db.exists("Payment Terms Template", "_Test Split Payment Term based on Shipment + Arrival Date"):
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
