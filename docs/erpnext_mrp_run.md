# MRP Calculations

The core of the MRP Tools is a background process that calculates the material plan. This process runs asynchronously and populates the `MRP Entry` table, which serves as the data source for the MRP Workbench. The calculation is designed to be idempotent, meaning it clears all previous data before generating the new plan to ensure accuracy.

### 1. MRP Settings

![MRP Settings](images/mrp_settings.png)

The `MRP Settings` doctype allows you to configure various parameters for the MRP calculation:

-   **Custom Item Lead Time Field**: This setting allows you to select an Item DocField to be used as the primary lead time (in days) for procurement or manufacturing. By default, this is `lead_time_days`.
-   **Item Additional Lead Time Field**: Optionally, you can select another Item DocField to add to the primary lead time. This is useful for incorporating custom lead time factors.
-   **Custom Purchase Order Item Delivery Date Field**: This setting allows you to select a mandatory Date DocField from the `Purchase Order Item` doctype. This field will be used as the delivery date for calculating `Ordered Qty` in the MRP run. By default, `schedule_date` is used.
-   **Custom Re-order Qty Item Field**: Here you can select another `Item` DocField to be used as the Re-order Quantity. Defaults to the 'Minimum Order Qty' field 

The calculation is executed in several distinct stages:

### 2. Item and Period Scaffolding

First, the system creates a planning scaffold for all relevant items over the defined time horizon.

- **BOM Level Calculation**: The process starts by calculating the Bill of Materials (BOM) level for every stock item. It uses a recursive SQL query to determine the deepest level an item appears in any default, active BOM. Top-level items are at level 0.
- **Time Horizon Generation**: Based on the "Look Ahead" setting in `MRP Settings`, the system generates a series of weekly periods (e.g., `2026-W40`, `2026-W41`, etc.).
- **MRP Entry Creation**: An `MRP Entry` record is created for each item for each week in the look-ahead period. This creates the grid of data that will be populated in the subsequent steps.

### 3. Demand Calculation

Next, the system calculates all sources of demand.

- **Open Orders Demand**:
    - **Reserved Qty**: Calculates demand from open Sales Orders.
    - **Reserved Qty for Production**: Calculates demand for raw materials from open Work Orders.
    - **Upstream Sales Order Demand**: Explodes the demand from Sales Orders down through the BOMs to calculate requirements for sub-assemblies and components.
- **Forecast Demand**:
    - **Forecast Demand**: Calculates demand from the `MRP Forecast` doctype for top-level items.
    - **Upstream Forecast Demand**: Explodes the forecast demand down through the BOMs to calculate requirements for sub-assemblies and components.

### 4. Scheduled Receipts Calculation

The system then calculates all sources of future supply.

- **Planned Qty**: Calculates scheduled receipts from open Work Orders for manufactured items.
- **Ordered Qty**: Calculates scheduled receipts from open Purchase Orders for purchased items. The delivery date for these receipts is determined by the `Purchase Order Item Delivery Date Field` set in `MRP Settings`.

### 5. Totals and Projections

Finally, the system calculates the net position and suggests actions.

- **Totals Calculation**: The various demand and supply fields are summed into total fields like `Open Orders`, `Total Forecast Demand`, and `Scheduled Receipts`.
- **Suggestions and Projected Stock**: This is the core MRP logic. For each item, the calculation proceeds chronologically, week by week:
    1.  **Beginning Inventory**: The `On Hand Inventory` for the first period is the current actual stock level. For all subsequent periods, it is the `Projected On Hand Inventory` from the previous period.
    2.  **Net Requirements**: The system calculates the total demand for the period based on the "Requirement based on" setting (e.g., Forecast only, Open Orders + Forecast, etc.).
    3.  **Shortage Calculation**: It determines if there is a shortage by comparing the on-hand inventory and scheduled receipts against the total demand and the item's `Safety Stock` (from the Item master).
    4.  **Suggested Receipts**: If a shortage exists, the system calculates a `Suggested Receipt`. This value considers the shortage quantity and the item's `Min Order Qty` (from the Item master).
    5.  **Projected Inventory**: It calculates the `Projected On Hand Inventory` at the end of the period.
    6.  **Suggested Orders**: The `Suggested Receipt` is offset by the item's lead time to generate a `Suggested Order` in the appropriate earlier time bucket. For example, if an item has a 2-week lead time, a suggested receipt in Week 42 will generate a suggested order in Week 40.
    7.  **Urgency Flag**: If a suggested order is calculated for a period that is already in the past, the item is flagged as `Urgent`.
- **Cash Requirements**: Finally, the system projects the financial impact of the plan.
    - **Order Value**: Calculates the estimated cost of the `Suggested Orders` using the item's buying price list or valuation rate.
    - **Payable Value**: Projects the cash outflow based on the default Supplier's **Payment Terms**. The system calculates the due date (assuming the invoice is dated upon receipt of goods) and distributes the payable amount to the corresponding weeks.
    - **Custom Due Dates**: For more precise cash planning, the system supports dynamic due dates on the `Payment Term` doctype. This allows you to split payments based on milestones:
        - **Order date**: The payment is calculated relative to when the `Suggested Order` is placed.
        - **Shipment date**: The payment is calculated relative to the shipment date (Order date + Item's primary lead time).
        - **Arrival date**: The payment is calculated relative to the arrival date (Order date + Item's total lead time).
        - If no custom due date is set, the system defaults to the **Arrival date**.

## MRP Entry Fields

The following are the key fields calculated for each item in each period:

| Field                           | Description                                                                                                                                                           |
| ------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Item Details**                |                                                                                                                                                                       |
| `item_code`                     | The item being planned.                                                                                                                                               |
| `bom_level`                     | The calculated BOM level of the item.                                                                                                                                 |
| `target_date`                   | The target date for the planning period (week).                                                                                                                       |
| `reorder_level`                 | The minimum stock level for the item, from the `Safety Stock` field on the Item master.                                                                               |
| `reorder_quantity`              | The minimum order quantity (MOQ) for the item, from the `Min Order Qty` field on the Item master.                                                                     |
| `lead_time`                     | The lead time (in days) for procuring or manufacturing the item, derived from the 'Item Lead Time Field' and 'Item Additional Lead Time Field' in MRP Settings.       |
| **Inventory & Demand**          |                                                                                                                                                                       |
| `on_hand_inventory`             | The stock on hand at the beginning of the period.                                                                                                                     |
| `open_orders`                   | Total demand from firm orders (Sales Orders and Work Orders).                                                                                                         |
| `total_forecast_demand`         | Total demand from forecasts, including exploded demand for components.                                                                                                |
| **Supply**                      |                                                                                                                                                                       |
| `scheduled_receipts`            | Total expected supply from open Work Orders and Purchase Orders.                                                                                                      |
| **Calculations & Projections**  |                                                                                                                                                                       |
| `suggested_receipts`            | The quantity the MRP calculation suggests should be received in this period to avoid a shortage.                                                                      |
| `suggested_orders`              | The quantity that should be ordered, offset by lead time. This is the primary action field.                                                                           |
| `projected_on_hand_inventory`   | The projected stock on hand at the end of the period after considering all demand, supply, and suggested receipts.                                                    |
| `suggested_orders_value`        | The estimated value of the suggested orders.                                                                                                                          |
| `suggested_orders_value_payable`| The projected cash outflow for the period, based on the supplier's payment terms.                                                                                     |