import json

import frappe
from frappe.config import get_modules_from_all_apps_for_user


@frappe.whitelist()
def get_current_stock_levels(item_codes: list[str] | str) -> dict[str, float]:
	codes: list[str] = json.loads(item_codes) if isinstance(item_codes, str) else item_codes
	if not codes:
		return {}

	rows = frappe.db.sql(
		"""
		SELECT item_code, SUM(actual_qty) AS actual_qty
		FROM tabBin
		WHERE item_code IN %(codes)s
		AND warehouse NOT IN (
			SELECT name FROM `tabWarehouse` WHERE is_rejected_warehouse = 1
		)
		GROUP BY item_code
		""",
		{"codes": codes},
		as_dict=True,
	)
	return {r.item_code: float(r.actual_qty or 0) for r in rows}


def check_app_permission():
	if frappe.session.user == "Administrator":
		return True

	allowed_modules = get_modules_from_all_apps_for_user()
	allowed_modules = [x["module_name"] for x in allowed_modules]
	if "MRP" not in allowed_modules:
		return False

	roles = frappe.get_roles()
	if any(role in ["System Manager", "MRP User", "MRP Manager"] for role in roles):
		return True

	return False
