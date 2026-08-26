import json
import random
import frappe

from datetime import timedelta
from frappe.utils import now_datetime

def get_integration_headers():
    api_key = frappe.conf.get(
        "payment_integration_api_key"
    )

    api_secret = frappe.conf.get(
        "payment_integration_api_secret"
    )

    if not api_key:
        frappe.throw(
            "Payment Integration API Key is not configured"
        )

    if not api_secret:
        frappe.throw(
            "Payment Integration API Secret is not configured"
        )

    return {
        "Authorization":
            f"token {api_key}:{api_secret}",

        "Content-Type":
            "application/json",

        "Accept":
            "application/json",
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
            "http_status":
                response.status_code,
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
                "doctype":
                    "Payment API Log",

                "timestamp":
                    frappe.utils.now(),

                "api_name":
                    api_name,

                "transaction_unique_id":
                    transaction_unique_id,

                "purchase_invoice":
                    purchase_invoice,

                "request_method":
                    request_method,

                "http_status":
                    http_status,

                "status":
                    status,

                "response_code":
                    response_code,

                "error_message":
                    error_message,

                "request_payload":
                    (
                        json.dumps(
                            request_payload,
                            default=str,
                        )
                        if request_payload is not None
                        else None
                    ),

                "response_payload":
                    (
                        json.dumps(
                            response_payload,
                            default=str,
                        )
                        if response_payload is not None
                        else None
                    ),
            }
        )

        log.insert(
            ignore_permissions=True
        )

        frappe.db.commit()

    except Exception:

        frappe.log_error(
            title=
                "Payment API Log Creation Failed",

            message=
                frappe.get_traceback(),
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
            "account_number":
                bank_account_number,

            "enabled":
                1,
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
        invoice.get("payment_transactions")
        or []
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
        invoice.get("payment_transactions")
        or []
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
            "payment_initiated_on":
                frappe.utils.now(),

            "amount":
                amount,

            "payment_status":
                "OTP Pending",

            "transaction_unique_id":
                transaction_unique_id,

            "bank_payment_mode":
                bank_payment_mode,

            "otp_verification_status":
                "OTP Pending",

            "response_code":
                response_code,

            "otp_request_id":
                otp_request_id,

            "from_bank":
                from_bank,

            "to_bank":
                to_bank,
        },
    )

    invoice.save(
        ignore_permissions=True
    )

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

        invoice.save(
            ignore_permissions=True
        )

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

        frappe.throw(
            "Amount is required"
        )

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

    beneficiary_account_name = (
        beneficiary_account
    )

    existing_payment_name = frappe.db.get_value(
        "Payment Transaction",
        {
            "unique_id":
                transaction_unique_id,
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
                "transaction_unique_id":
                    transaction_unique_id,
            },
            "name",
        )

        return {

            "success":
                True,

            "transaction_unique_id":
                transaction_unique_id,

            "purchase_invoice":
                purchase_invoice,

            "payment_transaction":
                payment.name,

            "otp_request_id":
                existing_otp_name,

            "payment_status":
                payment.payment_status,

            "debit_account":
                debit_account,

            "debit_account_configuration":
                debit_account_name,

            "beneficiary_account":
                beneficiary_account,

            "beneficiary_account_configuration":
                beneficiary_account_name,

            "message":
                "Payment transaction already exists.",
        }

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
            "doctype":
                "Payment Transaction",

            "unique_id":
                transaction_unique_id,

            "purchase_invoice":
                purchase_invoice,

            # Link field gets the configuration NAME
            "debit_account":
                debit_account_name,

            # Beneficiary is the actual account number
            "beneficiary_account":
                beneficiary_account_name,

            "amount":
                amount,

            "mode_of_payment":
                mode_of_payment,

            "payment_status":
                "OTP_PENDING",
        }
    )

    payment.insert(
        ignore_permissions=True
    )

    otp_doc = frappe.get_doc(
        {
            "doctype":
                "Payment OTP",

            "transaction_unique_id":
                transaction_unique_id,

            "purchase_invoice":
                purchase_invoice,

            "payment_transaction":
                payment.name,

            "phone_number":
                debit_bank.phone_number,

            "otp":
                otp,

            "generated_on":
                generated_on,

            "expires_on":
                expires_on,

            "verification_status":
                "Pending",

            "attempt_count":
                0,
        }
    )

    otp_doc.insert(
        ignore_permissions=True
    )

    frappe.db.commit()

    return {

        "success":
            True,

        "transaction_unique_id":
            transaction_unique_id,

        "purchase_invoice":
            purchase_invoice,

        "payment_transaction":
            payment.name,

        "otp_request_id":
            otp_doc.name,

        "expires_on":
            expires_on,

        "payment_status":
            "OTP_PENDING",

        "debit_account":
            debit_account,

        "debit_account_configuration":
            debit_account_name,

        "beneficiary_account":
            beneficiary_account,

        "beneficiary_account_configuration":
            beneficiary_account_name,

        "message":
            "OTP generated successfully.",
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

        frappe.throw(
            "OTP is required"
        )

    otp_name = frappe.db.get_value(
        "Payment OTP",
        {
            "transaction_unique_id":
                transaction_unique_id,
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
            "unique_id":
                transaction_unique_id,
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

            "success":
                True,

            "verified":
                True,

            "transaction_unique_id":
                transaction_unique_id,

            "payment_transaction":
                payment.name,

            "payment_status":
                payment.payment_status,

            "bank_transaction_id":
                payment.bank_transaction_id,

            "response_code":
                payment.response_code,

            "message":
                "OTP has already been verified. "
                "Payment is pending for bank processing.",
        }

    if (
        otp_doc.attempt_count or 0
    ) >= 3:

        otp_doc.verification_status = "Failed"

        otp_doc.save(
            ignore_permissions=True
        )

        frappe.db.commit()

        update_payment_status(
            payment,
            payment_status="FAILED",
            response_message=
                "Maximum OTP attempts exceeded.",
        )

        frappe.throw(
            "Maximum OTP attempts exceeded"
        )

    if (
        otp_doc.expires_on
        and now_datetime()
        > otp_doc.expires_on
    ):

        otp_doc.verification_status = "Expired"

        otp_doc.save(
            ignore_permissions=True
        )

        frappe.db.commit()

        update_payment_status(
            payment,
            payment_status="FAILED",
            response_message=
                "OTP has expired.",
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
            response_message=
                "Invalid OTP.",
        )

        return {

            "success":
                False,

            "verified":
                False,

            "transaction_unique_id":
                transaction_unique_id,

            "payment_transaction":
                payment.name,

            "payment_status":
                "OTP_PENDING",

            "message":
                "Invalid OTP.",

            "attempt_count":
                otp_doc.attempt_count,
        }

    otp_doc.verification_status = "Verified"

    otp_doc.save(
        ignore_permissions=True
    )

    frappe.db.commit()

    update_payment_status(
        payment,
        payment_status="PENDING",
        response_message=
            "OTP verified successfully. "
            "Payment is pending for bank processing.",
    )

    return {

        "success":
            True,

        "verified":
            True,

        "transaction_unique_id":
            transaction_unique_id,

        "payment_transaction":
            payment.name,

        "payment_status":
            "PENDING",

        "bank_transaction_id":
            payment.bank_transaction_id,

        "response_code":
            payment.response_code,

        "response_message":
            "OTP verified successfully. "
            "Payment is pending for bank processing.",

        "message":
            "OTP verified. Payment has been queued "
            "for bank processing.",
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


@frappe.whitelist()
def generate_bulk_otp(
    bulk_request_id,
    transactions,
):
    """
    Generate ONE OTP for ONE Bulk Payment.

    IMPORTANT:
    - Every transaction keeps its own transaction_unique_id.
    - Every transaction still gets its own Payment Transaction.
    - ONLY ONE Bulk Payment OTP document is created.
    - Existing Payment OTP workflow is NOT touched.
    - Normal single-payment OTP workflow is NOT touched.
    """

    if not bulk_request_id:

        frappe.throw(
            "Bulk Request ID is required."
        )

    # -----------------------------------------------------
    # PARSE TRANSACTIONS
    # -----------------------------------------------------

    if isinstance(
        transactions,
        str,
    ):

        transactions = frappe.parse_json(
            transactions
        )

    if not isinstance(
        transactions,
        list
    ) or not transactions:

        frappe.throw(
            "At least one transaction is required."
        )

    # -----------------------------------------------------
    # CHECK WHETHER THIS BULK PAYMENT ALREADY HAS
    # A BULK OTP
    #
    # This prevents Generate OTP from generating
    # another OTP for the same Bulk Request ID.
    # -----------------------------------------------------

    existing_bulk_otp = frappe.db.get_value(
        "Bulk Payment OTP",
        {
            "bulk_request_id":
                bulk_request_id,
        },
        [
            "name",
            "otp",
            "status",
            "generated_on",
            "expires_on",
            "attempt_count",
            "transactions_json",
        ],
        as_dict=True,
    )

    if existing_bulk_otp:

        # -------------------------------------------------
        # If OTP is still pending, return the same OTP
        # request information.
        #
        # We DO NOT generate another OTP.
        # -------------------------------------------------

        stored_transactions = []

        if existing_bulk_otp.transactions_json:

            try:

                stored_transactions = (
                    frappe.parse_json(
                        existing_bulk_otp.transactions_json
                    )
                )

            except Exception:

                stored_transactions = []

        return {

            "success":
                True,

            "bulk_request_id":
                bulk_request_id,

            "otp_request_id":
                existing_bulk_otp.name,

            "expires_on":
                existing_bulk_otp.expires_on,

            "status":
                existing_bulk_otp.status,

            "transactions":
                stored_transactions,

            "message":
                (
                    "Bulk payment OTP already exists. "
                    "No new OTP was generated."
                ),
        }

    # -----------------------------------------------------
    # GENERATE ONE OTP
    # -----------------------------------------------------

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

    created_transactions = []

    try:

        # =================================================
        # CREATE PAYMENT TRANSACTIONS
        #
        # One Payment Transaction per invoice.
        #
        # NO Payment OTP is created here.
        # =================================================

        for item in transactions:

            transaction_unique_id = item.get(
                "transaction_unique_id"
            )

            purchase_invoice = item.get(
                "purchase_invoice"
            )

            debit_account = item.get(
                "debit_account"
            )

            beneficiary_account = item.get(
                "beneficiary_account"
            )

            amount = item.get(
                "amount"
            )

            mode_of_payment = item.get(
                "mode_of_payment"
            )

            # ---------------------------------------------
            # VALIDATION
            # ---------------------------------------------

            if not transaction_unique_id:

                frappe.throw(
                    "Transaction Unique ID is required."
                )

            if not purchase_invoice:

                frappe.throw(
                    "Purchase Invoice is required."
                )

            if not debit_account:

                frappe.throw(
                    "Debit Account is required."
                )

            if not beneficiary_account:

                frappe.throw(
                    "Beneficiary Account is required."
                )

            if amount is None:

                frappe.throw(
                    "Amount is required."
                )

            try:

                amount = float(
                    amount
                )

            except (
                TypeError,
                ValueError,
            ):

                frappe.throw(
                    "Amount must be a valid number."
                )

            if amount <= 0:

                frappe.throw(
                    "Amount must be greater than zero."
                )

            if not mode_of_payment:

                frappe.throw(
                    "Mode of Payment is required."
                )

            # ---------------------------------------------
            # PREVENT DUPLICATE TRANSACTION
            # ---------------------------------------------

            existing_payment = frappe.db.get_value(
                "Payment Transaction",
                {
                    "unique_id":
                        transaction_unique_id,
                },
                "name",
            )

            if existing_payment:

                frappe.throw(
                    "Payment Transaction already exists "
                    "for "
                    f"{transaction_unique_id}."
                )

            # ---------------------------------------------
            # GET DEBIT BANK
            # ---------------------------------------------

            debit_bank = get_bank_account(
                debit_account,
                "Debit",
            )

            if not debit_bank.enabled:

                frappe.throw(
                    f"Debit account {debit_account} "
                    "is disabled."
                )

            # -------------------------------------------------
            # Payment Transaction.debit_account is a Link.
            # Use the Bank Account document name.
            # -------------------------------------------------

            debit_account_configuration = (
                debit_bank.name
            )

            # ---------------------------------------------
            # CREATE PAYMENT TRANSACTION
            #
            # IMPORTANT:
            # It remains OTP_PENDING until the ONE bulk
            # OTP is successfully verified.
            # ---------------------------------------------

            payment = frappe.get_doc(
                {
                    "doctype":
                        "Payment Transaction",

                    "unique_id":
                        transaction_unique_id,

                    "purchase_invoice":
                        purchase_invoice,

                    "debit_account":
                        debit_account_configuration,

                    "beneficiary_account":
                        beneficiary_account,

                    "amount":
                        amount,

                    "mode_of_payment":
                        mode_of_payment,

                    "payment_status":
                        "OTP_PENDING",
                }
            )

            payment.insert(
                ignore_permissions=True
            )

            # ---------------------------------------------
            # STORE TRANSACTION INFORMATION
            #
            # This goes into ONE Bulk Payment OTP record.
            # ---------------------------------------------

            created_transactions.append(
                {
                    "transaction_unique_id":
                        transaction_unique_id,

                    "purchase_invoice":
                        purchase_invoice,

                    "payment_transaction":
                        payment.name,

                    "payment_status":
                        "OTP_PENDING",

                    "response_code":
                        None,
                }
            )

        # =================================================
        # CREATE ONLY ONE BULK PAYMENT OTP DOCUMENT
        # =================================================

        bulk_otp_doc = frappe.get_doc(
            {
                "doctype":
                    "Bulk Payment OTP",

                "bulk_request_id":
                    bulk_request_id,

                "otp":
                    otp,

                "status":
                    "Pending",

                "generated_on":
                    generated_on,

                "expires_on":
                    expires_on,

                "attempt_count":
                    0,

                "transactions_json":
                    frappe.as_json(
                        created_transactions
                    ),
            }
        )

        bulk_otp_doc.insert(
            ignore_permissions=True
        )

        frappe.db.commit()

    except Exception:

        frappe.db.rollback()

        raise

    # =====================================================
    # RETURN
    # =====================================================

    return {

        "success":
            True,

        "bulk_request_id":
            bulk_request_id,

        "otp_request_id":
            bulk_otp_doc.name,

        "expires_on":
            expires_on,

        "transactions":
            created_transactions,

        "message":
            (
                "One OTP generated successfully for "
                "the complete Bulk Payment containing "
                f"{len(created_transactions)} transaction(s)."
            ),
    }

@frappe.whitelist()
def validate_bulk_otp(
    bulk_request_id,
    otp,
):
    """
    Verify ONE OTP for ONE Bulk Payment.

    The OTP belongs to Bulk Payment OTP.

    After successful verification:
        every Payment Transaction stored in
        transactions_json is changed from
        OTP_PENDING -> PENDING.

    Existing Payment OTP records are NOT used.
    Existing single-payment OTP workflow is NOT touched.
    """

    if not bulk_request_id:

        frappe.throw(
            "Bulk Request ID is required."
        )

    if not otp:

        frappe.throw(
            "OTP is required."
        )

    # =====================================================
    # FIND THE ONE BULK OTP
    # =====================================================

    bulk_otp = frappe.db.get_value(
        "Bulk Payment OTP",
        {
            "bulk_request_id":
                bulk_request_id,
        },
        [
            "name",
            "bulk_request_id",
            "otp",
            "status",
            "generated_on",
            "expires_on",
            "attempt_count",
            "transactions_json",
        ],
        as_dict=True,
    )

    if not bulk_otp:

        frappe.throw(
            "Bulk OTP request not found."
        )

    # =====================================================
    # ALREADY VERIFIED
    # =====================================================

    if (
        bulk_otp.status
        == "Verified"
    ):

        stored_transactions = []

        if bulk_otp.transactions_json:

            try:

                stored_transactions = (
                    frappe.parse_json(
                        bulk_otp.transactions_json
                    )
                )

            except Exception:

                stored_transactions = []

        result_transactions = []

        for transaction in stored_transactions:

            payment_name = transaction.get("payment_transaction")
    

            if not payment_name:

                continue

            payment = frappe.get_doc(
                "Payment Transaction",
                payment_name,
            )

            result_transactions.append(
                {
                    "transaction_unique_id":
                        payment.unique_id,

                    "purchase_invoice":
                        payment.purchase_invoice,

                    "payment_transaction":
                        payment.name,

                    "payment_status":
                        payment.payment_status,

                    "bank_transaction_id":
                        payment.bank_transaction_id,

                    "response_code":
                        payment.response_code,
                }
            )

        return {

            "success":
                True,

            "verified":
                True,

            "bulk_request_id":
                bulk_request_id,

            "otp_request_id":
                bulk_otp.name,

            "transactions":
                result_transactions,

            "message":
                "Bulk OTP has already been verified.",
        }

    # =====================================================
    # EXPIRED
    # =====================================================

    current_time = now_datetime()

    if (
        bulk_otp.expires_on
        and current_time
        > bulk_otp.expires_on
    ):

        frappe.db.set_value(
            "Bulk Payment OTP",
            bulk_otp.name,
            "status",
            "Expired",
            update_modified=True,
        )

        # ---------------------------------------------
        # Mark every transaction in this bulk as FAILED
        # ---------------------------------------------

        stored_transactions = []

        if bulk_otp.transactions_json:

            try:

                stored_transactions = (
                    frappe.parse_json(
                        bulk_otp.transactions_json
                    )
                )

            except Exception:

                stored_transactions = []

        for transaction in stored_transactions:

            payment_name = transaction.get(
                "payment_transaction"
            )

            if not payment_name:

                continue

            frappe.db.set_value(
                "Payment Transaction",
                payment_name,
                {
                    "payment_status":
                        "FAILED",

                    "response_message":
                        "Bulk OTP has expired.",
                },
                update_modified=True,
            )

        frappe.db.commit()

        frappe.throw(
            "OTP has expired."
        )

    # =====================================================
    # MAXIMUM ATTEMPTS
    # =====================================================

    attempt_count = (
        bulk_otp.attempt_count or 0
    )

    if attempt_count >= 3:

        frappe.db.set_value(
            "Bulk Payment OTP",
            bulk_otp.name,
            "status",
            "Failed",
            update_modified=True,
        )

        stored_transactions = []

        if bulk_otp.transactions_json:

            try:

                stored_transactions = (
                    frappe.parse_json(
                        bulk_otp.transactions_json
                    )
                )

            except Exception:

                stored_transactions = []

        for transaction in stored_transactions:

            payment_name = transaction.get(
                "payment_transaction"
            )

            if not payment_name:

                continue

            frappe.db.set_value(
                "Payment Transaction",
                payment_name,
                {
                    "payment_status":
                        "FAILED",

                    "response_message":
                        "Maximum OTP attempts exceeded.",
                },
                update_modified=True,
            )

        frappe.db.commit()

        frappe.throw(
            "Maximum OTP attempts exceeded."
        )

    # =====================================================
    # INCREMENT ATTEMPT
    # =====================================================

    new_attempt_count = (
        attempt_count + 1
    )

    frappe.db.set_value(
        "Bulk Payment OTP",
        bulk_otp.name,
        "attempt_count",
        new_attempt_count,
        update_modified=True,
    )

    # =====================================================
    # INVALID OTP
    # =====================================================

    if str(
        bulk_otp.otp
    ) != str(
        otp
    ):

        frappe.db.commit()

        return {

            "success":
                False,

            "verified":
                False,

            "bulk_request_id":
                bulk_request_id,

            "otp_request_id":
                bulk_otp.name,

            "message":
                "Invalid OTP.",

            "attempt_count":
                new_attempt_count,
        }

    # =====================================================
    # OTP IS VALID
    # =====================================================

    stored_transactions = []

    if bulk_otp.transactions_json:

        try:

            stored_transactions = (
                frappe.parse_json(
                    bulk_otp.transactions_json
                )
            )

        except Exception:

            frappe.throw(
                "Unable to read Bulk Payment transaction details."
            )

    if not stored_transactions:

        frappe.throw(
            "No transactions are associated with this Bulk Payment OTP."
        )

    result_transactions = []

    # =====================================================
    # UPDATE ALL TRANSACTIONS
    #
    # OTP_PENDING -> PENDING
    #
    # ONE OTP VERIFICATION UPDATES EVERY TRANSACTION.
    # =====================================================

    for transaction in stored_transactions:

        payment_name = transaction.get(
            "payment_transaction"
        )

        transaction_unique_id = transaction.get(
            "transaction_unique_id"
        )

        if not payment_name:

            continue

        payment = frappe.get_doc(
            "Payment Transaction",
            payment_name,
        )

        # -------------------------------------------------
        # Keep the individual transaction unique ID.
        # -------------------------------------------------

        if (
            transaction_unique_id
            and payment.unique_id
            != transaction_unique_id
        ):

            frappe.throw(
                "Transaction mismatch detected for "
                f"{transaction_unique_id}."
            )

        # -------------------------------------------------
        # ONLY CHANGE STATUS.
        #
        # Existing transaction workflow continues from
        # PENDING exactly as before.
        # -------------------------------------------------

        payment.payment_status = (
            "PENDING"
        )

        payment.response_message = (
            "Bulk OTP verified successfully. "
            "Payment is pending for bank processing."
        )

        payment.save(
            ignore_permissions=True
        )

        result_transactions.append(
            {
                "transaction_unique_id":
                    payment.unique_id,

                "purchase_invoice":
                    payment.purchase_invoice,

                "payment_transaction":
                    payment.name,

                "payment_status":
                    payment.payment_status,

                "bank_transaction_id":
                    payment.bank_transaction_id,

                "response_code":
                    payment.response_code,
            }
        )

    # =====================================================
    # MARK THE SINGLE BULK OTP AS VERIFIED
    # =====================================================

    frappe.db.set_value(
        "Bulk Payment OTP",
        bulk_otp.name,
        {
            "status":
                "Verified",

            "attempt_count":
                new_attempt_count,
        },
        update_modified=True,
    )

    frappe.db.commit()

    # =====================================================
    # RESPONSE
    # =====================================================

    return {

        "success":
            True,

        "verified":
            True,

        "bulk_request_id":
            bulk_request_id,

        "otp_request_id":
            bulk_otp.name,

        "transactions":
            result_transactions,

        "message":
            (
                "One OTP verified successfully. "
                f"{len(result_transactions)} transaction(s) "
                "are now pending for normal bank processing."
            ),
    }