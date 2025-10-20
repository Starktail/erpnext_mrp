# MRP Workbench

The MRP Workbench is the primary user interface for viewing and interacting with the material requirements plan. It provides a dynamic, grid-based view of your MRP data, allowing planners to quickly identify potential issues and take action.

![workbench](images/workbench.png)

### Layout and Structure

The workbench displays the MRP data in a pivoted grid:

-   **Rows**: Each row represents a single stock item.
-   **Columns**: The columns are structured to show both static item information and time-phased planning data.
    -   **Static Columns**: The initial columns display key item details like `Item Code`, `Item Name`, `Item Group`, `Reorder Level`, `Lead Time`, and `Default Supplier`.
    -   **Dynamic Weekly Columns**: The subsequent columns represent the weekly time buckets of the planning horizon (e.g., `2026-W40`, `2026-W41`). Each weekly column is a group that can be expanded to show detailed fields for that week (`On Hand Inventory`, `Open Orders`, `Suggested Receipts`, etc.) or collapsed to show a single key figure (defaulting to `Suggested Orders`).

### Key Features and Actions

The workbench includes several features to help you analyze and manage your material plan:

-   **Clear Filters**: Action to reset the grid's filters.
-   **Export to CSV**: Export the current view of the MRP grid to a CSV file for offline analysis or reporting.
-   **Column Field Selector**: A dropdown menu at the top allows you to choose which data field is displayed in the weekly columns when they are collapsed. This is useful for quickly scanning key metrics like `Suggested Orders` or `Projected On Hand Inventory` across the timeline.
-   **Visual Cues**: The grid uses color coding to draw attention to important items:
    -   <span style="background-color: #ffdddd;">Red Highlight</span>: Indicates an **Urgent Item**. This means a suggested order for this item is in a past time bucket, requiring immediate attention.
    -   <span style="background-color: #ddeeff;">Blue Highlight</span>: Indicates a cell with a **Suggested Order** greater than zero, highlighting the need to place a purchase or work order.
-   **Create Material Request**: This is the primary action on the workbench.
    1.  **Select Rows**: Use the checkboxes to select one or more item rows that have suggested orders.
    2.  **Click Button**: Click the "Create Material Request" button.
    3.  **Confirm**: A dialog box appears summarizing the items, quantities, and suppliers for the material requests that will be created.
    4.  **Creation**: Upon confirmation, the system automatically creates Purchase-type Material Requests. The items are intelligently grouped into separate Material Requests based on their `Default Supplier`. If no supplier is specified, items are grouped into a single request.
    5.  **Success Notification**: A final dialog shows the names of the newly created Material Requests, with links to navigate directly to them.