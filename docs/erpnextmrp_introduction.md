# Introduction
## What is MRP Tools for ERPNext?

MRP Tools for ERPNext is a Material Requirements Planning (MRP) app designed to enhance the manufacturing and inventory management capabilities of ERPNext. It provides a forward-looking planning engine that helps businesses predict material needs, optimize inventory levels, and streamline procurement and production processes.

By analyzing demand from sales orders and forecasts, and considering current inventory and scheduled receipts, the tool generates a time-phased plan for every item, ensuring that materials are available when and where they are needed.

## Key Features

- **BOM-Level Based Calculations**: The MRP engine correctly calculates demand for sub-assemblies and raw materials by exploding the Bill of Materials (BOM) for top-level items.
- **Time-Phased Planning Horizon**: View material requirements, inventory projections, and suggested orders across a configurable look-ahead period, presented in weekly buckets.
- **Demand from Multiple Sources**: Consolidates demand from both firm Sales Orders and user-defined MRP Forecasts.
- **Interactive MRP Workbench**: A modern, grid-based interface to visualize the complete MRP plan, identify potential shortages, and take action.
- **Automated Material Request Generation**: Select suggested orders directly from the workbench to create Purchase-type Material Requests, grouped by supplier.
- **Urgent Item Highlighting**: The system automatically flags orders that need immediate attention because their lead time extends into the past.


## Under the Hood

- [Frappe Framework](https://frappe.io/framework): A full-stack web application framework written in Python and Javascript. The framework provides a robust foundation for building web applications, including a database abstraction layer, user authentication, and a REST API.
- [Frappe UI](https://ui.frappe.io/): A set of components and utilities for rapid UI development for Frappe apps.
- [AG Grid](https://www.ag-grid.com/)

## Installation

Go [here](https://github.com/dvdl16/erpnext_mrp) for installation.

## Support

- [Starktail Website](https://starktail.com)
- [Starktail Email Support](mailto:support@starktail.com)