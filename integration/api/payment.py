import random
from datetime import timedelta

import frappe
from frappe.utils import now_datetime



@frappe.whitelist()
def generate_otp(
    transaction_unique_id,
    purchase_invoice,
    debit_account,
    beneficiary_account,
    amount,
    mode_of_payment
):
    if not transaction_unique_id:
        frappe.throw("Transaction Unique ID is required")

    if not purchase_invoice:
        frappe.throw("Purchase Invoice is required")

    if not debit_account:
        frappe.throw("Debit Account is required")

    if not beneficiary_account:
        frappe.throw("Beneficiary Account is required")

    if not amount or float(amount) <= 0:
        frappe.throw("Amount must be greater than zero")

    if not mode_of_payment:
        frappe.throw("Mode of Payment is required")

    account = frappe.get_doc(
        "Bank Account Configuration",
        debit_account
    )

    if not account.enabled:
        frappe.throw("Debit account configuration is disabled")

    otp = str(random.randint(100000, 999999))

    generated_on = now_datetime()
    expires_on = generated_on + timedelta(minutes=5)

    payment = frappe.get_doc({
        "doctype": "Payment Transaction",
        "unique_id": transaction_unique_id,
        "purchase_invoice": purchase_invoice,
        "debit_account": debit_account,
        "beneficiary_account": beneficiary_account,
        "amount": amount,
        "mode_of_payment": mode_of_payment,
        "payment_status": "OTP_PENDING"
    })

    payment.insert(ignore_permissions=True)

    otp_doc = frappe.get_doc({
        "doctype": "Payment OTP",
        "transaction_unique_id": transaction_unique_id,
        "payment_transaction": payment.name,
        "phone_number": account.phone_number,
        "otp": otp,
        "generated_on": generated_on,
        "expires_on": expires_on,
        "verification_status": "Pending",
        "attempt_count": 0
    })

    otp_doc.insert(ignore_permissions=True)

    return {
        "success": True,
        "transaction_unique_id": transaction_unique_id,
        "purchase_invoice": purchase_invoice,
        "payment_transaction": payment.name,
        "otp_request_id": otp_doc.name,
        "expires_on": expires_on
    }

@frappe.whitelist()
def validate_otp(transaction_unique_id, otp):

    if not transaction_unique_id:
        frappe.throw("Transaction Unique ID is required")

    if not otp:
        frappe.throw("OTP is required")

    otp_name = frappe.db.get_value(
        "Payment OTP",
        {
            "transaction_unique_id": transaction_unique_id
        },
        "name"
    )

    if not otp_name:
        frappe.throw("OTP request not found")

    otp_doc = frappe.get_doc("Payment OTP", otp_name)

    if otp_doc.verification_status == "Verified":
        frappe.throw("OTP has already been verified")

    if otp_doc.attempt_count >= 3:
        otp_doc.verification_status = "Failed"
        otp_doc.save(ignore_permissions=True)

        frappe.throw("Maximum OTP attempts exceeded")

    if now_datetime() > otp_doc.expires_on:
        otp_doc.verification_status = "Expired"
        otp_doc.save(ignore_permissions=True)

        frappe.throw("OTP has expired")

    otp_doc.attempt_count = (otp_doc.attempt_count or 0) + 1

    if str(otp_doc.otp) != str(otp):
        otp_doc.verification_status = "Failed"

        otp_doc.save(ignore_permissions=True)

        return {
            "success": False,
            "verified": False,
            "message": "Invalid OTP",
            "attempt_count": otp_doc.attempt_count
        }

    otp_doc.verification_status = "Verified"
    otp_doc.save(ignore_permissions=True)

    payment_name = frappe.db.get_value(
        "Payment Transaction",
        {
            "unique_id": transaction_unique_id
        },
        "name"
    )

    if not payment_name:
        frappe.throw("Payment Transaction not found")

    payment = frappe.get_doc(
        "Payment Transaction",
        payment_name
    )

    payment.payment_status = "OTP_VERIFIED"
    payment.save(ignore_permissions=True)

    return {
        "success": True,
        "verified": True,
        "transaction_unique_id": transaction_unique_id,
        "payment_transaction": payment.name,
        "message": "OTP verified successfully. Payment is ready for bank processing."
    }