import datetime
import itertools
import math
from datetime import date

import frappe
from erpnext.stock.report.stock_balance.stock_balance import execute as execute_stock_balance_report
from frappe import _

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
		lead_time_expression = f"IFNULL(t_item.`{lead_time_field}`, 0) + IFNULL(t_item.`{additional_lead_time_field}`, 0)"
	else:
		lead_time_expression = f"t_item.`{lead_time_field}`"

	# 2. Run the recursive query to get all items and their BOM levels
	sql_query = f"""
        WITH RECURSIVE bom_hierarchy (item_code, level) AS (
            -- Anchor Member: Items that are not components in any active, default BOM (Level 0)
            SELECT
                t_item.name,
                0
            FROM
                `tabItem` AS t_item
            WHERE
                t_item.name NOT IN (
                    SELECT DISTINCT
                        t_bom_item.item_code
                    FROM
                        `tabBOM Item` AS t_bom_item
                    JOIN
                        `tabBOM` AS t_bom ON t_bom_item.parent = t_bom.name
                    WHERE
                        t_bom.is_active = 1
                        AND t_bom.is_default = 1
                )

            UNION ALL

            -- Recursive Member: Find components of items with a known level from default BOMs
            SELECT
                t_bom_item.item_code,
                bh.level + 1
            FROM
                `tabBOM Item` AS t_bom_item
            JOIN
                `tabBOM` AS t_bom ON t_bom_item.parent = t_bom.name
            JOIN
                bom_hierarchy AS bh ON t_bom.item = bh.item_code
            WHERE
                t_bom.is_active = 1
                AND t_bom.is_default = 1
        ),
        bom_levels AS (
            -- Calculate the maximum (deepest) level for each item
            SELECT
                item_code,
                MAX(level) AS bom_level
            FROM
                bom_hierarchy
            GROUP BY
                item_code
        )
        -- Final Selection
        SELECT
            t_item.name AS item_code,
            {lead_time_expression} AS lead_time,
            COALESCE(bl.bom_level, 0) AS bom_level,
            (EXISTS (
                SELECT 1
                FROM `tabBOM` AS t_bom
                WHERE t_bom.item = t_item.name AND t_bom.is_active = 1 AND t_bom.is_default = 1
            )) AS is_manufactured
        FROM
            `tabItem` AS t_item
        LEFT JOIN
            bom_levels AS bl ON t_item.name = bl.item_code
        WHERE
            t_item.disabled = 0
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
		year, week, _ = target_date.isocalendar()
		period_str = f"-{year}CW{week:02d}"
		if period_str not in periods:
			periods[period_str] = target_date

	# Convert to a list of items for itertools
	period_data = list(periods.items())

	# 4. Efficiently combine items and periods and prepare for bulk insert
	# item is a tuple: (item_code, bom_level, is_manufactured)
	# period is a tuple: (period_str, target_date)
	owner = frappe.session.user
	creation = datetime.datetime.now()
	final_values = [(f"{item[0]}{period[0]}", item[0], item[1], item[2], item[3], period[1], owner, creation) for item, period in itertools.product(item_list, period_data)]
	# 5. Perform a bulk insert of all generated records
	frappe.db.bulk_insert(
		"MRP Entry",
		fields=[
			"name",
			"item_code",
			"lead_time",
			"bom_level",
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

	sql_query = f"""
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
		lead_time_expression = f"IFNULL(child_item.`{lead_time_field}`, 0) + IFNULL(child_item.`{additional_lead_time_field}`, 0)"
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
                de.required_qty * bom_item.stock_qty,
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
	sql_query = f"""
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

	sql_query = f"""
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
		lead_time_expression = f"IFNULL(child_item.`{lead_time_field}`, 0) + IFNULL(child_item.`{additional_lead_time_field}`, 0)"
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
                de.required_qty * bom_item.stock_qty,
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

	sql_query = f"""
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

	sql_query = f"""
        SELECT
            po_item.item_code,
            CASE
                WHEN po_item.schedule_date < %(start_date)s THEN DATE_FORMAT(%(start_date)s, '%%xCW%%v')
                ELSE DATE_FORMAT(po_item.schedule_date, '%%xCW%%v')
            END AS calendar_week,
            SUM((po_item.qty - po_item.received_qty) * po_item.conversion_factor) AS total_ordered_qty
        FROM `tabPurchase Order Item` AS po_item
        JOIN `tabPurchase Order` AS po ON po_item.parent = po.name
        WHERE
            po_item.qty > po_item.received_qty
            AND po.status NOT IN ('Closed', 'Delivered', 'Cancelled')
            AND po.docstatus = 1
            AND (po_item.delivered_by_supplier IS NULL OR po_item.delivered_by_supplier = 0)
            AND po_item.schedule_date <= %(end_date)s
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
	update_query = f"""
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

	# Get item details in a single query
	item_details_query = """
        SELECT DISTINCT
            mrp.item_code,
            ir.warehouse_reorder_level,
            ir.warehouse_reorder_qty,
            id.default_supplier
        FROM `tabMRP Entry` AS mrp
        LEFT JOIN `tabItem Reorder` AS ir
            ON mrp.item_code = ir.parent AND ir.material_request_type = 'Purchase' AND ir.idx = 1
        LEFT JOIN `tabItem Default` AS id
            ON mrp.item_code = id.parent AND id.default_supplier IS NOT NULL
    """
	item_details_list = frappe.db.sql(item_details_query, as_dict=True)

	settings = frappe.get_cached_doc("MRP Settings")
	requirement_based_on = settings.requirement_based_on

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

	for item_code, item_mrp_entries_dicts in grouped_mrp_entries.items():
		mrp_entry_docs = [frappe.get_doc("MRP Entry", d.name) for d in item_mrp_entries_dicts]
		item_details = item_details_map.get(item_code)

		# Set current stock level as starting stock on hand
		mrp_entry_docs[0].on_hand_inventory = sum([stock_level.opening_qty for stock_level in stock_levels if stock_level.item_code == item_code])

		for index, entry in enumerate(mrp_entry_docs):
			# Set the starting SOH of the current entry to the projected SOH of the last entry
			if index != 0:
				entry.on_hand_inventory = mrp_entry_docs[index - 1].projected_on_hand_inventory

			# Set the re-order details
			if item_details:
				entry.reorder_level = item_details.get("warehouse_reorder_level")
				entry.reorder_quantity = item_details.get("warehouse_reorder_qty")

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

			# Determine if there is a shortage
			entry.suggested_receipts = 0
			shortage = (entry.on_hand_inventory or 0) - demand + (entry.scheduled_receipts or 0) - (entry.reorder_level or 0)
			if shortage < 0:
				shortage *= -1
				moq = entry.reorder_quantity or 1
				entry.suggested_receipts = math.ceil(shortage / moq) * moq

			entry.projected_on_hand_inventory = (entry.on_hand_inventory or 0) - demand + (entry.scheduled_receipts or 0) + (entry.suggested_receipts or 0)

		# Based on lead time, set the suggested order qty for the correct earlier entry
		is_urgent = 0
		for index, entry in reversed(list(enumerate(mrp_entry_docs))):
			if entry.suggested_receipts and entry.lead_time:
				weeks_before = math.ceil(entry.lead_time / 7)
				# If we should have ordered already, flag this entry
				if index - weeks_before < 0:
					is_urgent = 1
					mrp_entry_docs[0].suggested_orders = (mrp_entry_docs[0].suggested_orders or 0) + entry.suggested_receipts
				else:
					mrp_entry_docs[index - weeks_before].suggested_orders = (mrp_entry_docs[index - weeks_before].suggested_orders or 0) + entry.suggested_receipts

			entry.is_urgent = is_urgent
			entry.save()
