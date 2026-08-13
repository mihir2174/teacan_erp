#!/usr/bin/env python3
"""
Run on BOTH local and live:
  cd ~/frappe-bench/apps/teacan_erp/teacan_erp
  python3 patch_api.py
"""
import os

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api.py")
if not os.path.exists(path):
    path = "api.py"

s = open(path).read()

FUNC = '''

@frappe.whitelist()
def sync_tally_customer_outstanding():
    _ledger_guard()
    import re as _re
    comp = _tally_company()

    # Step 1: Clean old Tally payment entries to avoid double counting
    frappe.db.sql("DELETE FROM `tabCustomer Ledger` WHERE ref LIKE 'TALLY-R-%'")
    frappe.db.sql("DELETE FROM `tabCustomer Payment` WHERE source='Tally'")
    # Clean orphaned payment ledger entries
    frappe.db.sql("""DELETE FROM `tabCustomer Ledger`
        WHERE ref_type='Customer Payment'
        AND ref NOT IN (SELECT name FROM `tabCustomer Payment`)
        AND ref NOT LIKE 'TALLY%'""")
    frappe.db.commit()

    # Step 2: Pull closing balance of all Sundry Debtors from Tally
    xml = ('<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>'
           '<TYPE>Collection</TYPE><ID>CustBal</ID></HEADER><BODY><DESC><STATICVARIABLES>'
           '<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>'
           '<SVCURRENTCOMPANY>' + _x(comp) + '</SVCURRENTCOMPANY>'
           '</STATICVARIABLES><TDL><TDLMESSAGE>'
           '<COLLECTION NAME="CustBal" ISMODIFY="No">'
           '<TYPE>Ledger</TYPE>'
           '<CHILDOF>Sundry Debtors</CHILDOF>'
           '<FETCH>Name,ClosingBalance</FETCH>'
           '</COLLECTION></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>')
    t = _tally_post(xml)

    def unesc(val):
        return (val or "").replace("&amp;", "&").replace("&quot;", '"').replace("&apos;", "'").replace("&lt;", "<").replace("&gt;", ">").strip()

    created_cust = created_ledger = updated = 0

    for lm in _re.finditer(r'<LEDGER[^>]*\\bNAME="([^"]*)"[^>]*>(.*?)</LEDGER>', t or "", _re.S):
        name = unesc(lm.group(1))
        block = lm.group(2)
        cb = _re.search(r"<CLOSINGBALANCE[^>]*>(.*?)</CLOSINGBALANCE>", block, _re.S)
        if not name.strip():
            continue
        m = _re.search(r"-?[\\d,]+(?:\\.\\d+)?", (cb.group(1) if cb else "0").replace(",", ""))
        outstanding = float(m.group(0)) if m else 0.0
        # Tally: negative closing balance = customer owes (debit)
        # positive closing balance = we owe customer (credit)

        # Find or create customer
        cust = None
        for c in frappe.get_all("Customer", filters={"tally_ledger": name}, fields=["name"]):
            cust = c.name
        if not cust:
            for c in frappe.get_all("Customer", filters={"customer_name": name}, fields=["name"]):
                cust = c.name
        if not cust:
            safe_name = _re.sub(r"[^\\w\\s\\-.,()]+", "", name, flags=_re.UNICODE).strip() or "Customer"
            if frappe.db.exists("Customer", safe_name):
                cust = safe_name
            else:
                frappe.get_doc({"doctype": "Customer", "customer_name": safe_name, "tally_ledger": name}).insert(ignore_permissions=True)
                cust = safe_name
                created_cust += 1

        ref_key = "TALLY-OPENING-" + name
        # Tally sign: negative = debit (they owe), positive = credit (we owe)
        debit_amt = abs(outstanding) if outstanding < 0 else 0
        credit_amt = outstanding if outstanding > 0 else 0

        if frappe.db.exists("Customer Ledger", {"ref": ref_key}):
            existing = frappe.get_all("Customer Ledger", filters={"ref": ref_key}, fields=["name"])
            if existing:
                frappe.db.set_value("Customer Ledger", existing[0].name, {
                    "debit": debit_amt, "credit": credit_amt})
            updated += 1
        else:
            cl = frappe.get_doc({"doctype": "Customer Ledger", "customer": cust,
                "ref_type": "", "ref": ref_key, "channel": "A",
                "debit": debit_amt, "credit": credit_amt})
            cl.flags.ignore_links = True
            cl.flags.ignore_mandatory = True
            cl.insert(ignore_permissions=True)
            created_ledger += 1

    frappe.db.commit()
    return {"ok": True, "customers_created": created_cust,
            "ledger_entries_created": created_ledger, "updated": updated}
'''

if "def sync_tally_customer_outstanding" in s:
    # Replace existing function
    import re
    s = re.sub(
        r'@frappe\.whitelist\(\)\ndef sync_tally_customer_outstanding\(\):.+?(?=\n@frappe\.whitelist|\n# ----|\Z)',
        FUNC.strip() + '\n',
        s, count=1, flags=re.S
    )
    print("Replaced existing sync_tally_customer_outstanding")
else:
    s += FUNC
    print("Added sync_tally_customer_outstanding")

# Also add raw_stock_log if missing
if "def raw_stock_log" not in s:
    s += '''

@frappe.whitelist()
def raw_stock_log(from_date=None, to_date=None):
    from frappe.utils import today
    f = from_date or today()
    t = to_date or today()
    moves = frappe.get_all("Raw Stock Move",
        filters={"creation": ["between", [f, t + " 23:59:59"]]},
        fields=["name", "material", "quantity", "creation"],
        order_by="creation desc", limit_page_length=500)
    out = []
    for m in moves:
        d = str(m.creation)[:10]
        out.append({"name": m.name, "material": m.material, "quantity": m.quantity, "date": d})
    return out
'''
    print("Added raw_stock_log")

open(path, "w").write(s)
print("api.py patched successfully")
