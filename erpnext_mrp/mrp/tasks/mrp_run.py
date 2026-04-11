import datetime
import itertools
import math
from datetime import date

_NO_REORDER_SENTINEL = 9999

import frappe
from erpnext.controllers.accounts_controller import get_due_date, get_payment_terms
from erpnext.stock.report.stock_balance.stock_balance import execute as execute_stock_balance_report
from frappe import _
from frappe.utils import add_days, getdate
from pypika import Order

from erpnext_mrp.mrp.doctype.mrp_settings.mrp_settings import get_context


@frappe.whitelist()
def trigger_mrp_run():
	frappe.get_doc("Scheduled Job Type", "mrp_run.mrp_run").enqueue(force=True)


@frappe.whitelist()
def get_forecast_coverage_status() -> dict:
	settings = frappe.get_cached_doc("MRP Settings")
	look_ahead: int = settings.look_ahead or 6
	requirement_based_on: str = settings.requirement_based_on or "Forecast only"

	if requirement_based_on == "Open Orders only":
		return {
			"covered": True,
			"requirement_based_on": requirement_based_on,
			"look_ahead_weeks": look_ahead,
			"look_ahead_end_date": None,
			"max_forecast_date": None,
			"weeks_short": 0,
		}

	today = date.today()
	look_ahead_end_date = today + datetime.timedelta(weeks=look_ahead)

	row = frappe.db.sql(
		"SELECT MAX(forecast_date) AS max_date FROM `tabMRP Forecast`",
		as_dict=True,
	)
	max_forecast_date = row[0].get("max_date") if row else None

	if max_forecast_date is None:
		weeks_short = look_ahead
		covered = False
	elif getdate(max_forecast_date) >= getdate(look_ahead_end_date):
		weeks_short = 0
		covered = True
	else:
		gap_days = (getdate(look_ahead_end_date) - getdate(max_forecast_date)).days
		weeks_short = math.ceil(gap_days / 7)
		covered = False

	return {
		"covered": covered,
		"requirement_based_on": requirement_based_on,
		"look_ahead_weeks": look_ahead,
		"look_ahead_end_date": str(look_ahead_end_date),
		"max_forecast_date": str(max_forecast_date) if max_forecast_date else None,
		"weeks_short": weeks_short,
	}


def mrp_run(enqueue: bool = True):
	create_mrp_item_entries()
	process_mrp_item_entries(enqueue=enqueue)


def create_mrp_item_entries():
	"""
	Calculate BOM levels and create MRP Entry records for each item for each week in a look-ahead period.

	This function is idempotent: it clears all existing MRP Entry records before inserting
	the newly calculated levels. The BOM level is determined by the deepest nesting level of an item in all **default** BOMs.
	- Level 0: Top-level items that are not used as components in any other default BOM.
	- Level n: Components that are n levels deep in a default BOM hierarchy.

	This implementation uses a raw recursive SQL query for better performance.

	We use frappe.db.sql because WITH RECURSIVE is a special construct that frappe.qb/pypika do not expose.
	"""
	# 1. Clear all existing records from the MRP Entry table
	frappe.db.delete("MRP Entry")

	settings = frappe.get_cached_doc("MRP Settings")
	lead_time_field = "lead_time_days"
	if settings.item_lead_time_field:
		lead_time_field = settings.item_lead_time_field.split("|")[0].strip()

	additional_lead_time_field = None
	if settings.item_additional_lead_time_field:
		additional_lead_time_field = settings.item_additional_lead_time_field.split("|")[0].strip()

	if additional_lead_time_field:
		lead_time_expression = f"COALESCE(t_item.`{lead_time_field}`, 0) + COALESCE(CAST(NULLIF(t_item.`{additional_lead_time_field}`, '') AS SIGNED), 0)"
	else:
		lead_time_expression = f"t_item.`{lead_time_field}`"

	# 2. Run the recursive query to get all items and their BOM levels
	sql_query = f""" # nosemgrep: frappe-sql-format-injection
        WITH RECURSIVE bom_hierarchy (item_code, level, root_bom) AS (
			-- Anchor: root items (not a component in any active, default BOM)
			SELECT
				t_item.name AS item_code,
				0 AS level,
				(
					SELECT b.name
					FROM `tabBOM` b
					WHERE b.item = t_item.name
					AND b.is_active = 1
					AND b.is_default = 1
					LIMIT 1
				) AS root_bom
			FROM `tabItem` AS t_item
			WHERE t_item.name NOT IN (
				SELECT DISTINCT bi.item_code
				FROM `tabBOM Item` bi
				JOIN `tabBOM` b ON bi.parent = b.name
				WHERE b.is_active = 1
				AND b.is_default = 1
			)

			UNION ALL

			-- Recursive: explode components; keep the same root_bom flowing downward
			SELECT
				bi.item_code AS item_code,
				bh.level + 1 AS level,
				bh.root_bom AS root_bom
			FROM `tabBOM Item` bi
			JOIN `tabBOM` b ON bi.parent = b.name
			JOIN bom_hierarchy bh ON b.item = bh.item_code
			WHERE b.is_active = 1
			AND b.is_default = 1
		),
		bom_rollup AS (
			SELECT
				item_code,
				MAX(level) AS bom_level,
				GROUP_CONCAT(DISTINCT root_bom ORDER BY root_bom SEPARATOR ', ') AS root_bom_names
			FROM bom_hierarchy
			GROUP BY item_code
		)

		SELECT
			t_item.name AS item_code,
			{lead_time_expression} AS lead_time,
			COALESCE(br.bom_level, 0) AS bom_level,
			br.root_bom_names AS root_bom_name,
			(EXISTS (
				SELECT 1
				FROM `tabBOM` b
				WHERE b.item = t_item.name
				AND b.is_active = 1
				AND b.is_default = 1
			)) AS is_manufactured,
			0 AS is_header
		FROM `tabItem` AS t_item
		LEFT JOIN bom_rollup br ON t_item.name = br.item_code
		WHERE t_item.disabled = 0
		AND t_item.is_stock_item = 1;

    """
	item_list = frappe.db.sql(sql_query)  # nosemgrep

	# 3. Generate weekly periods for the look-ahead horizon
	if settings.item_condition:
		item_codes = [item[0] for item in item_list]
		item_docs = frappe.get_all("Item", filters={"name": ("in", item_codes)}, fields=["*"])

		valid_item_codes = set()
		for item_doc in item_docs:
			context = get_context(item_doc)
			if frappe.safe_eval(settings.item_condition, None, context):
				valid_item_codes.add(item_doc.name)

		item_list = [item for item in item_list if item[0] in valid_item_codes]

	if settings.periods_type != "Calendar Week":
		raise ValueError(_("Only 'Calendar Week' is a supported period type"))
	look_ahead = settings.look_ahead or 6

	today = date.today()
	# Use a dictionary to store unique periods with their target dates
	periods = {}
	for i in range(look_ahead):
		target_date = today + datetime.timedelta(weeks=i)
		year, week, _unused = target_date.isocalendar()
		period_str = f"-{year}CW{week:02d}"
		if period_str not in periods:
			periods[period_str] = target_date

	# Convert to a list of items for itertools
	period_data = list(periods.items())

	# 4. Efficiently combine items and periods and prepare for bulk insert
	# item is a tuple: (item_code, lead_time, bom_level, root_bom, is_manufactured, is_header)
	# period is a tuple: (period_str, target_date)
	owner = frappe.session.user
	creation = datetime.datetime.now()
	final_values = [
		(
			f"{item[0]}{period[0]}",
			item[0],
			item[1],
			item[2],
			item[3],
			item[4],
			1 if period[0] == period_data[0][0] else 0,
			period[1],
			owner,
			creation,
		)
		for item, period in itertools.product(item_list, period_data)
	]

	# 5. Don't store bom_levels on every period, only the first period
	final_values = [
		(*row[:4], row[4] if period_data[0][0] in row[0] else None, *row[5:]) for row in final_values
	]

	# 6. Perform a bulk insert of all generated records
	frappe.db.bulk_insert(
		"MRP Entry",
		fields=[
			"name",
			"item_code",
			"lead_time",
			"bom_level",
			"bom_list",
			"is_manufactured",
			"is_header",
			"target_date",
			"owner",
			"creation",
		],
		values=final_values,
		ignore_duplicates=True,
	)


def process_mrp_item_entries(enqueue: bool):
	"""
	Main background task to process all MRP calculations for each item and period.
	"""
	_update_reserved_qty()
	_update_reserved_qty_for_production()
	_update_forecast_demand()
	_update_planned_qty()
	_update_ordered_qty()
	_process_levels_sequentially(enqueue=enqueue)


def _update_forecast_demand():
	"""
	Calculates forecast quantities for each item and week, then bulk updates MRP Entry.
	"""
	settings = frappe.get_cached_doc("MRP Settings")
	look_ahead = settings.look_ahead or 6
	start_date = date.today()
	end_date = start_date + datetime.timedelta(weeks=look_ahead)

	sql_query = """
        SELECT
            item_code,
            CASE
                WHEN forecast_date < %(start_date)s THEN DATE_FORMAT(%(start_date)s, '%%xCW%%v')
                ELSE DATE_FORMAT(forecast_date, '%%xCW%%v')
            END AS calendar_week,
            SUM(forecast_quantity) AS total_forecast_quantity
        FROM `tabMRP Forecast`
        WHERE forecast_date <= %(end_date)s
        GROUP BY item_code, calendar_week;
    """
	forecast_data = frappe.db.sql(
		sql_query, values={"start_date": start_date, "end_date": end_date}, as_dict=True
	)

	if not forecast_data:
		return

	# Use a CASE statement for efficient bulk updates
	update_cases = []
	mrp_entry_names = []
	for row in forecast_data:
		mrp_entry_name = f"{row.item_code}-{row.calendar_week}"
		mrp_entry_names.append(frappe.db.escape(mrp_entry_name))
		update_cases.append(
			f"WHEN name = {frappe.db.escape(mrp_entry_name)} THEN {row.total_forecast_quantity}"
		)

	if not mrp_entry_names:
		return

	case_str = " ".join(update_cases)
	names_str = ", ".join(mrp_entry_names)

	update_query = f"""# nosemgrep: frappe-sql-format-injection
        UPDATE `tabMRP Entry`
        SET forecast_demand = CASE
            {case_str}
            ELSE forecast_demand
        END
        WHERE name IN ({names_str})
    """
	frappe.db.sql(update_query)


def _update_reserved_qty():
	"""
	Calculates open sales order quantities for each item and week, then bulk updates MRP Entry.

	This query is an adaptation of the standard ERPNext reserved quantity calculation,
	modified to group results by the calendar week of the Sales Order Item's delivery date.

	Same as Bin > reserved_qty.
	Based on erpnext/stock/stock_balance.py > get_reserved_qty
	"""
	settings = frappe.get_cached_doc("MRP Settings")
	look_ahead = settings.look_ahead or 6
	start_date = date.today()
	end_date = start_date + datetime.timedelta(weeks=look_ahead)

	# Note: DATE_FORMAT(date, '%%xCW%%v') is used to create the week string, e.g., '2025CW39'.
	# The double '%' is to escape the '%' for the frappe.db.sql parameter substitution.
	sql_query = """
        SELECT
            item_code,
            CASE
                WHEN delivery_date < %(start_date)s THEN DATE_FORMAT(%(start_date)s, '%%xCW%%v')
                ELSE DATE_FORMAT(delivery_date, '%%xCW%%v')
            END AS calendar_week,
            SUM(reserved_qty) AS total_reserved_qty
        FROM (
            SELECT
                item_code,
                delivery_date,
                (
                    dnpi_qty * (
                        (so_item_qty - so_item_delivered_qty - IF(dont_reserve_qty_on_return, so_item_returned_qty, 0))
                        / so_item_qty
                    )
                ) AS reserved_qty
            FROM (
                SELECT
                    dnpi.item_code,
                    dnpi.qty AS dnpi_qty,
                    soi.qty AS so_item_qty,
                    soi.delivered_qty AS so_item_delivered_qty,
                    soi.returned_qty AS so_item_returned_qty,
                    soi.delivery_date,
                    0 AS dont_reserve_qty_on_return
                FROM `tabPacked Item` AS dnpi
                JOIN `tabSales Order Item` AS soi ON dnpi.parent_detail_docname = soi.name
                JOIN `tabSales Order` AS so ON dnpi.parent = so.name
                WHERE so.docstatus = 1
                    AND so.status NOT IN ('On Hold', 'Closed')
                    AND (soi.delivered_by_supplier IS NULL OR soi.delivered_by_supplier = 0)
                    AND dnpi.item_code != dnpi.parent_item

                UNION ALL

                SELECT
                    so_item.item_code,
                    so_item.stock_qty AS dnpi_qty,
                    so_item.qty AS so_item_qty,
                    so_item.delivered_qty AS so_item_delivered_qty,
                    so_item.returned_qty AS so_item_returned_qty,
                    so_item.delivery_date,
                    0 AS dont_reserve_qty_on_return
                FROM `tabSales Order Item` AS so_item
                JOIN `tabSales Order` AS so ON so_item.parent = so.name
                WHERE so.docstatus = 1
                    AND so.status NOT IN ('On Hold', 'Closed')
                    AND (so_item.delivered_by_supplier IS NULL OR so_item.delivered_by_supplier = 0)
            ) AS combined_so_items
            WHERE so_item_qty >= so_item_delivered_qty
        ) AS final_so_data
        WHERE delivery_date <= %(end_date)s
        GROUP BY item_code, calendar_week;
    """
	open_orders_data = frappe.db.sql(
		sql_query, values={"start_date": start_date, "end_date": end_date}, as_dict=True
	)

	if not open_orders_data:
		return

	# Use a CASE statement for efficient bulk updates
	update_cases = []
	mrp_entry_names = []
	for row in open_orders_data:
		mrp_entry_name = f"{row.item_code}-{row.calendar_week}"
		mrp_entry_names.append(frappe.db.escape(mrp_entry_name))
		update_cases.append(f"WHEN name = {frappe.db.escape(mrp_entry_name)} THEN {row.total_reserved_qty}")

	if not mrp_entry_names:
		return

	case_str = " ".join(update_cases)
	names_str = ", ".join(mrp_entry_names)

	update_query = f"""# nosemgrep: frappe-sql-format-injection
        UPDATE `tabMRP Entry`
        SET reserved_qty = CASE
            {case_str}
            ELSE reserved_qty
        END
        WHERE name IN ({names_str})
    """
	frappe.db.sql(update_query)


def _update_reserved_qty_for_production():
	"""
	Calculates material requirements from open Work Orders for each item and week, then bulk updates MRP Entry

	Same as Bin > reserved_qty_for_production.
	Based on erpnext/manufacturing/doctype/work_order/work_order.py > get_reserved_qty_for_production
	"""
	settings = frappe.get_cached_doc("MRP Settings")
	look_ahead = settings.look_ahead or 6
	start_date = date.today()
	end_date = start_date + datetime.timedelta(weeks=look_ahead)

	sql_query = """
        SELECT
            wo_item.item_code,
            CASE
                WHEN wo.planned_start_date < %(start_date)s THEN DATE_FORMAT(%(start_date)s, '%%xCW%%v')
                ELSE DATE_FORMAT(wo.planned_start_date, '%%xCW%%v')
            END AS calendar_week,
            SUM(wo_item.required_qty - wo_item.transferred_qty) AS total_required_qty
        FROM `tabWork Order Item` AS wo_item
        JOIN `tabWork Order` AS wo ON wo_item.parent = wo.name
        WHERE wo.docstatus = 1
            AND wo.status NOT IN ('Completed', 'Stopped', 'Closed', 'Cancelled')
            AND wo.planned_start_date <= %(end_date)s
            AND (wo_item.required_qty > wo_item.transferred_qty)
        GROUP BY
            wo_item.item_code,
            calendar_week;
    """
	production_demand_data = frappe.db.sql(
		sql_query, values={"start_date": start_date, "end_date": end_date}, as_dict=True
	)

	if not production_demand_data:
		return

	update_cases = []
	mrp_entry_names = []
	for row in production_demand_data:
		mrp_entry_name = f"{row.item_code}-{row.calendar_week}"
		mrp_entry_names.append(frappe.db.escape(mrp_entry_name))
		update_cases.append(
			f"WHEN name = {frappe.db.escape(mrp_entry_name)} THEN COALESCE(reserved_qty_for_production, 0) + {row.total_required_qty}"
		)

	if not mrp_entry_names:
		return

	case_str = " ".join(update_cases)
	names_str = ", ".join(mrp_entry_names)

	update_query = f"""# nosemgrep: frappe-sql-format-injection
        UPDATE `tabMRP Entry`
        SET reserved_qty_for_production = CASE
            {case_str}
            ELSE reserved_qty_for_production
        END
        WHERE name IN ({names_str});
    """
	frappe.db.sql(update_query)


def _update_planned_qty():
	"""
	Calculates open Work Order quantities (planned receipts) for each item and week,
	then bulk updates the 'scheduled_receipts' field in MRP Entry.
	Equivalent to Bin > planned_qty.
	"""
	settings = frappe.get_cached_doc("MRP Settings")
	look_ahead = settings.look_ahead or 6
	start_date = date.today()
	end_date = start_date + datetime.timedelta(weeks=look_ahead)

	sql_query = """
        SELECT
            production_item,
            CASE
                WHEN planned_start_date < %(start_date)s THEN DATE_FORMAT(%(start_date)s, '%%xCW%%v')
                ELSE DATE_FORMAT(planned_start_date, '%%xCW%%v')
            END AS calendar_week,
            SUM(qty - produced_qty) AS total_planned_qty
        FROM `tabWork Order`
        WHERE
            status NOT IN ('Stopped', 'Completed', 'Closed', 'Cancelled')
            AND docstatus = 1
            AND qty > produced_qty
            AND planned_start_date <= %(end_date)s
        GROUP BY
            production_item,
            calendar_week;
    """
	planned_data = frappe.db.sql(
		sql_query, values={"start_date": start_date, "end_date": end_date}, as_dict=True
	)

	if not planned_data:
		return

	update_cases = []
	mrp_entry_names = []
	for row in planned_data:
		mrp_entry_name = f"{row.production_item}-{row.calendar_week}"
		mrp_entry_names.append(frappe.db.escape(mrp_entry_name))
		update_cases.append(
			f"WHEN name = {frappe.db.escape(mrp_entry_name)} THEN COALESCE(planned_qty, 0) + {row.total_planned_qty}"
		)

	if not mrp_entry_names:
		return

	case_str = " ".join(update_cases)
	names_str = ", ".join(mrp_entry_names)

	update_query = f"""# nosemgrep: frappe-sql-format-injection
        UPDATE `tabMRP Entry`
        SET planned_qty = CASE
            {case_str}
            ELSE planned_qty
        END
        WHERE name IN ({names_str});
    """
	frappe.db.sql(update_query)


def _update_ordered_qty():
	"""
	Calculates open Purchase Order quantities (ordered receipts) for each item and week,
	then bulk updates the 'scheduled_receipts' field in MRP Entry.
	Equivalent to Bin > ordered_qty.
	"""
	settings = frappe.get_cached_doc("MRP Settings")
	look_ahead = settings.look_ahead or 6
	start_date = date.today()
	end_date = start_date + datetime.timedelta(weeks=look_ahead)

	receiving_date_field = "schedule_date"
	if settings.po_item_delivery_date_field:
		receiving_date_field = settings.po_item_delivery_date_field.split("|")[0].strip()

	receiving_date_expression = f"po_item.`{receiving_date_field}`"

	partial_receipt_condition = ""
	if not settings.assume_remaining_qty:
		partial_receipt_condition = "AND (po_item.received_qty = 0 OR po_item.received_qty IS NULL)"

	sql_query = f"""# nosemgrep: frappe-sql-format-injection
        SELECT
            po_item.item_code,
            CASE
                WHEN {receiving_date_expression} < %(start_date)s THEN DATE_FORMAT(%(start_date)s, '%%xCW%%v')
                ELSE DATE_FORMAT({receiving_date_expression}, '%%xCW%%v')
            END AS calendar_week,
            SUM((po_item.qty - po_item.received_qty) * po_item.conversion_factor) AS total_ordered_qty,
            SUM((po_item.qty - po_item.received_qty) * po_item.base_rate) AS total_ordered_value
        FROM `tabPurchase Order Item` AS po_item
        JOIN `tabPurchase Order` AS po ON po_item.parent = po.name
        WHERE
            po_item.qty > po_item.received_qty
            AND po.status NOT IN ('Closed', 'Delivered', 'Cancelled')
            AND po.docstatus = 1
            AND (po_item.delivered_by_supplier IS NULL OR po_item.delivered_by_supplier = 0)
            AND {receiving_date_expression} <= %(end_date)s
            {partial_receipt_condition}
        GROUP BY
            po_item.item_code,
            calendar_week;
    """
	ordered_data = frappe.db.sql(
		sql_query, values={"start_date": start_date, "end_date": end_date}, as_dict=True
	)

	if not ordered_data:
		return

	qty_cases: list[str] = []
	value_cases: list[str] = []
	mrp_entry_names: list[str] = []
	for row in ordered_data:
		mrp_entry_name = f"{row.item_code}-{row.calendar_week}"
		escaped = frappe.db.escape(mrp_entry_name)
		mrp_entry_names.append(escaped)
		qty_cases.append(f"WHEN name = {escaped} THEN COALESCE(ordered_qty, 0) + {row.total_ordered_qty}")
		value_cases.append(
			f"WHEN name = {escaped} THEN COALESCE(scheduled_receipts_value, 0) + {row.total_ordered_value}"
		)

	if not mrp_entry_names:
		return

	qty_case_str = " ".join(qty_cases)
	value_case_str = " ".join(value_cases)
	names_str = ", ".join(mrp_entry_names)

	update_query = f"""# nosemgrep: frappe-sql-format-injection
        UPDATE `tabMRP Entry`
        SET
            ordered_qty = CASE {qty_case_str} ELSE ordered_qty END,
            scheduled_receipts_value = CASE {value_case_str} ELSE scheduled_receipts_value END
        WHERE name IN ({names_str});
    """
	frappe.db.sql(update_query)


def _get_all_item_details() -> dict[str, frappe._dict]:
	settings = frappe.get_cached_doc("MRP Settings")

	lead_time_field = "lead_time_days"
	if settings.item_lead_time_field:
		lead_time_field = settings.item_lead_time_field.split("|")[0].strip()

	additional_lead_time_field = None
	if settings.item_additional_lead_time_field:
		additional_lead_time_field = settings.item_additional_lead_time_field.split("|")[0].strip()

	if additional_lead_time_field:
		lead_time_expression = f"COALESCE(t_item.`{lead_time_field}`, 0)"
		additional_lead_time_expression = (
			f"COALESCE(CAST(NULLIF(t_item.`{additional_lead_time_field}`, '') AS SIGNED), 0)"
		)
	else:
		lead_time_expression = f"t_item.`{lead_time_field}`"
		additional_lead_time_expression = "0"

	reorder_qty_field = "min_order_qty"
	if settings.reorder_qty_item_field:
		reorder_qty_field = settings.reorder_qty_item_field.split("|")[0].strip()

	item_details_query = f"""# nosemgrep: frappe-sql-format-injection
        SELECT DISTINCT
            mrp.item_code,
            t_item.safety_stock,
            t_item.{reorder_qty_field} AS reorder_quantity,
            t_item.valuation_rate AS fall_back_valuation_rate,
            {lead_time_expression} AS primary_lead_time,
            {additional_lead_time_expression} AS additional_lead_time,
            id.default_supplier
        FROM `tabMRP Entry` AS mrp
        JOIN `tabItem` AS t_item ON mrp.item_code = t_item.name
        LEFT JOIN `tabItem Default` AS id
            ON mrp.item_code = id.parent AND id.default_supplier IS NOT NULL
    """
	rows = frappe.db.sql(item_details_query, as_dict=True)  # nosemgrep
	return {row.item_code: row for row in rows}


def _fetch_grouped_mrp_entries(item_codes: list[str]) -> dict[str, list[frappe._dict]]:
	mrp_entries_dicts = frappe.get_all(
		"MRP Entry",
		filters={"item_code": ("in", item_codes)},
		fields=["*"],
		order_by="item_code, target_date asc",
	)
	grouped: dict[str, list[frappe._dict]] = {}
	for entry_dict in mrp_entries_dicts:
		grouped.setdefault(entry_dict.item_code, []).append(entry_dict)
	return grouped


def _calculate_suggested_receipts_batch(
	item_codes: list[str],
	item_details_map: dict[str, frappe._dict],
	stock_levels: list,
	requirement_based_on: str,
) -> None:
	grouped_mrp_entries = _fetch_grouped_mrp_entries(item_codes)

	for item_code, item_mrp_entries_dicts in grouped_mrp_entries.items():
		mrp_entry_docs = [frappe.get_doc("MRP Entry", d.name) for d in item_mrp_entries_dicts]
		item_details = item_details_map.get(item_code)

		mrp_entry_docs[0].on_hand_inventory = sum(
			sl.bal_qty for sl in stock_levels if sl.item_code == item_code
		)
		mrp_entry_docs[0].on_hand_inventory_excl_reorder_level = mrp_entry_docs[0].on_hand_inventory
		mrp_entry_docs[0].on_hand_inventory_no_action = mrp_entry_docs[0].on_hand_inventory

		for index, entry in enumerate(mrp_entry_docs):
			if index != 0:
				entry.on_hand_inventory_no_action = mrp_entry_docs[
					index - 1
				].projected_on_hand_inventory_no_action
				entry.on_hand_inventory = mrp_entry_docs[index - 1].projected_on_hand_inventory
				entry.on_hand_inventory_excl_reorder_level = mrp_entry_docs[
					index - 1
				].projected_on_hand_inventory_excl_reorder_level
			if item_details:
				entry.reorder_level = item_details.get("safety_stock")
				entry.reorder_quantity = item_details.get("reorder_quantity")
				entry.default_supplier = item_details.get("default_supplier")

			open_orders = entry.open_orders or 0
			forecast_demand = entry.forecast_demand or 0
			upstream_net_demand = entry.upstream_net_demand or 0

			if requirement_based_on == "Forecast only":
				demand = forecast_demand
			elif requirement_based_on == "Open Orders only":
				demand = open_orders
			elif requirement_based_on == "Open Orders + Forecast":
				demand = open_orders + forecast_demand
			elif requirement_based_on == "Open Orders + Forecast (orders consume the forecast)":
				demand = open_orders + max(0, forecast_demand - open_orders)
			else:
				raise ValueError(_("Unkown 'Requirement based on' setting"))

			demand += upstream_net_demand

			entry.suggested_receipts = 0
			shortage = (
				(entry.on_hand_inventory or 0)
				- demand
				+ (entry.scheduled_receipts or 0)
				- (entry.reorder_level or 0)
			)
			if shortage < 0:
				moq = entry.reorder_quantity or 1
				entry.suggested_receipts = math.ceil(-shortage / moq) * moq

			entry.projected_on_hand_inventory = (
				(entry.on_hand_inventory or 0)
				- demand
				+ (entry.scheduled_receipts or 0)
				+ (entry.suggested_receipts or 0)
			)

			entry.suggested_receipts_excl_reorder_level = 0
			shortage_excl = (
				(entry.on_hand_inventory_excl_reorder_level or 0) - demand + (entry.scheduled_receipts or 0)
			)
			if shortage_excl < 0:
				moq = entry.reorder_quantity or 1
				entry.suggested_receipts_excl_reorder_level = math.ceil(-shortage_excl / moq) * moq

			entry.projected_on_hand_inventory_excl_reorder_level = (
				(entry.on_hand_inventory_excl_reorder_level or 0)
				- demand
				+ (entry.scheduled_receipts or 0)
				+ (entry.suggested_receipts_excl_reorder_level or 0)
			)

			entry.projected_on_hand_inventory_no_action = (
				(entry.on_hand_inventory_no_action or 0) - demand + (entry.scheduled_receipts or 0)
			)

		for entry in mrp_entry_docs:
			entry.save()


def _fetch_open_po_lines_for_items(item_codes: list[str]) -> dict[str, list[frappe._dict]]:
	if not item_codes:
		return {}

	settings = frappe.get_cached_doc("MRP Settings")
	partial_receipt_condition = ""
	if not settings.assume_remaining_qty:
		partial_receipt_condition = "AND (po_item.received_qty = 0 OR po_item.received_qty IS NULL)"

	placeholders = ", ".join([frappe.db.escape(c) for c in item_codes])

	arrival_date_col = (
		"po_item.custom_expected_arrival_date"
		if frappe.db.has_column("Purchase Order Item", "custom_expected_arrival_date")
		else "NULL"
	)

	sql_query = f"""# nosemgrep: frappe-sql-format-injection
        SELECT
            po_item.item_code,
            po.transaction_date,
            po_item.schedule_date,
            {arrival_date_col} AS custom_expected_arrival_date,
            (po_item.qty - po_item.received_qty) * po_item.base_rate AS remaining_value
        FROM `tabPurchase Order Item` AS po_item
        JOIN `tabPurchase Order` AS po ON po_item.parent = po.name
        WHERE
            po_item.qty > po_item.received_qty
            AND po.status NOT IN ('Closed', 'Delivered', 'Cancelled')
            AND po.docstatus = 1
            AND (po_item.delivered_by_supplier IS NULL OR po_item.delivered_by_supplier = 0)
            AND po_item.item_code IN ({placeholders})
            {partial_receipt_condition}
    """
	rows = frappe.db.sql(sql_query, as_dict=True)  # nosemgrep

	grouped: dict[str, list[frappe._dict]] = {}
	for row in rows:
		grouped.setdefault(row.item_code, []).append(row)
	return grouped


def _finalise_item_batch(
	item_codes: list[str],
	item_details_map: dict[str, frappe._dict],
	stock_levels: list,
	item_prices: dict[str, float],
	supplier_payment_terms: dict[str, str],
	payment_term_details: dict[str, frappe._dict],
	total_batches: int = 1,
) -> None:
	grouped_mrp_entries = _fetch_grouped_mrp_entries(item_codes)
	po_lines_by_item = _fetch_open_po_lines_for_items(item_codes)

	for item_code, item_mrp_entries_dicts in grouped_mrp_entries.items():
		mrp_entry_docs = [frappe.get_doc("MRP Entry", d.name) for d in item_mrp_entries_dicts]
		item_details = item_details_map.get(item_code)

		price = item_prices.get(item_code)
		if not price:
			item_stock_levels = [
				sl.val_rate for sl in stock_levels if sl.item_code == item_code and sl.val_rate > 0
			]
			valuation_rate = sum(item_stock_levels) / len(item_stock_levels) if item_stock_levels else 0
			price = valuation_rate or (item_details.get("fall_back_valuation_rate") if item_details else None)

		for index, entry in reversed(list(enumerate(mrp_entry_docs))):
			if entry.suggested_receipts:
				weeks_before = math.ceil(entry.lead_time / 7)
				if index - weeks_before < 0:
					mrp_entry_docs[0].suggested_orders = (
						mrp_entry_docs[0].suggested_orders or 0
					) + entry.suggested_receipts
				else:
					mrp_entry_docs[index - weeks_before].suggested_orders = (
						mrp_entry_docs[index - weeks_before].suggested_orders or 0
					) + entry.suggested_receipts

		today = date.today()

		first_shortage_entry = next((e for e in mrp_entry_docs if e.suggested_receipts > 0), None)
		if first_shortage_entry:
			needed_date = getdate(first_shortage_entry.target_date)
			lead_time = first_shortage_entry.lead_time or 0
			order_date = add_days(needed_date, -lead_time)
			mrp_entry_docs[0].days_to_reorder = (getdate(order_date) - today).days
			mrp_entry_docs[0].needs_reorder = 1
		else:
			mrp_entry_docs[0].days_to_reorder = _NO_REORDER_SENTINEL
			mrp_entry_docs[0].needs_reorder = 0

		first_shortage_excl_entry = next(
			(e for e in mrp_entry_docs if e.suggested_receipts_excl_reorder_level > 0), None
		)
		if first_shortage_excl_entry:
			needed_date = getdate(first_shortage_excl_entry.target_date)
			lead_time = first_shortage_excl_entry.lead_time or 0
			order_date = add_days(needed_date, -lead_time)
			mrp_entry_docs[0].days_to_reorder_excl_reorder_level = (getdate(order_date) - today).days
			mrp_entry_docs[0].needs_reorder_excl_reorder_level = 1
		else:
			mrp_entry_docs[0].days_to_reorder_excl_reorder_level = _NO_REORDER_SENTINEL
			mrp_entry_docs[0].needs_reorder_excl_reorder_level = 0

		if price and price > 0:
			for entry in mrp_entry_docs:
				if entry.suggested_orders:
					new_value = entry.suggested_orders * price
					if entry.suggested_orders_value != new_value:
						entry.suggested_orders_value = new_value

		supplier_name = item_details.get("default_supplier") if item_details else None
		payment_terms_template = supplier_payment_terms.get(supplier_name) if supplier_name else None

		if supplier_name and payment_terms_template:
			entry_map = {e.name: e for e in mrp_entry_docs}
			for entry in mrp_entry_docs:
				if entry.suggested_orders_value:
					schedule = get_payment_terms(
						payment_terms_template,
						posting_date=entry.target_date,
						grand_total=entry.suggested_orders_value,
						base_grand_total=entry.suggested_orders_value,
					)
					if schedule:
						for term in schedule:
							base_date = None
							payment_term_name = term.get("payment_term")
							if payment_term_name:
								custom_due_date_type = payment_term_details.get(payment_term_name, {}).get(
									"custom_due_date"
								)
								if custom_due_date_type == "Order date":
									base_date = entry.target_date
								elif custom_due_date_type == "Shipment date":
									base_date = add_days(
										entry.target_date, item_details.get("primary_lead_time") or 0
									)
								elif custom_due_date_type == "Arrival date":
									total_lead_time = (item_details.get("primary_lead_time") or 0) + (
										item_details.get("additional_lead_time") or 0
									)
									base_date = add_days(entry.target_date, total_lead_time)
								else:
									base_date = entry.target_date
							if base_date:
								term.due_date = get_due_date(term, posting_date=base_date)
							due_date = term.get("due_date")
							payment_amount = term.get("payment_amount")
							if due_date and payment_amount:
								year, week, _day = getdate(due_date).isocalendar()
								target_name = f"{item_code}-{year}CW{week:02d}"
								target_entry = entry_map.get(target_name)
								if target_entry:
									target_entry.suggested_orders_value_payable = (
										target_entry.suggested_orders_value_payable or 0
									) + payment_amount
								elif getdate(due_date) < mrp_entry_docs[0].target_date:
									mrp_entry_docs[0].suggested_orders_value_payable = (
										mrp_entry_docs[0].suggested_orders_value_payable or 0
									) + payment_amount
		else:
			for entry in mrp_entry_docs:
				entry.suggested_orders_value_payable = entry.suggested_orders_value

		# Calculate Scheduled Receipts Payable using actual PO dates.
		# Each open PO line is processed individually so its own transaction_date (order),
		# schedule_date (shipment/ETD), and custom_expected_arrival_date (arrival/ETA) can be used
		# as the base date for the matching payment term type.
		item_po_lines = po_lines_by_item.get(item_code, [])

		if supplier_name and payment_terms_template and item_po_lines:
			entry_map = {e.name: e for e in mrp_entry_docs}
			for po_line in item_po_lines:
				remaining_value = po_line.get("remaining_value") or 0
				if not remaining_value:
					continue

				order_date = (
					getdate(po_line.get("transaction_date")) if po_line.get("transaction_date") else None
				)
				shipment_date = (
					getdate(po_line.get("schedule_date")) if po_line.get("schedule_date") else None
				)
				arrival_date = (
					getdate(po_line.get("custom_expected_arrival_date"))
					if po_line.get("custom_expected_arrival_date")
					else shipment_date
				)
				posting_date = arrival_date or shipment_date or order_date or date.today()

				schedule = get_payment_terms(
					payment_terms_template,
					posting_date=posting_date,
					grand_total=remaining_value,
					base_grand_total=remaining_value,
				)
				if not schedule:
					continue

				for term in schedule:
					base_date = None
					payment_term_name = term.get("payment_term")
					if payment_term_name:
						custom_due_date_type = payment_term_details.get(payment_term_name, {}).get(
							"custom_due_date"
						)
						if custom_due_date_type == "Order date":
							base_date = order_date
						elif custom_due_date_type == "Shipment date":
							base_date = shipment_date
						elif custom_due_date_type == "Arrival date":
							base_date = arrival_date
						else:
							base_date = posting_date

					if base_date:
						term.due_date = get_due_date(term, posting_date=base_date)

					due_date = term.get("due_date")
					payment_amount = term.get("payment_amount")
					if due_date and payment_amount:
						year, week, _day = getdate(due_date).isocalendar()
						target_name = f"{item_code}-{year}CW{week:02d}"
						target_entry = entry_map.get(target_name)
						if target_entry:
							target_entry.scheduled_receipts_value_payable = (
								target_entry.scheduled_receipts_value_payable or 0
							) + payment_amount
						elif getdate(due_date) < mrp_entry_docs[0].target_date:
							mrp_entry_docs[0].scheduled_receipts_value_payable = (
								mrp_entry_docs[0].scheduled_receipts_value_payable or 0
							) + payment_amount

		elif not (supplier_name and payment_terms_template):
			for entry in mrp_entry_docs:
				entry.scheduled_receipts_value_payable = entry.scheduled_receipts_value

		for entry in mrp_entry_docs:
			entry.total_payable = (entry.suggested_orders_value_payable or 0) + (
				entry.scheduled_receipts_value_payable or 0
			)
			entry.save()

	if total_batches > 1:
		try:
			remaining = frappe.cache().redis_client.decr("mrp_batch_pending")
		except Exception:
			remaining = 0
		if remaining <= 0:
			frappe.cache().delete_key("mrp_batch_pending")
			_publish_mrp_run_complete()
	else:
		_publish_mrp_run_complete()


def _calculate_totals_for_level(level: int) -> None:
	frappe.db.sql(
		"""
        UPDATE `tabMRP Entry`
        SET
            open_orders = COALESCE(reserved_qty, 0)
                        + COALESCE(reserved_qty_for_production, 0),
            total_forecast_demand = COALESCE(forecast_demand, 0) + COALESCE(upstream_net_demand, 0),
            scheduled_receipts = COALESCE(planned_qty, 0) + COALESCE(ordered_qty, 0)
        WHERE bom_level = %(level)s
        """,
		values={"level": level},
	)


def _explode_net_demand_for_level(level: int) -> None:
	today = date.today()
	sql_query = """# nosemgrep: frappe-sql-format-injection
        SELECT
            bom_item.item_code AS child_item_code,
            DATE_FORMAT(
                GREATEST(
                    CASE
                        WHEN parent_me.is_manufactured = 1
                            THEN DATE_SUB(parent_me.target_date, INTERVAL parent_me.lead_time DAY)
                        ELSE parent_me.target_date
                    END,
                    %(today)s
                ),
                '%%xCW%%v'
            ) AS calendar_week,
            SUM(
                parent_me.suggested_receipts * bom_item.stock_qty / bom.quantity
            ) AS demand_qty
        FROM `tabMRP Entry` AS parent_me
        JOIN `tabBOM` AS bom
            ON parent_me.item_code = bom.item
            AND bom.is_active = 1
            AND bom.is_default = 1
        JOIN `tabBOM Item` AS bom_item
            ON bom.name = bom_item.parent
        WHERE
            parent_me.bom_level = %(level)s
            AND parent_me.is_manufactured = 1
            AND parent_me.suggested_receipts > 0
        GROUP BY
            bom_item.item_code,
            calendar_week
    """
	explosion_data = frappe.db.sql(
		sql_query, values={"level": level, "today": today}, as_dict=True
	)  # nosemgrep

	if not explosion_data:
		return

	update_cases: list[str] = []
	mrp_entry_names: list[str] = []
	for row in explosion_data:
		mrp_entry_name = f"{row.child_item_code}-{row.calendar_week}"
		escaped_name = frappe.db.escape(mrp_entry_name)
		demand_qty = float(row.demand_qty)
		mrp_entry_names.append(escaped_name)
		update_cases.append(
			f"WHEN name = {escaped_name} THEN COALESCE(upstream_net_demand, 0) + {demand_qty}"
		)

	case_str = " ".join(update_cases)
	names_str = ", ".join(mrp_entry_names)
	update_query = f"""# nosemgrep: frappe-sql-format-injection
        UPDATE `tabMRP Entry`
        SET upstream_net_demand = CASE
            {case_str}
            ELSE upstream_net_demand
        END
        WHERE name IN ({names_str})
    """
	frappe.db.sql(update_query)  # nosemgrep


def _process_suggested_receipts_for_level(
	level: int,
	stock_levels: list,
	item_details_map: dict[str, frappe._dict],
	requirement_based_on: str,
) -> None:
	item_codes_at_level: list[str] = frappe.db.sql_list(
		"SELECT DISTINCT item_code FROM `tabMRP Entry` WHERE bom_level = %(level)s",
		values={"level": level},
	)
	batch_size = 500
	for i in range(0, len(item_codes_at_level), batch_size):
		batch_codes = item_codes_at_level[i : i + batch_size]
		batch = [item_details_map[c] for c in batch_codes if c in item_details_map]
		if not batch:
			continue
		batch_item_codes = [item["item_code"] for item in batch]
		batch_map = {item["item_code"]: item for item in batch}
		_calculate_suggested_receipts_batch(batch_item_codes, batch_map, stock_levels, requirement_based_on)


def _finalise_suggestions(
	stock_levels: list,
	item_details_map: dict[str, frappe._dict],
	enqueue: bool,
) -> None:
	item_codes = list(item_details_map.keys())
	item_prices = _get_item_prices(item_codes)

	suppliers = list(
		set(v["default_supplier"] for v in item_details_map.values() if v.get("default_supplier"))
	)
	supplier_payment_terms: dict[str, str] = {}
	if suppliers:
		supplier_payment_terms = {
			s.name: s.payment_terms
			for s in frappe.get_all(
				"Supplier", filters={"name": ("in", suppliers)}, fields=["name", "payment_terms"]
			)
		}
	payment_term_details: dict[str, frappe._dict] = {
		pt.name: pt for pt in frappe.get_all("Payment Term", fields=["name", "custom_due_date"])
	}

	batch_size = 250
	all_item_details = list(item_details_map.values())
	total_batches = math.ceil(len(all_item_details) / batch_size) if all_item_details else 1

	if enqueue and total_batches > 1:
		frappe.cache().set_value("mrp_batch_pending", total_batches)

	for i in range(0, len(all_item_details), batch_size):
		batch = all_item_details[i : i + batch_size]
		batch_codes = [item["item_code"] for item in batch]
		batch_map = {item["item_code"]: item for item in batch}
		if enqueue:
			frappe.enqueue(
				"erpnext_mrp.mrp.tasks.mrp_run._finalise_item_batch",
				queue="long",
				item_codes=batch_codes,
				item_details_map=batch_map,
				stock_levels=stock_levels,
				item_prices=item_prices,
				supplier_payment_terms=supplier_payment_terms,
				payment_term_details=payment_term_details,
				total_batches=total_batches,
			)
		else:
			_finalise_item_batch(
				item_codes=batch_codes,
				item_details_map=batch_map,
				stock_levels=stock_levels,
				item_prices=item_prices,
				supplier_payment_terms=supplier_payment_terms,
				payment_term_details=payment_term_details,
				total_batches=total_batches,
			)

	if not enqueue:
		_publish_mrp_run_complete()


def _process_levels_sequentially(enqueue: bool) -> None:
	filters = frappe._dict({"from_date": date.today(), "to_date": date.today()})
	stock_level_report = execute_stock_balance_report(filters=filters)
	stock_levels = stock_level_report[1]

	settings = frappe.get_cached_doc("MRP Settings")
	requirement_based_on = settings.requirement_based_on

	max_level_result = frappe.db.sql("SELECT COALESCE(MAX(bom_level), 0) FROM `tabMRP Entry`")
	max_level = int(max_level_result[0][0])

	item_details_map = _get_all_item_details()

	for level in range(max_level + 1):
		_calculate_totals_for_level(level)
		_process_suggested_receipts_for_level(level, stock_levels, item_details_map, requirement_based_on)
		if level < max_level:
			_explode_net_demand_for_level(level)

	_finalise_suggestions(stock_levels=stock_levels, item_details_map=item_details_map, enqueue=enqueue)


def _get_item_prices(item_codes: list[str]) -> dict[str, float]:
	today = date.today()
	ItemPrice = frappe.qb.DocType("Item Price")

	item_prices_docs = (
		frappe.qb.from_(ItemPrice)
		.select(ItemPrice.item_code, ItemPrice.price_list_rate, ItemPrice.creation)
		.where(
			(ItemPrice.item_code.isin(item_codes))
			& (ItemPrice.buying == 1)
			& (ItemPrice.valid_from <= today)
			& ((ItemPrice.valid_upto >= today) | (ItemPrice.valid_upto.isnull()))
		)
		.orderby(ItemPrice.creation, order=Order.desc)
		# .run(as_dict=True)
	)

	item_prices_docs = item_prices_docs.run(as_dict=True)

	item_prices = {}
	for d in item_prices_docs:
		if d.item_code not in item_prices:
			item_prices[d.item_code] = d.price_list_rate

	return item_prices


def _publish_mrp_run_complete() -> None:
	"""Notify all users with an MRP role so the Vue UI can refresh its data."""
	import datetime

	message = {"completed_at": datetime.datetime.now().isoformat()}
	users = frappe.get_all(
		"Has Role",
		filters={"role": ["in", ["MRP Manager", "MRP User"]], "parenttype": "User"},
		pluck="parent",
		distinct=True,
	)
	for user in users:
		frappe.publish_realtime(event="mrp_run_complete", message=message, user=user)
