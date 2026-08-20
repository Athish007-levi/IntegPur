import frappe

from frappe.utils import now_datetime

from integration.api.mock_bank import (
    initiate_payment,
    get_payment_status,
)


BANK_INITIATION_STATUS = "PENDING"

INITIATION_STATUS = "PENDING"

POLLING_STATUSES = {
    "PENDING",
    "PROCESSING",
}

TERMINAL_STATUSES = {
    "COMPLETED",
    "FAILED",
    "REJECTED",
}

ACTION_INITIATE = "INITIATE_PAYMENT"
ACTION_STATUS = "CHECK_PAYMENT_STATUS"


def normalize_status(status):
    if status is None:
        return None

    return (
        str(status)
        .strip()
        .upper()
    )


def create_scheduler_log(
    payment,
    action,
    scheduler_status,
    previous_status=None,
    new_status=None,
    bank_transaction_id=None,
    response_code=None,
    response_message=None,
    processing_time_ms=None,
    success=None,
    error_message=None,
    commit=False,
):

    try:
        log = frappe.new_doc(
            "Payment Scheduler Log"
        )

        log.name = (
            "PSL-"
            + frappe.generate_hash(
                length=12
            )
        )

        log.payment_transaction = (
            payment.name
        )

        log.transaction_unique_id = (
            payment.unique_id
        )

        log.purchase_invoice = (
            payment.purchase_invoice
        )

        log.scheduler_action = (
            action
        )

        log.previous_status = (
            previous_status
        )

        log.new_status = (
            new_status
        )

        log.bank_transaction_id = (
            bank_transaction_id
            or payment.bank_transaction_id
        )

        log.response_code = (
            response_code
        )

        log.response_message = (
            response_message
        )

        log.processing_time_ms = (
            processing_time_ms
        )

        if success is not None:
            log.success = (
                1 if success else 0
            )

        log.error_message = (
            error_message
        )

        log.scheduler_run_time = (
            now_datetime()
        )

        log.insert(
            ignore_permissions=True
        )

        if commit:
            frappe.db.commit()

        return log.name

    except Exception:
        frappe.log_error(
            title=(
                "Payment Scheduler Log Creation Failed"
            ),
            message=frappe.get_traceback(),
        )

        return None


def lock_payment_transaction(
    payment_name
):

    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabPayment Transaction`
        WHERE name = %s
        FOR UPDATE
        """,
        (payment_name,),
        as_dict=True,
    )

    if not rows:
        return None

    return frappe.get_doc(
        "Payment Transaction",
        payment_name,
    )


def update_payment_transaction(
    payment,
    payment_status=None,
    bank_transaction_id=None,
    response_code=None,
    response_message=None,
):

    values = {}

    if payment_status is not None:
        values["payment_status"] = (
            payment_status
        )

    if bank_transaction_id is not None:
        values["bank_transaction_id"] = (
            bank_transaction_id
        )

    if response_code is not None:
        values["response_code"] = (
            response_code
        )

    if response_message is not None:
        values["response_message"] = (
            response_message
        )

    if not values:
        return

    frappe.db.set_value(
        "Payment Transaction",
        payment.name,
        values,
        update_modified=True,
    )


def get_response_message(
    result
):

    if not isinstance(result, dict):
        return None

    message = result.get(
        "response_message"
    )

    if message:
        return message

    response = result.get(
        "response"
    )

    if isinstance(response, dict):
        return (
            response.get(
                "response_message"
            )
            or response.get(
                "message"
            )
            or response.get(
                "error_message"
            )
        )

    return (
        result.get("message")
        or result.get("error_message")
        or result.get("error")
    )


def get_response_code(
    result
):

    if not isinstance(result, dict):
        return None

    response_code = result.get(
        "response_code"
    )

    if response_code:
        return response_code

    response = result.get(
        "response"
    )

    if isinstance(response, dict):
        return response.get(
            "response_code"
        )

    return None


def get_payment_status_from_result(
    result
):

    if not isinstance(result, dict):
        return None

    status = result.get(
        "payment_status"
    )

    if status:
        return status

    response = result.get(
        "response"
    )

    if isinstance(response, dict):
        return response.get(
            "payment_status"
        )

    return None


def get_bank_transaction_id(
    result
):

    if not isinstance(result, dict):
        return None

    transaction_id = result.get(
        "transaction_id"
    )

    if transaction_id:
        return transaction_id

    bank_transaction_id = result.get(
        "bank_transaction_id"
    )

    if bank_transaction_id:
        return bank_transaction_id

    response = result.get(
        "response"
    )

    if isinstance(response, dict):
        return (
            response.get(
                "transaction_id"
            )
            or response.get(
                "bank_transaction_id"
            )
        )

    return None


def get_processing_time(
    result
):

    if not isinstance(result, dict):
        return None

    processing_time = result.get(
        "processing_time_ms"
    )

    if processing_time is not None:
        return processing_time

    response = result.get(
        "response"
    )

    if isinstance(response, dict):
        return response.get(
            "processing_time_ms"
        )

    return None


def should_initiate_payment(
    payment
):

    status = normalize_status(
        payment.payment_status
    )

    if status != INITIATION_STATUS:
        return False

    if payment.bank_transaction_id:
        return False

    return True


def should_check_payment_status(
    payment
):

    status = normalize_status(
        payment.payment_status
    )

    if status not in POLLING_STATUSES:
        return False

    if not payment.bank_transaction_id:
        return False

    return True


def initiate_single_payment(
    payment
):

    previous_status = normalize_status(
        payment.payment_status
    )

    if not payment.unique_id:

        create_scheduler_log(
            payment=payment,
            action=ACTION_INITIATE,
            scheduler_status="FAILED",
            previous_status=previous_status,
            success=False,
            error_message=(
                "Transaction Unique ID is missing."
            ),
        )

        return {
            "success": False,
            "message": (
                "Transaction Unique ID is missing."
            ),
        }

    if not payment.purchase_invoice:

        create_scheduler_log(
            payment=payment,
            action=ACTION_INITIATE,
            scheduler_status="FAILED",
            previous_status=previous_status,
            success=False,
            error_message=(
                "Purchase Invoice is missing."
            ),
        )

        return {
            "success": False,
            "message": (
                "Purchase Invoice is missing."
            ),
        }

    if not payment.debit_account:

        create_scheduler_log(
            payment=payment,
            action=ACTION_INITIATE,
            scheduler_status="FAILED",
            previous_status=previous_status,
            success=False,
            error_message=(
                "Debit Account is missing."
            ),
        )

        return {
            "success": False,
            "message": (
                "Debit Account is missing."
            ),
        }

    if not payment.beneficiary_account:

        create_scheduler_log(
            payment=payment,
            action=ACTION_INITIATE,
            scheduler_status="FAILED",
            previous_status=previous_status,
            success=False,
            error_message=(
                "Beneficiary Account is missing."
            ),
        )

        return {
            "success": False,
            "message": (
                "Beneficiary Account is missing."
            ),
        }

    if not payment.amount:

        create_scheduler_log(
            payment=payment,
            action=ACTION_INITIATE,
            scheduler_status="FAILED",
            previous_status=previous_status,
            success=False,
            error_message=(
                "Payment amount is missing."
            ),
        )

        return {
            "success": False,
            "message": (
                "Payment amount is missing."
            ),
        }

    if not payment.mode_of_payment:

        create_scheduler_log(
            payment=payment,
            action=ACTION_INITIATE,
            scheduler_status="FAILED",
            previous_status=previous_status,
            success=False,
            error_message=(
                "Mode of Payment is missing."
            ),
        )

        return {
            "success": False,
            "message": (
                "Mode of Payment is missing."
            ),
        }

    create_scheduler_log(
        payment=payment,
        action=ACTION_INITIATE,
        scheduler_status="STARTED",
        previous_status=previous_status,
        success=None,
    )

    try:

        result = initiate_payment(
            transaction_unique_id=(
                payment.unique_id
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
            payment_status=(
                BANK_INITIATION_STATUS
            ),
        )

    except Exception as exc:

        error_message = str(exc)

        create_scheduler_log(
            payment=payment,
            action=ACTION_INITIATE,
            scheduler_status="FAILED",
            previous_status=previous_status,
            success=False,
            error_message=error_message,
        )

        frappe.log_error(
            title=(
                "Payment Initiation Scheduler Failed"
            ),
            message=frappe.get_traceback(),
        )

        return {
            "success": False,
            "message": error_message,
        }

    response_code = get_response_code(
        result
    )

    response_message = (
        get_response_message(
            result
        )
    )

    processing_time_ms = (
        get_processing_time(
            result
        )
    )

    bank_status = (
        get_payment_status_from_result(
            result
        )
    )

    bank_transaction_id = (
        get_bank_transaction_id(
            result
        )
    )

    bank_status = normalize_status(
        bank_status
    )

    if not result.get("success"):

        final_status = (
            bank_status
            if bank_status in {
                "PENDING",
                "PROCESSING",
                "COMPLETED",
                "FAILED",
                "REJECTED",
            }
            else "PENDING"
        )

        update_payment_transaction(
            payment=payment,
            payment_status=final_status,
            bank_transaction_id=(
                bank_transaction_id
            ),
            response_code=response_code,
            response_message=(
                response_message
                or (
                    "Payment initiation did not return "
                    "a definitive result."
                )
            ),
        )

        create_scheduler_log(
            payment=payment,
            action=ACTION_INITIATE,
            scheduler_status="FAILED",
            previous_status=previous_status,
            new_status=final_status,
            bank_transaction_id=(
                bank_transaction_id
            ),
            response_code=response_code,
            response_message=(
                response_message
            ),
            processing_time_ms=(
                processing_time_ms
            ),
            success=False,
            error_message=(
                response_message
                or (
                    "Payment initiation failed. "
                    "Payment remains pending."
                )
            ),
        )

        return {
            "success": False,
            "payment_status": final_status,
            "bank_transaction_id": (
                bank_transaction_id
            ),
            "response_code": response_code,
            "response_message": (
                response_message
            ),
        }

    if not bank_status:

        final_status = "PENDING"

        update_payment_transaction(
            payment=payment,
            payment_status=final_status,
            bank_transaction_id=(
                bank_transaction_id
            ),
            response_code=response_code,
            response_message=(
                response_message
                or (
                    "Bank did not return "
                    "payment_status."
                )
            ),
        )

        create_scheduler_log(
            payment=payment,
            action=ACTION_INITIATE,
            scheduler_status="FAILED",
            previous_status=previous_status,
            new_status=final_status,
            bank_transaction_id=(
                bank_transaction_id
            ),
            response_code=response_code,
            response_message=(
                response_message
            ),
            processing_time_ms=(
                processing_time_ms
            ),
            success=False,
            error_message=(
                "Bank did not return payment_status."
            ),
        )

        return {
            "success": False,
            "payment_status": final_status,
        }

    update_payment_transaction(
        payment=payment,
        payment_status=bank_status,
        bank_transaction_id=(
            bank_transaction_id
        ),
        response_code=response_code,
        response_message=response_message,
    )

    payment = frappe.get_doc(
        "Payment Transaction",
        payment.name,
    )

    create_scheduler_log(
        payment=payment,
        action=ACTION_INITIATE,
        scheduler_status="SUCCESS",
        previous_status=previous_status,
        new_status=bank_status,
        bank_transaction_id=(
            payment.bank_transaction_id
        ),
        response_code=response_code,
        response_message=response_message,
        processing_time_ms=(
            processing_time_ms
        ),
        success=True,
    )

    return {
        "success": True,
        "transaction_unique_id": (
            payment.unique_id
        ),
        "previous_status": previous_status,
        "payment_status": bank_status,
        "bank_transaction_id": (
            payment.bank_transaction_id
        ),
        "response_code": response_code,
        "response_message": response_message,
    }


def check_single_payment_status(
    payment
):

    previous_status = normalize_status(
        payment.payment_status
    )

    transaction_unique_id = (
        payment.unique_id
    )

    if not transaction_unique_id:

        create_scheduler_log(
            payment=payment,
            action=ACTION_STATUS,
            scheduler_status="FAILED",
            previous_status=previous_status,
            success=False,
            error_message=(
                "Transaction Unique ID is missing."
            ),
        )

        return {
            "success": False,
            "message": (
                "Transaction Unique ID is missing."
            ),
        }

    if not payment.debit_account:

        create_scheduler_log(
            payment=payment,
            action=ACTION_STATUS,
            scheduler_status="FAILED",
            previous_status=previous_status,
            success=False,
            error_message=(
                "Debit Account is missing."
            ),
        )

        return {
            "success": False,
            "message": (
                "Debit Account is missing."
            ),
        }

    if not payment.bank_transaction_id:

        create_scheduler_log(
            payment=payment,
            action=ACTION_STATUS,
            scheduler_status="SKIPPED",
            previous_status=previous_status,
            new_status=previous_status,
            success=True,
            error_message=(
                "Bank transaction ID is missing. "
                "Payment will be handled by initiation."
            ),
        )

        return {
            "success": True,
            "message": (
                "Skipped because bank transaction "
                "ID is missing."
            ),
        }

    create_scheduler_log(
        payment=payment,
        action=ACTION_STATUS,
        scheduler_status="STARTED",
        previous_status=previous_status,
        bank_transaction_id=(
            payment.bank_transaction_id
        ),
        success=None,
    )

    try:

        result = get_payment_status(
            transaction_unique_id=(
                transaction_unique_id
            ),
            debit_account=(
                payment.debit_account
            ),
        )

    except Exception as exc:

        error_message = str(exc)

        create_scheduler_log(
            payment=payment,
            action=ACTION_STATUS,
            scheduler_status="FAILED",
            previous_status=previous_status,
            bank_transaction_id=(
                payment.bank_transaction_id
            ),
            success=False,
            error_message=error_message,
        )

        frappe.log_error(
            title=(
                "Payment Status Scheduler Failed"
            ),
            message=frappe.get_traceback(),
        )

        return {
            "success": False,
            "message": error_message,
        }

    response_code = get_response_code(
        result
    )

    response_message = (
        get_response_message(
            result
        )
    )

    processing_time_ms = (
        get_processing_time(
            result
        )
    )

    bank_status = (
        get_payment_status_from_result(
            result
        )
    )

    bank_transaction_id = (
        get_bank_transaction_id(
            result
        )
        or payment.bank_transaction_id
    )

    bank_status = normalize_status(
        bank_status
    )

    if not result.get("success"):

        if bank_status in {
            "COMPLETED",
            "FAILED",
            "REJECTED",
        }:

            final_status = bank_status

        else:

            final_status = previous_status

        update_payment_transaction(
            payment=payment,
            payment_status=final_status,
            bank_transaction_id=(
                bank_transaction_id
            ),
            response_code=response_code,
            response_message=response_message,
        )

        create_scheduler_log(
            payment=payment,
            action=ACTION_STATUS,
            scheduler_status="FAILED",
            previous_status=previous_status,
            new_status=final_status,
            bank_transaction_id=(
                bank_transaction_id
            ),
            response_code=response_code,
            response_message=response_message,
            processing_time_ms=(
                processing_time_ms
            ),
            success=False,
            error_message=(
                response_message
                or (
                    "Payment status enquiry failed."
                )
            ),
        )

        return {
            "success": False,
            "payment_status": final_status,
            "response_code": response_code,
            "response_message": (
                response_message
            ),
        }

    if not bank_status:

        create_scheduler_log(
            payment=payment,
            action=ACTION_STATUS,
            scheduler_status="FAILED",
            previous_status=previous_status,
            new_status=previous_status,
            bank_transaction_id=(
                payment.bank_transaction_id
            ),
            response_code=response_code,
            response_message=response_message,
            processing_time_ms=(
                processing_time_ms
            ),
            success=False,
            error_message=(
                "Bank did not return payment_status."
            ),
        )

        return {
            "success": False,
            "message": (
                "Bank did not return payment_status."
            ),
        }

    update_payment_transaction(
        payment=payment,
        payment_status=bank_status,
        bank_transaction_id=(
            bank_transaction_id
        ),
        response_code=response_code,
        response_message=response_message,
    )

    payment = frappe.get_doc(
        "Payment Transaction",
        payment.name,
    )

    create_scheduler_log(
        payment=payment,
        action=ACTION_STATUS,
        scheduler_status="SUCCESS",
        previous_status=previous_status,
        new_status=bank_status,
        bank_transaction_id=(
            payment.bank_transaction_id
        ),
        response_code=response_code,
        response_message=response_message,
        processing_time_ms=(
            processing_time_ms
        ),
        success=True,
    )

    return {
        "success": True,
        "transaction_unique_id": (
            payment.unique_id
        ),
        "previous_status": previous_status,
        "payment_status": bank_status,
        "bank_transaction_id": (
            payment.bank_transaction_id
        ),
        "response_code": response_code,
        "response_message": response_message,
    }


def sync_single_payment_transaction(
    payment_data
):

    payment_name = (
        payment_data.name
    )

    payment = lock_payment_transaction(
        payment_name
    )

    if not payment:

        return {
            "success": False,
            "message": (
                "Payment Transaction no longer exists."
            ),
        }

    try:

        current_status = normalize_status(
            payment.payment_status
        )

        if current_status in TERMINAL_STATUSES:

            frappe.db.commit()

            return {
                "success": True,
                "transaction_unique_id": (
                    payment.unique_id
                ),
                "payment_status": current_status,
                "message": (
                    "Payment is already in "
                    "a terminal status."
                ),
            }

        if current_status == "OTP_PENDING":

            frappe.db.commit()

            return {
                "success": True,
                "transaction_unique_id": (
                    payment.unique_id
                ),
                "payment_status": current_status,
                "message": (
                    "Waiting for OTP verification."
                ),
            }

        if should_initiate_payment(
            payment
        ):

            result = initiate_single_payment(
                payment
            )

            frappe.db.commit()

            return result

        if should_check_payment_status(
            payment
        ):

            result = check_single_payment_status(
                payment
            )

            frappe.db.commit()

            return result

        frappe.db.commit()

        return {
            "success": True,
            "transaction_unique_id": (
                payment.unique_id
            ),
            "payment_status": current_status,
            "message": (
                "Payment does not currently require "
                "scheduler processing."
            ),
        }

    except Exception:

        frappe.db.rollback()

        frappe.log_error(
            title=(
                "Payment Transaction "
                "Scheduler Processing Failed"
            ),
            message=frappe.get_traceback(),
        )

        return {
            "success": False,
            "message": (
                "Payment scheduler processing failed."
            ),
        }


def sync_pending_payment_transactions():

    payments = frappe.get_all(
        "Payment Transaction",

        filters={
            "payment_status": [
                "in",
                [
                    "OTP_PENDING",
                    "PENDING",
                    "PROCESSING",
                ],
            ],
        },

        fields=[
            "name",
            "unique_id",
            "purchase_invoice",
            "debit_account",
            "beneficiary_account",
            "amount",
            "mode_of_payment",
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

            frappe.db.rollback()

            frappe.log_error(
                title=(
                    "Payment Transaction "
                    "Scheduler Failed"
                ),
                message=(
                    frappe.get_traceback()
                ),
            )


def run_payment_scheduler():

    return sync_pending_payment_transactions()