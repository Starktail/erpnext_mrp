import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_mrp.api import get_current_stock_levels


def _bin_rows(*items: tuple[str, float]) -> list[frappe._dict]:
	return [frappe._dict(item_code=code, actual_qty=qty) for code, qty in items]


class TestGetCurrentStockLevels(FrappeTestCase):
	def test_returns_summed_qty_for_known_items(self):
		rows = _bin_rows(("ITEM-A", 15.0), ("ITEM-B", 20.0))
		with patch.object(frappe.db, "sql", return_value=rows):
			result = get_current_stock_levels(json.dumps(["ITEM-A", "ITEM-B"]))
		self.assertAlmostEqual(result["ITEM-A"], 15.0)
		self.assertAlmostEqual(result["ITEM-B"], 20.0)

	def test_empty_item_codes_returns_empty_dict(self):
		with patch.object(frappe.db, "sql") as mock_sql:
			result = get_current_stock_levels(json.dumps([]))
		mock_sql.assert_not_called()
		self.assertEqual(result, {})

	def test_item_with_no_bin_is_absent_from_result(self):
		with patch.object(frappe.db, "sql", return_value=[]):
			result = get_current_stock_levels(json.dumps(["NEVER-STOCKED"]))
		self.assertNotIn("NEVER-STOCKED", result)

	def test_accepts_list_directly(self):
		rows = _bin_rows(("ITEM-C", 7.5))
		with patch.object(frappe.db, "sql", return_value=rows):
			result = get_current_stock_levels(["ITEM-C"])
		self.assertAlmostEqual(result["ITEM-C"], 7.5)

	def test_none_actual_qty_treated_as_zero(self):
		rows = _bin_rows(("ITEM-D", None))
		with patch.object(frappe.db, "sql", return_value=rows):
			result = get_current_stock_levels(["ITEM-D"])
		self.assertAlmostEqual(result["ITEM-D"], 0.0)
