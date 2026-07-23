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

# ------------------------- TALLY INTEGRATION -------------------------

def _tally_url():
    return (frappe.conf.get("tally_url") or "http://localhost:9000").rstrip("/")


def _tally_ledgers():
    return {
        "sales": frappe.conf.get("tally_sales_ledger") or "Sales Gst - 5%",
        "cgst": frappe.conf.get("tally_cgst_ledger") or "C GST",
        "sgst": frappe.conf.get("tally_sgst_ledger") or "S GST",
    }


def _x(s):
    s = "" if s is None else str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _tally_post(xml):
    import requests
    url = _tally_url()
    try:
        r = requests.post(url, data=xml.encode("utf-8"), headers={"Content-Type": "text/xml"}, timeout=25)
        return r.text or ""
    except Exception as e:
        frappe.throw("Cannot reach Tally at " + url + " - is TallyPrime open on the Windows PC? (" + str(e)[:120] + ")")


def _tally_err(t):
    import re
    m = re.search(r"<LINEERROR>(.*?)</LINEERROR>", t or "", re.S)
    if not m:
        return ""
    e = m.group(1)
    return e.replace("&apos;", "'").replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").strip()


def _tally_all_ledgers_raw():
    xml = ('<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>'
           '<TYPE>Collection</TYPE><ID>All Ledgers</ID></HEADER><BODY><DESC><STATICVARIABLES>'
           '<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES><TDL><TDLMESSAGE>'
           '<COLLECTION NAME="All Ledgers" ISMODIFY="No"><TYPE>Ledger</TYPE><FETCH>NAME</FETCH>'
           '</COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>')
    return _tally_post(xml)


def _tally_has_ledger(name):
    return ('name="' + _x(name).lower() + '"') in _tally_all_ledgers_raw().lower()


def _tally_create_party(name):
    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME="' + _x(name) + '" ACTION="Create">'
           '<NAME>' + _x(name) + '</NAME><PARENT>Sundry Debtors</PARENT></LEDGER></TALLYMESSAGE>'
           '</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')
    t = _tally_post(xml)
    return ("<CREATED>1" in t), t


@frappe.whitelist()
def tally_check():
    _ledger_guard()
    t = _tally_all_ledgers_raw()
    ok = ("<LEDGER" in t) or ("<ENVELOPE" in t)
    return {"ok": ok, "url": _tally_url(), "ledger_names_found": t.count("<LEDGER "), "reply_start": t[:160]}


@frappe.whitelist()
def post_invoice_to_tally(invoice, force=0):
    _ledger_guard()
    inv = frappe.get_doc("Order Invoice", invoice)
    if (inv.get("tally_status") or "") == "Posted" and not int(force or 0):
        return {"ok": False, "error": "Already posted to Tally (" + (inv.get("tally_vch_no") or inv.name) + "). It will not be posted twice."}

    goods = float(inv.get("a_goods") or 0)
    cgst = float(inv.get("a_cgst") or 0)
    sgst = float(inv.get("a_sgst") or 0)
    total = float(inv.get("a_amount") or 0)
    if total <= 0:
        return {"ok": False, "error": "Invoice A total is 0 - nothing to post."}
    if abs((goods + cgst + sgst) - total) > 0.05:
        return {"ok": False, "error": "Invoice A parts do not add up. Open the invoice, re-save it, then try again."}

    cust = (inv.get("customer") or "").strip()
    if not cust:
        return {"ok": False, "error": "Invoice has no customer."}
    tled = cust
    if frappe.db.exists("Customer", cust):
        tled = (frappe.db.get_value("Customer", cust, "tally_ledger") or cust).strip() or cust

    if not _tally_has_ledger(tled):
        created, rep = _tally_create_party(tled)
        if not created and "already exist" not in rep.lower():
            err = _tally_err(rep) or "Could not create the customer ledger in Tally."
            frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err})
            frappe.db.commit()
            return {"ok": False, "error": err}

    L = _tally_ledgers()
    d8 = str(inv.creation)[:10].replace("-", "")
    rows = []
    rows.append('<ALLLEDGERENTRIES.LIST><LEDGERNAME>' + _x(tled) + '</LEDGERNAME>'
                '<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><AMOUNT>-' + ("%.2f" % total) + '</AMOUNT></ALLLEDGERENTRIES.LIST>')
    rows.append('<ALLLEDGERENTRIES.LIST><LEDGERNAME>' + _x(L["sales"]) + '</LEDGERNAME>'
                '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>' + ("%.2f" % goods) + '</AMOUNT></ALLLEDGERENTRIES.LIST>')
    if cgst > 0:
        rows.append('<ALLLEDGERENTRIES.LIST><LEDGERNAME>' + _x(L["cgst"]) + '</LEDGERNAME>'
                    '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>' + ("%.2f" % cgst) + '</AMOUNT></ALLLEDGERENTRIES.LIST>')
    if sgst > 0:
        rows.append('<ALLLEDGERENTRIES.LIST><LEDGERNAME>' + _x(L["sgst"]) + '</LEDGERNAME>'
                    '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>' + ("%.2f" % sgst) + '</AMOUNT></ALLLEDGERENTRIES.LIST>')

    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="Sales" ACTION="Create">'
           '<DATE>' + d8 + '</DATE><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>'
           '<VOUCHERNUMBER>' + _x(inv.name) + '</VOUCHERNUMBER>'
           '<PARTYLEDGERNAME>' + _x(tled) + '</PARTYLEDGERNAME>'
           '<PERSISTEDVIEW>Accounting Voucher View</PERSISTEDVIEW>'
           '<NARRATION>Shalini ERP ' + _x(inv.name) + ' / ' + _x(inv.get("order") or "") + '</NARRATION>'
           + "".join(rows) +
           '</VOUCHER></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')

    t = _tally_post(xml)
    if "<CREATED>1" in t:
        frappe.db.set_value("Order Invoice", inv.name, {
            "tally_status": "Posted", "tally_vch_no": inv.name,
            "tally_posted_on": frappe.utils.now(), "tally_error": ""})
        frappe.db.commit()
        return {"ok": True, "voucher": inv.name, "party": tled, "total": total}

    err = _tally_err(t) or ("Tally did not accept the voucher. Reply: " + (t[:180] if t else "(empty)"))
    frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err})
    frappe.db.commit()
    return {"ok": False, "error": err}

@frappe.whitelist()
def pull_tally_receipts():
    _ledger_guard()
    import re
    from frappe.utils import today
    start = frappe.conf.get("tally_books_from") or "20260401"
    end = today().replace("-", "")
    xml = ('<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>'
           '<TYPE>Collection</TYPE><ID>ErpReceipts</ID></HEADER><BODY><DESC><STATICVARIABLES>'
           '<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>'
           '<SVFROMDATE>' + start + '</SVFROMDATE><SVTODATE>' + end + '</SVTODATE>'
           '</STATICVARIABLES><TDL><TDLMESSAGE>'
           '<COLLECTION NAME="ErpReceipts" ISMODIFY="No">'
           '<TYPE>Voucher</TYPE><FILTERS>ErpIsRcpt</FILTERS>'
           '<FETCH>DATE,VOUCHERNUMBER,VOUCHERTYPENAME,PARTYLEDGERNAME,AMOUNT,GUID</FETCH>'
           '</COLLECTION>'
           '<SYSTEM TYPE="Formulae" NAME="ErpIsRcpt">$$IsEqual:$VoucherTypeName:"Receipt"</SYSTEM>'
           '</TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>')
    t = _tally_post(xml)

    cmap = {}
    for c in frappe.get_all("Customer", fields=["name", "tally_ledger"]):
        cmap[(c.tally_ledger or c.name).strip().lower()] = c.name

    made, skipped, unmatched = 0, 0, []
    for vm in re.finditer(r"<VOUCHER[^>]*>(.*?)</VOUCHER>", t or "", re.S):
        v = vm.group(1)
        def fld(tag):
            m = re.search("<" + tag + r">(.*?)</" + tag + ">", v, re.S)
            return (m.group(1) if m else "").strip()
        if fld("VOUCHERTYPENAME").lower() != "receipt":
            continue
        guid = fld("GUID")
        party = fld("PARTYLEDGERNAME").replace("&amp;", "&").replace("&quot;", '"').replace("&apos;", "'").replace("&lt;", "<").replace("&gt;", ">")
        try:
            amt = abs(float(fld("AMOUNT") or 0))
        except Exception:
            amt = 0
        d8 = fld("DATE")
        pdate = (d8[:4] + "-" + d8[4:6] + "-" + d8[6:8]) if len(d8) == 8 else None
        vno = fld("VOUCHERNUMBER")
        if not guid or amt <= 0:
            continue
        if frappe.db.exists("Customer Payment", {"tally_voucher_id": guid}):
            skipped += 1
            continue
        cust = cmap.get(party.strip().lower())
        if not cust:
            if party and party not in unmatched:
                unmatched.append(party)
            continue
        doc = frappe.get_doc({
            "doctype": "Customer Payment", "customer": cust, "channel": "A",
            "amount": amt, "status": "Confirmed", "source": "Tally",
            "reference": ("Tally Rcpt " + vno).strip(), "tally_voucher_id": guid,
            "payment_date": pdate,
        })
        doc.insert(ignore_permissions=True)
        made += 1
    frappe.db.commit()
    return {"ok": True, "imported": made, "already_had": skipped, "unmatched_tally_parties": unmatched}

@frappe.whitelist()
def pull_tally_receipts():
    _ledger_guard()
    import re
    from frappe.utils import today
    start = frappe.conf.get("tally_books_from") or "20260401"
    end = today().replace("-", "")
    xml = ('<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>'
           '<TYPE>Data</TYPE><ID>Voucher Register</ID></HEADER><BODY><DESC><STATICVARIABLES>'
           '<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>'
           '<SVFROMDATE>' + start + '</SVFROMDATE><SVTODATE>' + end + '</SVTODATE>'
           '<VOUCHERTYPENAME>Receipt</VOUCHERTYPENAME>'
           '</STATICVARIABLES></DESC></BODY></ENVELOPE>')
    t = _tally_post(xml)

    def unesc(s):
        return (s or "").replace("&amp;", "&").replace("&quot;", '"').replace("&apos;", "'").replace("&lt;", "<").replace("&gt;", ">").strip()

    cmap = {}
    for c in frappe.get_all("Customer", fields=["name", "tally_ledger"]):
        cmap[(c.tally_ledger or c.name).strip().lower()] = c.name

    made, skipped, unmatched, seen = 0, 0, [], 0
    for vm in re.finditer(r"<VOUCHER\b[^>]*>(.*?)</VOUCHER>", t or "", re.S):
        v = vm.group(1)
        seen += 1

        def fld(tag):
            m = re.search("<" + tag + r">(.*?)</" + tag + ">", v, re.S)
            return (m.group(1) if m else "").strip()

        vtype = fld("VOUCHERTYPENAME").lower()
        if vtype and vtype != "receipt":
            continue
        guid = fld("GUID")
        d8 = fld("DATE")
        pdate = (d8[:4] + "-" + d8[4:6] + "-" + d8[6:8]) if len(d8) == 8 else None
        vno = fld("VOUCHERNUMBER")
        if not guid:
            continue

        matched_any = False
        for em in re.finditer(r"<(?:ALLLEDGERENTRIES|LEDGERENTRIES)\.LIST>(.*?)</(?:ALLLEDGERENTRIES|LEDGERENTRIES)\.LIST>", v, re.S):
            e = em.group(1)
            lm = re.search(r"<LEDGERNAME>(.*?)</LEDGERNAME>", e, re.S)
            am = re.search(r"<AMOUNT>(.*?)</AMOUNT>", e, re.S)
            if not lm:
                continue
            lname = unesc(lm.group(1))
            cust = cmap.get(lname.lower())
            if not cust:
                continue
            matched_any = True
            try:
                amt = abs(float((am.group(1) if am else "0").strip() or 0))
            except Exception:
                amt = 0
            if amt <= 0:
                continue
            key = guid + "|" + cust
            if frappe.db.exists("Customer Payment", {"tally_voucher_id": key}):
                skipped += 1
                continue
            frappe.get_doc({
                "doctype": "Customer Payment", "customer": cust, "channel": "A",
                "amount": amt, "status": "Confirmed", "source": "Tally",
                "reference": ("Tally Rcpt " + vno).strip(), "tally_voucher_id": key,
                "payment_date": pdate,
            }).insert(ignore_permissions=True)
            made += 1
        if not matched_any:
            for em in re.finditer(r"<LEDGERNAME>(.*?)</LEDGERNAME>", v, re.S):
                nm = unesc(em.group(1))
                if nm and nm.lower() not in cmap and nm not in unmatched:
                    unmatched.append(nm)
    frappe.db.commit()
    return {"ok": True, "imported": made, "already_had": skipped,
            "receipts_seen_in_tally": seen, "unmatched_tally_parties": unmatched[:8]}

@frappe.whitelist()
def pull_tally_receipts():
    _ledger_guard()
    import re
    from frappe.utils import today
    start = frappe.conf.get("tally_books_from") or "20260401"
    end = today().replace("-", "")
    xml = ('<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>'
           '<TYPE>Data</TYPE><ID>Voucher Register</ID></HEADER><BODY><DESC><STATICVARIABLES>'
           '<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>'
           '<SVFROMDATE>' + start + '</SVFROMDATE><SVTODATE>' + end + '</SVTODATE>'
           '<VOUCHERTYPENAME>Receipt</VOUCHERTYPENAME>'
           '</STATICVARIABLES></DESC></BODY></ENVELOPE>')
    t = _tally_post(xml)

    def unesc(s):
        return (s or "").replace("&amp;", "&").replace("&quot;", '"').replace("&apos;", "'").replace("&lt;", "<").replace("&gt;", ">").strip()

    cmap = {}
    for c in frappe.get_all("Customer", fields=["name", "tally_ledger"]):
        cmap[(c.tally_ledger or c.name).strip().lower()] = c.name

    made, skipped, unmatched, seen = 0, 0, [], 0
    for vm in re.finditer(r"<VOUCHER\b[^>]*>(.*?)</VOUCHER>", t or "", re.S):
        v = vm.group(1)
        seen += 1

        def fld(tag):
            m = re.search("<" + tag + r">(.*?)</" + tag + ">", v, re.S)
            return (m.group(1) if m else "").strip()

        vtype = fld("VOUCHERTYPENAME").lower()
        if vtype and vtype != "receipt":
            continue
        guid = fld("GUID")
        d8 = fld("DATE")
        pdate = (d8[:4] + "-" + d8[4:6] + "-" + d8[6:8]) if len(d8) == 8 else None
        vno = fld("VOUCHERNUMBER")
        if not guid:
            continue

        matched_any = False
        for em in re.finditer(r"<(?:ALLLEDGERENTRIES|LEDGERENTRIES)\.LIST>(.*?)</(?:ALLLEDGERENTRIES|LEDGERENTRIES)\.LIST>", v, re.S):
            e = em.group(1)
            lm = re.search(r"<LEDGERNAME>(.*?)</LEDGERNAME>", e, re.S)
            am = re.search(r"<AMOUNT>(.*?)</AMOUNT>", e, re.S)
            if not lm:
                continue
            lname = unesc(lm.group(1))
            cust = cmap.get(lname.lower())
            if not cust:
                continue
            matched_any = True
            try:
                amt = abs(float((am.group(1) if am else "0").strip() or 0))
            except Exception:
                amt = 0
            if amt <= 0:
                continue
            key = guid + "|" + cust
            if frappe.db.exists("Customer Payment", {"tally_voucher_id": key}):
                skipped += 1
                continue
            frappe.get_doc({
                "doctype": "Customer Payment", "customer": cust, "channel": "A",
                "amount": amt, "status": "Confirmed", "source": "Tally",
                "reference": ("Tally Rcpt " + vno).strip(), "tally_voucher_id": key,
                "payment_date": pdate,
            }).insert(ignore_permissions=True)
            made += 1
        if not matched_any:
            for em in re.finditer(r"<LEDGERNAME>(.*?)</LEDGERNAME>", v, re.S):
                nm = unesc(em.group(1))
                if nm and nm.lower() not in cmap and nm not in unmatched:
                    unmatched.append(nm)
    frappe.db.commit()
    return {"ok": True, "imported": made, "already_had": skipped,
            "receipts_seen_in_tally": seen, "unmatched_tally_parties": unmatched[:8]}

def _tally_unit():
    return frappe.conf.get("tally_unit") or "nos"


def _tally_ensure_unit():
    u = _tally_unit()
    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><UNIT NAME="' + _x(u) + '" ACTION="Create">'
           '<NAME>' + _x(u) + '</NAME><ISSIMPLEUNIT>Yes</ISSIMPLEUNIT><DECIMALPLACES>0</DECIMALPLACES>'
           '</UNIT></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')
    _tally_post(xml)


def _tally_all_items_raw():
    xml = ('<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>'
           '<TYPE>Collection</TYPE><ID>All Items</ID></HEADER><BODY><DESC><STATICVARIABLES>'
           '<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT></STATICVARIABLES><TDL><TDLMESSAGE>'
           '<COLLECTION NAME="All Items" ISMODIFY="No"><TYPE>StockItem</TYPE><FETCH>NAME</FETCH>'
           '</COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>')
    return _tally_post(xml)


def _tally_create_item(name):
    u = _tally_unit()
    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><STOCKITEM NAME="' + _x(name) + '" ACTION="Create">'
           '<NAME>' + _x(name) + '</NAME><BASEUNITS>' + _x(u) + '</BASEUNITS>'
           '</STOCKITEM></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')
    t = _tally_post(xml)
    return ("<CREATED>1" in t), t


def _tally_create_party_gst(name, gstin):
    g = ''
    if gstin:
        g = '<GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE><PARTYGSTIN>' + _x(gstin) + '</PARTYGSTIN>'
    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME="' + _x(name) + '" ACTION="Create">'
           '<NAME>' + _x(name) + '</NAME><PARENT>Sundry Debtors</PARENT>' + g +
           '</LEDGER></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')
    t = _tally_post(xml)
    return ("<CREATED>1" in t), t


@frappe.whitelist()
def post_invoice_to_tally(invoice, force=0):
    _ledger_guard()
    inv = frappe.get_doc("Order Invoice", invoice)
    if (inv.get("tally_status") or "") == "Posted" and not int(force or 0):
        return {"ok": False, "error": "Already posted to Tally (" + (inv.get("tally_vch_no") or inv.name) + "). It will not be posted twice."}

    cgst = float(inv.get("a_cgst") or 0)
    sgst = float(inv.get("a_sgst") or 0)
    disc = float(inv.get("discount") or 0)
    share = float(inv.get("split_pct") or 0)

    cust = (inv.get("customer") or "").strip()
    if not cust:
        return {"ok": False, "error": "Invoice has no customer."}
    tled, gstin = cust, ""
    if frappe.db.exists("Customer", cust):
        row = frappe.db.get_value("Customer", cust, ["tally_ledger", "gstin"], as_dict=True) or {}
        tled = (row.get("tally_ledger") or cust).strip() or cust
        gstin = (row.get("gstin") or "").strip()

    lines = []
    if inv.get("order") and frappe.db.exists("Customer Order", inv.order):
        order = frappe.get_doc("Customer Order", inv.order)
        for it in (order.items or []):
            qty = float(it.qty or 0)
            main = float(it.rate or 0)
            d = main * (1.0 - disc / 100.0)
            a_rate = _inv_r2(d * share / 100.0)
            amt = _inv_r2(a_rate * qty)
            if qty <= 0 or amt <= 0:
                continue
            pname = it.product
            if frappe.db.exists("Product", it.product):
                pname = frappe.db.get_value("Product", it.product, "product_name") or it.product
            lines.append({"item": pname, "qty": qty, "rate": a_rate, "amount": amt})
    if not lines:
        return {"ok": False, "error": "No order items found for this invoice - cannot build an item invoice."}

    goods = _inv_r2(sum(l["amount"] for l in lines))
    total = _inv_r2(goods + cgst + sgst)
    if total <= 0:
        return {"ok": False, "error": "Invoice A total is 0 - nothing to post."}

    if not _tally_has_ledger(tled):
        created, rep = _tally_create_party_gst(tled, gstin)
        if not created and "already exist" not in rep.lower():
            err = _tally_err(rep) or "Could not create the customer ledger in Tally."
            frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err})
            frappe.db.commit()
            return {"ok": False, "error": err}
    _tally_ensure_unit()
    items_raw = _tally_all_items_raw().lower()
    for l in lines:
        if ('name="' + _x(l["item"]).lower() + '"') not in items_raw:
            created, rep = _tally_create_item(l["item"])
            if not created and "already exist" not in rep.lower():
                err = _tally_err(rep) or ("Could not create stock item '" + l["item"] + "' in Tally.")
                frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err})
                frappe.db.commit()
                return {"ok": False, "error": err}

    L = _tally_ledgers()
    u = _tally_unit()
    d8 = str(inv.creation)[:10].replace("-", "")

    inv_rows = []
    for l in lines:
        q = ("%g" % l["qty"])
        inv_rows.append('<ALLINVENTORYENTRIES.LIST>'
                        '<STOCKITEMNAME>' + _x(l["item"]) + '</STOCKITEMNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>'
                        '<RATE>' + ("%.2f" % l["rate"]) + '/' + _x(u) + '</RATE>'
                        '<ACTUALQTY> ' + q + ' ' + _x(u) + '</ACTUALQTY>'
                        '<BILLEDQTY> ' + q + ' ' + _x(u) + '</BILLEDQTY>'
                        '<AMOUNT>' + ("%.2f" % l["amount"]) + '</AMOUNT>'
                        '<ACCOUNTINGALLOCATIONS.LIST>'
                        '<LEDGERNAME>' + _x(L["sales"]) + '</LEDGERNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>'
                        '<AMOUNT>' + ("%.2f" % l["amount"]) + '</AMOUNT>'
                        '</ACCOUNTINGALLOCATIONS.LIST>'
                        '</ALLINVENTORYENTRIES.LIST>')

    led_rows = ['<LEDGERENTRIES.LIST><LEDGERNAME>' + _x(tled) + '</LEDGERNAME>'
                '<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><ISPARTYLEDGER>Yes</ISPARTYLEDGER>'
                '<AMOUNT>-' + ("%.2f" % total) + '</AMOUNT></LEDGERENTRIES.LIST>']
    if cgst > 0:
        led_rows.append('<LEDGERENTRIES.LIST><LEDGERNAME>' + _x(L["cgst"]) + '</LEDGERNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>' + ("%.2f" % cgst) + '</AMOUNT></LEDGERENTRIES.LIST>')
    if sgst > 0:
        led_rows.append('<LEDGERENTRIES.LIST><LEDGERNAME>' + _x(L["sgst"]) + '</LEDGERNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>' + ("%.2f" % sgst) + '</AMOUNT></LEDGERENTRIES.LIST>')

    gst_tag = ('<PARTYGSTIN>' + _x(gstin) + '</PARTYGSTIN>') if gstin else ''
    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="Sales" ACTION="Create">'
           '<DATE>' + d8 + '</DATE><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>'
           '<VOUCHERNUMBER>' + _x(inv.name) + '</VOUCHERNUMBER>'
           '<PARTYLEDGERNAME>' + _x(tled) + '</PARTYLEDGERNAME>'
           '<PARTYNAME>' + _x(tled) + '</PARTYNAME>' + gst_tag +
           '<ISINVOICE>Yes</ISINVOICE>'
           '<PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>'
           '<NARRATION>Shalini ERP ' + _x(inv.name) + ' / ' + _x(inv.get("order") or "") + '</NARRATION>'
           + "".join(led_rows) + "".join(inv_rows) +
           '</VOUCHER></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')

    t = _tally_post(xml)
    if "<CREATED>1" in t:
        frappe.db.set_value("Order Invoice", inv.name, {
            "tally_status": "Posted", "tally_vch_no": inv.name,
            "tally_posted_on": frappe.utils.now(), "tally_error": ""})
        frappe.db.commit()
        return {"ok": True, "voucher": inv.name, "party": tled, "total": total, "items": len(lines)}

    err = _tally_err(t) or ("Tally did not accept the invoice. Reply: " + (t[:180] if t else "(empty)"))
    frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err})
    frappe.db.commit()
    return {"ok": False, "error": err}

def _tally_import_ok(t):
    import re
    c = re.search(r"<CREATED>(\d+)</CREATED>", t or "")
    a = re.search(r"<ALTERED>(\d+)</ALTERED>", t or "")
    n = (int(c.group(1)) if c else 0) + (int(a.group(1)) if a else 0)
    return (n >= 1) and ("<LINEERROR>" not in (t or ""))


def _tally_create_item(name):
    u = _tally_unit()
    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><STOCKITEM NAME="' + _x(name) + '" ACTION="Create">'
           '<NAME>' + _x(name) + '</NAME><BASEUNITS>' + _x(u) + '</BASEUNITS>'
           '</STOCKITEM></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')
    t = _tally_post(xml)
    return _tally_import_ok(t), t


def _tally_create_party_gst(name, gstin):
    g = ''
    if gstin:
        g = '<GSTREGISTRATIONTYPE>Regular</GSTREGISTRATIONTYPE><PARTYGSTIN>' + _x(gstin) + '</PARTYGSTIN>'
    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME="' + _x(name) + '" ACTION="Create">'
           '<NAME>' + _x(name) + '</NAME><PARENT>Sundry Debtors</PARENT>' + g +
           '</LEDGER></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')
    t = _tally_post(xml)
    return _tally_import_ok(t), t

def _tally_ensure_unit(u=None):
    u = (u or frappe.conf.get("tally_unit") or "nos").strip()
    dec = "3" if u == "kg" else "0"
    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><UNIT NAME="' + _x(u) + '" ACTION="Create">'
           '<NAME>' + _x(u) + '</NAME><ISSIMPLEUNIT>Yes</ISSIMPLEUNIT><DECIMALPLACES>' + dec + '</DECIMALPLACES>'
           '</UNIT></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')
    _tally_post(xml)


def _tally_create_item(name, unit=None):
    u = (unit or frappe.conf.get("tally_unit") or "nos").strip()
    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><STOCKITEM NAME="' + _x(name) + '" ACTION="Create">'
           '<NAME>' + _x(name) + '</NAME><BASEUNITS>' + _x(u) + '</BASEUNITS>'
           '</STOCKITEM></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')
    t = _tally_post(xml)
    return _tally_import_ok(t), t


@frappe.whitelist()
def post_invoice_to_tally(invoice, force=0):
    _ledger_guard()
    inv = frappe.get_doc("Order Invoice", invoice)
    if (inv.get("tally_status") or "") == "Posted" and not int(force or 0):
        return {"ok": False, "error": "Already posted to Tally (" + (inv.get("tally_vch_no") or inv.name) + "). It will not be posted twice."}

    cgst = float(inv.get("a_cgst") or 0)
    sgst = float(inv.get("a_sgst") or 0)
    disc = float(inv.get("discount") or 0)
    share = float(inv.get("split_pct") or 0)

    cust = (inv.get("customer") or "").strip()
    if not cust:
        return {"ok": False, "error": "Invoice has no customer."}
    tled, gstin = cust, ""
    if frappe.db.exists("Customer", cust):
        row = frappe.db.get_value("Customer", cust, ["tally_ledger", "gstin"], as_dict=True) or {}
        tled = (row.get("tally_ledger") or cust).strip() or cust
        gstin = (row.get("gstin") or "").strip()

    lines = []
    if inv.get("order") and frappe.db.exists("Customer Order", inv.order):
        order = frappe.get_doc("Customer Order", inv.order)
        for it in (order.items or []):
            qty = float(it.qty or 0)
            main = float(it.rate or 0)
            d = main * (1.0 - disc / 100.0)
            a_rate = _inv_r2(d * share / 100.0)
            amt = _inv_r2(a_rate * qty)
            if qty <= 0 or amt <= 0:
                continue
            pname, punit = it.product, "nos"
            if frappe.db.exists("Product", it.product):
                pr = frappe.db.get_value("Product", it.product, ["product_name", "unit"], as_dict=True) or {}
                pname = pr.get("product_name") or it.product
                punit = (pr.get("unit") or "nos").strip() or "nos"
            lines.append({"item": pname, "qty": qty, "rate": a_rate, "amount": amt, "unit": punit})
    if not lines:
        return {"ok": False, "error": "No order items found for this invoice - cannot build an item invoice."}

    goods = _inv_r2(sum(l["amount"] for l in lines))
    total = _inv_r2(goods + cgst + sgst)
    if total <= 0:
        return {"ok": False, "error": "Invoice A total is 0 - nothing to post."}

    if not _tally_has_ledger(tled):
        created, rep = _tally_create_party_gst(tled, gstin)
        if not created and "already exist" not in rep.lower():
            err = _tally_err(rep) or "Could not create the customer ledger in Tally."
            frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err})
            frappe.db.commit()
            return {"ok": False, "error": err}

    for u in sorted(set(l["unit"] for l in lines)):
        _tally_ensure_unit(u)
    items_raw = _tally_all_items_raw().lower()
    for l in lines:
        if ('name="' + _x(l["item"]).lower() + '"') not in items_raw:
            created, rep = _tally_create_item(l["item"], l["unit"])
            if not created and "already exist" not in rep.lower():
                err = _tally_err(rep) or ("Could not create stock item '" + l["item"] + "' in Tally.")
                frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err})
                frappe.db.commit()
                return {"ok": False, "error": err}

    L = _tally_ledgers()
    d8 = str(inv.creation)[:10].replace("-", "")

    inv_rows = []
    for l in lines:
        q = ("%g" % l["qty"])
        u = l["unit"]
        inv_rows.append('<ALLINVENTORYENTRIES.LIST>'
                        '<STOCKITEMNAME>' + _x(l["item"]) + '</STOCKITEMNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>'
                        '<RATE>' + ("%.2f" % l["rate"]) + '/' + _x(u) + '</RATE>'
                        '<ACTUALQTY> ' + q + ' ' + _x(u) + '</ACTUALQTY>'
                        '<BILLEDQTY> ' + q + ' ' + _x(u) + '</BILLEDQTY>'
                        '<AMOUNT>' + ("%.2f" % l["amount"]) + '</AMOUNT>'
                        '<ACCOUNTINGALLOCATIONS.LIST>'
                        '<LEDGERNAME>' + _x(L["sales"]) + '</LEDGERNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>'
                        '<AMOUNT>' + ("%.2f" % l["amount"]) + '</AMOUNT>'
                        '</ACCOUNTINGALLOCATIONS.LIST>'
                        '</ALLINVENTORYENTRIES.LIST>')

    led_rows = ['<LEDGERENTRIES.LIST><LEDGERNAME>' + _x(tled) + '</LEDGERNAME>'
                '<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><ISPARTYLEDGER>Yes</ISPARTYLEDGER>'
                '<AMOUNT>-' + ("%.2f" % total) + '</AMOUNT></LEDGERENTRIES.LIST>']
    if cgst > 0:
        led_rows.append('<LEDGERENTRIES.LIST><LEDGERNAME>' + _x(L["cgst"]) + '</LEDGERNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>' + ("%.2f" % cgst) + '</AMOUNT></LEDGERENTRIES.LIST>')
    if sgst > 0:
        led_rows.append('<LEDGERENTRIES.LIST><LEDGERNAME>' + _x(L["sgst"]) + '</LEDGERNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>' + ("%.2f" % sgst) + '</AMOUNT></LEDGERENTRIES.LIST>')

    gst_tag = ('<PARTYGSTIN>' + _x(gstin) + '</PARTYGSTIN>') if gstin else ''
    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="Sales" ACTION="Create">'
           '<DATE>' + d8 + '</DATE><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>'
           '<VOUCHERNUMBER>' + _x(inv.name) + '</VOUCHERNUMBER>'
           '<PARTYLEDGERNAME>' + _x(tled) + '</PARTYLEDGERNAME>'
           '<PARTYNAME>' + _x(tled) + '</PARTYNAME>' + gst_tag +
           '<ISINVOICE>Yes</ISINVOICE>'
           '<PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>'
           '<NARRATION>Shalini ERP ' + _x(inv.name) + ' / ' + _x(inv.get("order") or "") + '</NARRATION>'
           + "".join(led_rows) + "".join(inv_rows) +
           '</VOUCHER></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')

    t = _tally_post(xml)
    if "<CREATED>1" in t:
        frappe.db.set_value("Order Invoice", inv.name, {
            "tally_status": "Posted", "tally_vch_no": inv.name,
            "tally_posted_on": frappe.utils.now(), "tally_error": ""})
        frappe.db.commit()
        return {"ok": True, "voucher": inv.name, "party": tled, "total": total, "items": len(lines)}

    err = _tally_err(t) or ("Tally did not accept the invoice. Reply: " + (t[:180] if t else "(empty)"))
    frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err})
    frappe.db.commit()
    return {"ok": False, "error": err}

@frappe.whitelist()
def save_push_token(token, device=None):
    _ledger_guard()
    token = (token or "").strip()
    if not token:
        return {"ok": False}
    if not frappe.get_all("FCM Token", filters={"token": token}, limit=1):
        frappe.get_doc({"doctype": "FCM Token", "token": token, "user": frappe.session.user,
                        "device": (device or "")[:120], "enabled": 1}).insert(ignore_permissions=True)
        frappe.db.commit()
    return {"ok": True}


def _fcm_access_token():
    from google.oauth2 import service_account
    import google.auth.transport.requests
    path = frappe.conf.get("fcm_service_account")
    creds = service_account.Credentials.from_service_account_file(
        path, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def _fcm_send(title, body):
    pid = frappe.conf.get("fcm_project_id")
    if not pid or not frappe.conf.get("fcm_service_account"):
        return 0
    import requests
    try:
        at = _fcm_access_token()
    except Exception:
        frappe.log_error(frappe.get_traceback()[:3000], "FCM auth failed")
        return 0
    sent = 0
    for row in frappe.get_all("FCM Token", filters={"enabled": 1}, fields=["name", "token"]):
        try:
            r = requests.post(
                "https://fcm.googleapis.com/v1/projects/" + pid + "/messages:send",
                headers={"Authorization": "Bearer " + at, "Content-Type": "application/json"},
                json={"message": {"token": row.token,
                                  "notification": {"title": title, "body": body},
                                  "webpush": {"fcm_options": {"link": "/shalini"},
                                              "headers": {"Urgency": "high"}}}},
                timeout=10)
            if r.status_code == 200:
                sent += 1
            elif r.status_code == 404 or "UNREGISTERED" in (r.text or ""):
                frappe.delete_doc("FCM Token", row.name, ignore_permissions=True, force=True)
        except Exception:
            pass
    frappe.db.commit()
    return sent


@frappe.whitelist()
def fcm_test():
    _ledger_guard()
    n = _fcm_send("Shalini ERP test", "If you can read this on your phone, FCM works.")
    return {"ok": True, "sent_to": n, "registered_phones": len(frappe.get_all("FCM Token", filters={"enabled": 1}))}


@frappe.whitelist()
def notify_new_order(order):
    if not frappe.db.exists("Customer Order", order):
        return {"ok": False, "sent": False, "reason": "order not found"}
    d = frappe.db.get_value("Customer Order", order, ["customer", "salesman", "total_amount", "total_qty"], as_dict=True) or {}
    sm = d.get("salesman") or frappe.session.user
    smname = frappe.db.get_value("User", sm, "full_name") or sm
    title = "New order " + str(order) + " - " + (d.get("customer") or "-")
    body = ("By " + str(smname) + "  |  Qty " + str(d.get("total_qty") or 0) +
            "  |  Rs " + str(d.get("total_amount") or 0))
    n = _fcm_send(title, body)
    if n > 0:
        return {"ok": True, "sent": True, "via": "fcm", "phones": n}
    topic = (frappe.conf.get("ntfy_topic") or "").strip()
    if topic:
        try:
            import requests
            requests.post("https://ntfy.sh/" + topic, data=body.encode("utf-8"),
                          headers={"Title": title, "Priority": "high"}, timeout=10)
            return {"ok": True, "sent": True, "via": "ntfy"}
        except Exception:
            pass
    return {"ok": True, "sent": False, "reason": "no phones registered / not configured"}

# ---- Tally target: office PC + fixed company (code defaults) ----

def _tally_url():
    return (frappe.conf.get("tally_url") or "http://192.168.1.5:9000").rstrip("/")


def _tally_company():
    return (frappe.conf.get("tally_company") or "Shalini ERP").strip()


def _tally_post(xml):
    import requests
    comp = _tally_company()
    if comp and "SVCURRENTCOMPANY" not in xml:
        tag = "<SVCURRENTCOMPANY>" + _x(comp) + "</SVCURRENTCOMPANY>"
        if "<STATICVARIABLES>" in xml:
            xml = xml.replace("<STATICVARIABLES>", "<STATICVARIABLES>" + tag, 1)
        elif "</REPORTNAME>" in xml:
            xml = xml.replace("</REPORTNAME>", "</REPORTNAME><STATICVARIABLES>" + tag + "</STATICVARIABLES>", 1)
    url = _tally_url()
    try:
        r = requests.post(url, data=xml.encode("utf-8"), headers={"Content-Type": "text/xml"}, timeout=25)
        return r.text or ""
    except Exception as e:
        frappe.throw("Cannot reach Tally at " + url + " - is TallyPrime open on the Tally PC? (" + str(e)[:120] + ")")

@frappe.whitelist()
def api_health():
    _ledger_guard()
    out = {"doctypes": {}, "fields": {}, "config_set": {}}
    dts = ["Product", "Order Item", "Customer Order", "Order Invoice", "Customer",
           "Customer Payment", "Vendor", "Purchase Item", "Purchase", "Vendor Payment",
           "Daily Expense", "Production Item", "Production", "Stock Move",
           "Raw Material", "Raw Stock Move", "FCM Token"]
    for dt in dts:
        out["doctypes"][dt] = bool(frappe.db.exists("DocType", dt))

    def has_field(dt, fn):
        try:
            return bool(out["doctypes"].get(dt) and frappe.get_meta(dt).get_field(fn))
        except Exception:
            return False

    req = [("Order Invoice", "a_amount"), ("Order Invoice", "b_amount"),
           ("Order Invoice", "grand_total"), ("Order Invoice", "tally_status"),
           ("Product", "unit"), ("Customer", "tally_ledger"), ("Customer", "salesman"),
           ("Customer Payment", "tally_voucher_id"), ("Customer Payment", "channel")]
    opt = [("Customer", "opening_a"), ("Customer", "opening_b"), ("Vendor", "opening_payable")]
    for dt, fn in req:
        out["fields"][dt + "." + fn] = has_field(dt, fn)
    for dt, fn in opt:
        out["fields"][dt + "." + fn + " (optional)"] = has_field(dt, fn)

    for k in ["tally_url", "tally_company", "tally_sales_ledger", "tally_cgst_ledger",
              "tally_sgst_ledger", "fcm_project_id", "fcm_service_account", "ntfy_topic"]:
        out["config_set"][k] = bool(frappe.conf.get(k))

    missing = [k for k, v in out["doctypes"].items() if not v]
    missing += [k for k, v in out["fields"].items() if (not v and "(optional)" not in k)]
    out["missing"] = missing
    out["ok"] = not missing
    out["hint"] = "All good - APIs have everything they need." if not missing else \
        "Run: bench execute teacan_erp.build.setup_all  (creates the missing pieces), then restart."
    return out

# ===== ITEM-MODE POSTING for the ERP company (auto-creates everything) =====

def _ensure_gst_ledgers():
    L = _tally_ledgers()
    specs = [
        (L["sales"], "Sales Accounts"),
        (L["cgst"], "Duties & Taxes"),
        (L["sgst"], "Duties & Taxes"),
    ]
    made = []
    for name, parent in specs:
        if _tally_has_ledger(name):
            continue
        xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
               '<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME><STATICVARIABLES>'
               '<SVCURRENTCOMPANY>' + _x(_tally_company()) + '</SVCURRENTCOMPANY>'
               '</STATICVARIABLES></REQUESTDESC><REQUESTDATA>'
               '<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME="' + _x(name) + '" ACTION="Create">'
               '<NAME>' + _x(name) + '</NAME><PARENT>' + _x(parent) + '</PARENT>'
               '</LEDGER></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')
        _tally_post(xml)
        made.append(name)
    return made


@frappe.whitelist()
def post_invoice_to_tally(invoice, force=0):
    _ledger_guard()
    inv = frappe.get_doc("Order Invoice", invoice)
    if (inv.get("tally_status") or "") == "Posted" and not int(force or 0):
        return {"ok": False, "error": "Already posted (" + (inv.get("tally_vch_no") or inv.name) + ")"}

    cgst = float(inv.get("a_cgst") or 0)
    sgst = float(inv.get("a_sgst") or 0)
    disc = float(inv.get("discount") or 0)
    share = float(inv.get("split_pct") or 0)

    cust = (inv.get("customer") or "").strip()
    if not cust:
        return {"ok": False, "error": "No customer"}
    tled, gstin = cust, ""
    if frappe.db.exists("Customer", cust):
        row = frappe.db.get_value("Customer", cust, ["tally_ledger", "gstin"], as_dict=True) or {}
        tled = (row.get("tally_ledger") or cust).strip() or cust
        gstin = (row.get("gstin") or "").strip()

    lines = []
    if inv.get("order") and frappe.db.exists("Customer Order", inv.order):
        order = frappe.get_doc("Customer Order", inv.order)
        for it in (order.items or []):
            qty = float(it.qty or 0)
            main = float(it.rate or 0)
            d = main * (1.0 - disc / 100.0)
            a_rate = round(d * share / 100.0, 2)
            amt = round(a_rate * qty, 2)
            if qty <= 0 or amt <= 0:
                continue
            pname, punit = it.product, "nos"
            if frappe.db.exists("Product", it.product):
                pr = frappe.db.get_value("Product", it.product, ["product_name", "unit"], as_dict=True) or {}
                pname = pr.get("product_name") or it.product
                punit = (pr.get("unit") or "nos").strip() or "nos"
            lines.append({"item": pname, "qty": qty, "rate": a_rate, "amount": amt, "unit": punit})
    if not lines:
        return {"ok": False, "error": "No order items to post"}

    goods = round(sum(l["amount"] for l in lines), 2)
    total = round(goods + cgst + sgst, 2)
    if total <= 0:
        return {"ok": False, "error": "Invoice A total is 0"}

    # ensure masters exist in the company
    _ensure_gst_ledgers()
    if not _tally_has_ledger(tled):
        ok, rep = _tally_create_party_gst(tled, gstin)
        if not ok and "already exist" not in rep.lower():
            err = _tally_err(rep) or "Could not create customer ledger"
            frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err}); frappe.db.commit()
            return {"ok": False, "error": err}
    for u in sorted(set(l["unit"] for l in lines)):
        _tally_ensure_unit(u)
    items_raw = _tally_all_items_raw().lower()
    for l in lines:
        if ('name="' + _x(l["item"]).lower() + '"') not in items_raw:
            ok, rep = _tally_create_item(l["item"], l["unit"])
            if not ok and "already exist" not in rep.lower():
                err = _tally_err(rep) or ("Could not create item '" + l["item"] + "'")
                frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err}); frappe.db.commit()
                return {"ok": False, "error": err}

    L = _tally_ledgers()
    d8 = str(inv.creation)[:10].replace("-", "")
    inv_rows = []
    for l in lines:
        q = ("%g" % l["qty"])
        u = l["unit"]
        inv_rows.append('<ALLINVENTORYENTRIES.LIST>'
                        '<STOCKITEMNAME>' + _x(l["item"]) + '</STOCKITEMNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>'
                        '<RATE>' + ("%.2f" % l["rate"]) + '/' + _x(u) + '</RATE>'
                        '<ACTUALQTY> ' + q + ' ' + _x(u) + '</ACTUALQTY>'
                        '<BILLEDQTY> ' + q + ' ' + _x(u) + '</BILLEDQTY>'
                        '<AMOUNT>' + ("%.2f" % l["amount"]) + '</AMOUNT>'
                        '<ACCOUNTINGALLOCATIONS.LIST>'
                        '<LEDGERNAME>' + _x(L["sales"]) + '</LEDGERNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>'
                        '<AMOUNT>' + ("%.2f" % l["amount"]) + '</AMOUNT>'
                        '</ACCOUNTINGALLOCATIONS.LIST></ALLINVENTORYENTRIES.LIST>')

    led_rows = ['<LEDGERENTRIES.LIST><LEDGERNAME>' + _x(tled) + '</LEDGERNAME>'
                '<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><ISPARTYLEDGER>Yes</ISPARTYLEDGER>'
                '<AMOUNT>-' + ("%.2f" % total) + '</AMOUNT></LEDGERENTRIES.LIST>']
    if cgst > 0:
        led_rows.append('<LEDGERENTRIES.LIST><LEDGERNAME>' + _x(L["cgst"]) + '</LEDGERNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>' + ("%.2f" % cgst) + '</AMOUNT></LEDGERENTRIES.LIST>')
    if sgst > 0:
        led_rows.append('<LEDGERENTRIES.LIST><LEDGERNAME>' + _x(L["sgst"]) + '</LEDGERNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>' + ("%.2f" % sgst) + '</AMOUNT></LEDGERENTRIES.LIST>')

    gst_tag = ('<PARTYGSTIN>' + _x(gstin) + '</PARTYGSTIN>') if gstin else ''
    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME><STATICVARIABLES>'
           '<SVCURRENTCOMPANY>' + _x(_tally_company()) + '</SVCURRENTCOMPANY>'
           '</STATICVARIABLES></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="Sales" ACTION="Create">'
           '<DATE>' + d8 + '</DATE><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>'
           '<VOUCHERNUMBER>' + _x(inv.name) + '</VOUCHERNUMBER>'
           '<PARTYLEDGERNAME>' + _x(tled) + '</PARTYLEDGERNAME>'
           '<PARTYNAME>' + _x(tled) + '</PARTYNAME>' + gst_tag +
           '<ISINVOICE>Yes</ISINVOICE><PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>'
           '<NARRATION>Shalini ERP ' + _x(inv.name) + ' / ' + _x(inv.get("order") or "") + '</NARRATION>'
           + "".join(led_rows) + "".join(inv_rows) +
           '</VOUCHER></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')

    t = _tally_post(xml)
    if _tally_import_ok(t):
        frappe.db.set_value("Order Invoice", inv.name, {
            "tally_status": "Posted", "tally_vch_no": inv.name,
            "tally_posted_on": frappe.utils.now(), "tally_error": ""})
        frappe.db.commit()
        return {"ok": True, "voucher": inv.name, "party": tled, "total": total, "items": len(lines)}
    err = _tally_err(t) or ("Tally did not accept the invoice. Reply: " + (t[:200] if t else "(empty)"))
    frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err})
    frappe.db.commit()
    return {"ok": False, "error": err}

# ===== per-rate ledger mapping + corrected company default =====

def _tally_company():
    return (frappe.conf.get("tally_company") or "Shalini ERP").strip()

def _tally_ledgers_for_rate(rate=5):
    rate = float(rate or 5)
    half = rate / 2
    sales = frappe.conf.get("tally_sales_ledger") or ("Sales Gst - %g%%" % rate)
    cgst = frappe.conf.get("tally_cgst_ledger") or "C GST"
    sgst = frappe.conf.get("tally_sgst_ledger") or "S GST"
    if not frappe.conf.get("tally_sales_ledger"):
        sales = "Sales Gst - %g%%" % rate
    return {"sales": sales, "cgst": cgst, "sgst": sgst}

def _ensure_ledger(name, parent):
    if _tally_has_ledger(name):
        return
    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME><STATICVARIABLES>'
           '<SVCURRENTCOMPANY>' + _x(_tally_company()) + '</SVCURRENTCOMPANY>'
           '</STATICVARIABLES></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME="' + _x(name) + '" ACTION="Create">'
           '<NAME>' + _x(name) + '</NAME><PARENT>' + _x(parent) + '</PARENT>'
           '</LEDGER></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')
    _tally_post(xml)

@frappe.whitelist()
def post_invoice_to_tally(invoice, force=0):
    _ledger_guard()
    inv = frappe.get_doc("Order Invoice", invoice)
    if (inv.get("tally_status") or "") == "Posted" and not int(force or 0):
        return {"ok": False, "error": "Already posted (" + (inv.get("tally_vch_no") or inv.name) + ")"}

    gst_rate = float(inv.get("gst_rate") or 5)
    cgst = float(inv.get("a_cgst") or 0)
    sgst = float(inv.get("a_sgst") or 0)
    disc = float(inv.get("discount") or 0)
    share = float(inv.get("split_pct") or 0)

    cust = (inv.get("customer") or "").strip()
    if not cust:
        return {"ok": False, "error": "No customer"}
    tled, gstin = cust, ""
    if frappe.db.exists("Customer", cust):
        row = frappe.db.get_value("Customer", cust, ["tally_ledger", "gstin"], as_dict=True) or {}
        tled = (row.get("tally_ledger") or cust).strip() or cust
        gstin = (row.get("gstin") or "").strip()

    lines = []
    if inv.get("order") and frappe.db.exists("Customer Order", inv.order):
        order = frappe.get_doc("Customer Order", inv.order)
        for it in (order.items or []):
            qty = float(it.qty or 0)
            main = float(it.rate or 0)
            d = main * (1.0 - disc / 100.0)
            a_rate = round(d * share / 100.0, 2)
            amt = round(a_rate * qty, 2)
            if qty <= 0 or amt <= 0:
                continue
            pname, punit = it.product, "nos"
            if frappe.db.exists("Product", it.product):
                pr = frappe.db.get_value("Product", it.product, ["product_name", "unit"], as_dict=True) or {}
                pname = pr.get("product_name") or it.product
                punit = (pr.get("unit") or "nos").strip() or "nos"
            lines.append({"item": pname, "qty": qty, "rate": a_rate, "amount": amt, "unit": punit})
    if not lines:
        return {"ok": False, "error": "No order items to post"}

    goods = round(sum(l["amount"] for l in lines), 2)
    total = round(goods + cgst + sgst, 2)
    if total <= 0:
        return {"ok": False, "error": "Invoice A total is 0"}

    L = _tally_ledgers_for_rate(gst_rate)
    _ensure_ledger(L["sales"], "Sales Accounts")
    _ensure_ledger(L["cgst"], "Duties & Taxes")
    _ensure_ledger(L["sgst"], "Duties & Taxes")

    if not _tally_has_ledger(tled):
        ok, rep = _tally_create_party_gst(tled, gstin)
        if not ok and "already exist" not in rep.lower():
            err = _tally_err(rep) or "Could not create customer ledger"
            frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err}); frappe.db.commit()
            return {"ok": False, "error": err}

    for u in sorted(set(l["unit"] for l in lines)):
        _tally_ensure_unit(u)
    items_raw = _tally_all_items_raw().lower()
    for l in lines:
        if ('name="' + _x(l["item"]).lower() + '"') not in items_raw:
            ok, rep = _tally_create_item(l["item"], l["unit"])
            if not ok and "already exist" not in rep.lower():
                err = _tally_err(rep) or ("Could not create item '" + l["item"] + "'")
                frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err}); frappe.db.commit()
                return {"ok": False, "error": err}

    d8 = str(inv.creation)[:10].replace("-", "")
    inv_rows = []
    for l in lines:
        q = ("%g" % l["qty"])
        u = l["unit"]
        inv_rows.append('<ALLINVENTORYENTRIES.LIST>'
                        '<STOCKITEMNAME>' + _x(l["item"]) + '</STOCKITEMNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>'
                        '<RATE>' + ("%.2f" % l["rate"]) + '/' + _x(u) + '</RATE>'
                        '<ACTUALQTY> ' + q + ' ' + _x(u) + '</ACTUALQTY>'
                        '<BILLEDQTY> ' + q + ' ' + _x(u) + '</BILLEDQTY>'
                        '<AMOUNT>' + ("%.2f" % l["amount"]) + '</AMOUNT>'
                        '<ACCOUNTINGALLOCATIONS.LIST>'
                        '<LEDGERNAME>' + _x(L["sales"]) + '</LEDGERNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>'
                        '<AMOUNT>' + ("%.2f" % l["amount"]) + '</AMOUNT>'
                        '</ACCOUNTINGALLOCATIONS.LIST></ALLINVENTORYENTRIES.LIST>')

    led_rows = ['<LEDGERENTRIES.LIST><LEDGERNAME>' + _x(tled) + '</LEDGERNAME>'
                '<ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE><ISPARTYLEDGER>Yes</ISPARTYLEDGER>'
                '<AMOUNT>-' + ("%.2f" % total) + '</AMOUNT></LEDGERENTRIES.LIST>']
    if cgst > 0:
        led_rows.append('<LEDGERENTRIES.LIST><LEDGERNAME>' + _x(L["cgst"]) + '</LEDGERNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>' + ("%.2f" % cgst) + '</AMOUNT></LEDGERENTRIES.LIST>')
    if sgst > 0:
        led_rows.append('<LEDGERENTRIES.LIST><LEDGERNAME>' + _x(L["sgst"]) + '</LEDGERNAME>'
                        '<ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE><AMOUNT>' + ("%.2f" % sgst) + '</AMOUNT></LEDGERENTRIES.LIST>')

    gst_tag = ('<PARTYGSTIN>' + _x(gstin) + '</PARTYGSTIN>') if gstin else ''
    xml = ('<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>'
           '<REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME><STATICVARIABLES>'
           '<SVCURRENTCOMPANY>' + _x(_tally_company()) + '</SVCURRENTCOMPANY>'
           '</STATICVARIABLES></REQUESTDESC><REQUESTDATA>'
           '<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="Sales" ACTION="Create">'
           '<DATE>' + d8 + '</DATE><VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>'
           '<VOUCHERNUMBER>' + _x(inv.name) + '</VOUCHERNUMBER>'
           '<PARTYLEDGERNAME>' + _x(tled) + '</PARTYLEDGERNAME>'
           '<PARTYNAME>' + _x(tled) + '</PARTYNAME>' + gst_tag +
           '<ISINVOICE>Yes</ISINVOICE><PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>'
           '<NARRATION>Shalini ERP ' + _x(inv.name) + ' / ' + _x(inv.get("order") or "") + '</NARRATION>'
           + "".join(led_rows) + "".join(inv_rows) +
           '</VOUCHER></TALLYMESSAGE></REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>')

    t = _tally_post(xml)
    if _tally_import_ok(t):
        frappe.db.set_value("Order Invoice", inv.name, {
            "tally_status": "Posted", "tally_vch_no": inv.name,
            "tally_posted_on": frappe.utils.now(), "tally_error": ""})
        frappe.db.commit()
        return {"ok": True, "voucher": inv.name, "party": tled, "total": total, "items": len(lines)}
    err = _tally_err(t) or ("Tally did not accept the invoice. Reply: " + (t[:200] if t else "(empty)"))
    frappe.db.set_value("Order Invoice", inv.name, {"tally_status": "Error", "tally_error": err})
    frappe.db.commit()
    return {"ok": False, "error": err}

# ===== TALLY -> ERP : purchases, vendors, vendor payments =====

def _tv_num(s):
    import re
    if s is None:
        return 0.0
    m = re.search(r"-?\d+(?:\.\d+)?", str(s).replace(",", ""))
    return float(m.group(0)) if m else 0.0


def _tv_unesc(s):
    return (s or "").replace("&amp;", "&").replace("&quot;", '"').replace("&apos;", "'") \
                    .replace("&lt;", "<").replace("&gt;", ">").strip()


def _tally_vouchers(vtype, start, end):
    xml = ('<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>'
           '<TYPE>Data</TYPE><ID>Voucher Register</ID></HEADER><BODY><DESC><STATICVARIABLES>'
           '<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>'
           '<SVCURRENTCOMPANY>' + _x(_tally_company()) + '</SVCURRENTCOMPANY>'
           '<SVFROMDATE>' + start + '</SVFROMDATE><SVTODATE>' + end + '</SVTODATE>'
           '<VOUCHERTYPENAME>' + _x(vtype) + '</VOUCHERTYPENAME>'
           '</STATICVARIABLES></DESC></BODY></ENVELOPE>')
    return _tally_post(xml)


def _vendor_map():
    m = {}
    for v in frappe.get_all("Vendor", fields=["name", "tally_ledger"]):
        m[(v.tally_ledger or v.name).strip().lower()] = v.name
    return m


@frappe.whitelist()
def pull_tally_purchases():
    _ledger_guard()
    import re
    from frappe.utils import today
    start = frappe.conf.get("tally_books_from") or "20250401"
    end = today().replace("-", "")

    tax_words = ("gst", "tax", "cess", "vat", "duty")
    made_p = skip_p = seen_p = 0
    made_v = made_m = 0
    made_pay = skip_pay = 0
    unmatched = []

    vmap = _vendor_map()
    t = _tally_vouchers("Purchase", start, end)

    for vm in re.finditer(r"<VOUCHER\b[^>]*>(.*?)</VOUCHER>", t or "", re.S):
        v = vm.group(1)
        seen_p += 1

        def fld(tag, blob=None):
            m = re.search("<" + tag + r">(.*?)</" + tag + ">", blob if blob is not None else v, re.S)
            return _tv_unesc(m.group(1)) if m else ""

        vtype = fld("VOUCHERTYPENAME").lower()
        if vtype and "purchase" not in vtype:
            continue
        guid = fld("GUID")
        if not guid:
            continue
        if frappe.db.exists("Purchase", {"tally_voucher_id": guid}):
            skip_p += 1
            continue

        d8 = fld("DATE")
        pdate = (d8[:4] + "-" + d8[4:6] + "-" + d8[6:8]) if len(d8) == 8 else None
        vno = fld("VOUCHERNUMBER")
        bill = fld("REFERENCE") or vno
        gstin = fld("PARTYGSTIN")

        party = fld("PARTYLEDGERNAME") or fld("PARTYNAME")
        if not party:
            for em in re.finditer(r"<(?:ALLLEDGERENTRIES|LEDGERENTRIES)\.LIST>(.*?)</(?:ALLLEDGERENTRIES|LEDGERENTRIES)\.LIST>", v, re.S):
                e = em.group(1)
                if "<ISPARTYLEDGER>Yes</ISPARTYLEDGER>" in e:
                    party = fld("LEDGERNAME", e)
                    break
        if not party:
            continue

        tax = 0.0
        for em in re.finditer(r"<(?:ALLLEDGERENTRIES|LEDGERENTRIES)\.LIST>(.*?)</(?:ALLLEDGERENTRIES|LEDGERENTRIES)\.LIST>", v, re.S):
            e = em.group(1)
            ln = fld("LEDGERNAME", e)
            if not ln or ln.strip().lower() == party.strip().lower():
                continue
            low = ln.lower()
            if any(w in low for w in tax_words):
                tax += abs(_tv_num(fld("AMOUNT", e)))

        lines = []
        for im in re.finditer(r"<ALLINVENTORYENTRIES\.LIST>(.*?)</ALLINVENTORYENTRIES\.LIST>", v, re.S):
            e = im.group(1)
            item = fld("STOCKITEMNAME", e)
            if not item:
                continue
            qty = abs(_tv_num(fld("BILLEDQTY", e) or fld("ACTUALQTY", e)))
            amt = abs(_tv_num(fld("AMOUNT", e)))
            rate = abs(_tv_num(fld("RATE", e)))
            if qty <= 0:
                qty = 1.0
            if rate <= 0 and qty:
                rate = amt / qty
            lines.append({"item": item, "qty": qty, "rate": rate, "amount": amt})

        if not lines:
            for em in re.finditer(r"<(?:ALLLEDGERENTRIES|LEDGERENTRIES)\.LIST>(.*?)</(?:ALLLEDGERENTRIES|LEDGERENTRIES)\.LIST>", v, re.S):
                e = em.group(1)
                ln = fld("LEDGERNAME", e)
                low = (ln or "").lower()
                if not ln or ln.strip().lower() == party.strip().lower():
                    continue
                if any(w in low for w in tax_words):
                    continue
                amt = abs(_tv_num(fld("AMOUNT", e)))
                if amt > 0:
                    lines.append({"item": ln, "qty": 1.0, "rate": amt, "amount": amt})
                    break
            if not lines:
                continue

        goods = sum(l["amount"] for l in lines)
        gst_pct = 0.0
        if goods > 0 and tax > 0:
            raw = tax / goods * 100.0
            gst_pct = round(raw, 2)
            for std in (3, 5, 12, 18, 28):
                if abs(raw - std) < 0.6:
                    gst_pct = float(std)
                    break

        vend = vmap.get(party.strip().lower())
        if not vend:
            if frappe.db.exists("Vendor", party):
                vend = party
            else:
                frappe.get_doc({"doctype": "Vendor", "vendor_name": party,
                                "gstin": gstin or "", "tally_ledger": party}).insert(ignore_permissions=True)
                vend = party
                made_v += 1
            vmap[party.strip().lower()] = vend

        items = []
        for l in lines:
            if not frappe.db.exists("Raw Material", l["item"]):
                frappe.get_doc({"doctype": "Raw Material", "material_name": l["item"]}).insert(ignore_permissions=True)
                made_m += 1
            items.append({"material": l["item"], "quantity": l["qty"],
                          "price": round(l["rate"], 2), "gst_pct": gst_pct})

        doc = frappe.get_doc({"doctype": "Purchase", "vendor_name": vend,
                              "vendor_gstin": gstin or "", "items": items})
        doc.insert(ignore_permissions=True)
        frappe.db.set_value("Purchase", doc.name, {
            "tally_voucher_id": guid, "bill_no": bill,
            "purchase_date": pdate, "source": "Tally"})
        made_p += 1

    t2 = _tally_vouchers("Payment", start, end)
    for vm in re.finditer(r"<VOUCHER\b[^>]*>(.*?)</VOUCHER>", t2 or "", re.S):
        v = vm.group(1)

        def f2(tag, blob=None):
            m = re.search("<" + tag + r">(.*?)</" + tag + ">", blob if blob is not None else v, re.S)
            return _tv_unesc(m.group(1)) if m else ""

        guid = f2("GUID")
        if not guid:
            continue
        d8 = f2("DATE")
        pdate = (d8[:4] + "-" + d8[4:6] + "-" + d8[6:8]) if len(d8) == 8 else None
        vno = f2("VOUCHERNUMBER")
        for em in re.finditer(r"<(?:ALLLEDGERENTRIES|LEDGERENTRIES)\.LIST>(.*?)</(?:ALLLEDGERENTRIES|LEDGERENTRIES)\.LIST>", v, re.S):
            e = em.group(1)
            ln = f2("LEDGERNAME", e)
            if not ln:
                continue
            vend = vmap.get(ln.strip().lower())
            if not vend:
                if ln not in unmatched:
                    unmatched.append(ln)
                continue
            amt = abs(_tv_num(f2("AMOUNT", e)))
            if amt <= 0:
                continue
            key = guid + "|" + vend
            if frappe.db.exists("Vendor Payment", {"tally_voucher_id": key}):
                skip_pay += 1
                continue
            doc = frappe.get_doc({"doctype": "Vendor Payment", "vendor": vend, "amount": amt,
                                  "payment_date": pdate, "reference": ("Tally " + vno).strip()})
            doc.insert(ignore_permissions=True)
            frappe.db.set_value("Vendor Payment", doc.name, {"tally_voucher_id": key})
            made_pay += 1

    frappe.db.commit()
    return {"ok": True, "purchases_imported": made_p, "purchases_already_had": skip_p,
            "purchase_vouchers_seen": seen_p, "vendors_created": made_v,
            "materials_created": made_m, "vendor_payments_imported": made_pay,
            "vendor_payments_already_had": skip_pay,
            "unmatched_payment_ledgers": unmatched[:8]}


@frappe.whitelist()
def vendor_ledger(vendor):
    _ledger_guard()
    v = frappe.get_doc("Vendor", vendor)
    purs = frappe.get_all("Purchase", filters={"vendor_name": vendor},
                          fields=["name", "total_amount", "creation"], order_by="creation asc")
    pays = frappe.get_all("Vendor Payment", filters={"vendor": vendor},
                          fields=["name", "amount", "reference", "payment_date", "creation"], order_by="creation asc")
    purchased = sum((r.total_amount or 0) for r in purs)
    paid = sum((r.amount or 0) for r in pays)
    rows = []
    for r in purs:
        pd = frappe.db.get_value("Purchase", r.name, "purchase_date")
        bill = frappe.db.get_value("Purchase", r.name, "bill_no")
        dt = str(pd) if pd else str(r.creation)[:10]
        rows.append({"date": dt, "sort": dt + "1", "desc": "Purchase - " + (bill or r.name),
                     "debit": (r.total_amount or 0), "credit": 0})
    for r in pays:
        dt = str(r.payment_date) if r.payment_date else str(r.creation)[:10]
        rows.append({"date": dt, "sort": dt + "2", "desc": "Payment - " + (r.reference or r.name),
                     "debit": 0, "credit": (r.amount or 0)})
    rows.sort(key=lambda x: x["sort"])
    bal = 0.0
    for r in rows:
        bal += r["debit"] - r["credit"]
        r["balance"] = bal
    return {"vendor": v.name, "vendor_name": v.vendor_name, "gstin": v.gstin,
            "purchased": purchased, "paid": paid, "outstanding": purchased - paid, "statement": rows}

@frappe.whitelist()
def live_stock():
    prods = frappe.get_all("Product", fields=["name", "product_name", "unit", "price"], order_by="product_name asc")
    moves = frappe.get_all("Stock Move", fields=["product", "quantity"])
    pending = frappe.get_all("Customer Order", filters={"status": "Pending"}, fields=["name"])

    stock_map = {}
    for m in moves:
        if m.product:
            stock_map[m.product] = stock_map.get(m.product, 0) + (m.quantity or 0)

    pending_map = {}
    for o in pending:
        items = frappe.get_all("Order Item", filters={"parent": o.name}, fields=["product", "qty"])
        for it in items:
            if it.product:
                pending_map[it.product] = pending_map.get(it.product, 0) + (it.qty or 0)

    out = []
    for p in prods:
        s = stock_map.get(p.name, 0)
        pend = pending_map.get(p.name, 0)
        out.append({
            "product": p.name, "product_name": p.product_name,
            "unit": p.unit or "nos", "price": p.price or 0,
            "in_stock": s, "pending_orders": pend, "available": s - pend,
        })
    return out


@frappe.whitelist()
def deduct_stock_on_confirm(order):
    if not frappe.db.exists("Customer Order", order):
        return
    doc = frappe.get_doc("Customer Order", order)
    if doc.status != "Confirmed":
        return
    already = frappe.get_all("Stock Move", filters={"reference": order, "entry_type": "Order Deduct"}, limit=1)
    if already:
        return
    for it in (doc.items or []):
        if (it.qty or 0) > 0:
            frappe.get_doc({
                "doctype": "Stock Move", "product": it.product,
                "quantity": -(it.qty or 0), "entry_type": "Order Deduct",
                "reference": order, "notes": "Auto-deducted on order confirm",
            }).insert(ignore_permissions=True)
    frappe.db.commit()

def validate_order_invoice(doc, method=None):
    if not doc.order or not frappe.db.exists("Customer Order", doc.order):
        return
    order = frappe.get_doc("Customer Order", doc.order)
    discount = doc.discount or 0
    pct = doc.split_pct if doc.split_pct is not None else 50
    gst = doc.gst_rate if doc.gst_rate is not None else 18
    charges = (doc.transportation or 0) + (doc.packaging or 0)
    special = float(doc.get("b_special_discount") or 0)
    ex_qty = float(doc.get("b_extra_qty") or 0)
    ex_price = float(doc.get("b_extra_price") or 0)
    extra = _inv_r2(ex_qty * ex_price)

    def split(share, extra_charge, gstrate):
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
        total = _inv_r2(goods + cgst + sgst + extra_charge)
        return goods, cgst, sgst, total

    ag, ac, asg, at = split(pct, 0, gst)
    bg, bc, bsg, bt = split(100 - pct, charges, 0)
    bg_total = _inv_r2(bg + extra)
    bt = _inv_r2(bg_total + charges + special)

    doc.a_goods = ag
    doc.a_cgst = ac
    doc.a_sgst = asg
    doc.a_amount = at
    doc.b_goods = bg_total
    doc.b_cgst = 0
    doc.b_sgst = 0
    doc.b_charges = charges
    doc.b_amount = bt
    doc.grand_total = _inv_r2(at + bt)


def validate_customer_order(doc, method=None):
    tq = 0.0
    ta = 0.0
    for row in (doc.items or []):
        if not row.rate:
            row.rate = frappe.db.get_value("Product", row.product, "price") or 0
        amt = (row.qty or 0) * (row.rate or 0)
        try:
            row.amount = amt
        except Exception:
            pass
        tq += (row.qty or 0)
        ta += amt
    doc.total_qty = tq
    doc.total_amount = ta

@frappe.whitelist()
def stock_log(from_date=None, to_date=None):
    _prod_allowed()
    filters = {}
    if from_date and to_date:
        filters["creation"] = ["between", [from_date + " 00:00:00", to_date + " 23:59:59"]]
    rows = frappe.get_all("Stock Move", filters=filters,
                          fields=["name", "product", "quantity", "entry_type", "reference", "notes", "creation"],
                          order_by="creation desc", limit_page_length=500)
    out = []
    for r in rows:
        out.append({
            "name": r.name,
            "product": r.product,
            "product_name": frappe.db.get_value("Product", r.product, "product_name") or r.product,
            "quantity": r.quantity or 0,
            "entry_type": r.entry_type or "",
            "reference": r.reference or "",
            "notes": r.notes or "",
            "date": str(r.creation)[:10],
            "time": str(r.creation)[11:16],
        })
    return out


@frappe.whitelist()
def rozmel(from_date=None, to_date=None):
    _ledger_guard()
    from frappe.utils import today, add_days
    d1 = from_date or today()
    d2 = to_date or d1

    def rows_for(a, b):
        out = []
        for r in frappe.get_all("Customer Payment",
                                filters={"status": "Confirmed", "payment_date": ["between", [a, b]]},
                                fields=["name", "customer", "amount", "channel", "reference", "payment_date"]):
            out.append({"date": str(r.payment_date), "kind": "in",
                        "desc": "Receipt - " + (r.customer or ""),
                        "ref": (r.reference or r.name), "cin": r.amount or 0, "cout": 0})
        for r in frappe.get_all("Vendor Payment",
                                filters={"payment_date": ["between", [a, b]]},
                                fields=["name", "vendor", "amount", "reference", "payment_date"]):
            out.append({"date": str(r.payment_date), "kind": "out",
                        "desc": "Paid - " + (r.vendor or ""),
                        "ref": (r.reference or r.name), "cin": 0, "cout": r.amount or 0})
        for r in frappe.get_all("Daily Expense",
                                filters={"expense_date": ["between", [a, b]]},
                                fields=["name", "title", "category", "amount", "expense_date"]):
            out.append({"date": str(r.expense_date), "kind": "out",
                        "desc": "Expense - " + (r.title or ""),
                        "ref": (r.category or ""), "cin": 0, "cout": r.amount or 0})
        return out

    prev = rows_for("1900-01-01", add_days(d1, -1))
    opening = sum(x["cin"] for x in prev) - sum(x["cout"] for x in prev)

    rows = rows_for(d1, d2)
    rows.sort(key=lambda x: x["date"])
    bal = opening
    for r in rows:
        bal = bal + r["cin"] - r["cout"]
        r["balance"] = bal

    return {"from_date": d1, "to_date": d2, "opening": opening, "rows": rows,
            "total_in": sum(r["cin"] for r in rows),
            "total_out": sum(r["cout"] for r in rows),
            "closing": bal}

@frappe.whitelist()
def stock_log(from_date=None, to_date=None):
    from frappe.utils import today, add_days
    d2 = to_date or today()
    d1 = from_date or add_days(d2, -30)
    rng = {"creation": ["between", [str(d1) + " 00:00:00", str(d2) + " 23:59:59"]]}
    base = ["name", "product", "quantity", "creation"]
    extra = ["entry_type", "reference", "notes"]
    try:
        rows = frappe.get_all("Stock Move", filters=rng, fields=base + extra,
                              order_by="creation desc", limit_page_length=1000)
    except Exception:
        rows = frappe.get_all("Stock Move", filters=rng, fields=base,
                              order_by="creation desc", limit_page_length=1000)
    out = []
    for r in rows:
        out.append({
            "name": r.get("name"),
            "product": r.get("product"),
            "product_name": frappe.db.get_value("Product", r.get("product"), "product_name") or r.get("product") or "",
            "quantity": r.get("quantity") or 0,
            "entry_type": r.get("entry_type") or "",
            "reference": r.get("reference") or "",
            "notes": r.get("notes") or "",
            "date": str(r.get("creation"))[:10],
            "time": str(r.get("creation"))[11:16],
        })
    return out


@frappe.whitelist()
def my_customers():
    user = frappe.session.user
    rows = frappe.get_all("Customer", fields=["name", "customer_name", "gstin", "contact", "address", "salesman"],
                          order_by="customer_name asc")
    if "System Manager" in frappe.get_roles():
        return rows
    mine = [r for r in rows if (r.get("salesman") or "") == user]
    if not mine:
        names = set()
        for o in frappe.get_all("Customer Order", filters={"salesman": user}, fields=["customer"]):
            if o.customer:
                names.add(o.customer.strip().lower())
        mine = [r for r in rows if (r.get("customer_name") or r.get("name") or "").strip().lower() in names]
    return mine


@frappe.whitelist()
def set_cash_opening(opening_date, amount):
    _ledger_guard()
    amt = float(amount or 0)
    existing = frappe.db.get_value("Cash Opening", {"opening_date": opening_date}, "name")
    if existing:
        frappe.db.set_value("Cash Opening", existing, "amount", amt)
    else:
        frappe.get_doc({"doctype": "Cash Opening", "opening_date": opening_date,
                        "amount": amt}).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True, "opening_date": opening_date, "amount": amt}


@frappe.whitelist()
def rozmel(from_date=None, to_date=None):
    _ledger_guard()
    from frappe.utils import today, add_days
    d1 = from_date or today()
    d2 = to_date or d1

    def rows_for(a, b):
        out = []
        for r in frappe.get_all("Customer Payment",
                                filters={"status": "Confirmed", "payment_date": ["between", [a, b]]},
                                fields=["name", "customer", "amount", "reference", "payment_date"]):
            out.append({"date": str(r.payment_date), "desc": "Receipt - " + (r.customer or ""),
                        "ref": (r.reference or r.name), "cin": r.amount or 0, "cout": 0})
        for r in frappe.get_all("Vendor Payment",
                                filters={"payment_date": ["between", [a, b]]},
                                fields=["name", "vendor", "amount", "reference", "payment_date"]):
            out.append({"date": str(r.payment_date), "desc": "Paid - " + (r.vendor or ""),
                        "ref": (r.reference or r.name), "cin": 0, "cout": r.amount or 0})
        for r in frappe.get_all("Daily Expense",
                                filters={"expense_date": ["between", [a, b]]},
                                fields=["name", "title", "category", "amount", "expense_date"]):
            out.append({"date": str(r.expense_date), "desc": "Expense - " + (r.title or ""),
                        "ref": (r.category or ""), "cin": 0, "cout": r.amount or 0})
        return out

    base_amt = 0.0
    base_date = "1900-01-01"
    if frappe.db.exists("DocType", "Cash Opening"):
        co = frappe.get_all("Cash Opening", filters={"opening_date": ["<=", d1]},
                            fields=["opening_date", "amount"], order_by="opening_date desc", limit_page_length=1)
        if co:
            base_amt = float(co[0].amount or 0)
            base_date = str(co[0].opening_date)

    prev = rows_for(base_date, add_days(d1, -1))
    opening = base_amt + sum(x["cin"] for x in prev) - sum(x["cout"] for x in prev)

    rows = rows_for(d1, d2)
    rows.sort(key=lambda x: x["date"])
    bal = opening
    for r in rows:
        bal = bal + r["cin"] - r["cout"]
        r["balance"] = bal

    return {"from_date": d1, "to_date": d2, "opening": opening,
            "opening_set_on": base_date if base_date != "1900-01-01" else None,
            "opening_base": base_amt, "rows": rows,
            "total_in": sum(r["cin"] for r in rows),
            "total_out": sum(r["cout"] for r in rows),
            "closing": bal}
