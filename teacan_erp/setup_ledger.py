import frappe

def execute():
    try:
        doc = frappe.get_doc("DocType", "Customer Ledger")
        doc.fields = []
        fields = [
            {"fieldname": "customer", "fieldtype": "Link", "options": "Customer", "label": "Customer", "reqd": 1, "in_list_view": 1},
            {"fieldname": "sales_person", "fieldtype": "Link", "options": "User", "label": "Sales Person", "in_list_view": 1},
            {"fieldname": "credit", "fieldtype": "Currency", "label": "Credit", "default": "0", "in_list_view": 1},
            {"fieldname": "debit", "fieldtype": "Currency", "label": "Debit", "default": "0", "in_list_view": 1},
            {"fieldname": "channel", "fieldtype": "Select", "label": "Channel", "options": "A\nB", "in_list_view": 1},
            {"fieldname": "ref_type", "fieldtype": "Select", "label": "Reference Type", "options": "Order Invoice\nCustomer Payment", "in_list_view": 1},
            {"fieldname": "ref", "fieldtype": "Dynamic Link", "label": "Reference", "options": "ref_type", "in_list_view": 1}
        ]
        for f in fields:
            doc.append("fields", f)
        
        doc.custom = 0
        doc.save(ignore_permissions=True)
        frappe.db.commit()
        print("Updated Doctype Customer Ledger")
    except Exception as e:
        print(f"Error: {e}")
