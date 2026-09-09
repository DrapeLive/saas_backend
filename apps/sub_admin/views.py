from django.db import transaction
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.models import User
from apps.accounts.permissions import IsAdmin
from apps.core.openapi import RESPONSE_400, RESPONSE_404
from apps.sub_admin.serializers import (
    RestrictAgentsSerializer,
    RestrictCategoriesSerializer,
    SubAdminCreateSerializer,
    SubAdminDetailSerializer,
    SubAdminListSerializer,
    SubAdminUpdateSerializer,
)
from apps.sub_admin.services import get_subadmin_profile


@extend_schema_view(
    list=extend_schema(
        tags=["Sub Admins"],
        summary="List sub-admins",
        description="Lists sub-admin users belonging to the caller's company.",
        responses={200: SubAdminListSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["Sub Admins"],
        summary="Get sub-admin",
        responses={200: SubAdminDetailSerializer, 404: RESPONSE_404},
    ),
    create=extend_schema(
        tags=["Sub Admins"],
        summary="Create sub-admin",
        description="Creates a sub-admin user + profile in the caller's company.",
        responses={201: SubAdminDetailSerializer, 400: RESPONSE_400},
    ),
    partial_update=extend_schema(
        tags=["Sub Admins"],
        summary="Update sub-admin",
        description="Updates approval threshold / role template.",
        responses={200: SubAdminDetailSerializer, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
    destroy=extend_schema(
        tags=["Sub Admins"],
        summary="Deactivate sub-admin",
        description="Deactivates a sub-admin user. Returns 204.",
        responses={204: None, 404: RESPONSE_404},
    ),
    restrict_agents=extend_schema(
        tags=["Sub Admins"],
        summary="Restrict sub-admin to agents",
        description="Replaces the set of agents a sub-admin may manage.",
        responses={200: SubAdminDetailSerializer, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
    restrict_categories=extend_schema(
        tags=["Sub Admins"],
        summary="Restrict sub-admin to categories",
        description="Replaces the set of product categories a sub-admin may manage.",
        responses={200: SubAdminDetailSerializer, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
)
class SubAdminViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdmin,)

    def get_serializer_class(self):
        if self.action == "create":
            return SubAdminCreateSerializer
        if self.action in ("update", "partial_update"):
            return SubAdminUpdateSerializer
        if self.action == "restrict_agents":
            return RestrictAgentsSerializer
        if self.action == "restrict_categories":
            return RestrictCategoriesSerializer
        if self.action == "list":
            return SubAdminListSerializer
        return SubAdminDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["company"] = self._get_company(self.request)
        return context

    def _get_company(self, request):
        return request.company or request.user.company

    def _get_subadmin_user(self, pk, company):
        """Return the User (role=subadmin) in this company, or None."""
        return (
            User.objects.select_related("subadmin_profile")
            .filter(role="subadmin", company=company, pk=pk)
            .first()
        )

    def list(self, request, *args, **kwargs):
        company = self._get_company(request)
        users = User.objects.filter(company=company, role="subadmin").select_related(
            "subadmin_profile"
        )
        return Response(SubAdminListSerializer(users, many=True).data)

    def retrieve(self, request, pk=None, *args, **kwargs):
        company = self._get_company(request)
        user = self._get_subadmin_user(pk, company)
        if not user:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(SubAdminDetailSerializer(user.subadmin_profile).data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        company = self._get_company(request)
        serializer = SubAdminCreateSerializer(
            data=request.data, context={"company": company}
        )
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        return Response(
            SubAdminDetailSerializer(profile).data, status=status.HTTP_201_CREATED
        )

    @transaction.atomic
    def partial_update(self, request, pk=None, *args, **kwargs):
        company = self._get_company(request)
        user = self._get_subadmin_user(pk, company)
        if not user:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = SubAdminUpdateSerializer(
            user.subadmin_profile,
            data=request.data,
            partial=True,
            context={"company": company},
        )
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        return Response(SubAdminDetailSerializer(profile).data)

    def destroy(self, request, pk=None, *args, **kwargs):
        company = self._get_company(request)
        user = self._get_subadmin_user(pk, company)
        if not user:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        user.is_active = False
        user.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="restrict-agents")
    @transaction.atomic
    def restrict_agents(self, request, pk=None, *args, **kwargs):
        company = self._get_company(request)
        user = self._get_subadmin_user(pk, company)
        if not user:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = RestrictAgentsSerializer(
            data=request.data, context={"company": company}
        )
        serializer.is_valid(raise_exception=True)
        user.subadmin_profile.restricted_agents.set(serializer.validated_data["agent_ids"])
        return Response(SubAdminDetailSerializer(user.subadmin_profile).data)

    @action(detail=True, methods=["post"], url_path="restrict-categories")
    @transaction.atomic
    def restrict_categories(self, request, pk=None, *args, **kwargs):
        company = self._get_company(request)
        user = self._get_subadmin_user(pk, company)
        if not user:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = RestrictCategoriesSerializer(
            data=request.data, context={"company": company}
        )
        serializer.is_valid(raise_exception=True)
        user.subadmin_profile.restricted_categories.set(
            serializer.validated_data["category_ids"]
        )
        return Response(SubAdminDetailSerializer(user.subadmin_profile).data)