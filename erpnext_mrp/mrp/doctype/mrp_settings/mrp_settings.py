# Copyright (c) 2025, Finfoot Tech (Pty) Ltd and contributors
# For license information, please see license.txt

from collections import namedtuple

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import nowdate
from frappe.utils.caching import redis_cache
from frappe.utils.safe_exec import get_safe_globals


class MRPSettings(Document):
	def validate(self):
		self.validate_condition()

	def validate_condition(self):
		temp_doc = frappe.new_doc("Item")
		if self.item_condition:
			try:
				frappe.safe_eval(self.item_condition, None, get_context(temp_doc.as_dict()))
			except Exception:
				frappe.throw(_("The Condition '{0}' is invalid").format(self.item_condition))

	@frappe.whitelist()
	@redis_cache(ttl=600)
	def get_docfields(
		self, doctype: str, field_type: str | None = None, mandatory_fields_only: bool | None = False
	) -> list[dict]:
		"""
		Get a list of DocFields for the given Doctype
		"""
		invalid_field_types = [
			"Column Break",
			"Fold",
			"Heading",
			"Read Only",
			"Section Break",
			"Tab Break",
			"Table",
			"Table MultiSelect",
		]
		field_type_filter = (
			["fieldtype", "=", field_type] if field_type else ["fieldtype", "not in", invalid_field_types]
		)
		mandatory_fields_filters = [["reqd", "=", "1"]] if mandatory_fields_only else []
		docfields = frappe.get_all(
			"DocField",
			fields=["label", "name", "fieldname"],
			filters=[field_type_filter, ["parent", "=", doctype], *mandatory_fields_filters],
		)
		custom_fields = frappe.get_all(
			"Custom Field",
			fields=["label", "name", "fieldname"],
			filters=[
				field_type_filter,
				["dt", "=", doctype],
				*mandatory_fields_filters,
			],
		)
		return docfields + custom_fields


def get_context(doc):
	Frappe = namedtuple("frappe", ["utils"])
	return {
		"doc": doc,
		"nowdate": nowdate,
		"frappe": Frappe(utils=get_safe_globals().get("frappe").get("utils")),
	}
