import json
import requests
import frappe


def get_integration_headers():
    api_key = frappe.conf.get("payment_integration_api_key")
    api_secret = frappe.conf.get("payment_integration_api_secret")

    if not api_key:
        frappe.throw(
            "Payment Integration API Key is not configured"
        )

    if not api_secret:
        frappe.throw(
            "Payment Integration API Secret is not configured"
        )

    return {
        "Authorization": f"token {api_key}:{api_secret}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get_integration_url():
    integration_url = frappe.conf.get(
        "payment_integration_url"
    )

    if not integration_url:
        frappe.throw(
            "Payment Integration URL is not configured"
        )

    return integration_url.rstrip("/")


def parse_response(response):
    try:
        return response.json()
    except ValueError:
        return {
            "success": False,
            "message": response.text,
            "http_status": response.status_code,
        }


def get_response_message(result):
    if not isinstance(result, dict):
        return None

    message = result.get("message")

    if isinstance(message, dict):
        return (
            message.get("message")
            or message.get("response_message")
            or message.get("error_message")
            or message.get("error")
        )

    if isinstance(message, str):
        return message

    return (
        result.get("response_message")
        or result.get("error_message")
        or result.get("error")
        or result.get("exception")
        or result.get("exc")
    )


def get_response_value(result, key):
    if not isinstance(result, dict):
        return None

    message = result.get("message")

    if isinstance(message, dict):
        if key in message:
            return message.get(key)

    return result.get(key)


def log_payment_api(
    api_name,
    transaction_unique_id=None,
    purchase_invoice=None,
    request_method="POST",
    http_status=None,
    status="Failed",
    response_code=None,
    error_message=None,
    request_payload=None,
    response_payload=None,
):
    try:
        log = frappe.get_doc(
            {
                "doctype": "Payment API Log",
                "timestamp": frappe.utils.now(),
                "api_name": api_name,
                "transaction_unique_id": (
                    transaction_unique_id
                ),
                "purchase_invoice": purchase_invoice,
                "request_method": request_method,
                "http_status": http_status,
                "status": status,
                "response_code": response_code,
                "error_message": error_message,
                "request_payload": (
                    json.dumps(
                        request_payload,
                        default=str,
                    )
                    if request_payload is not None
                    else None
                ),
                "response_payload": (
                    json.dumps(
                        response_payload,
                        default=str,
                    )
                    if response_payload is not None
                    else None
                ),
            }
        )

        log.insert(ignore_permissions=True)
        frappe.db.commit()

    except Exception:
        frappe.log_error(
            title="Payment API Log Creation Failed",
            message=frappe.get_traceback(),
        )


def get_bank_account(
    bank_account_number,
    account_role,
):

    if not bank_account_number:
        frappe.throw(
            f"{account_role} Bank Account Number is required"
        )

    account_name = frappe.db.get_value(
        "Bank Account Configuration",
        {
            "account_number": bank_account_number,
            "enabled": 1,
        },
        "name",
    )

    if not account_name:
        frappe.throw(
            "No enabled Bank Account Configuration found "
            f"for {account_role} account number: "
            f"{bank_account_number}"
        )

    return frappe.get_doc(
        "Bank Account Configuration",
        account_name,
    )


def get_purchase_payment_row(
    purchase_invoice,
    transaction_unique_id,
):
    invoice = frappe.get_doc(
        "Purchase Invoice",
        purchase_invoice,
    )

    for row in (
        invoice.get("payment_transactions") or []
    ):
        if (
            row.transaction_unique_id
            == transaction_unique_id
        ):
            return invoice, row

    return invoice, None


def create_purchase_payment(
    purchase_invoice,
    transaction_unique_id,
    amount,
    from_bank,
    to_bank,
    bank_payment_mode,
    result,
):
    invoice = frappe.get_doc(
        "Purchase Invoice",
        purchase_invoice,
    )

    existing_row = None

    for row in (
        invoice.get("payment_transactions") or []
    ):
        if (
            row.transaction_unique_id
            == transaction_unique_id
        ):
            existing_row = row
            break

    if existing_row:
        return invoice, existing_row

    response_code = get_response_value(
        result,
        "response_code",
    )

    message = (
        result.get("message")
        if isinstance(result, dict)
        else None
    )

    if not isinstance(message, dict):
        message = {}

    otp_request_id = (
        message.get("otp_request_id")
        or (
            result.get("otp_request_id")
            if isinstance(result, dict)
            else None
        )
    )

    row = invoice.append(
        "payment_transactions",
        {
            "payment_initiated_on": (
                frappe.utils.now()
            ),
            "amount": amount,
            "payment_status": "OTP Pending",
            "transaction_unique_id": (
                transaction_unique_id
            ),
            "bank_payment_mode": (
                bank_payment_mode
            ),
            "otp_verification_status": (
                "OTP Pending"
            ),
            "response_code": response_code,
            "otp_request_id": otp_request_id,
            "from_bank": from_bank,
            "to_bank": to_bank,
        },
    )

    invoice.save(ignore_permissions=True)
    frappe.db.commit()

    return invoice, row


def update_purchase_payment(
    purchase_invoice,
    transaction_unique_id,
    payment_status=None,
    otp_verification_status=None,
    response_code=None,
    bank_transaction_id=None,
    otp_request_id=None,
):
    invoice, row = get_purchase_payment_row(
        purchase_invoice,
        transaction_unique_id,
    )

    if not row:
        frappe.throw(
            "Purchase Payment transaction not found "
            f"for Transaction Unique ID: "
            f"{transaction_unique_id}"
        )

    changed = False

    if payment_status is not None:
        row.payment_status = payment_status
        changed = True

    if otp_verification_status is not None:
        row.otp_verification_status = (
            otp_verification_status
        )
        changed = True

    if response_code is not None:
        row.response_code = response_code
        changed = True

    if bank_transaction_id is not None:
        row.bank_transaction_id = (
            bank_transaction_id
        )
        changed = True

    if otp_request_id is not None:
        row.otp_request_id = otp_request_id
        changed = True

    if changed:
        invoice.save(ignore_permissions=True)
        frappe.db.commit()

    return invoice, row


@frappe.whitelist()
def generate_otp(
    transaction_unique_id,
    purchase_invoice,
    debit_account,
    beneficiary_account,
    amount,
    mode_of_payment,
):

    if not transaction_unique_id:
        frappe.throw(
            "Transaction Unique ID is required"
        )

    if not purchase_invoice:
        frappe.throw(
            "Purchase Invoice is required"
        )

    if not debit_account:
        frappe.throw(
            "Debit Account is required"
        )

    if not beneficiary_account:
        frappe.throw(
            "Beneficiary Account is required"
        )

    if not amount:
        frappe.throw("Amount is required")

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        frappe.throw(
            "Amount must be a valid number"
        )

    if amount <= 0:
        frappe.throw(
            "Amount must be greater than zero"
        )

    if not mode_of_payment:
        frappe.throw(
            "Mode of Payment is required"
        )

    debit_bank = get_bank_account(
        debit_account,
        "Debit",
    )

    debit_account_name = debit_bank.name

    beneficiary_account_name = frappe.db.get_value(
        "Bank Account Configuration",
        {
            "account_number": beneficiary_account,
            "enabled": 1,
        },
        "name",
    )

    existing_payment_name = frappe.db.get_value(
        "Payment Transaction",
        {
            "unique_id": transaction_unique_id,
        },
        "name",
    )

    if existing_payment_name:
        payment = frappe.get_doc(
            "Payment Transaction",
            existing_payment_name,
        )

        existing_otp_name = frappe.db.get_value(
            "Payment OTP",
            {
                "transaction_unique_id": (
                    transaction_unique_id
                ),
            },
            "name",
        )

        return {
            "success": True,
            "transaction_unique_id": (
                transaction_unique_id
            ),
            "purchase_invoice": purchase_invoice,
            "payment_transaction": payment.name,
            "otp_request_id": existing_otp_name,
            "payment_status": payment.payment_status,
            "debit_account": debit_account,
            "debit_account_configuration": (
                debit_account_name
            ),
            "beneficiary_account": (
                beneficiary_account
            ),
            "beneficiary_account_configuration": (
                beneficiary_account_name
            ),
            "message": (
                "Payment transaction already exists."
            ),
        }


    import random
    from datetime import timedelta

    from frappe.utils import now_datetime

    otp = str(
        random.randint(
            100000,
            999999,
        )
    )

    generated_on = now_datetime()
    expires_on = (
        generated_on
        + timedelta(minutes=5)
    )

    payment = frappe.get_doc(
        {
            "doctype": "Payment Transaction",
            "unique_id": transaction_unique_id,
            "purchase_invoice": purchase_invoice,
            "debit_account": debit_account_name,
            "beneficiary_account": (
                beneficiary_account_name
                or beneficiary_account
            ),
            "amount": amount,
            "mode_of_payment": mode_of_payment,
            "payment_status": "OTP_PENDING",
        }
    )

    payment.insert(
        ignore_permissions=True
    )


    otp_doc = frappe.get_doc(
        {
            "doctype": "Payment OTP",
            "transaction_unique_id": (
                transaction_unique_id
            ),
            "purchase_invoice": purchase_invoice,
            "payment_transaction": payment.name,
            "phone_number": (
                debit_bank.phone_number
            ),
            "otp": otp,
            "generated_on": generated_on,
            "expires_on": expires_on,
            "verification_status": "Pending",
            "attempt_count": 0,
        }
    )

    otp_doc.insert(
        ignore_permissions=True
    )

    frappe.db.commit()



    return {
        "success": True,
        "transaction_unique_id": (
            transaction_unique_id
        ),
        "purchase_invoice": purchase_invoice,
        "payment_transaction": payment.name,
        "otp_request_id": otp_doc.name,
        "expires_on": expires_on,
        "payment_status": "OTP_PENDING",
        "debit_account": debit_account,
        "debit_account_configuration": (
            debit_account_name
        ),
        "beneficiary_account": (
            beneficiary_account
        ),
        "beneficiary_account_configuration": (
            beneficiary_account_name
        ),
        "message": "OTP generated successfully.",
    }


@frappe.whitelist()
def validate_otp(
    transaction_unique_id,
    otp,
):


    if not transaction_unique_id:
        frappe.throw(
            "Transaction Unique ID is required"
        )

    if not otp:
        frappe.throw("OTP is required")



    otp_name = frappe.db.get_value(
        "Payment OTP",
        {
            "transaction_unique_id": (
                transaction_unique_id
            ),
        },
        "name",
    )

    if not otp_name:
        frappe.throw(
            "OTP request not found"
        )

    otp_doc = frappe.get_doc(
        "Payment OTP",
        otp_name,
    )

    payment_name = frappe.db.get_value(
        "Payment Transaction",
        {
            "unique_id": transaction_unique_id,
        },
        "name",
    )

    if not payment_name:
        frappe.throw(
            "Payment Transaction not found for "
            f"Transaction Unique ID: "
            f"{transaction_unique_id}"
        )

    payment = frappe.get_doc(
        "Payment Transaction",
        payment_name,
    )

    if otp_doc.verification_status == "Verified":
        return {
            "success": True,
            "verified": True,
            "transaction_unique_id": (
                transaction_unique_id
            ),
            "payment_transaction": payment.name,
            "payment_status": payment.payment_status,
            "bank_transaction_id": (
                payment.bank_transaction_id
            ),
            "message": (
                "OTP has already been verified."
            ),
        }

    if (otp_doc.attempt_count or 0) >= 3:
        otp_doc.verification_status = "Failed"
        otp_doc.save(
            ignore_permissions=True
        )
        frappe.db.commit()

        update_payment_status(
            payment,
            payment_status="FAILED",
            response_message=(
                "Maximum OTP attempts exceeded."
            ),
        )

        frappe.throw(
            "Maximum OTP attempts exceeded"
        )

    from frappe.utils import now_datetime

    if now_datetime() > otp_doc.expires_on:
        otp_doc.verification_status = "Expired"
        otp_doc.save(
            ignore_permissions=True
        )
        frappe.db.commit()

        update_payment_status(
            payment,
            payment_status="FAILED",
            response_message=(
                "OTP has expired."
            ),
        )

        frappe.throw(
            "OTP has expired"
        )

    otp_doc.attempt_count = (
        (otp_doc.attempt_count or 0)
        + 1
    )


    if str(otp_doc.otp) != str(otp):
        otp_doc.verification_status = "Failed"

        otp_doc.save(
            ignore_permissions=True
        )

        frappe.db.commit()

        update_payment_status(
            payment,
            payment_status="OTP_PENDING",
            response_message="Invalid OTP.",
        )

        return {
            "success": False,
            "verified": False,
            "transaction_unique_id": (
                transaction_unique_id
            ),
            "payment_transaction": payment.name,
            "payment_status": "OTP_PENDING",
            "message": "Invalid OTP.",
            "attempt_count": (
                otp_doc.attempt_count
            ),
        }

    otp_doc.verification_status = "Verified"

    otp_doc.save(
        ignore_permissions=True
    )

    frappe.db.commit()

    update_payment_status(
        payment,
        payment_status="OTP_VERIFIED",
        response_message=(
            "OTP verified successfully."
        ),
    )

    update_payment_status(
        payment,
        payment_status="PROCESSING",
        response_message=(
            "OTP verified. Processing payment."
        ),
    )

    from integration.api.mock_bank import (
        initiate_payment as mock_bank_initiate_payment
    )

    try:
        bank_result = (
            mock_bank_initiate_payment(
                transaction_unique_id=(
                    transaction_unique_id
                ),
                purchase_invoice=(
                    payment.purchase_invoice
                ),
                debit_account=(
                    payment.debit_account
                ),
                beneficiary_account=(
                    payment.beneficiary_account
                ),
                amount=payment.amount,
                mode_of_payment=(
                    payment.mode_of_payment
                ),
            )
        )

    except Exception as exc:
        update_payment_status(
            payment,
            payment_status="FAILED",
            response_message=str(exc),
        )

        return {
            "success": False,
            "verified": True,
            "transaction_unique_id": (
                transaction_unique_id
            ),
            "payment_transaction": payment.name,
            "payment_status": "FAILED",
            "message": (
                "OTP verified, but payment processing "
                f"failed: {str(exc)}"
            ),
        }

    processing_time_ms = (
        get_response_value(
            bank_result,
            "processing_time_ms",
        )
    )

    bank_transaction_id = (
        get_response_value(
            bank_result,
            "transaction_id",
        )
        or get_response_value(
            bank_result,
            "bank_transaction_id",
        )
    )

    response_code = get_response_value(
        bank_result,
        "response_code",
    )

    response_message = get_response_message(
        bank_result
    )

    bank_status = get_response_value(
        bank_result,
        "payment_status",
    )

    if not bank_status:
        bank_response = (
            bank_result.get("response")
            if isinstance(bank_result, dict)
            else None
        )

        bank_status = get_response_value(
            bank_response,
            "status",
        )

    if bank_status:
        bank_status = str(
            bank_status
        ).upper()


    status_map = {
        "INITIATED": "INITIATED",
        "OTP_PENDING": "OTP_PENDING",
        "OTP_VERIFIED": "OTP_VERIFIED",
        "PROCESSING": "PROCESSING",
        "COMPLETED": "COMPLETED",
        "PENDING": "PENDING",
        "FAILED": "FAILED",
        "REJECTED": "REJECTED",
        "SUCCESS": "COMPLETED",
    }

    final_status = status_map.get(
        bank_status,
        "FAILED",
    )

    if (
        isinstance(bank_result, dict)
        and bank_result.get("success")
        and not bank_status
    ):
        final_status = "COMPLETED"

    update_payment_status(
        payment,
        payment_status=final_status,
        bank_transaction_id=(
            bank_transaction_id
        ),
        response_code=response_code,
        response_message=response_message,
    )

    if final_status == "COMPLETED":
        return {
            "success": True,
            "verified": True,
            "transaction_unique_id": (
                transaction_unique_id
            ),
            "payment_transaction": payment.name,
            "payment_status": "COMPLETED",
            "bank_transaction_id": (
                bank_transaction_id
            ),
            "response_code": response_code,
            "response_message": (
                response_message
            ),
            "processing_time_ms": (
                processing_time_ms
            ),
            "message": (
                "Payment process completed."
            ),
        }

    if final_status in {
        "PROCESSING",
        "PENDING",
    }:
        return {
            "success": True,
            "verified": True,
            "transaction_unique_id": (
                transaction_unique_id
            ),
            "payment_transaction": payment.name,
            "payment_status": final_status,
            "bank_transaction_id": (
                bank_transaction_id
            ),
            "response_code": response_code,
            "response_message": (
                response_message
            ),
            "processing_time_ms": (
                processing_time_ms
            ),
            "message": (
                "OTP verified. Payment is being processed."
            ),
        }

    return {
        "success": False,
        "verified": True,
        "transaction_unique_id": (
            transaction_unique_id
        ),
        "payment_transaction": payment.name,
        "payment_status": final_status,
        "bank_transaction_id": (
            bank_transaction_id
        ),
        "response_code": response_code,
        "response_message": (
            response_message
        ),
        "processing_time_ms": (
            processing_time_ms
        ),
        "message": (
            response_message
            or "Payment processing failed."
        ),
    }


def update_payment_status(
    payment,
    payment_status=None,
    bank_transaction_id=None,
    response_code=None,
    response_message=None,
):

    changed = False

    if payment_status is not None:
        payment.payment_status = payment_status
        changed = True

    if bank_transaction_id is not None:
        payment.bank_transaction_id = (
            bank_transaction_id
        )
        changed = True

    if response_code is not None:
        payment.response_code = response_code
        changed = True

    if response_message is not None:
        payment.response_message = (
            response_message
        )
        changed = True

    if changed:
        payment.save(
            ignore_permissions=True
        )
        frappe.db.commit()

    return payment

