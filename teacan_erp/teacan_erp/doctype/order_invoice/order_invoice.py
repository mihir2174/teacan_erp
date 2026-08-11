# Copyright (c) 2026, Mihir Chavda and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class OrderInvoice(Document):
	def on_update(self):
		self.update_ledger()
	
	def on_trash(self):
		frappe.db.delete("Customer Ledger", {"ref_type": "Order Invoice", "ref": self.name})
	
	def update_ledger(self):
		for channel, amount_field in [("A", "a_amount"), ("B", "b_amount")]:
			ledger = frappe.get_all("Customer Ledger", filters={"ref_type": "Order Invoice", "ref": self.name, "channel": channel})
			if ledger:
				doc = frappe.get_doc("Customer Ledger", ledger[0].name)
			else:
				doc = frappe.new_doc("Customer Ledger")
				doc.ref_type = "Order Invoice"
				doc.ref = self.name
				doc.channel = channel
			
			doc.customer = self.customer
			
			sales_person = frappe.db.get_value("Customer Order", self.order, "salesman") if self.order else None
			doc.sales_person = sales_person
			
			doc.debit = getattr(self, amount_field, 0.0)
			doc.credit = 0
			doc.save(ignore_permissions=True)
