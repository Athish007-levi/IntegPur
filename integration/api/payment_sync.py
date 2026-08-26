import frappe


@frappe.whitelist()
def get_payment_transactions():

    # ========================================================
    # PAYMENT TRANSACTIONS
    # ========================================================

    payments = frappe.get_all(
        "Payment Transaction",
        filters={
            "payment_status": [
                "in",
                [
                    "OTP_PENDING",
                    "PENDING",
                    "PROCESSING",
                    "COMPLETED",
                    "FAILED",
                    "REJECTED",
                ],
            ],
        },
        fields=[
            "name",
            "unique_id",
            "purchase_invoice",
            "payment_status",
            "bank_transaction_id",
            "response_code",
            "response_message",
            "modified",
        ],
        order_by="modified desc",
        limit_page_length=100,
    )

    data = []

    # ========================================================
    # PROCESS EACH PAYMENT TRANSACTION
    # ========================================================

    for payment in payments:

        transaction_unique_id = (
            payment.unique_id
        )

        # ----------------------------------------------------
        # OTP LOOKUP
        #
        # IMPORTANT:
        #
        # OTP status is NOT derived from Payment Transaction
        # payment_status.
        #
        # OTP status comes directly from Payment OTP.
        #
        # The relationship is:
        #
        # Payment Transaction.unique_id
        #             ↓
        # Payment OTP.transaction_unique_id
        #
        # This works for BOTH:
        #   - single payment
        #   - bulk payment
        #
        # because every bulk transaction has its own
        # Payment OTP row with the same transaction_unique_id.
        # ----------------------------------------------------

        otp_verification_status = None
        otp_request_id = None
        otp_attempt_count = None
        otp_expires_on = None

        if transaction_unique_id:

            otp_data = frappe.db.get_value(
                "Payment OTP",
                {
                    "transaction_unique_id":
                        transaction_unique_id,
                },
                [
                    "name",
                    "verification_status",
                    "attempt_count",
                    "expires_on",
                ],
                as_dict=True,
            )

            if otp_data:

                otp_request_id = (
                    otp_data.name
                )

                otp_verification_status = (
                    otp_data.verification_status
                )

                otp_attempt_count = (
                    otp_data.attempt_count
                )

                otp_expires_on = (
                    otp_data.expires_on
                )

        # ----------------------------------------------------
        # RETURN PAYMENT + OTP INFORMATION
        # ----------------------------------------------------

        data.append({

            # Payment Transaction
            "payment_transaction":
                payment.name,

            "transaction_unique_id":
                transaction_unique_id,

            "purchase_invoice":
                payment.purchase_invoice,

            "payment_status":
                payment.payment_status,

            "bank_transaction_id":
                payment.bank_transaction_id,

            "response_code":
                payment.response_code,

            "response_message":
                payment.response_message,

            "modified":
                payment.modified,

            # ------------------------------------------------
            # OTP INFORMATION
            # ------------------------------------------------

            "otp_request_id":
                otp_request_id,

            "otp_verification_status":
                otp_verification_status,

            "otp_attempt_count":
                otp_attempt_count,

            "otp_expires_on":
                otp_expires_on,
        })

    # ========================================================
    # RESPONSE
    # ========================================================

    return {
        "success": True,
        "data": data,
    }