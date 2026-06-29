from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.models import RoleType
from apps.accounts.permissions import CompanyApproved, IsCompanyStaff
from apps.customers.models import CustomerProfile
from apps.customers.serializers import (
    CustomerCommunicationLogSerializer,
    CustomerCreateSerializer,
    CustomerDocumentSerializer,
    CustomerSerializer,
    CustomerUpdateSerializer,
)
from apps.customers.services import compute_segment, verify_gstin


class IsAdminOrSubAdmin(IsCompanyStaff):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.user.role in (RoleType.SUPER_ADMIN, RoleType.ADMIN, RoleType.SUB_ADMIN)


class CustomerViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get_serializer_class(self):
        if self.action == "create":
            return CustomerCreateSerializer
        if self.action in ("partial_update", "update"):
            return CustomerUpdateSerializer
        if self.action == "documents":
            return CustomerDocumentSerializer
        if self.action == "communication_logs":
            return CustomerCommunicationLogSerializer
        return CustomerSerializer

    def get_permissions(self):
        if self.action in ("import_preview", "import_confirm", "verify_gstin",
                           "compute_segment", "credit_block", "credit_unblock"):
            return [IsAuthenticated(), CompanyApproved(), IsAdminOrSubAdmin()]
        if self.action in ("documents", "communication_logs"):
            return [IsAuthenticated(), CompanyApproved(), IsCompanyStaff()]
        return [IsAuthenticated(), CompanyApproved(), IsAdminOrSubAdmin()]

    def get_queryset(self):
        return CustomerProfile.objects.select_related(
            "company", "assigned_agent__user", "user"
        )

    def list(self, request, *args, **kwargs):
        if request.user.role == "superadmin":
            customers = self.get_queryset()
        else:
            customers = self.get_queryset().filter(company=request.user.company)

        search = request.query_params.get("search")
        if search:
            customers = customers.filter(
                Q(trade_name__icontains=search)
                | Q(legal_name__icontains=search)
                | Q(phone__icontains=search)
                | Q(gstin__icontains=search)
                | Q(email__icontains=search)
            )

        status_filter = request.query_params.get("status")
        if status_filter:
            customers = customers.filter(status=status_filter)

        segment_filter = request.query_params.get("segment")
        if segment_filter:
            customers = customers.filter(segment=segment_filter)

        assigned_agent = request.query_params.get("assigned_agent")
        if assigned_agent:
            customers = customers.filter(assigned_agent_id=assigned_agent)

        ordering = request.query_params.get("ordering", "-created_at")
        customers = customers.order_by(ordering)

        tag = request.query_params.get("tag")
        if tag:
            customers = [c for c in customers if tag in c.tags]
        else:
            customers = list(customers)

        serializer = CustomerSerializer(customers, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        customer = self.get_object()
        serializer = CustomerSerializer(customer)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        gstin = request.data.get("gstin", "")
        if gstin and CustomerProfile.objects.filter(company=request.user.company, gstin=gstin).exists():
            return Response(
                {"gstin": ["Customer with this GSTIN already exists in your company."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = CustomerCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = serializer.save(company=request.user.company)
        if customer.gstin:
            result = verify_gstin(customer.gstin)
            if result["valid"]:
                customer.gstin_verified = True
                customer.gstin_legal_name = result["legal_name"]
                customer.gstin_status = result["status"]
                customer.gstin_type = result["type"]
                customer.save(update_fields=[
                    "gstin_verified", "gstin_legal_name", "gstin_status", "gstin_type"
                ])
        return Response(CustomerSerializer(customer).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        customer = self.get_object()
        serializer = CustomerUpdateSerializer(customer, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        customer = serializer.save()
        if "gstin" in request.data and customer.gstin:
            result = verify_gstin(customer.gstin)
            if result["valid"]:
                customer.gstin_verified = True
                customer.gstin_legal_name = result["legal_name"]
                customer.gstin_status = result["status"]
                customer.gstin_type = result["type"]
                customer.save(update_fields=[
                    "gstin_verified", "gstin_legal_name", "gstin_status", "gstin_type"
                ])
        return Response(CustomerSerializer(customer).data)

    def destroy(self, request, *args, **kwargs):
        customer = self.get_object()
        customer.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="import-preview")
    def import_preview(self, request, *args, **kwargs):
        rows = request.data.get("rows", []) if isinstance(request.data, dict) else []
        validated = []
        errors = []
        for i, row in enumerate(rows, start=1):
            row_serializer = CustomerCreateSerializer(data=row)
            if row_serializer.is_valid():
                validated.append({"row_number": i, **row})
            else:
                errors.append({"row_number": i, "errors": row_serializer.errors})
        return Response({"valid": validated, "errors": errors, "total": len(rows)})

    @action(detail=False, methods=["post"], url_path="import-confirm")
    def import_confirm(self, request, *args, **kwargs):
        rows = request.data.get("rows", []) if isinstance(request.data, dict) else []
        created = []
        errors = []
        for i, row in enumerate(rows, start=1):
            row_serializer = CustomerCreateSerializer(data=row)
            if row_serializer.is_valid():
                customer = row_serializer.save(company=request.user.company)
                created.append(CustomerSerializer(customer).data)
            else:
                errors.append({"row_number": i, "errors": row_serializer.errors})
        return Response(
            {"created": created, "errors": errors, "total": len(rows)},
            status=status.HTTP_201_CREATED if created else status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=True, methods=["post"], url_path="verify-gstin")
    def verify_gstin(self, request, *args, **kwargs):
        customer = self.get_object()
        if not customer.gstin:
            return Response(
                {"error": "Customer has no GSTIN"}, status=status.HTTP_400_BAD_REQUEST
            )
        result = verify_gstin(customer.gstin)
        if result["valid"]:
            customer.gstin_verified = True
            customer.gstin_legal_name = result["legal_name"]
            customer.gstin_status = result["status"]
            customer.gstin_type = result["type"]
            customer.save(update_fields=[
                "gstin_verified", "gstin_legal_name", "gstin_status", "gstin_type"
            ])
        return Response(result)

    @action(detail=True, methods=["post"], url_path="compute-segment")
    def compute_segment(self, request, *args, **kwargs):
        customer = self.get_object()
        segment = compute_segment(customer)
        customer.segment = segment
        customer.save(update_fields=["segment"])
        return Response({"segment": segment})

    @action(detail=True, methods=["post"], url_path="credit-block")
    def credit_block(self, request, *args, **kwargs):
        customer = self.get_object()
        customer.is_credit_blocked = True
        customer.save(update_fields=["is_credit_blocked"])
        return Response({"is_credit_blocked": True})

    @action(detail=True, methods=["post"], url_path="credit-unblock")
    def credit_unblock(self, request, *args, **kwargs):
        customer = self.get_object()
        customer.is_credit_blocked = False
        customer.save(update_fields=["is_credit_blocked"])
        return Response({"is_credit_blocked": False})

    @action(detail=True, methods=["get", "post"], url_path="documents")
    def documents(self, request, *args, **kwargs):
        customer = self.get_object()
        if request.method == "GET":
            docs = customer.documents.all()
            serializer = CustomerDocumentSerializer(docs, many=True)
            return Response(serializer.data)
        serializer = CustomerDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doc = serializer.save(customer=customer, uploaded_by=request.user)
        return Response(CustomerDocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="communication-logs")
    def communication_logs(self, request, *args, **kwargs):
        customer = self.get_object()
        logs = customer.communication_logs.all()
        serializer = CustomerCommunicationLogSerializer(logs, many=True)
        return Response(serializer.data)
