#!/usr/bin/env python3
"""
Run on BOTH local and live:
  cd ~/frappe-bench/apps/teacan_erp/teacan_erp
  python3 /path/to/fix_doctypes.py
  cd ~/frappe-bench && bench --site <site> migrate && bench --site <site> clear-cache
"""
import json, os

BASE = os.path.dirname(os.path.abspath(__file__))
# If run from teacan_erp/teacan_erp, the doctype folder is here
DT_DIR = os.path.join(BASE, "teacan_erp", "doctype") if os.path.isdir(os.path.join(BASE, "teacan_erp", "doctype")) else os.path.join(BASE, "doctype")

# ---- 1. Add prod_discount to Order Item ----
oi_path = os.path.join(DT_DIR, "order_item", "order_item.json")
with open(oi_path) as f:
    oi = json.load(f)
names = [fd["fieldname"] for fd in oi["fields"]]
if "prod_discount" not in names:
    oi["fields"].append({"fieldname": "prod_discount", "fieldtype": "Float", "label": "Discount %", "default": "0"})
    if "field_order" in oi and "prod_discount" not in oi["field_order"]:
        # Insert after rate
        idx = oi["field_order"].index("rate") + 1 if "rate" in oi["field_order"] else len(oi["field_order"])
        oi["field_order"].insert(idx, "prod_discount")
    print("Added prod_discount to Order Item")
else:
    print("prod_discount already in Order Item")
# Also make sure fetch_from is removed from rate
for fd in oi["fields"]:
    if fd["fieldname"] == "rate" and "fetch_from" in fd:
        del fd["fetch_from"]
        print("Removed fetch_from from rate")
with open(oi_path, "w") as f:
    json.dump(oi, f, indent=1)

# ---- 2. Create Customer Ledger DocType if missing ----
cl_dir = os.path.join(DT_DIR, "customer_ledger")
cl_path = os.path.join(cl_dir, "customer_ledger.json")
cl_py = os.path.join(cl_dir, "customer_ledger.py")
if not os.path.exists(cl_path):
    os.makedirs(cl_dir, exist_ok=True)
    cl = {
        "actions": [], "allow_rename": 1, "autoname": "CL-.#####",
        "creation": "2026-08-11 00:00:00.000000", "doctype": "DocType",
        "engine": "InnoDB", "module": "Teacan ERP", "name": "Customer Ledger",
        "owner": "Administrator", "istable": 0, "editable_grid": 1,
        "field_order": ["customer", "ref_type", "ref", "channel", "debit", "credit"],
        "fields": [
            {"fieldname": "customer", "fieldtype": "Link", "label": "Customer", "options": "Customer", "reqd": 1},
            {"fieldname": "ref_type", "fieldtype": "Data", "label": "Ref Type"},
            {"fieldname": "ref", "fieldtype": "Data", "label": "Ref"},
            {"fieldname": "channel", "fieldtype": "Data", "label": "Channel"},
            {"fieldname": "debit", "fieldtype": "Currency", "label": "Debit"},
            {"fieldname": "credit", "fieldtype": "Currency", "label": "Credit"},
        ],
        "index_web_pages_for_search": 1, "links": [], "modified": "2026-08-11 00:00:00.000000",
        "modified_by": "Administrator", "permissions": [
            {"create": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "read": 1, "report": 1, "role": "System Manager", "share": 1, "write": 1}
        ],
        "sort_field": "creation", "sort_order": "DESC", "states": []
    }
    with open(cl_path, "w") as f:
        json.dump(cl, f, indent=1)
    if not os.path.exists(cl_py):
        with open(cl_py, "w") as f:
            f.write("import frappe\nfrom frappe.model.document import Document\n\nclass CustomerLedger(Document):\n    pass\n")
    init_py = os.path.join(cl_dir, "__init__.py")
    if not os.path.exists(init_py):
        open(init_py, "w").write("")
    print("Created Customer Ledger DocType")
else:
    print("Customer Ledger DocType already exists")

# ---- 3. Ensure Customer has state and tally_ledger fields ----
cust_path = os.path.join(DT_DIR, "customer", "customer.json")
with open(cust_path) as f:
    cust = json.load(f)
cnames = [fd["fieldname"] for fd in cust["fields"]]
changed = False
for fname, flabel, ftype in [("state", "State", "Data"), ("tally_ledger", "Tally Ledger", "Data")]:
    if fname not in cnames:
        cust["fields"].append({"fieldname": fname, "fieldtype": ftype, "label": flabel})
        if "field_order" in cust and fname not in cust["field_order"]:
            cust["field_order"].append(fname)
        print(f"Added {fname} to Customer")
        changed = True
if changed:
    with open(cust_path, "w") as f:
        json.dump(cust, f, indent=1)

print("\nAll DocType fixes done. Now run: bench --site <site> migrate")
