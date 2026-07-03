import frappe
from frappe.utils.password import update_password

ROLE_MAP = [
    ("System Manager", "Admin"),
    ("Salesman", "Salesman"),
    ("Production Manager", "Production Manager"),
]

def _is_admin():
    return "System Manager" in frappe.get_roles()

def role_for(user):
    roles = set(frappe.get_roles(user))
    for r, label in ROLE_MAP:
        if r in roles:
            return label
    return "Salesman"

@frappe.whitelist()
def whoami():
    user = frappe.session.user
    full_name = frappe.db.get_value("User", user, "full_name") or user
    return {"user": user, "full_name": full_name, "role": role_for(user)}

@frappe.whitelist()
def list_team():
    if not _is_admin():
        frappe.throw("Not permitted", frappe.PermissionError)
    users = frappe.get_all(
        "User",
        filters={"enabled": 1, "user_type": "System User"},
        fields=["name", "full_name", "enabled"],
    )
    return [
        {"email": u.name, "full_name": u.full_name, "role": role_for(u.name), "enabled": u.enabled}
        for u in users if u.name != "Guest"
    ]

@frappe.whitelist()
def create_team_user(email, full_name, role, new_password):
    if not _is_admin():
        frappe.throw("Not permitted", frappe.PermissionError)
    if role not in ("Admin", "Salesman", "Production Manager"):
        frappe.throw("Invalid role")
    if not new_password or len(new_password) < 6:
        frappe.throw("Password must be at least 6 characters")
    if frappe.db.exists("User", email):
        frappe.throw("A user with this email already exists")
    user = frappe.get_doc({
        "doctype": "User",
        "email": email,
        "first_name": full_name,
        "send_welcome_email": 0,
        "user_type": "System User",
    })
    user.insert(ignore_permissions=True)
    sys_role = "System Manager" if role == "Admin" else role
    user.add_roles(sys_role)
    update_password(user.name, new_password)
    return {"email": email, "full_name": full_name, "role": role}

@frappe.whitelist()
def reset_user_password(email, new_password):
    if not _is_admin():
        frappe.throw("Not permitted", frappe.PermissionError)
    if email == "Administrator":
        frappe.throw("Cannot change the Administrator password here")
    if not frappe.db.exists("User", email):
        frappe.throw("User not found")
    if not new_password or len(new_password) < 6:
        frappe.throw("Password must be at least 6 characters")
    update_password(email, new_password)
    return {"email": email, "ok": True}

def validate_customer_order(doc, method=None):
    if not doc.salesman:
        doc.salesman = frappe.session.user
    total_qty = 0
    total_amount = 0
    for row in (doc.items or []):
        if (not row.rate) and row.product:
            row.rate = frappe.db.get_value("Product", row.product, "price") or 0
        row.amount = (row.qty or 0) * (row.rate or 0)
        total_qty += (row.qty or 0)
        total_amount += row.amount
    doc.total_qty = total_qty
    doc.total_amount = total_amount
    if not doc.is_new():
        before = doc.get_doc_before_save()
        if before and before.status != doc.status and not _is_admin():
            frappe.throw("Only an admin can change order status")

def validate_purchase(doc, method=None):
    total_qty = 0
    total_amount = 0
    for row in (doc.items or []):
        base = (row.quantity or 0) * (row.price or 0)
        gst = base * (row.gst_pct or 0) / 100.0
        row.amount = base + gst
        total_qty += (row.quantity or 0)
        total_amount += row.amount
    doc.total_qty = total_qty
    doc.total_amount = total_amount

def validate_production(doc, method=None):
    total_made = 0
    total_defective = 0
    total_good = 0
    for row in (doc.items or []):
        good = (row.made_qty or 0) - (row.defective_qty or 0)
        if good < 0:
            good = 0
        row.good_qty = good
        total_made += (row.made_qty or 0)
        total_defective += (row.defective_qty or 0)
        total_good += good
    doc.total_made = total_made
    doc.total_defective = total_defective
    doc.total_good = total_good

def production_after_save(doc, method=None):
    before = doc.get_doc_before_save()
    was_completed = bool(before) and before.stage == "Completed"
    if doc.stage == "Completed" and not was_completed:
        for row in (doc.items or []):
            extra = (row.good_qty or 0) - (row.order_qty or 0)
            if extra > 0:
                frappe.get_doc({
                    "doctype": "Stock Move",
                    "product": row.product,
                    "quantity": extra,
                    "entry_type": "Production",
                    "reference": doc.name,
                    "notes": "Extra pieces from " + doc.name,
                }).insert(ignore_permissions=True)

def _prod_allowed():
    if not (_is_admin() or "Production Manager" in frappe.get_roles()):
        frappe.throw("Not permitted", frappe.PermissionError)

@frappe.whitelist()
def approved_orders():
    _prod_allowed()
    orders = frappe.get_all("Customer Order", filters={"status": "Confirmed"},
        fields=["name", "customer", "total_qty", "total_amount"], order_by="creation desc")
    out = []
    for o in orders:
        prod = frappe.db.get_value("Production", {"order": o.name}, "name")
        items = frappe.get_all("Order Item", filters={"parent": o.name},
            fields=["product", "qty"])
        out.append({"name": o.name, "customer": o.customer, "total_qty": o.total_qty,
            "total_amount": o.total_amount, "in_production": bool(prod),
            "production": prod, "items": items})
    return out

@frappe.whitelist()
def raw_material_stock():
    _prod_allowed()
    rows = frappe.get_all("Purchase Item", fields=["material", "quantity"])
    agg = {}
    for r in rows:
        if r.material:
            agg[r.material] = agg.get(r.material, 0) + (r.quantity or 0)
    mats = frappe.get_all("Raw Material", fields=["name"], order_by="name asc")
    return [{"material": m.name, "stock": agg.get(m.name, 0)} for m in mats]

@frappe.whitelist()
def finished_stock():
    _prod_allowed()
    rows = frappe.get_all("Stock Move", fields=["product", "quantity"])
    agg = {}
    for r in rows:
        if r.product:
            agg[r.product] = agg.get(r.product, 0) + (r.quantity or 0)
    prods = frappe.get_all("Product", fields=["name", "product_name"], order_by="product_name asc")
    return [{"product": p.name, "product_name": p.product_name, "stock": agg.get(p.name, 0)} for p in prods]

def _inv_r2(n):
    n = n or 0
    return int(n * 100 + 0.5) / 100.0

def validate_order_invoice(doc, method=None):
    if not doc.order or not frappe.db.exists("Customer Order", doc.order):
        return
    order = frappe.get_doc("Customer Order", doc.order)
    discount = doc.discount or 0
    pct = doc.split_pct if doc.split_pct is not None else 50
    gst = doc.gst_rate if doc.gst_rate is not None else 18
    charges = (doc.transportation or 0) + (doc.packaging or 0)

    def split(share, extra, gstrate):
        goods = 0.0
        for it in (order.items or []):
            main = it.rate or 0
            disc = main * (1 - discount / 100.0)
            rate = _inv_r2(disc * share / 100.0)
            goods += _inv_r2(rate * (it.qty or 0))
        goods = _inv_r2(goods)
        half = gstrate / 2.0
        cgst = _inv_r2(goods * half / 100.0)
        sgst = _inv_r2(goods * half / 100.0)
        total = _inv_r2(goods + cgst + sgst + extra)
        return goods, cgst, sgst, total

    ag, ac, asg, at = split(pct, 0, gst)
    bg, bc, bsg, bt = split(100 - pct, charges, 0)
    doc.a_goods = ag; doc.a_cgst = ac; doc.a_sgst = asg; doc.a_amount = at
    doc.b_goods = bg; doc.b_cgst = bc; doc.b_sgst = bsg; doc.b_charges = charges; doc.b_amount = bt
    doc.grand_total = _inv_r2(at + bt)

def _ledger_guard():
    if not _is_admin():
        frappe.throw("Not permitted", frappe.PermissionError)

@frappe.whitelist()
def customer_ledger_list():
    _ledger_guard()
    customers = frappe.get_all("Customer", fields=["name", "customer_name", "gstin", "salesman"], order_by="customer_name asc")
    inv = frappe.get_all("Order Invoice", fields=["customer", "grand_total"])
    pay = frappe.get_all("Customer Payment", fields=["customer", "amount", "status"])
    bill, paid, pend = {}, {}, {}
    for r in inv:
        if r.customer:
            bill[r.customer] = bill.get(r.customer, 0.0) + (r.grand_total or 0)
    for r in pay:
        if not r.customer:
            continue
        if r.status == "Confirmed":
            paid[r.customer] = paid.get(r.customer, 0.0) + (r.amount or 0)
        elif r.status == "Pending":
            pend[r.customer] = pend.get(r.customer, 0.0) + (r.amount or 0)
    out = []
    for c in customers:
        billed = bill.get(c.name, 0.0)
        collected = paid.get(c.name, 0.0)
        out.append({
            "name": c.name, "customer_name": c.customer_name, "gstin": c.gstin, "salesman": c.salesman,
            "billed": billed, "collected": collected, "pending": pend.get(c.name, 0.0),
            "outstanding": billed - collected,
        })
    return out

@frappe.whitelist()
def customer_ledger(customer):
    _ledger_guard()
    cust = frappe.get_doc("Customer", customer)
    invs = frappe.get_all("Order Invoice", filters={"customer": customer},
        fields=["name", "order", "a_amount", "b_amount", "grand_total", "creation"], order_by="creation asc")
    pays = frappe.get_all("Customer Payment", filters={"customer": customer},
        fields=["name", "channel", "amount", "status", "source", "reference", "payment_date", "creation"], order_by="creation asc")

    a_billed = sum((i.a_amount or 0) for i in invs)
    b_billed = sum((i.b_amount or 0) for i in invs)
    total_billed = sum((i.grand_total or 0) for i in invs)
    a_paid = sum((p.amount or 0) for p in pays if p.channel == "A" and p.status == "Confirmed")
    b_paid = sum((p.amount or 0) for p in pays if p.channel == "B" and p.status == "Confirmed")
    collected = a_paid + b_paid
    pending = sum((p.amount or 0) for p in pays if p.status == "Pending")

    rows = []
    for i in invs:
        d = str(i.creation)[:10]
        rows.append({"date": d, "sort": d + "1", "desc": "Invoice A - " + i.name, "debit": (i.a_amount or 0), "credit": 0})
        rows.append({"date": d, "sort": d + "2", "desc": "Invoice B - " + i.name, "debit": (i.b_amount or 0), "credit": 0})
    for p in pays:
        if p.status == "Confirmed":
            d = str(p.payment_date) if p.payment_date else str(p.creation)[:10]
            label = "Tally" if p.channel == "A" else "Collected"
            rows.append({"date": d, "sort": d + "3", "desc": "Payment (" + label + ") - " + (p.reference or p.name), "debit": 0, "credit": (p.amount or 0)})
    rows.sort(key=lambda x: x["sort"])
    bal = 0.0
    for r in rows:
        bal += r["debit"] - r["credit"]
        r["balance"] = bal

    pending_list = [{
        "name": p.name, "amount": (p.amount or 0),
        "date": str(p.payment_date) if p.payment_date else str(p.creation)[:10],
        "source": p.source, "reference": p.reference, "channel": p.channel,
    } for p in pays if p.status == "Pending"]

    return {
        "customer": cust.name, "customer_name": cust.customer_name, "gstin": cust.gstin, "salesman": cust.salesman,
        "a_billed": a_billed, "b_billed": b_billed, "total_billed": total_billed,
        "a_paid": a_paid, "b_paid": b_paid, "collected": collected, "pending": pending,
        "outstanding": total_billed - collected, "a_out": a_billed - a_paid, "b_out": b_billed - b_paid,
        "statement": rows, "pending_list": pending_list,
    }

@frappe.whitelist()
def vendor_ledger_list():
    _ledger_guard()
    vendors = frappe.get_all("Vendor", fields=["name", "vendor_name", "gstin"], order_by="vendor_name asc")
    pur = frappe.get_all("Purchase", fields=["vendor_name", "total_amount"])
    pay = frappe.get_all("Vendor Payment", fields=["vendor", "amount"])
    bill, paid = {}, {}
    for r in pur:
        if r.vendor_name:
            bill[r.vendor_name] = bill.get(r.vendor_name, 0.0) + (r.total_amount or 0)
    for r in pay:
        if r.vendor:
            paid[r.vendor] = paid.get(r.vendor, 0.0) + (r.amount or 0)
    out = []
    for v in vendors:
        b = bill.get(v.name, 0.0); p = paid.get(v.name, 0.0)
        out.append({"name": v.name, "vendor_name": v.vendor_name, "gstin": v.gstin,
            "purchased": b, "paid": p, "outstanding": b - p})
    return out

@frappe.whitelist()
def vendor_ledger(vendor):
    _ledger_guard()
    v = frappe.get_doc("Vendor", vendor)
    purs = frappe.get_all("Purchase", filters={"vendor_name": vendor}, fields=["name", "total_amount", "creation"], order_by="creation asc")
    pays = frappe.get_all("Vendor Payment", filters={"vendor": vendor}, fields=["name", "amount", "reference", "payment_date", "creation"], order_by="creation asc")
    purchased = sum((r.total_amount or 0) for r in purs)
    paid = sum((r.amount or 0) for r in pays)
    rows = []
    for r in purs:
        dt = str(r.creation)[:10]
        rows.append({"date": dt, "sort": dt + "1", "desc": "Purchase - " + r.name, "debit": (r.total_amount or 0), "credit": 0})
    for r in pays:
        dt = str(r.payment_date) if r.payment_date else str(r.creation)[:10]
        rows.append({"date": dt, "sort": dt + "2", "desc": "Payment - " + (r.reference or r.name), "debit": 0, "credit": (r.amount or 0)})
    rows.sort(key=lambda x: x["sort"])
    bal = 0.0
    for r in rows:
        bal += r["debit"] - r["credit"]; r["balance"] = bal
    return {"vendor": v.name, "vendor_name": v.vendor_name, "gstin": v.gstin,
        "purchased": purchased, "paid": paid, "outstanding": purchased - paid, "statement": rows}

@frappe.whitelist()
def my_outstanding():
    user = frappe.session.user
    orders = frappe.get_all("Customer Order", filters={"salesman": user}, fields=["customer"])
    custs = sorted(set([(o.customer or "").strip() for o in orders if o.customer]))
    inv = frappe.get_all("Order Invoice", fields=["customer", "a_amount", "b_amount"])
    pay = frappe.get_all("Customer Payment", fields=["customer", "channel", "amount", "status"])
    ab, bb, ap, bp, pend = {}, {}, {}, {}, {}
    for r in inv:
        if r.customer:
            ab[r.customer] = ab.get(r.customer, 0.0) + (r.a_amount or 0)
            bb[r.customer] = bb.get(r.customer, 0.0) + (r.b_amount or 0)
    for r in pay:
        if not r.customer:
            continue
        if r.status == "Confirmed":
            if r.channel == "A":
                ap[r.customer] = ap.get(r.customer, 0.0) + (r.amount or 0)
            else:
                bp[r.customer] = bp.get(r.customer, 0.0) + (r.amount or 0)
        elif r.status == "Pending":
            pend[r.customer] = pend.get(r.customer, 0.0) + (r.amount or 0)
    out = []
    for c in custs:
        out.append({"customer": c, "a_billed": ab.get(c, 0.0), "b_billed": bb.get(c, 0.0),
            "a_out": ab.get(c, 0.0) - ap.get(c, 0.0), "b_out": bb.get(c, 0.0) - bp.get(c, 0.0),
            "pending": pend.get(c, 0.0)})
    return out

@frappe.whitelist()
def daily_report(date=None):
    _ledger_guard()
    from frappe.utils import today
    d = date or today()
    cin = frappe.get_all("Customer Payment", filters={"status": "Confirmed", "payment_date": d}, fields=["customer", "channel", "amount", "reference"])
    vout = frappe.get_all("Vendor Payment", filters={"payment_date": d}, fields=["vendor", "amount", "reference"])
    exp = frappe.get_all("Daily Expense", filters={"expense_date": d}, fields=["title", "category", "amount"])
    prod = frappe.get_all("Production", filters=[["modified", "between", [d + " 00:00:00", d + " 23:59:59"]]], fields=["name", "order", "customer", "stage", "total_made", "total_good"])
    pend = frappe.get_all("Customer Payment", filters={"status": "Pending"}, fields=["customer", "amount", "reference", "payment_date"])
    cin_t = sum((r.amount or 0) for r in cin)
    vout_t = sum((r.amount or 0) for r in vout)
    exp_t = sum((r.amount or 0) for r in exp)
    pend_t = sum((r.amount or 0) for r in pend)
    return {"date": d,
        "collections_in": cin, "collections_in_total": cin_t,
        "vendor_out": vout, "vendor_out_total": vout_t,
        "expenses": exp, "expenses_total": exp_t,
        "production": prod,
        "pending_collections": pend, "pending_total": pend_t,
        "net": cin_t - vout_t - exp_t}

@frappe.whitelist()
def period_report(from_date=None, to_date=None):
    _ledger_guard()
    from frappe.utils import today
    f = from_date or today()
    t = to_date or f
    start = f + " 00:00:00"; end = t + " 23:59:59"
    cin = frappe.get_all("Customer Payment", filters={"status": "Confirmed", "payment_date": ["between", [f, t]]}, fields=["customer", "channel", "amount", "reference"])
    vout = frappe.get_all("Vendor Payment", filters={"payment_date": ["between", [f, t]]}, fields=["vendor", "amount", "reference"])
    exp = frappe.get_all("Daily Expense", filters={"expense_date": ["between", [f, t]]}, fields=["title", "category", "amount"])
    prod = frappe.get_all("Production", filters=[["modified", "between", [start, end]]], fields=["name", "order", "customer", "stage", "total_made", "total_good"])
    pend = frappe.get_all("Customer Payment", filters={"status": "Pending", "payment_date": ["between", [f, t]]}, fields=["customer", "amount", "reference"])
    cin_t = sum((r.amount or 0) for r in cin); vout_t = sum((r.amount or 0) for r in vout)
    exp_t = sum((r.amount or 0) for r in exp); pend_t = sum((r.amount or 0) for r in pend)
    return {"from": f, "to": t, "collections_in": cin, "collections_in_total": cin_t,
        "vendor_out": vout, "vendor_out_total": vout_t, "expenses": exp, "expenses_total": exp_t,
        "production": prod, "pending_collections": pend, "pending_total": pend_t, "net": cin_t - vout_t - exp_t}

@frappe.whitelist()
def raw_material_stock():
    _prod_allowed()
    agg = {}
    for r in frappe.get_all("Purchase Item", fields=["material", "quantity"]):
        if r.material:
            agg[r.material] = agg.get(r.material, 0) + (r.quantity or 0)
    try:
        for r in frappe.get_all("Raw Stock Move", fields=["material", "quantity"]):
            if r.material:
                agg[r.material] = agg.get(r.material, 0) + (r.quantity or 0)
    except Exception:
        pass
    mats = frappe.get_all("Raw Material", fields=["name"], order_by="name asc")
    return [{"material": m.name, "stock": agg.get(m.name, 0)} for m in mats]
