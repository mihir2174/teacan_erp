import frappe

def execute():
    try:
        doc = frappe.get_doc("DocType", "Customer Ledger")
        print(f"Module: {doc.module}, Custom: {doc.custom}")
    except Exception as e:
        print(e)
