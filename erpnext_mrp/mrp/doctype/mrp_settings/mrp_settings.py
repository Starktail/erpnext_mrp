# Copyright (c) 2025, Finfoot Tech (Pty) Ltd and contributors
# For license information, please see license.txt

from collections import namedtuple

import frappe
from frappe import _
from frappe.model import no_value_fields
from frappe.model.document import Document
from frappe.utils import now_datetime, nowdate
from frappe.utils.caching import redis_cache
from frappe.utils.safe_exec import get_safe_globals


class MRPSettings(Document):
	def validate(self):
		self.validate_condition()
		if any(self.has_value_changed(fieldname) for fieldname in self.get_calculation_fields()):
			self.calculation_settings_changed_on = now_datetime()

	def get_calculation_fields(self) -> list[str]:
		"""
		The fields on the Calculation Settings tab. Changing any of them changes the MRP results,
		unlike the display tabs, which only change how the same results are shown.
		"""
		fieldnames = []
		in_calculation_tab = False
		for df in self.meta.fields:
			if df.fieldtype == "Tab Break":
				in_calculation_tab = df.fieldname == "calculation_settings_tab"
			elif (
				in_calculation_tab
				and df.fieldtype not in no_value_fields
				and df.fieldname != "calculation_settings_changed_on"
			):
				fieldnames.append(df.fieldname)
		return fieldnames

	def on_update(self):
		self.clear_stockout_flags()

	def clear_stockout_flags(self):
		"""
		Stockout flags only mean something while suggestions are deferred within the lead time.
		Clear them as soon as the setting is turned off, rather than leaving stale flags until
		the next MRP run.
		"""
		if self.defer_suggestions_within_lead_time:
			return
		frappe.db.set_value(
			"MRP Entry",
			{"has_stockout": 1},
			{"has_stockout": 0, "first_stockout_date": None, "stockout_qty": 0},
			update_modified=False,
		)

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
