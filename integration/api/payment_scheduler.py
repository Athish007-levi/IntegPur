import requests
import frappe

from integration.api.mock_bank import (
    get_payment_status,
)


PENDING_STATUSES = {
    "PENDING",
    "PROCESSING",
}


# =========================================================
# ERPNext URL
# =========================================================

def get_erpnext_url():
    

    return "http://loji.local:8000"


# =========================================================
# REFLECT PAYMENT CHANGE TO ERPNEXT
# =========================================================

def reflect_payment_to_erpnext(payment):
    """
    Reflect the current Payment Transaction state
    into the matching Purchase Payment child row
    in ERPNext.

    ERPNext endpoint uses:
        @frappe.whitelist(allow_guest=True)

    Therefore no API key or secret is required.
    """

    if not payment.unique_id:
        return {
            "success": False,
            "message": "Payment Transaction has no unique_id.",
        }

    if not payment.purchase_invoice:
        return {
            "success": False,
            "message": "Payment Transaction has no purchase_invoice.",
        }

    erpnext_url = get_erpnext_url()

    if not erpnext_url:
        return {
            "success": False,
            "message": "ERPNext URL is not configured.",
        }

    url = (
        f"{erpnext_url}"
        "/api/method/"
        "erpnext_app.api.payment."
        "reflect_payment_transaction"
    )

    payload = {
        "transaction_unique_id": payment.unique_id,
        "purchase_invoice": payment.purchase_invoice,
        "payment_status": payment.payment_status,
        "bank_transaction_id": payment.bank_transaction_id,
        "response_code": payment.response_code,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=15,
        )

        try:
            result = response.json()

        except ValueError:
            result = {
                "success": False,
                "message": response.text,
            }

        if response.status_code != 200:

            frappe.log_error(
                title="ERPNext Payment Reflection Failed",
                message=(
                    f"HTTP Status: {response.status_code}\n\n"
                    f"URL:\n{url}\n\n"
                    f"Payload:\n"
                    f"{frappe.as_json(payload)}\n\n"
                    f"Response:\n"
                    f"{frappe.as_json(result)}"
                ),
            )

            return {
                "success": False,
                "http_status": response.status_code,
                "response": result,
            }

        return {
            "success": True,
            "http_status": response.status_code,
            "response": result,
        }

    except requests.RequestException as exc:

        frappe.log_error(
            title="ERPNext Payment Reflection Request Failed",
            message=(
                f"URL:\n{url}\n\n"
                f"Payload:\n"
                f"{frappe.as_json(payload)}\n\n"
                f"Error:\n{str(exc)}"
            ),
        )

        return {
            "success": False,
            "http_status": None,
            "message": str(exc),
        }


# =========================================================
# MAIN SCHEDULER
# =========================================================

def sync_pending_payment_transactions():
    """
    Find Integration Payment Transactions that are still
    pending/processing and check their status with the bank.
    """

    payments = frappe.get_all(
        "Payment Transaction",

        filters={
            "payment_status": [
                "in",
                list(PENDING_STATUSES),
            ],
        },

        fields=[
            "name",
            "unique_id",
            "purchase_invoice",
            "debit_account",
            "payment_status",
            "bank_transaction_id",
            "response_code",
            "response_message",
        ],

        limit_page_length=100,
    )

    for payment_data in payments:

        try:

            sync_single_payment_transaction(
                payment_data
            )

        except Exception:

            frappe.log_error(
                title=(
                    "Payment Transaction "
                    "Scheduler Failed"
                ),
                message=frappe.get_traceback(),
            )


# =========================================================
# SINGLE PAYMENT TRANSACTION
# =========================================================

def sync_single_payment_transaction(
    payment_data
):
    """
    Check one pending Payment Transaction against
    the bank and reflect any change to ERPNext.
    """

    transaction_unique_id = (
        payment_data.unique_id
    )

    debit_account = (
        payment_data.debit_account
    )

    if not transaction_unique_id:
        return

    if not debit_account:
        return

    # -----------------------------------------------------
    # 1. ASK BANK FOR CURRENT STATUS
    # -----------------------------------------------------

    result = get_payment_status(
        transaction_unique_id=(
            transaction_unique_id
        ),

        debit_account=(
            debit_account
        ),
    )

    if not result.get("success"):
        return

    payment_status = result.get(
        "payment_status"
    )

    if not payment_status:
        return

    payment_status = (
        str(payment_status)
        .strip()
        .upper()
    )

    # -----------------------------------------------------
    # 2. LOAD CURRENT PAYMENT TRANSACTION
    # -----------------------------------------------------

    payment = frappe.get_doc(
        "Payment Transaction",
        payment_data.name,
    )

    old_status = (
        str(
            payment.payment_status
            or ""
        )
        .strip()
        .upper()
    )

    # -----------------------------------------------------
    # 3. GET VALUES FROM BANK RESPONSE
    # -----------------------------------------------------

    bank_transaction_id = (
        result.get("transaction_id")
    )

    response_code = (
        result.get("response_code")
    )

    response_message = (
        result.get("response_message")
    )

    # -----------------------------------------------------
    # 4. DETECT WHETHER ANYTHING CHANGED
    # -----------------------------------------------------

    changed = False

    if old_status != payment_status:
        changed = True

    if (
        bank_transaction_id
        and payment.bank_transaction_id
        != bank_transaction_id
    ):
        changed = True

    if (
        response_code
        and payment.response_code
        != response_code
    ):
        changed = True

    if (
        response_message
        and payment.response_message
        != response_message
    ):
        changed = True

    # -----------------------------------------------------
    # 5. NOTHING CHANGED
    #
    # Do not update Integration.
    # Do not call ERPNext.
    # -----------------------------------------------------

    if not changed:
        return

    # -----------------------------------------------------
    # 6. UPDATE INTEGRATION PAYMENT TRANSACTION
    # -----------------------------------------------------

    if old_status != payment_status:

        payment.payment_status = (
            payment_status
        )

    if bank_transaction_id:

        payment.bank_transaction_id = (
            bank_transaction_id
        )

    if response_code:

        payment.response_code = (
            response_code
        )

    if response_message:

        payment.response_message = (
            response_message
        )

    payment.save(
        ignore_permissions=True
    )

    frappe.db.commit()

    # -----------------------------------------------------
    # 7. REFLECT CHANGE TO ERPNEXT
    # -----------------------------------------------------

    reflection_result = (
        reflect_payment_to_erpnext(
            payment=payment,
            result=result,
            payment_status=payment_status,
        )
    )

    # -----------------------------------------------------
    # 8. LOG REFLECTION FAILURE
    # -----------------------------------------------------

    if not reflection_result.get(
        "success"
    ):

        frappe.log_error(
            title=(
                "ERPNext Payment Reflection Failed"
            ),

            message=frappe.as_json(
                {
                    "transaction_unique_id": (
                        transaction_unique_id
                    ),

                    "payment_status": (
                        payment_status
                    ),

                    "reflection_result": (
                        reflection_result
                    ),
                }
            ),
        )

    # -----------------------------------------------------
    # 9. RETURN RESULT
    # -----------------------------------------------------

    return {
        "success": True,

        "changed": changed,

        "transaction_unique_id": (
            transaction_unique_id
        ),

        "payment_status": (
            payment_status
        ),

        "reflection_result": (
            reflection_result
        ),
    }
