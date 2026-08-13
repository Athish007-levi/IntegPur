import random
from datetime import timedelta

import frappe
from frappe.utils import now_datetime


@frappe.whitelist()
def generate_otp(transaction_unique_id, purchase_invoice, phone_number):
    # Basic validation
    if not transaction_unique_id:
        frappe.throw("Transaction Unique ID is required")

    if not purchase_invoice:
        frappe.throw("Purchase Invoice is required")

    if not phone_number:
        frappe.throw("Phone Number is required")

    # Generate a 6-digit OTP
    otp = str(random.randint(100000, 999999))

    generated_on = now_datetime()
    expires_on = generated_on + timedelta(minutes=5)

    # Create OTP record
    otp_doc = frappe.get_doc({
        "doctype": "Payment OTP",
        "transaction_unique_id": transaction_unique_id,
        "purchase_invoice": purchase_invoice,
        "phone_number": phone_number,
        "otp": otp,
        "generated_on": generated_on,
        "expires_on": expires_on,
        "verification_status": "Pending",
        "attempt_count": 0
    })

    otp_doc.insert(ignore_permissions=True)

    return {
        "success": True,
        "message": "OTP generated successfully",
        "transaction_unique_id": transaction_unique_id,
        "otp_request_id": otp_doc.name,
        "expires_on": expires_on
    }