import frappe


@frappe.whitelist()
def get_payment_transactions():

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

    for payment in payments:

        data.append({
            "payment_transaction": payment.name,

            "transaction_unique_id": (
                payment.unique_id
            ),

            "purchase_invoice": (
                payment.purchase_invoice
            ),

            "payment_status": (
                payment.payment_status
            ),

            "bank_transaction_id": (
                payment.bank_transaction_id
            ),

            "response_code": (
                payment.response_code
            ),

            "response_message": (
                payment.response_message
            ),

            "modified": (
                payment.modified
            ),
        })

    return {
        "success": True,
        "data": data,
    }