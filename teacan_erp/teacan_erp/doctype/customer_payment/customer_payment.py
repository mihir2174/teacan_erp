# Copyright (c) 2026, Mihir Chavda and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class CustomerPayment(Document):
	def on_update(self):
		self.update_ledger()
	
	def on_trash(self):
		frappe.db.delete("Customer Ledger", {"ref_type": "Customer Payment", "ref": self.name})
	
	def update_ledger(self):
		if self.status != "Confirmed":
			frappe.db.delete("Customer Ledger", {"ref_type": "Customer Payment", "ref": self.name})
			return

		ledger = frappe.get_all("Customer Ledger", filters={"ref_type": "Customer Payment", "ref": self.name})
		if ledger:
			doc = frappe.get_doc("Customer Ledger", ledger[0].name)
		else:
			doc = frappe.new_doc("Customer Ledger")
			doc.ref_type = "Customer Payment"
			doc.ref = self.name
		
		doc.customer = self.customer
		
		sales_person = None
		if self.invoice:
			order = frappe.db.get_value("Order Invoice", self.invoice, "order")
			if order:
				sales_person = frappe.db.get_value("Customer Order", order, "salesman")
		doc.sales_person = sales_person
		
		doc.channel = self.channel
		doc.debit = 0
		doc.credit = self.amount
		doc.save(ignore_permissions=True)
