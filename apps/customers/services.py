from apps.customers.models import GstStatus


def verify_gstin(gstin: str) -> dict:
    return {
        "valid": False,
        "legal_name": "",
        "status": GstStatus.UNVERIFIED,
        "type": "",
        "message": "GST verification service not configured",
    }
