### MRP Tools for ERPNext

MRP Tools for ERPNext

> #### 🚧🚧 This app is still in requirements generation and POC phase 🚧🚧


![demo screenshot](docs/demo.png)

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app erpnext_mrp
```

### Frappe UI

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

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/erpnext_mrp
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
