#!/usr/bin/env python3
"""Fix validate_order_invoice to include special discount + extras in b_amount"""
s = open("api.py").read()

old = '''    ag, ac, asg, at = split(pct, 0, gst)
    bg, bc, bsg, bt = split(100 - pct, charges, 0)
    doc.a_goods = ag; doc.a_cgst = ac; doc.a_sgst = asg; doc.a_amount = at
    doc.b_goods = bg; doc.b_cgst = bc; doc.b_sgst = bsg; doc.b_charges = charges; doc.b_amount = bt
    doc.grand_total = _inv_r2(at + bt)'''

new = '''    ag, ac, asg, at = split(pct, 0, gst)
    bg, bc, bsg, bt = split(100 - pct, charges, 0)
    # Include special discount and extra products in Invoice B total
    sp_disc = float(doc.get("b_special_discount") or 0)
    ex_amt = float(doc.get("b_extra_qty") or 0) * float(doc.get("b_extra_price") or 0)
    bt_final = _inv_r2(bt + sp_disc + ex_amt)
    bg_final = _inv_r2(bg + ex_amt)
    doc.a_goods = ag; doc.a_cgst = ac; doc.a_sgst = asg; doc.a_amount = at
    doc.b_goods = bg_final; doc.b_cgst = bc; doc.b_sgst = bsg; doc.b_charges = charges; doc.b_amount = bt_final
    doc.grand_total = _inv_r2(at + bt_final)'''

if old in s:
    s = s.replace(old, new)
    print("Fixed: b_amount now includes special discount + extras")
else:
    print("ERROR: anchor not found")

open("api.py", "w").write(s)
