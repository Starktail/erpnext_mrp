import datetime
import itertools

import frappe
from frappe import _


@frappe.whitelist()
def create_mrp_item_entries():
    """
    Calculate BOM levels and create MRP Entry records for each item for each week in a look-ahead period.

    This function is idempotent: it clears all existing MRP Entry records before inserting new ones.
    It uses a performant SQL query to get item levels and `itertools` to efficiently combine
    items with time periods, avoiding slow loops.
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
    pass
