import frappe


@frappe.whitelist()
def update_mrp_item_entries():
    """
    Calculate the BOM level for all stock items and bulk insert them into the MRP Entry table.

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
            t_item.name AS name,
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

    # 3. Perform a bulk insert of the results
    if not item_list:
        frappe.log_info("No items to update in MRP Entry.", "MRP Item Level Update")
        return

    # Prepare records for bulk insert
    # mrp_entries_to_save = []
    # for item in item_list:
    #     mrp_entry = frappe.new_doc("MRP Entry")
    #     mrp_entry.update(item)
    #     mrp_entries_to_save.append(mrp_entry)

    frappe.db.bulk_insert("MRP Entry", fields=["name", "item_code", "bom_level"], values=item_list, ignore_duplicates=True)

    frappe.msgprint(
        f"Successfully updated {len(item_list)} records in MRP Entry.",
        "MRP Item Level Update",
    )