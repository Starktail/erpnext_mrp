#!/bin/bash

# This is used in pacakge.json to block the help pages from public access, and copy the assets to the correct directory

AUTH_CONTENT="import frappe
from frappe import _

if frappe.session.user=='Guest':
    frappe.throw(_(\"You need to be logged in to access this page\"), frappe.PermissionError)"

for file in erpnext_mrp/www/erpnext_mrp_*.html; do
  if [ -f "$file" ]; then
    py_file="erpnext_mrp/www/$(basename "$file" .html).py"
    echo "$AUTH_CONTENT" > "$py_file"
  fi
done

rm -rf ./erpnext_mrp/public/chunks
mv ./erpnext_mrp/www/assets/erpnext_mrp/chunks ./erpnext_mrp/public/.
mv ./erpnext_mrp/www/assets/erpnext_mrp/*.js ./erpnext_mrp/public/.
mv ./erpnext_mrp/www/assets/erpnext_mrp/*.css ./erpnext_mrp/public/.