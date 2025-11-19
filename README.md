<div align="center" markdown="1">

<img src="erpnext_mrp/public/mrp-logo.png" width="80" />


# MRP Tools for ERPNext

**Material Requirements Planning (MRP) app for ERPNext**
![demo screenshot](docs/images/workbench.png)
</div>


### MRP Tools for ERPNext

![CI workflow](#)
![codecov](#)

MRP Tools for ERPNext


### License

MIT


### Features

- **BOM-Level Based Calculations**: The MRP engine correctly calculates demand for sub-assemblies and raw materials by exploding the Bill of Materials (BOM) for top-level items.
- **Time-Phased Planning Horizon**: View material requirements, inventory projections, and suggested orders across a configurable look-ahead period, presented in weekly buckets.
- **Demand from Multiple Sources**: Consolidates demand from both firm Sales Orders and user-defined MRP Forecasts.
- **Interactive MRP Workbench**: A modern, grid-based interface to visualize the complete MRP plan, identify potential shortages, and take action.
- **Automated Material Request Generation**: Select suggested orders directly from the workbench to create Purchase-type Material Requests, grouped by supplier.
- **Urgent Item Highlighting**: The system automatically flags orders that need immediate attention because their lead time extends into the past.

### User documentation

📄 [MRP Tools for ERPNext Documentation](https://erpnext-mrp-docs.starktail.com/erpnextmrp_introduction)

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app erpnext_mrp
```

### Development

#### Frappe UI

The frontend was cloned using [frappe-ui-starter](https://github.com/netchampfaris/frappe-ui-starter):
```shell
cd apps/erpnext_mrp
npx degit netchampfaris/frappe-ui-starter frontend
cd frontend
yarn
yarn dev --host
```

In a development environment, you need to put the below key-value pair in your site_config.json file:
```
"ignore_csrf": 1
```
This will prevent CSRFToken errors while using the vite dev server. In production environment, the csrf_token is attached to the window object in index.html for you.

The Vite dev server will start on the port 8080. This can be changed from vite.config.js. The development server is configured to proxy your frappe app (usually running on port 8000). If you have a site named todo.test, open http://todo.test:8080 in your browser. If you see a button named "Click to send 'ping' request", congratulations!

If you notice the browser URL is /frontend, this is the base URL where your frontend app will run in production. To change this, open src/router.js and change the base URL passed to createWebHistory.


#### Tests

To run unit tests:

```shell
bench --site test_site run-tests --app erpnext_mrp --coverage
```

To run UI/integration tests:

The following depencies are required
```shell
sudo apt update
# Dependencies for cypress: https://docs.cypress.io/guides/continuous-integration/introduction#UbuntuDebian
sudo apt-get install libgtk2.0-0 libgtk-3-0 libgbm-dev libnotify-dev libgconf-2-4 libnss3 libxss1 libasound2 libxtst6 xauth xvfb

sudo apt-get install chromium
```

```shell
bench --site test_site run-ui-tests erpnext_mrp --headless --browser chromium
```

#### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/erpnext_mrp
pre-commit install

#(optional) Run against all the files
pre-commit run --all-files
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade


We use [Semgrep](https://semgrep.dev/docs/getting-started/) rules specific to [Frappe Framework](https://github.com/frappe/frappe)
```shell
# Install semgrep
python3 -m pip install semgrep

# Clone the rules repository
git clone --depth 1 https://github.com/frappe/semgrep-rules.git frappe-semgrep-rules

# Run semgrep specifying rules folder as config 
semgrep --config=/workspace/development/frappe-semgrep-rules/rules apps/erpnext_mrp
```

#### Updating Documentation

For documentation, we use [vitepress](https://vitepress.dev/). You can run `yarn docs:dev` to preview the docs when applying changes

#### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request, as well as [Semgrep](https://semgrep.dev/docs/getting-started/)

