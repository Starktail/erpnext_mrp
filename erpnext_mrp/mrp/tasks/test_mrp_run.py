import os
import json
from typing import List

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_mrp.mrp.tasks.mrp_run import create_mrp_item_entries

test_data_file_items = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "test_mrp_data_items.json")
test_data_file_boms = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "test_mrp_data_boms.json")

class TestMRPRun(FrappeTestCase):
	"""
	Integration tests for mrp_run(), using test_mrp_data.json as mock data.
	"""

	def setUp(self):
		super().setUp()
		# Clear any existing records
		frappe.db.delete("MRP Entry")
		frappe.db.commit()  # nosemgrep

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
	
	def test_create_mrp_item_entries(self):
		create_mrp_item_entries()
		assert True


def create_item(
	item_code: str,
	item_name: str,
	item_group: str,
	lead_time_days: int,
	opening_stock: int = 0
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
		item.valuation_rate = 0
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
