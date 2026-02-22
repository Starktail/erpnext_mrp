# MRP Workbench

The MRP Workbench is the primary user interface for viewing and interacting with the material requirements plan. It provides a dynamic, grid-based view of your MRP data, allowing planners to quickly identify potential issues and take action.

![workbench](images/workbench.png)

### Layout and Structure

The workbench displays the MRP data in a pivoted grid:

-   **Rows**: Each primary row represents a single stock item. You can expand these item rows to reveal detail rows, which break down the calculation for each specific metric (e.g., `On Hand Inventory`, `Open Sales/Work Orders`, `Suggested Receipts`) across the time horizon.
-   **Columns**: The columns are structured to show both static item information and time-phased planning data.
    -   **Static Columns**: The initial columns display key item details like `Item Code`, `Item Name`, `Item Group`, `UoM`, `BOM`, `Lvl`, `Safety Stock`, `Re-order Qty`, `Lead Time`, `Supplier`, and `Days to Reorder`.
    -   **Dynamic Weekly Columns**: The subsequent columns represent the weekly time buckets of the planning horizon (e.g., `2026-W40`, `2026-W41`). For the primary item rows, these columns display a single key figure determined by the field selector. For the expanded detail rows, they show the value for that specific metric.

### Key Features and Actions

The workbench includes several features to help you analyze and manage your material plan:

-   **Clear Filters**: Action to reset the grid's filters.
-   **Rerun MRP Calculations**: This action triggers a background job to recalculate the entire material requirements plan. A dialog will appear to confirm that the process has started and will provide a link to monitor the background job's progress. Once the calculation is complete, you can reload the page to see the updated plan.
-   **Export to CSV**: Export the current view of the MRP grid to a CSV file for offline analysis or reporting.
-   **Only show items with suggested orders**: A checkbox that filters the grid to display only those items that have a `Suggested Order` quantity greater than zero in at least one of the weekly time buckets.
- **Column Field Selector**: A dropdown menu at the top allows you to choose which data field is displayed in the weekly columns for the primary item rows. This is useful for quickly scanning key metrics like `Suggested Orders`, `Projected On Hand Inventory`, or `Suggested Orders Value Payable` across the timeline without needing to expand the rows.
-   **Visual Cues**: The grid uses color coding to draw attention to important items:
    -   <span style="background-color: #ffdddd;">Red Highlight</span>: Indicates a **P1 - Critical** urgent item. This means the item is required and there is not enough quantity on order.
    -   <span style="background-color: #eab26eff;">Orange Highlight</span>: Indicates a **P2 - Attention** urgent item. This means there is enough quantity on order, but it's scheduled to arrive late.
    -   **P3 - Optional** urgent items (ordered but stock will be below safety stock) do not have a specific row highlight but are indicated by the `Urgency Level` column.
    -   <span style="background-color: #ddeeff;">Blue Highlight</span>: Indicates a cell with a **Suggested Order** greater than zero, highlighting the need to place a purchase or work order.
-   **Create Material Request**: This is the primary action on the workbench.
    1.  **Select Rows**: Use the checkboxes to select one or more item rows that have suggested orders.
    2.  **Click Button**: Click the "Create Material Request" button.
    3.  **Confirm**: A dialog box appears summarizing the items, quantities, and suppliers for the material requests that will be created.
    4.  **Creation**: Upon confirmation, the system automatically creates Purchase-type Material Requests. The items are intelligently grouped into separate Material Requests based on their `Default Supplier`. If no supplier is specified, items are grouped into a single request.
    5.  **Success Notification**: A final dialog shows the names of the newly created Material Requests, with links to navigate directly to them.