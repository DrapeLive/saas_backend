from django.db import transaction
from django.db.models import Q
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
from apps.accounts.models import RoleTemplate, SubAdminProfile, User
from apps.accounts.permissions import IsAdmin
from apps.core.openapi import RESPONSE_400, RESPONSE_404
from apps.sub_admin.serializers import (
    RestrictAgentsSerializer,
    RestrictCategoriesSerializer,
    RoleTemplateCreateSerializer,
    RoleTemplateDetailSerializer,
    RoleTemplateUpdateSerializer,
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
        profiles = SubAdminProfile.objects.filter(
            user__company=company, user__role="subadmin"
        ).select_related("user")
        return Response(SubAdminListSerializer(profiles, many=True).data)

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


@extend_schema_view(
    list=extend_schema(
        tags=["Role Templates"],
        summary="List role templates",
        description="Lists the caller's company templates plus platform-wide defaults.",
        responses={200: RoleTemplateDetailSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["Role Templates"],
        summary="Get role template",
        responses={200: RoleTemplateDetailSerializer, 404: RESPONSE_404},
    ),
    create=extend_schema(
        tags=["Role Templates"],
        summary="Create role template",
        description="Creates a company-scoped role template with permissions.",
        responses={201: RoleTemplateDetailSerializer, 400: RESPONSE_400},
    ),
    partial_update=extend_schema(
        tags=["Role Templates"],
        summary="Update role template",
        description="Updates a company role template. Platform-wide templates are read-only.",
        responses={200: RoleTemplateDetailSerializer, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
    destroy=extend_schema(
        tags=["Role Templates"],
        summary="Delete role template",
        description="Deletes a company role template. Blocked if any subadmin uses it.",
        responses={204: None, 409: RESPONSE_400, 404: RESPONSE_404},
    ),
)
class RoleTemplateViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdmin,)

    def get_serializer_class(self):
        if self.action == "create":
            return RoleTemplateCreateSerializer
        if self.action == "partial_update":
            return RoleTemplateUpdateSerializer
        return RoleTemplateDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["company"] = self._get_company(self.request)
        return context

    def _get_company(self, request):
        return request.company or request.user.company

    def _get_company_template(self, pk, company):
        """Return a RoleTemplate owned by this company, or None."""
        return RoleTemplate.objects.filter(company=company, pk=pk).first()

    def _get_visible_template(self, pk, company):
        """Return a template the caller may view (own company or platform-wide)."""
        return (
            RoleTemplate.objects.filter(Q(company=company) | Q(company__isnull=True))
            .filter(pk=pk)
            .first()
        )

    def list(self, request, *args, **kwargs):
        company = self._get_company(request)
        templates = RoleTemplate.objects.filter(
            Q(company=company) | Q(company__isnull=True)
        ).prefetch_related("permissions")
        return Response(RoleTemplateDetailSerializer(templates, many=True).data)

    def retrieve(self, request, pk=None, *args, **kwargs):
        company = self._get_company(request)
        template = self._get_visible_template(pk, company)
        if not template:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(RoleTemplateDetailSerializer(template).data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        company = self._get_company(request)
        serializer = RoleTemplateCreateSerializer(
            data=request.data, context={"company": company}
        )
        serializer.is_valid(raise_exception=True)
        template = serializer.save()
        return Response(
            RoleTemplateDetailSerializer(template).data,
            status=status.HTTP_201_CREATED,
        )

    @transaction.atomic
    def partial_update(self, request, pk=None, *args, **kwargs):
        company = self._get_company(request)
        template = self._get_company_template(pk, company)
        if not template:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = RoleTemplateUpdateSerializer(
            template,
            data=request.data,
            partial=True,
            context={"company": company},
        )
        serializer.is_valid(raise_exception=True)
        template = serializer.save()
        return Response(RoleTemplateDetailSerializer(template).data)

    @transaction.atomic
    def destroy(self, request, pk=None, *args, **kwargs):
        company = self._get_company(request)
        template = self._get_company_template(pk, company)
        if not template:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if SubAdminProfile.objects.filter(role_template=template).exists():
            return Response(
                {
                    "detail": "Cannot delete: role template is assigned to one or more sub-admins."
                },
                status=status.HTTP_409_CONFLICT,
            )
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)