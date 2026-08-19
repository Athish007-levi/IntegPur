import time

import frappe
import requests


SUPPORTED_PAYMENT_MODES = {
    "NEFT",
    "RTGS",
    "IMPS",
    "UPI",
}

SUPPORTED_PAYMENT_STATUSES = {
    "COMPLETED",
    "PENDING",
    "FAILED",
}

def get_bank_account(bank_account):

    if not bank_account:
        frappe.throw("Debit bank account is required")

    account = frappe.get_doc(
        "Bank Account Configuration",
        bank_account,
    )

    if not account.enabled:
        frappe.throw(
            f"Bank Account Configuration {account.name} is disabled"
        )

    if not account.account_number:
        frappe.throw(
            "Account Number is not configured for bank account "
            f"{account.name}"
        )

    if not account.api_user:
        frappe.throw(
            "API User is not configured for bank account "
            f"{account.name}"
        )

    # Password fields must be retrieved through Frappe's password API.
    api_key = account.get_password("api_key")
    api_secret = account.get_password("api_secret")

    if not api_key:
        frappe.throw(
            "API Key is not configured for bank account "
            f"{account.name}"
        )

    if not api_secret:
        frappe.throw(
            "API Secret is not configured for bank account "
            f"{account.name}"
        )

    if not account.payment_initiation_url:
        frappe.throw(
            "Payment Initiation URL is not configured for bank account "
            f"{account.name}"
        )

    if not account.payment_status_url:
        frappe.throw(
            "Payment Status URL is not configured for bank account "
            f"{account.name}"
        )

    return {
        "doc": account,
        "name": account.name,
        "account_name": account.account_name,
        "account_number": account.account_number,
        "api_user": account.api_user,
        "api_key": api_key,
        "api_secret": api_secret,
        "payment_initiation_url": account.payment_initiation_url,
        "payment_status_url": account.payment_status_url,
    }

def get_headers(account):

    return {
        "Authorization": (
            f"token {account['api_key']}:{account['api_secret']}"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def parse_response(response):

    try:
        return response.json()

    except ValueError:
        return {
            "success": False,
            "response_code": str(response.status_code),
            "response_message": response.text,
            "payment_status": "ERROR",
            "transaction_id": None,
            "response_timestamp": None,
        }


def get_message(result):


    if not isinstance(result, dict):
        return None

    message = result.get("message")

    if isinstance(message, dict):
        return (
            message.get("response_message")
            or message.get("message")
            or message.get("error_message")
            or message.get("error")
        )

    if isinstance(message, str):
        return message

    return (
        result.get("response_message")
        or result.get("message")
        or result.get("error_message")
        or result.get("error")
        or result.get("exception")
    )


def get_value(result, key):

    if not isinstance(result, dict):
        return None

    message = result.get("message")

    if isinstance(message, dict):
        if key in message:
            return message.get(key)

    return result.get(key)


def build_result(
    response,
    result,
    processing_time_ms,
    request_payload,
):
    

    payment_status = get_value(
        result,
        "payment_status",
    )

    payment_status = (
        str(payment_status).upper()
        if payment_status
        else None
    )

  
    api_success = response.status_code in {
        200,
        202,
    }

    return {
        "success": api_success,
        "http_status": response.status_code,
        "processing_time_ms": processing_time_ms,
        "request_payload": request_payload,
        "response": result,

        "request_id": get_value(
            result,
            "request_id",
        ),

        "response_code": get_value(
            result,
            "response_code",
        ),

        "response_message": get_message(
            result
        ),

        "transaction_id": (
            get_value(result, "transaction_id")
            or get_value(
                result,
                "bank_transaction_id",
            )
        ),

        "payment_status": payment_status,

        "debit_account_number": get_value(
            result,
            "debit_account_number",
        ),

        "beneficiary_account_number": get_value(
            result,
            "beneficiary_account_number",
        ),

        "mode_of_payment": get_value(
            result,
            "mode_of_payment",
        ),

        "amount": get_value(
            result,
            "amount",
        ),

        "currency": get_value(
            result,
            "currency",
        ),

        "available_balance": get_value(
            result,
            "available_balance",
        ),

        "processed_at": get_value(
            result,
            "processed_at",
        ),

        "response_timestamp": get_value(
            result,
            "response_timestamp",
        ),
    }

def normalize_payment_mode(mode_of_payment):


    if not mode_of_payment:
        frappe.throw("Mode of Payment is required")

    original_mode = str(
        mode_of_payment
    ).strip()

    normalized_mode = original_mode.upper()

    # Common ERPNext labels.
    aliases = {
        "BANK TRANSFER": "NEFT",
        "BANK": "NEFT",
        "BANK TRANSFER - NEFT": "NEFT",
        "BANK TRANSFER (NEFT)": "NEFT",
        "NEFT TRANSFER": "NEFT",
    }

    normalized_mode = aliases.get(
        normalized_mode,
        normalized_mode,
    )

    if normalized_mode not in SUPPORTED_PAYMENT_MODES:
        frappe.throw(
            "Unsupported Mock Bank payment mode: "
            f"{original_mode}. Supported modes are: "
            f"{', '.join(sorted(SUPPORTED_PAYMENT_MODES))}"
        )

    return normalized_mode

def normalize_payment_status(payment_status):

    if not payment_status:
        payment_status = "COMPLETED"

    normalized_status = str(
        payment_status
    ).strip().upper()

    if normalized_status not in SUPPORTED_PAYMENT_STATUSES:
        frappe.throw(
            "Unsupported Mock Bank payment status: "
            f"{payment_status}. Supported statuses are: "
            f"{', '.join(sorted(SUPPORTED_PAYMENT_STATUSES))}"
        )

    return normalized_status

def initiate_payment(
    transaction_unique_id,
    purchase_invoice,
    debit_account,
    beneficiary_account,
    amount,
    mode_of_payment,
    payment_status="COMPLETED",
):
    

    if not transaction_unique_id:
        frappe.throw(
            "Transaction Unique ID is required"
        )


    if not purchase_invoice:
        frappe.throw(
            "Purchase Invoice is required"
        )

    if not beneficiary_account:
        frappe.throw(
            "Beneficiary account is required"
        )

    if not amount:
        frappe.throw(
            "Payment amount is required"
        )

    try:
        amount = float(amount)

    except (TypeError, ValueError):
        frappe.throw(
            "Payment amount must be a valid number"
        )

    if amount <= 0:
        frappe.throw(
            "Payment amount must be greater than zero"
        )

    normalized_mode = normalize_payment_mode(
        mode_of_payment
    )

    normalized_status = normalize_payment_status(
        payment_status
    )

    account = get_bank_account(
        debit_account
    )

    payload = {
        "unique_id": transaction_unique_id,
        "account_number": str(
            beneficiary_account
        ),
        "payment_status": normalized_status,
        "mode_of_payment": normalized_mode,
        "amount": amount,
    }

    started_at = time.perf_counter()

    try:
        response = requests.post(
            account["payment_initiation_url"],
            json=payload,
            headers=get_headers(account),
            timeout=30,
        )

        processing_time_ms = (
            time.perf_counter() - started_at
        ) * 1000

        result = parse_response(
            response
        )

        return build_result(
            response=response,
            result=result,
            processing_time_ms=processing_time_ms,
            request_payload=payload,
        )

    except requests.RequestException as exc:
        processing_time_ms = (
            time.perf_counter() - started_at
        ) * 1000

        return {
            "success": False,
            "http_status": None,
            "processing_time_ms": processing_time_ms,
            "request_payload": payload,
            "response": None,
            "request_id": None,
            "response_code": None,
            "response_message": str(exc),
            "transaction_id": None,
            "payment_status": None,
            "debit_account_number": None,
            "beneficiary_account_number": str(
                beneficiary_account
            ),
            "mode_of_payment": normalized_mode,
            "amount": amount,
            "currency": None,
            "available_balance": None,
            "processed_at": None,
            "response_timestamp": None,
        }

def get_payment_status(
    transaction_unique_id,
    debit_account,
):


    if not transaction_unique_id:
        frappe.throw(
            "Transaction Unique ID is required"
        )

    account = get_bank_account(
        debit_account
    )


    payload = {
        "unique_id": transaction_unique_id,
    }

    started_at = time.perf_counter()

    try:
        response = requests.post(
            account["payment_status_url"],
            json=payload,
            headers=get_headers(account),
            timeout=30,
        )

        processing_time_ms = (
            time.perf_counter() - started_at
        ) * 1000

        result = parse_response(
            response
        )

        return build_result(
            response=response,
            result=result,
            processing_time_ms=processing_time_ms,
            request_payload=payload,
        )

    except requests.RequestException as exc:
        processing_time_ms = (
            time.perf_counter() - started_at
        ) * 1000

        return {
            "success": False,
            "http_status": None,
            "processing_time_ms": processing_time_ms,
            "request_payload": payload,
            "response": None,
            "request_id": None,
            "response_code": None,
            "response_message": str(exc),
            "transaction_id": None,
            "payment_status": None,
            "debit_account_number": None,
            "beneficiary_account_number": None,
            "mode_of_payment": None,
            "amount": None,
            "currency": None,
            "available_balance": None,
            "processed_at": None,
            "response_timestamp": None,
        }
