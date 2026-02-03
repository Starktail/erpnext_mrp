import datetime
import itertools
import math
from datetime import date

import frappe
from erpnext.controllers.accounts_controller import get_due_date, get_payment_terms
from erpnext.stock.report.stock_balance.stock_balance import execute as execute_stock_balance_report
from frappe import _
from frappe.utils import add_days, getdate
from pypika import Order

from erpnext_mrp.mrp.doctype.mrp_settings.mrp_settings import get_context


@frappe.whitelist()
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
	sql_query = f"""
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
			)) AS is_manufactured
		FROM `tabItem` AS t_item
		LEFT JOIN bom_rollup br ON t_item.name = br.item_code
		WHERE t_item.disabled = 0
		AND t_item.is_stock_item = 1;

    """
	item_list = frappe.db.sql(sql_query)

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
	# item is a tuple: (item_code, bom_level, root_bom, is_manufactured)
	# period is a tuple: (period_str, target_date)
	owner = frappe.session.user
	creation = datetime.datetime.now()
	final_values = [(f"{item[0]}{period[0]}", item[0], item[1], item[2], item[3], item[4], period[1], owner, creation) for item, period in itertools.product(item_list, period_data)]

	# 5. Don't store bom_levels on every period, only the first period
	final_values = [(*row[:4], row[4] if period_data[0][0] in row[0] else None, *row[5:]) for row in final_values]

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
	update_open_orders_demand()
	update_forecast_demand()
	update_scheduled_receipts()
	calculate_totals()
	calculate_suggestions_and_projected_stock(enqueue=enqueue)


def update_open_orders_demand():
	_update_reserved_qty()
	_update_reserved_qty_for_production()
	_update_upstream_so_demand()


def update_forecast_demand():
	_update_forecast_demand()
	_update_upstream_forecast_demand()


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
	forecast_data = frappe.db.sql(sql_query, values={"start_date": start_date, "end_date": end_date}, as_dict=True)

	if not forecast_data:
		return

	# Use a CASE statement for efficient bulk updates
	update_cases = []
	mrp_entry_names = []
	for row in forecast_data:
		mrp_entry_name = f"{row.item_code}-{row.calendar_week}"
		mrp_entry_names.append(frappe.db.escape(mrp_entry_name))
		update_cases.append(f"WHEN name = {frappe.db.escape(mrp_entry_name)} THEN {row.total_forecast_quantity}")

	if not mrp_entry_names:
		return

	case_str = " ".join(update_cases)
	names_str = ", ".join(mrp_entry_names)

	update_query = f"""
        UPDATE `tabMRP Entry`
        SET forecast_demand = CASE
            {case_str}
            ELSE forecast_demand
        END
        WHERE name IN ({names_str})
    """
	frappe.db.sql(update_query)


def _update_upstream_forecast_demand():
	"""
	Explodes forecast demand from parent items down to their components using a recursive CTE.
	"""
	settings = frappe.get_cached_doc("MRP Settings")
	lead_time_field = "lead_time_days"
	if settings.item_lead_time_field:
		lead_time_field = settings.item_lead_time_field.split("|")[0].strip()

	additional_lead_time_field = None
	if settings.item_additional_lead_time_field:
		additional_lead_time_field = settings.item_additional_lead_time_field.split("|")[0].strip()

	if additional_lead_time_field:
		lead_time_expression = f"COALESCE(child_item.`{lead_time_field}`, 0) + COALESCE(CAST(NULLIF(child_item.`{additional_lead_time_field}`, '') AS SIGNED), 0)"
	else:
		lead_time_expression = f"child_item.`{lead_time_field}`"

	sql_query = f"""
        WITH RECURSIVE DemandExplosion (item_code, target_date, required_qty, level, lead_time, is_manufactured) AS (
            -- Anchor: Initial demand from MRP entries with forecast_demand
            SELECT
                item_code,
                target_date,
                forecast_demand,
                0 as level,
                lead_time,
                is_manufactured
            FROM `tabMRP Entry`
            WHERE forecast_demand > 0

            UNION ALL

            -- Recursive Step: Explode demand to child components
            SELECT
                bom_item.item_code,
                CASE
                    WHEN de.is_manufactured = 1 THEN DATE_SUB(de.target_date, INTERVAL de.lead_time DAY)
                    ELSE de.target_date
                END,
                de.required_qty * bom_item.stock_qty * bom.quantity,
                de.level + 1,
                {lead_time_expression},
                (EXISTS (SELECT 1 FROM `tabBOM` b WHERE b.item = bom_item.item_code AND b.is_active = 1 AND b.is_default = 1))
            FROM DemandExplosion AS de
            JOIN `tabBOM` AS bom ON de.item_code = bom.item
            JOIN `tabBOM Item` AS bom_item ON bom.name = bom_item.parent
            JOIN `tabItem` AS child_item ON bom_item.item_code = child_item.name
            WHERE bom.is_active = 1 AND bom.is_default = 1
        ),
        AggregatedDemand AS (
            -- Aggregate demand for each component by week
            SELECT
                item_code,
                DATE_FORMAT(target_date, '%xCW%v') AS calendar_week,
                SUM(required_qty) AS total_demand
            FROM DemandExplosion
            WHERE level > 0
            GROUP BY item_code, calendar_week
        )
        -- Select the final aggregated demand
        SELECT * FROM AggregatedDemand;
    """

	upstream_demand_data = frappe.db.sql(sql_query, as_dict=True)

	if not upstream_demand_data:
		return

	update_cases = []
	mrp_entry_names = []
	for row in upstream_demand_data:
		mrp_entry_name = f"{row.item_code}-{row.calendar_week}"
		mrp_entry_names.append(frappe.db.escape(mrp_entry_name))
		update_cases.append(f"WHEN name = {frappe.db.escape(mrp_entry_name)} THEN COALESCE(upstream_forecast_demand, 0) + {row.total_demand}")

	if not mrp_entry_names:
		return

	case_str = " ".join(update_cases)
	names_str = ", ".join(mrp_entry_names)

	update_query = f"""
        UPDATE `tabMRP Entry`
        SET upstream_forecast_demand = CASE
            {case_str}
            ELSE upstream_forecast_demand
        END
        WHERE name IN ({names_str});
    """
	frappe.db.sql(update_query)


def update_scheduled_receipts():
	_update_planned_qty()
	_update_ordered_qty()


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
	open_orders_data = frappe.db.sql(sql_query, values={"start_date": start_date, "end_date": end_date}, as_dict=True)

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

	update_query = f"""
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
	production_demand_data = frappe.db.sql(sql_query, values={"start_date": start_date, "end_date": end_date}, as_dict=True)

	if not production_demand_data:
		return

	update_cases = []
	mrp_entry_names = []
	for row in production_demand_data:
		mrp_entry_name = f"{row.item_code}-{row.calendar_week}"
		mrp_entry_names.append(frappe.db.escape(mrp_entry_name))
		update_cases.append(f"WHEN name = {frappe.db.escape(mrp_entry_name)} THEN COALESCE(reserved_qty_for_production, 0) + {row.total_required_qty}")

	if not mrp_entry_names:
		return

	case_str = " ".join(update_cases)
	names_str = ", ".join(mrp_entry_names)

	update_query = f"""
        UPDATE `tabMRP Entry`
        SET reserved_qty_for_production = CASE
            {case_str}
            ELSE reserved_qty_for_production
        END
        WHERE name IN ({names_str});
    """
	frappe.db.sql(update_query)


def _update_upstream_so_demand():
	"""
	Explodes open orders demand from parent items down to their components using a recursive CTE.
	"""
	settings = frappe.get_cached_doc("MRP Settings")
	lead_time_field = "lead_time_days"
	if settings.item_lead_time_field:
		lead_time_field = settings.item_lead_time_field.split("|")[0].strip()

	additional_lead_time_field = None
	if settings.item_additional_lead_time_field:
		additional_lead_time_field = settings.item_additional_lead_time_field.split("|")[0].strip()

	if additional_lead_time_field:
		lead_time_expression = f"COALESCE(child_item.`{lead_time_field}`, 0) + COALESCE(CAST(NULLIF(child_item.`{additional_lead_time_field}`, '') AS SIGNED), 0)"
	else:
		lead_time_expression = f"child_item.`{lead_time_field}`"

	sql_query = f"""
        WITH RECURSIVE DemandExplosion (item_code, target_date, required_qty, level, lead_time, is_manufactured) AS (
            -- Anchor: Initial demand from MRP entries with reserved_qty
            SELECT
                item_code,
                target_date,
                reserved_qty,
                0 as level,
                lead_time,
                is_manufactured
            FROM `tabMRP Entry`
            WHERE reserved_qty > 0

            UNION ALL

            -- Recursive Step: Explode demand to child components
            SELECT
                bom_item.item_code,
                CASE
                    WHEN de.is_manufactured = 1 THEN DATE_SUB(de.target_date, INTERVAL de.lead_time DAY)
                    ELSE de.target_date
                END,
                de.required_qty * bom_item.stock_qty * bom.quantity,
                de.level + 1,
                {lead_time_expression},
                (EXISTS (SELECT 1 FROM `tabBOM` b WHERE b.item = bom_item.item_code AND b.is_active = 1 AND b.is_default = 1))
            FROM DemandExplosion AS de
            JOIN `tabBOM` AS bom ON de.item_code = bom.item
            JOIN `tabBOM Item` AS bom_item ON bom.name = bom_item.parent
            JOIN `tabItem` AS child_item ON bom_item.item_code = child_item.name
            WHERE bom.is_active = 1 AND bom.is_default = 1
        ),
        AggregatedDemand AS (
            -- Aggregate demand for each component by week
            SELECT
                item_code,
                DATE_FORMAT(target_date, '%xCW%v') AS calendar_week,
                SUM(required_qty) AS total_demand
            FROM DemandExplosion
            WHERE level > 0
            GROUP BY item_code, calendar_week
        )
        -- Select the final aggregated demand
        SELECT * FROM AggregatedDemand;
    """

	upstream_demand_data = frappe.db.sql(sql_query, as_dict=True)

	if not upstream_demand_data:
		return

	update_cases = []
	mrp_entry_names = []
	for row in upstream_demand_data:
		mrp_entry_name = f"{row.item_code}-{row.calendar_week}"
		mrp_entry_names.append(frappe.db.escape(mrp_entry_name))
		update_cases.append(f"WHEN name = {frappe.db.escape(mrp_entry_name)} THEN COALESCE(upstream_so_demand, 0) + {row.total_demand}")

	if not mrp_entry_names:
		return

	case_str = " ".join(update_cases)
	names_str = ", ".join(mrp_entry_names)

	update_query = f"""
        UPDATE `tabMRP Entry`
        SET upstream_so_demand = CASE
            {case_str}
            ELSE upstream_so_demand
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
	planned_data = frappe.db.sql(sql_query, values={"start_date": start_date, "end_date": end_date}, as_dict=True)

	if not planned_data:
		return

	update_cases = []
	mrp_entry_names = []
	for row in planned_data:
		mrp_entry_name = f"{row.production_item}-{row.calendar_week}"
		mrp_entry_names.append(frappe.db.escape(mrp_entry_name))
		update_cases.append(f"WHEN name = {frappe.db.escape(mrp_entry_name)} THEN COALESCE(planned_qty, 0) + {row.total_planned_qty}")

	if not mrp_entry_names:
		return

	case_str = " ".join(update_cases)
	names_str = ", ".join(mrp_entry_names)

	update_query = f"""
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

	sql_query = f"""
        SELECT
            po_item.item_code,
            CASE
                WHEN {receiving_date_expression} < %(start_date)s THEN DATE_FORMAT(%(start_date)s, '%%xCW%%v')
                ELSE DATE_FORMAT({receiving_date_expression}, '%%xCW%%v')
            END AS calendar_week,
            SUM((po_item.qty - po_item.received_qty) * po_item.conversion_factor) AS total_ordered_qty
        FROM `tabPurchase Order Item` AS po_item
        JOIN `tabPurchase Order` AS po ON po_item.parent = po.name
        WHERE
            po_item.qty > po_item.received_qty
            AND po.status NOT IN ('Closed', 'Delivered', 'Cancelled')
            AND po.docstatus = 1
            AND (po_item.delivered_by_supplier IS NULL OR po_item.delivered_by_supplier = 0)
            AND {receiving_date_expression} <= %(end_date)s
        GROUP BY
            po_item.item_code,
            calendar_week;
    """
	ordered_data = frappe.db.sql(sql_query, values={"start_date": start_date, "end_date": end_date}, as_dict=True)

	if not ordered_data:
		return

	update_cases = []
	mrp_entry_names = []
	for row in ordered_data:
		mrp_entry_name = f"{row.item_code}-{row.calendar_week}"
		mrp_entry_names.append(frappe.db.escape(mrp_entry_name))
		update_cases.append(f"WHEN name = {frappe.db.escape(mrp_entry_name)} THEN COALESCE(ordered_qty, 0) + {row.total_ordered_qty}")

	if not mrp_entry_names:
		return

	case_str = " ".join(update_cases)
	names_str = ", ".join(mrp_entry_names)

	update_query = f"""
        UPDATE `tabMRP Entry`
        SET ordered_qty = CASE
            {case_str}
            ELSE ordered_qty
        END
        WHERE name IN ({names_str});
    """
	frappe.db.sql(update_query)


def calculate_totals():
	update_query = """
        UPDATE `tabMRP Entry`
        SET
            open_orders = COALESCE(reserved_qty, 0) + COALESCE(reserved_qty_for_production, 0) + COALESCE(upstream_so_demand, 0),
            total_forecast_demand = COALESCE(forecast_demand, 0) + COALESCE(upstream_forecast_demand, 0),
            scheduled_receipts = COALESCE(planned_qty, 0) + COALESCE(ordered_qty, 0)
    """
	frappe.db.sql(update_query)


def calculate_suggestions_and_projected_stock(enqueue: bool):
	# Get stock levels
	filters = frappe._dict({"from_date": date.today(), "to_date": date.today()})
	stock_level_report = execute_stock_balance_report(filters=filters)
	# First row contains headers, second row contains data
	stock_levels = stock_level_report[1]

	settings = frappe.get_cached_doc("MRP Settings")
	requirement_based_on = settings.requirement_based_on

	lead_time_field = "lead_time_days"
	if settings.item_lead_time_field:
		lead_time_field = settings.item_lead_time_field.split("|")[0].strip()

	additional_lead_time_field = None
	if settings.item_additional_lead_time_field:
		additional_lead_time_field = settings.item_additional_lead_time_field.split("|")[0].strip()

	if additional_lead_time_field:
		lead_time_expression = f"COALESCE(t_item.`{lead_time_field}`, 0)"
		additional_lead_time_expression = f"COALESCE(CAST(NULLIF(t_item.`{additional_lead_time_field}`, '') AS SIGNED), 0)"
	else:
		lead_time_expression = f"t_item.`{lead_time_field}`"
		additional_lead_time_expression = "0"

	reorder_qty_field = "min_order_qty"
	if settings.reorder_qty_item_field:
		reorder_qty_field = settings.reorder_qty_item_field.split("|")[0].strip()

	# Get item details in a single query
	item_details_query = f"""
        SELECT DISTINCT
            mrp.item_code,
            t_item.safety_stock,
            t_item.{reorder_qty_field} as reorder_quantity,
			t_item.valuation_rate as fall_back_valuation_rate,
            COALESCE(t_item.`{lead_time_field}`, 0) as primary_lead_time,
            {lead_time_expression} AS primary_lead_time,
			{additional_lead_time_expression} AS additional_lead_time,
            id.default_supplier
        FROM `tabMRP Entry` AS mrp
        JOIN `tabItem` AS t_item
            ON mrp.item_code = t_item.name
        LEFT JOIN `tabItem Default` AS id
            ON mrp.item_code = id.parent AND id.default_supplier IS NOT NULL
    """
	item_details_list = frappe.db.sql(item_details_query, as_dict=True)

	# Process items in batches
	batch_size = 1000
	for i in range(0, len(item_details_list), batch_size):
		batch = item_details_list[i : i + batch_size]
		if enqueue:
			frappe.enqueue(
				"erpnext_mrp.mrp.tasks.mrp_run.process_item_batch",
				queue="long",
				item_batch=batch,
				stock_levels=stock_levels,
				requirement_based_on=requirement_based_on,
			)
		else:
			process_item_batch(item_batch=batch, stock_levels=stock_levels, requirement_based_on=requirement_based_on)


def process_item_batch(item_batch, stock_levels, requirement_based_on):
	item_codes = [item["item_code"] for item in item_batch]

	# Get all MRP entries for the batch of items with all fields needed for processing
	mrp_entries_dicts = frappe.get_all(
		"MRP Entry",
		filters={"item_code": ("in", item_codes)},
		fields=["*"],  # get all fields
		order_by="item_code, target_date asc",
	)

	# Group MRP entries by item_code
	grouped_mrp_entries = {}
	for entry_dict in mrp_entries_dicts:
		item_code = entry_dict.item_code
		if item_code not in grouped_mrp_entries:
			grouped_mrp_entries[item_code] = []
		grouped_mrp_entries[item_code].append(entry_dict)

	item_details_map = {item["item_code"]: item for item in item_batch}

	item_prices = _get_item_prices(item_codes)

	# Get supplier payment terms
	suppliers = list(set(item["default_supplier"] for item in item_batch if item.get("default_supplier")))
	supplier_payment_terms = {}
	if suppliers:
		supplier_payment_terms = {s.name: s.payment_terms for s in frappe.get_all("Supplier", filters={"name": ("in", suppliers)}, fields=["name", "payment_terms"])}

	# Get Payment Terms details for custom due dates
	payment_term_details = {}
	all_payment_terms = frappe.get_all("Payment Term", fields=["name", "custom_due_date"])
	for pt in all_payment_terms:
		payment_term_details[pt.name] = pt

	for item_code, item_mrp_entries_dicts in grouped_mrp_entries.items():
		mrp_entry_docs = [frappe.get_doc("MRP Entry", d.name) for d in item_mrp_entries_dicts]
		item_details = item_details_map.get(item_code)

		# Check for a buying price list first
		price = item_prices.get(item_code)
		if not price:
			# Get valuation rate from stock levels (Bin)
			item_stock_levels = [sl.val_rate for sl in stock_levels if sl.item_code == item_code and sl.val_rate > 0]
			valuation_rate = 0
			if item_stock_levels:
				valuation_rate = sum(item_stock_levels) / len(item_stock_levels)
			if valuation_rate:
				price = valuation_rate
			else:
				price = item_details.get("fall_back_valuation_rate")

		# Set current stock level as starting stock on hand
		mrp_entry_docs[0].on_hand_inventory = sum([stock_level.opening_qty for stock_level in stock_levels if stock_level.item_code == item_code])
		mrp_entry_docs[0].on_hand_inventory_excl_reorder_level = mrp_entry_docs[0].on_hand_inventory
		total_item_demand = 0

		for index, entry in enumerate(mrp_entry_docs):
			# Set the starting SOH of the current entry to the projected SOH of the last entry
			if index != 0:
				entry.on_hand_inventory = mrp_entry_docs[index - 1].projected_on_hand_inventory
				entry.on_hand_inventory_excl_reorder_level = mrp_entry_docs[index - 1].projected_on_hand_inventory_excl_reorder_level
			# Set the re-order details
			if item_details:
				entry.reorder_level = item_details.get("safety_stock")
				entry.reorder_quantity = item_details.get("reorder_quantity")

			# Set the default Supplier
			if item_details:
				entry.default_supplier = item_details.get("default_supplier")

			# Determine demand based on MRP settings
			open_orders = entry.open_orders or 0
			total_forecast_demand = entry.total_forecast_demand or 0

			if requirement_based_on == "Forecast only":
				demand = total_forecast_demand
			elif requirement_based_on == "Open Orders only":
				demand = open_orders
			elif requirement_based_on == "Open Orders + Forecast":
				demand = open_orders + total_forecast_demand
			elif requirement_based_on == "Open Orders + Forecast (orders consume the forecast)":
				demand = open_orders + max(0, total_forecast_demand - open_orders)
			else:
				# Default to Open Orders + Forecast
				raise ValueError(_("Unkown 'Requirement based on' setting"))

			total_item_demand += demand

			# Determine if there is a shortage taking safety stock into account
			entry.suggested_receipts = 0
			shortage = (entry.on_hand_inventory or 0) - demand + (entry.scheduled_receipts or 0) - (entry.reorder_level or 0)
			if shortage < 0:
				shortage *= -1
				moq = entry.reorder_quantity or 1
				entry.suggested_receipts = math.ceil(shortage / moq) * moq

			entry.projected_on_hand_inventory = (entry.on_hand_inventory or 0) - demand + (entry.scheduled_receipts or 0) + (entry.suggested_receipts or 0)

			# Determine if there is a shortage exlcuding safety stock
			entry.suggested_receipts_excl_reorder_level = 0
			shortage_excl_reorder_level = (entry.on_hand_inventory_excl_reorder_level or 0) - demand + (entry.scheduled_receipts or 0)
			if shortage_excl_reorder_level < 0:
				shortage_excl_reorder_level *= -1
				moq = entry.reorder_quantity or 1
				entry.suggested_receipts_excl_reorder_level = math.ceil(shortage_excl_reorder_level / moq) * moq

			entry.projected_on_hand_inventory_excl_reorder_level = (
				(entry.on_hand_inventory_excl_reorder_level or 0) - demand + (entry.scheduled_receipts or 0) + (entry.suggested_receipts_excl_reorder_level or 0)
			)

		# Based on lead time, set the suggested order qty for the correct earlier entry
		for index, entry in reversed(list(enumerate(mrp_entry_docs))):
			if entry.suggested_receipts:
				weeks_before = math.ceil(entry.lead_time / 7)
				# If we should have ordered already, set suggested_orders in current period
				if index - weeks_before < 0:
					mrp_entry_docs[0].suggested_orders = (mrp_entry_docs[0].suggested_orders or 0) + entry.suggested_receipts
				# Else, set suggested_orders in leadtime-adjusted period
				else:
					mrp_entry_docs[index - weeks_before].suggested_orders = (mrp_entry_docs[index - weeks_before].suggested_orders or 0) + entry.suggested_receipts

		# Determine Level of Urgency
		# Level 1: Required in first week and not enough On Order (excl safety stock)
		# Current SoH + Total scheduled_receipts < total demand and no suggested orders for period 0
		total_scheduled_receipts = sum([entry.scheduled_receipts for entry in mrp_entry_docs])
		if (mrp_entry_docs[0].on_hand_inventory + total_scheduled_receipts < total_item_demand) and (mrp_entry_docs[0].suggested_orders > 0):
			mrp_entry_docs[0].urgency_level = 1

		# Level 2. Enough On Order, but late (excl safety stock)
		# Current SoH + Total scheduled_receipts <= total demand (but no suggested orders for period 0)
		# OR
		# Somewhere we will run out of stock (aka any suggested_receipts_excl_reorder_level > 0)
		elif (mrp_entry_docs[0].on_hand_inventory + total_scheduled_receipts < total_item_demand) or sum([entry.suggested_receipts_excl_reorder_level for entry in mrp_entry_docs]) > 0:
			mrp_entry_docs[0].urgency_level = 2

		# Level 3. On order, but the stock level will drop below the safety stock level
		# Current SoH + Total scheduled_receipts >= total demand
		# AND
		# Somewhere we will land below the safety stock level (aka suggested_receipts > 0)
		elif sum([entry.suggested_receipts for entry in mrp_entry_docs]) > 0:
			mrp_entry_docs[0].urgency_level = 3

		else:
			mrp_entry_docs[0].urgency_level = 0

		# Now that all suggested_orders have been calculated, calculate their value
		if price and price > 0:
			for entry in mrp_entry_docs:
				if entry.suggested_orders:
					new_value = entry.suggested_orders * price
					if entry.suggested_orders_value != new_value:
						entry.suggested_orders_value = new_value

		# Calculate Cash Requirement (Payable Value)
		supplier_name = item_details.get("default_supplier")
		payment_terms_template = supplier_payment_terms.get(supplier_name) if supplier_name else None

		if supplier_name and payment_terms_template:
			# Map to quickly find entry by name
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
							# Determine the base date for due date calculation
							base_date = None
							payment_term_name = term.get("payment_term")
							if payment_term_name:
								custom_due_date_type = payment_term_details.get(payment_term_name, {}).get("custom_due_date")

								if custom_due_date_type == "Order date":
									base_date = entry.target_date
								elif custom_due_date_type == "Shipment date":
									base_date = add_days(entry.target_date, item_details.get("primary_lead_time") or 0)
								elif custom_due_date_type == "Arrival date":
									# Arrival Date Order Date (Order + Total Lead Time)
									total_lead_time = (item_details.get("primary_lead_time") or 0) + (item_details.get("additional_lead_time") or 0)
									base_date = add_days(entry.target_date, total_lead_time)
								else:
									base_date = entry.target_date

							if base_date:
								term.due_date = get_due_date(term, posting_date=base_date)

							due_date = term.get("due_date")
							payment_amount = term.get("payment_amount")
							if due_date and payment_amount:
								# Find target entry CW
								year, week, _day = getdate(due_date).isocalendar()
								target_name = f"{item_code}-{year}CW{week:02d}"
								target_entry = entry_map.get(target_name)
								if target_entry:
									target_entry.suggested_orders_value_payable = (target_entry.suggested_orders_value_payable or 0) + payment_amount
								elif getdate(due_date) < mrp_entry_docs[0].target_date:
									mrp_entry_docs[0].suggested_orders_value_payable = (mrp_entry_docs[0].suggested_orders_value_payable or 0) + payment_amount

		for entry in mrp_entry_docs:
			entry.save()


def _get_item_prices(item_codes: list[str]) -> dict[str, float]:
	today = date.today()
	ItemPrice = frappe.qb.DocType("Item Price")

	item_prices_docs = (
		frappe.qb.from_(ItemPrice)
		.select(ItemPrice.item_code, ItemPrice.price_list_rate, ItemPrice.creation)
		.where((ItemPrice.item_code.isin(item_codes)) & (ItemPrice.buying == 1) & (ItemPrice.valid_from <= today) & ((ItemPrice.valid_upto >= today) | (ItemPrice.valid_upto.isnull())))
		.orderby(ItemPrice.creation, order=Order.desc)
		# .run(as_dict=True)
	)

	item_prices_docs = item_prices_docs.run(as_dict=True)

	item_prices = {}
	for d in item_prices_docs:
		if d.item_code not in item_prices:
			item_prices[d.item_code] = d.price_list_rate

	return item_prices
