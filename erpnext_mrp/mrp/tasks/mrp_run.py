import datetime
import itertools

import frappe
from frappe import _


@frappe.whitelist()
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

    # 2. Run the recursive query to get all items and their BOM levels
    sql_query = """
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
            COALESCE(bl.bom_level, 0) AS bom_level
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
    settings = frappe.get_cached_doc("MRP Settings")
    if settings.periods_type != "Calendar Week":
        raise ValueError(_("Only 'Calendar Week' is a supported period type"))
    look_ahead = settings.look_ahead or 6

    today = datetime.date.today()
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
    # item is a tuple: (item_code, bom_level)
    # period is a tuple: (period_str, target_date)
    final_values = [
        (f"{item[0]}{period[0]}", item[0], item[1], period[1])
        for item, period in itertools.product(item_list, period_data)
    ]
    # 5. Perform a bulk insert of all generated records
    frappe.db.bulk_insert(
        "MRP Entry",
        fields=["name", "item_code", "bom_level", "target_date"],
        values=final_values,
        ignore_duplicates=True,
    )


@frappe.whitelist()
def process_mrp_item_entries():
    """
    Main background task to process all MRP calculations for each item and period.
    """
    update_open_orders_demand()
    #TODO: update_forecast_demand()
    update_scheduled_receipts()

def update_open_orders_demand():
    _update_reserved_qty()
    _update_reserved_qty_for_production()
    _update_upstream_so_demand()

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
    start_date = datetime.date.today()
    end_date = start_date + datetime.timedelta(weeks=look_ahead)

    # Note: DATE_FORMAT(date, '%%YCW%%v') is used to create the week string, e.g., '2025CW39'.
    # The double '%' is to escape the '%' for the frappe.db.sql parameter substitution.
    sql_query = f"""
        SELECT
            item_code,
            DATE_FORMAT(delivery_date, '%%YCW%%v') AS calendar_week,
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
        WHERE delivery_date BETWEEN %(start_date)s AND %(end_date)s
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
    start_date = datetime.date.today()
    end_date = start_date + datetime.timedelta(weeks=look_ahead)

    sql_query = f"""
        SELECT
            wo_item.item_code,
            DATE_FORMAT(wo.planned_start_date, '%%YCW%%v') AS calendar_week,
            SUM(wo_item.required_qty - wo_item.transferred_qty) AS total_required_qty
        FROM `tabWork Order Item` AS wo_item
        JOIN `tabWork Order` AS wo ON wo_item.parent = wo.name
        WHERE wo.docstatus = 1
            AND wo.status NOT IN ('Completed', 'Stopped', 'Closed', 'Cancelled')
            AND wo.planned_start_date BETWEEN %(start_date)s AND %(end_date)s
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
    sql_query = f"""
        WITH RECURSIVE DemandExplosion (item_code, target_date, required_qty) AS (
            -- Anchor: Initial demand from MRP entries with open_orders
            SELECT
                item_code,
                target_date,
                open_orders
            FROM `tabMRP Entry`
            WHERE open_orders > 0

            UNION ALL

            -- Recursive Step: Explode demand to child components
            SELECT
                bom_item.item_code,
                de.target_date,
                de.required_qty * bom_item.stock_qty
            FROM DemandExplosion AS de
            JOIN `tabBOM` AS bom ON de.item_code = bom.item
            JOIN `tabBOM Item` AS bom_item ON bom.name = bom_item.parent
            WHERE bom.is_active = 1 AND bom.is_default = 1
        ),
        AggregatedDemand AS (
            -- Aggregate demand for each component by week
            SELECT
                item_code,
                DATE_FORMAT(target_date, '%YCW%v') AS calendar_week,
                SUM(required_qty) AS total_demand
            FROM DemandExplosion
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
        update_cases.append(
            f"WHEN name = {frappe.db.escape(mrp_entry_name)} THEN COALESCE(upstream_so_demand, 0) + {row.total_demand}"
        )

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
    start_date = datetime.date.today()
    end_date = start_date + datetime.timedelta(weeks=look_ahead)

    sql_query = f"""
        SELECT
            production_item,
            DATE_FORMAT(planned_start_date, '%%YCW%%v') AS calendar_week,
            SUM(qty - produced_qty) AS total_planned_qty
        FROM `tabWork Order`
        WHERE
            status NOT IN ('Stopped', 'Completed', 'Closed', 'Cancelled')
            AND docstatus = 1
            AND qty > produced_qty
            AND planned_start_date BETWEEN %(start_date)s AND %(end_date)s
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
    start_date = datetime.date.today()
    end_date = start_date + datetime.timedelta(weeks=look_ahead)

    sql_query = f"""
        SELECT
            po_item.item_code,
            DATE_FORMAT(po_item.schedule_date, '%%YCW%%v') AS calendar_week,
            SUM((po_item.qty - po_item.received_qty) * po_item.conversion_factor) AS total_ordered_qty
        FROM `tabPurchase Order Item` AS po_item
        JOIN `tabPurchase Order` AS po ON po_item.parent = po.name
        WHERE
            po_item.qty > po_item.received_qty
            AND po.status NOT IN ('Closed', 'Delivered', 'Cancelled')
            AND po.docstatus = 1
            AND (po_item.delivered_by_supplier IS NULL OR po_item.delivered_by_supplier = 0)
            AND po_item.schedule_date BETWEEN %(start_date)s AND %(end_date)s
        GROUP BY
            po_item.item_code,
            calendar_week;
    """
    ordered_data = frappe.db.sql(
        sql_query, values={"start_date": start_date, "end_date": end_date}, as_dict=True
    )

    if not ordered_data:
        return

    update_cases = []
    mrp_entry_names = []
    for row in ordered_data:
        mrp_entry_name = f"{row.item_code}-{row.calendar_week}"
        mrp_entry_names.append(frappe.db.escape(mrp_entry_name))
        update_cases.append(
            f"WHEN name = {frappe.db.escape(mrp_entry_name)} THEN COALESCE(ordered_qty, 0) + {row.total_ordered_qty}"
        )

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
