# Copyright (c) 2025, Finfoot Tech (Pty) Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from collections import namedtuple
from frappe.utils import nowdate
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


def get_context(doc):
	Frappe = namedtuple("frappe", ["utils"])
	return {
		"doc": doc,
		"nowdate": nowdate,
		"frappe": Frappe(utils=get_safe_globals().get("frappe").get("utils")),
	}
