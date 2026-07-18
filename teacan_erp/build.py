import frappe

MODULE = "Teacan ERP"
SM = {"role": "System Manager", "read":1,"write":1,"create":1,"delete":1,
      "report":1,"export":1,"print":1,"email":1,"share":1}

def make(name, fields, perms=None, autoname=None, naming_rule=None, istable=0):
    if frappe.db.exists("DocType", name):
        frappe.delete_doc("DocType", name, force=1, ignore_permissions=True)
        frappe.db.commit()
    d = {"doctype":"DocType","name":name,"module":MODULE,"custom":0,
         "istable":istable,"editable_grid":1,"fields":fields,"permissions":perms or []}
    if autoname: d["autoname"] = autoname
    if naming_rule: d["naming_rule"] = naming_rule
    frappe.get_doc(d).insert(ignore_permissions=True)
    frappe.db.commit()
    print("OK -> table created:", name)

def reset():
    for dt in ["Order Invoice","Customer Order","Order Item","Product"]:
        if frappe.db.exists("DocType", dt):
            frappe.delete_doc("DocType", dt, force=1, ignore_permissions=True)
            print("removed table:", dt)
    for r in ["Salesman","Production Manager"]:
        if frappe.db.exists("Role", r):
            frappe.delete_doc("Role", r, force=1, ignore_permissions=True)
            print("removed role:", r)
    frappe.db.commit()
    for r in ["Salesman","Production Manager"]:
        frappe.get_doc({"doctype":"Role","role_name":r,"desk_access":1}).insert(ignore_permissions=True)
        print("role ready:", r)
    frappe.db.commit()
    print("RESET DONE")

def t1_product():
    make("Product", autoname="field:product_code", naming_rule="By fieldname",
        perms=[SM, {"role":"Salesman","read":1}],
        fields=[
            {"label":"Product Code","fieldname":"product_code","fieldtype":"Data","reqd":1,"unique":1,"in_list_view":1},
            {"label":"Product Name","fieldname":"product_name","fieldtype":"Data","reqd":1,"in_list_view":1},
            {"label":"Spec","fieldname":"spec","fieldtype":"Data"},
            {"label":"Price","fieldname":"price","fieldtype":"Currency","reqd":1,"in_list_view":1},
        ])

def t2_order_item():
    make("Order Item", istable=1,
        fields=[
            {"label":"Product","fieldname":"product","fieldtype":"Link","options":"Product","reqd":1,"in_list_view":1},
            {"label":"Qty","fieldname":"qty","fieldtype":"Float","default":"1","in_list_view":1},
            {"label":"Rate","fieldname":"rate","fieldtype":"Currency","fetch_from":"product.price","in_list_view":1},
            {"label":"Amount","fieldname":"amount","fieldtype":"Currency","read_only":1,"in_list_view":1},
        ])

def t3_customer_order():
    make("Customer Order", autoname="ORD-.#####", naming_rule="Expression (old style)",
        perms=[SM, {"role":"Salesman","read":1,"write":1,"create":1,"if_owner":1}],
        fields=[
            {"label":"Customer","fieldname":"customer","fieldtype":"Data","reqd":1,"in_list_view":1},
            {"label":"Contact","fieldname":"contact","fieldtype":"Data"},
            {"label":"Address","fieldname":"address","fieldtype":"Small Text"},
            {"label":"Customer GSTIN","fieldname":"customer_gstin","fieldtype":"Data"},
            {"label":"Status","fieldname":"status","fieldtype":"Select","options":"Pending\nConfirmed\nRejected","default":"Pending","in_list_view":1},
            {"label":"Salesman","fieldname":"salesman","fieldtype":"Link","options":"User","read_only":1},
            {"label":"Items","fieldname":"items","fieldtype":"Table","options":"Order Item","reqd":1},
            {"label":"Total Qty","fieldname":"total_qty","fieldtype":"Float","read_only":1},
            {"label":"Total Amount","fieldname":"total_amount","fieldtype":"Currency","read_only":1,"in_list_view":1},
        ])

def t4_order_invoice():
    make("Order Invoice", autoname="INV-.#####", naming_rule="Expression (old style)",
        perms=[SM],
        fields=[
            {"label":"Order","fieldname":"order","fieldtype":"Link","options":"Customer Order","reqd":1,"unique":1,"in_list_view":1},
            {"label":"Customer","fieldname":"customer","fieldtype":"Data","fetch_from":"order.customer","read_only":1,"in_list_view":1},
            {"label":"Discount %","fieldname":"discount","fieldtype":"Percent"},
            {"label":"Invoice A Split %","fieldname":"split_pct","fieldtype":"Percent","default":"50"},
            {"label":"Transportation","fieldname":"transportation","fieldtype":"Currency"},
            {"label":"Packaging","fieldname":"packaging","fieldtype":"Currency"},
            {"label":"GST Rate","fieldname":"gst_rate","fieldtype":"Percent","default":"18"},
        ])

def t5_raw_material():
    make("Raw Material", autoname="field:material_name", naming_rule="By fieldname",
        perms=[SM],
        fields=[
            {"label":"Material Name","fieldname":"material_name","fieldtype":"Data","reqd":1,"unique":1,"in_list_view":1},
        ])

def t6_purchase_item():
    make("Purchase Item", istable=1,
        fields=[
            {"label":"Material","fieldname":"material","fieldtype":"Link","options":"Raw Material","reqd":1,"in_list_view":1},
            {"label":"Quantity","fieldname":"quantity","fieldtype":"Float","default":"1","in_list_view":1},
            {"label":"Price","fieldname":"price","fieldtype":"Currency","in_list_view":1},
            {"label":"GST %","fieldname":"gst_pct","fieldtype":"Percent","default":"18","in_list_view":1},
            {"label":"Amount","fieldname":"amount","fieldtype":"Currency","read_only":1,"in_list_view":1},
        ])

def t7_purchase():
    make("Purchase", autoname="PUR-.#####", naming_rule="Expression (old style)",
        perms=[SM],
        fields=[
            {"label":"Vendor Name","fieldname":"vendor_name","fieldtype":"Data","reqd":1,"in_list_view":1},
            {"label":"Vendor GSTIN","fieldname":"vendor_gstin","fieldtype":"Data"},
            {"label":"Vendor Address","fieldname":"vendor_address","fieldtype":"Small Text"},
            {"label":"Vendor Email","fieldname":"vendor_email","fieldtype":"Data"},
            {"label":"Items","fieldname":"items","fieldtype":"Table","options":"Purchase Item","reqd":1},
            {"label":"Total Qty","fieldname":"total_qty","fieldtype":"Float","read_only":1},
            {"label":"Total Amount","fieldname":"total_amount","fieldtype":"Currency","read_only":1,"in_list_view":1},
        ])

def t5_raw_material():
    make("Raw Material", autoname="field:material_name", naming_rule="By fieldname",
        perms=[SM],
        fields=[
            {"label":"Material Name","fieldname":"material_name","fieldtype":"Data","reqd":1,"unique":1,"in_list_view":1},
        ])

def t6_purchase_item():
    make("Purchase Item", istable=1,
        fields=[
            {"label":"Material","fieldname":"material","fieldtype":"Link","options":"Raw Material","reqd":1,"in_list_view":1},
            {"label":"Quantity","fieldname":"quantity","fieldtype":"Float","default":"1","in_list_view":1},
            {"label":"Price","fieldname":"price","fieldtype":"Currency","in_list_view":1},
            {"label":"GST %","fieldname":"gst_pct","fieldtype":"Percent","default":"18","in_list_view":1},
            {"label":"Amount","fieldname":"amount","fieldtype":"Currency","read_only":1,"in_list_view":1},
        ])

def t7_purchase():
    make("Purchase", autoname="PUR-.#####", naming_rule="Expression (old style)",
        perms=[SM],
        fields=[
            {"label":"Vendor Name","fieldname":"vendor_name","fieldtype":"Data","reqd":1,"in_list_view":1},
            {"label":"Vendor GSTIN","fieldname":"vendor_gstin","fieldtype":"Data"},
            {"label":"Vendor Address","fieldname":"vendor_address","fieldtype":"Small Text"},
            {"label":"Vendor Email","fieldname":"vendor_email","fieldtype":"Data"},
            {"label":"Items","fieldname":"items","fieldtype":"Table","options":"Purchase Item","reqd":1},
            {"label":"Total Qty","fieldname":"total_qty","fieldtype":"Float","read_only":1},
            {"label":"Total Amount","fieldname":"total_amount","fieldtype":"Currency","read_only":1,"in_list_view":1},
        ])

def t8_production_item():
    make("Production Item", istable=1,
        fields=[
            {"label":"Product","fieldname":"product","fieldtype":"Link","options":"Product","reqd":1,"in_list_view":1},
            {"label":"Order Qty","fieldname":"order_qty","fieldtype":"Float","in_list_view":1},
            {"label":"Made Qty","fieldname":"made_qty","fieldtype":"Float","default":"0","in_list_view":1},
            {"label":"Defective Qty","fieldname":"defective_qty","fieldtype":"Float","default":"0","in_list_view":1},
            {"label":"Good Qty","fieldname":"good_qty","fieldtype":"Float","read_only":1,"in_list_view":1},
        ])

def t9_production():
    make("Production", autoname="PRD-.#####", naming_rule="Expression (old style)",
        perms=[SM, {"role":"Production Manager","read":1,"write":1,"create":1}],
        fields=[
            {"label":"Order","fieldname":"order","fieldtype":"Link","options":"Customer Order","reqd":1,"in_list_view":1},
            {"label":"Customer","fieldname":"customer","fieldtype":"Data","fetch_from":"order.customer","read_only":1,"in_list_view":1},
            {"label":"Stage","fieldname":"stage","fieldtype":"Select","options":"Started\nMade\nPackaging\nDispatch\nCompleted","default":"Started","in_list_view":1},
            {"label":"Items","fieldname":"items","fieldtype":"Table","options":"Production Item","reqd":1},
            {"label":"Total Made","fieldname":"total_made","fieldtype":"Float","read_only":1},
            {"label":"Total Defective","fieldname":"total_defective","fieldtype":"Float","read_only":1},
            {"label":"Total Good","fieldname":"total_good","fieldtype":"Float","read_only":1,"in_list_view":1},
            {"label":"Notes","fieldname":"notes","fieldtype":"Small Text"},
        ])

def t10_stock_move():
    make("Stock Move", autoname="STK-.#####", naming_rule="Expression (old style)",
        perms=[SM, {"role":"Production Manager","read":1,"write":1,"create":1}],
        fields=[
            {"label":"Product","fieldname":"product","fieldtype":"Link","options":"Product","reqd":1,"in_list_view":1},
            {"label":"Quantity","fieldname":"quantity","fieldtype":"Float","reqd":1,"in_list_view":1},
            {"label":"Entry Type","fieldname":"entry_type","fieldtype":"Select","options":"Manual Add\nProduction","default":"Manual Add","in_list_view":1},
            {"label":"Reference","fieldname":"reference","fieldtype":"Data","in_list_view":1},
            {"label":"Notes","fieldname":"notes","fieldtype":"Small Text"},
        ])

def grant_pm():
    for dt in ["Customer Order", "Product"]:
        d = frappe.get_doc("DocType", dt)
        if not any(p.role == "Production Manager" for p in d.permissions):
            d.append("permissions", {"role": "Production Manager", "read": 1})
            d.save(ignore_permissions=True)
            frappe.clear_cache(doctype=dt)
            print("granted Production Manager read on", dt)
        else:
            print("already granted on", dt)
    frappe.db.commit()
    print("GRANTS DONE")

def make_customer():
    make("Customer",
        [
            {"fieldname": "customer_name", "fieldtype": "Data", "label": "Customer Name", "reqd": 1, "unique": 1, "in_list_view": 1},
            {"fieldname": "gstin", "fieldtype": "Data", "label": "GSTIN", "in_list_view": 1},
            {"fieldname": "contact", "fieldtype": "Data", "label": "Contact"},
            {"fieldname": "address", "fieldtype": "Small Text", "label": "Address"},
            {"fieldname": "salesman", "fieldtype": "Link", "label": "Salesman", "options": "User"},
            {"fieldname": "tally_ledger", "fieldtype": "Data", "label": "Tally Ledger Name", "description": "Leave blank to use Customer Name"},
        ],
        perms=[
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "Salesman", "read": 1},
            {"role": "Production Manager", "read": 1},
        ],
        autoname="field:customer_name",
        naming_rule="By fieldname",
    )

def make_customer_payment():
    make("Customer Payment",
        [
            {"fieldname": "customer", "fieldtype": "Link", "label": "Customer", "options": "Customer", "reqd": 1, "in_list_view": 1},
            {"fieldname": "channel", "fieldtype": "Select", "label": "Channel", "options": "A\nB", "reqd": 1, "default": "B", "in_list_view": 1, "description": "A = billed via Tally, B = direct collection by salesman"},
            {"fieldname": "amount", "fieldtype": "Currency", "label": "Amount", "reqd": 1, "in_list_view": 1},
            {"fieldname": "payment_date", "fieldtype": "Date", "label": "Payment Date", "default": "Today", "in_list_view": 1},
            {"fieldname": "status", "fieldtype": "Select", "label": "Status", "options": "Pending\nConfirmed", "default": "Pending", "in_list_view": 1},
            {"fieldname": "source", "fieldtype": "Select", "label": "Source", "options": "Salesman\nTally", "default": "Salesman"},
            {"fieldname": "reference", "fieldtype": "Data", "label": "Reference / Voucher No"},
            {"fieldname": "tally_voucher_id", "fieldtype": "Data", "label": "Tally Voucher ID", "description": "Stops the same Tally receipt being imported twice"},
            {"fieldname": "invoice", "fieldtype": "Link", "label": "Against Invoice", "options": "Order Invoice"},
            {"fieldname": "notes", "fieldtype": "Small Text", "label": "Notes"},
        ],
        perms=[
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "Salesman", "read": 1, "create": 1},
        ],
        autoname="PAY-.#####",
        naming_rule="Expression (old style)",
    )

def add_invoice_amounts():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({
        "Order Invoice": [
            {"fieldname": "amounts_sb", "fieldtype": "Section Break", "label": "Computed Amounts", "insert_after": "gst_rate"},
            {"fieldname": "a_goods", "fieldtype": "Currency", "label": "Invoice A - Goods", "read_only": 1},
            {"fieldname": "a_cgst", "fieldtype": "Currency", "label": "Invoice A - CGST", "read_only": 1},
            {"fieldname": "a_sgst", "fieldtype": "Currency", "label": "Invoice A - SGST", "read_only": 1},
            {"fieldname": "a_amount", "fieldtype": "Currency", "label": "Invoice A Total", "read_only": 1, "in_list_view": 1},
            {"fieldname": "amounts_cb", "fieldtype": "Column Break"},
            {"fieldname": "b_goods", "fieldtype": "Currency", "label": "Invoice B - Goods", "read_only": 1},
            {"fieldname": "b_cgst", "fieldtype": "Currency", "label": "Invoice B - CGST", "read_only": 1},
            {"fieldname": "b_sgst", "fieldtype": "Currency", "label": "Invoice B - SGST", "read_only": 1},
            {"fieldname": "b_charges", "fieldtype": "Currency", "label": "Invoice B - Charges", "read_only": 1},
            {"fieldname": "b_amount", "fieldtype": "Currency", "label": "Invoice B Total", "read_only": 1},
            {"fieldname": "grand_total", "fieldtype": "Currency", "label": "Grand Total (A + B)", "read_only": 1},
        ]
    }, ignore_validate=True)
    frappe.db.commit()
    print("OK -> invoice amount fields added")

def recompute_invoices():
    names = frappe.get_all("Order Invoice", pluck="name")
    for nm in names:
        frappe.get_doc("Order Invoice", nm).save(ignore_permissions=True)
    frappe.db.commit()
    print("OK -> recomputed " + str(len(names)) + " invoice(s)")

def import_customers_from_orders():
    orders = frappe.get_all("Customer Order",
        fields=["customer", "contact", "address", "customer_gstin", "salesman"],
        order_by="creation asc")
    seen = {}
    for o in orders:
        nm = (o.customer or "").strip()
        if not nm or nm in seen:
            continue
        seen[nm] = o
    created = 0
    for nm, o in seen.items():
        if frappe.db.exists("Customer", nm):
            continue
        doc = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": nm,
            "contact": o.contact or "",
            "address": o.address or "",
            "gstin": o.customer_gstin or "",
            "salesman": o.salesman or None,
        })
        doc.insert(ignore_permissions=True)
        created += 1
    frappe.db.commit()
    print("OK -> customers in master: " + str(len(seen)) + " | newly created: " + str(created))

def make_vendor():
    make("Vendor",
        [
            {"fieldname": "vendor_name", "fieldtype": "Data", "label": "Vendor Name", "reqd": 1, "unique": 1, "in_list_view": 1},
            {"fieldname": "gstin", "fieldtype": "Data", "label": "GSTIN", "in_list_view": 1},
            {"fieldname": "address", "fieldtype": "Small Text", "label": "Address"},
            {"fieldname": "email", "fieldtype": "Data", "label": "Email"},
            {"fieldname": "tally_ledger", "fieldtype": "Data", "label": "Tally Ledger Name", "description": "Leave blank to use Vendor Name"},
        ],
        perms=[{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
        autoname="field:vendor_name", naming_rule="By fieldname")

def import_vendors_from_purchases():
    rows = frappe.get_all("Purchase", fields=["vendor_name", "vendor_gstin", "vendor_address", "vendor_email"], order_by="creation asc")
    seen = {}
    for r in rows:
        nm = (r.vendor_name or "").strip()
        if not nm or nm in seen:
            continue
        seen[nm] = r
    created = 0
    for nm, r in seen.items():
        if frappe.db.exists("Vendor", nm):
            continue
        frappe.get_doc({"doctype": "Vendor", "vendor_name": nm, "gstin": r.vendor_gstin or "", "address": r.vendor_address or "", "email": r.vendor_email or ""}).insert(ignore_permissions=True)
        created += 1
    frappe.db.commit()
    print("OK -> vendors in master: " + str(len(seen)) + " | newly created: " + str(created))

def make_vendor_payment():
    make("Vendor Payment",
        [
            {"fieldname": "vendor", "fieldtype": "Link", "label": "Vendor", "options": "Vendor", "reqd": 1, "in_list_view": 1},
            {"fieldname": "amount", "fieldtype": "Currency", "label": "Amount", "reqd": 1, "in_list_view": 1},
            {"fieldname": "payment_date", "fieldtype": "Date", "label": "Payment Date", "default": "Today", "in_list_view": 1},
            {"fieldname": "reference", "fieldtype": "Data", "label": "Reference / Mode"},
            {"fieldname": "notes", "fieldtype": "Small Text", "label": "Notes"},
        ],
        perms=[{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
        autoname="VPY-.#####", naming_rule="Expression (old style)")

def make_daily_expense():
    make("Daily Expense",
        [
            {"fieldname": "expense_date", "fieldtype": "Date", "label": "Date", "default": "Today", "reqd": 1, "in_list_view": 1},
            {"fieldname": "category", "fieldtype": "Select", "label": "Category", "options": "General\nTransport\nSalary\nUtility\nMaterial\nOther", "default": "General", "in_list_view": 1},
            {"fieldname": "title", "fieldtype": "Data", "label": "Title", "reqd": 1, "in_list_view": 1},
            {"fieldname": "amount", "fieldtype": "Currency", "label": "Amount", "reqd": 1, "in_list_view": 1},
            {"fieldname": "notes", "fieldtype": "Small Text", "label": "Notes"},
        ],
        perms=[{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
        autoname="EXP-.#####", naming_rule="Expression (old style)")

def make_raw_stock_move():
    make("Raw Stock Move",
        [
            {"fieldname": "material", "fieldtype": "Link", "label": "Raw Material", "options": "Raw Material", "reqd": 1, "in_list_view": 1},
            {"fieldname": "quantity", "fieldtype": "Float", "label": "Quantity (- = used)", "reqd": 1, "in_list_view": 1},
            {"fieldname": "entry_type", "fieldtype": "Select", "label": "Type", "options": "Used\nAdd", "default": "Used", "in_list_view": 1},
            {"fieldname": "reference", "fieldtype": "Data", "label": "Reference"},
            {"fieldname": "notes", "fieldtype": "Small Text", "label": "Notes"},
        ],
        perms=[
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "Production Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
        ],
        autoname="RSM-.#####", naming_rule="Expression (old style)")

def apply_stock_usage():
    dt = frappe.get_doc("DocType", "Stock Move")
    for fld in dt.fields:
        if fld.fieldname == "entry_type" and "Used" not in (fld.options or ""):
            fld.options = (fld.options or "") + "\nUsed"
    dt.save()
    frappe.clear_cache(doctype="Stock Move")
    frappe.db.commit()
    print("OK -> Stock Move 'Used' type added")

def make_raw_stock_move():
    make("Raw Stock Move",
        [
            {"fieldname": "material", "fieldtype": "Link", "label": "Raw Material", "options": "Raw Material", "reqd": 1, "in_list_view": 1},
            {"fieldname": "quantity", "fieldtype": "Float", "label": "Quantity (- = used)", "reqd": 1, "in_list_view": 1},
            {"fieldname": "entry_type", "fieldtype": "Select", "label": "Type", "options": "Used\nAdd", "default": "Used", "in_list_view": 1},
            {"fieldname": "reference", "fieldtype": "Data", "label": "Reference"},
            {"fieldname": "notes", "fieldtype": "Small Text", "label": "Notes"},
        ],
        perms=[
            {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
            {"role": "Production Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
        ],
        autoname="RSM-.#####", naming_rule="Expression (old style)")

def apply_stock_usage():
    dt = frappe.get_doc("DocType", "Stock Move")
    for fld in dt.fields:
        if fld.fieldname == "entry_type" and "Used" not in (fld.options or ""):
            fld.options = (fld.options or "") + "\nUsed"
    dt.save()
    frappe.clear_cache(doctype="Stock Move")
    frappe.db.commit()
    print("OK -> Stock Move 'Used' type added")

def add_tally_fields():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({
        "Order Invoice": [
            {"fieldname": "tally_status", "fieldtype": "Select", "label": "Tally Status",
             "options": "Not Posted\nPosted\nError", "default": "Not Posted", "insert_after": "grand_total"},
            {"fieldname": "tally_vch_no", "fieldtype": "Data", "label": "Tally Voucher No", "insert_after": "tally_status"},
            {"fieldname": "tally_posted_on", "fieldtype": "Datetime", "label": "Tally Posted On", "insert_after": "tally_vch_no"},
            {"fieldname": "tally_error", "fieldtype": "Small Text", "label": "Tally Error", "insert_after": "tally_posted_on"},
        ],
    })
    frappe.db.commit()
    print("OK -> tally tracking fields added to Order Invoice")

def add_unit_support():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({
        "Product": [
            {"fieldname": "unit", "fieldtype": "Select", "label": "Unit",
             "options": "nos\nkg", "default": "nos", "insert_after": "price"},
        ],
    })
    dt = frappe.get_doc("DocType", "Order Item")
    for f in dt.fields:
        if f.fieldname == "qty":
            f.fieldtype = "Float"
    dt.save()
    frappe.clear_cache(doctype="Order Item")
    frappe.db.commit()
    print("OK -> product unit added, qty now allows decimals")

def add_unit_support():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
    create_custom_fields({
        "Product": [
            {"fieldname": "unit", "fieldtype": "Select", "label": "Unit",
             "options": "nos\nkg", "default": "nos", "insert_after": "price"},
        ],
    })
    dt = frappe.get_doc("DocType", "Order Item")
    for f in dt.fields:
        if f.fieldname == "qty":
            f.fieldtype = "Float"
    dt.save()
    frappe.clear_cache(doctype="Order Item")
    frappe.db.commit()
    print("OK -> product unit added, qty now allows decimals")

def make_fcm_token():
    make("FCM Token",
        [
            {"fieldname": "token", "fieldtype": "Small Text", "label": "Token", "reqd": 1, "in_list_view": 1},
            {"fieldname": "user", "fieldtype": "Link", "label": "User", "options": "User", "in_list_view": 1},
            {"fieldname": "device", "fieldtype": "Data", "label": "Device"},
            {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1"},
        ],
        perms=[{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}])
