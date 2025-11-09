import frappe
from frappe.config import get_modules_from_all_apps_for_user


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
