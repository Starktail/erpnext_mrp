import frappe
from frappe.utils.telemetry import capture

no_cache = 1


def get_context(context):
	csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()
	context.csrf_token = csrf_token
	context.boot = get_boot()
	return context


def get_boot():
	return {
		"sysdefaults": frappe.defaults.get_defaults(),
	}


@frappe.whitelist(methods=["POST"], allow_guest=True)
def get_context_for_dev():
	if not frappe.conf.developer_mode:
		frappe.throw("This method is only meant for developer mode")
	return get_boot()
