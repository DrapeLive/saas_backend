from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.viewsets import GenericViewSet
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenViewBase

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.models import RoleType, User
from apps.accounts.permissions import (
    CanManageUsers,
    CompanyApproved,
    IsAgent,
    IsCompanyAdmin,
    IsCompanyAdminOrAbove,
    IsSuperAdmin,
)
from apps.accounts.serializers import (
    AgentJoinSerializer,
    AgentRegisterSerializer,
    CreateSubAdminSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
    SignupSerializer,
    UserAdminSerializer,
    UserProfileSerializer,
    UserProfileUpdateSerializer,
)
from apps.agents.models import (
    AgentCompanyMembership,
    AgentInvitation,
    AgentProfile,
)


def custom_exception_handler(exc, context):
    from rest_framework.views import exception_handler

    response = exception_handler(exc, context)
    if response is not None:
        detail = response.data
        if isinstance(detail, dict):
            messages = []
            for field, errors in detail.items():
                if isinstance(errors, list):
                    messages.extend(str(e) for e in errors)
                else:
                    messages.append(str(errors))
            response.data = {"detail": " | ".join(messages)}
    return response


class LoginView(TokenViewBase):
    permission_classes = (AllowAny,)
    throttle_scope = "login"
    throttle_classes = (ScopedRateThrottle,)
    serializer_class = LoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"].lower().strip()
        password = serializer.validated_data["password"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise AuthenticationFailed("No active account found with this email.")

        if not user.is_active:
            raise AuthenticationFailed("User account is disabled.")

        if not user.check_password(password):
            raise AuthenticationFailed("Incorrect password.")

        refresh = RefreshToken.for_user(user)
        refresh["role"] = user.role
        refresh["company_id"] = str(user.company_id) if user.company_id else None
        refresh["is_super_admin"] = user.role == RoleType.SUPER_ADMIN

        ip = request.META.get("REMOTE_ADDR", "")
        device = request.META.get("HTTP_USER_AGENT", "")[:200]
        User.objects.filter(pk=user.pk).update(
            last_login_ip=ip,
            last_login_device=device,
        )

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserProfileSerializer(user).data,
            }
        )


class SignupView(GenericViewSet):
    permission_classes = (AllowAny,)
    throttle_scope = "signup"
    throttle_classes = (ScopedRateThrottle,)
    serializer_class = SignupSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)
        refresh["role"] = user.role
        refresh["company_id"] = str(user.company_id)
        refresh["is_super_admin"] = False

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserProfileSerializer(user).data,
            },
            status=status.HTTP_201_CREATED,
        )


class AgentRegisterView(GenericViewSet):
    permission_classes = (AllowAny,)
    serializer_class = AgentRegisterSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        AgentProfile.objects.create(user=user)

        return Response(
            UserProfileSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )


class AuthViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get_permissions(self):
        if self.action in ("password_reset", "password_reset_confirm"):
            return [AllowAny()]
        if self.action == "join_company":
            return [IsAuthenticated(), IsAgent()]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action == "me":
            if self.request.method == "PATCH":
                return UserProfileUpdateSerializer
            return UserProfileSerializer
        if self.action == "password_change":
            return PasswordChangeSerializer
        if self.action == "password_reset":
            return PasswordResetSerializer
        if self.action == "password_reset_confirm":
            return PasswordResetConfirmSerializer
        if self.action == "logout":
            return None
        if self.action == "join_company":
            return AgentJoinSerializer
        return UserProfileSerializer

    @action(detail=False, methods=["get", "patch"], url_path="me")
    def me(self, request, *args, **kwargs):
        if request.method == "GET":
            return Response(UserProfileSerializer(request.user).data)

        serializer = UserProfileUpdateSerializer(
            request.user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserProfileSerializer(request.user).data)

    @action(detail=False, methods=["post"], url_path="password/change")
    def password_change(self, request, *args, **kwargs):
        serializer = PasswordChangeSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response({"detail": "Password changed successfully."})

    @action(detail=False, methods=["post"], url_path="password/reset", permission_classes=[AllowAny])
    def password_reset(self, request, *args, **kwargs):
        serializer = PasswordResetSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        reset_user = serializer.context.get("reset_user")
        if reset_user is None:
            try:
                reset_user = User.objects.get(
                    email=serializer.validated_data["email"], is_active=True
                )
            except User.DoesNotExist:
                return Response(
                    {"detail": "If an account exists, a reset link has been sent."}
                )

        uid = urlsafe_base64_encode(force_bytes(reset_user.pk))
        token = default_token_generator.make_token(reset_user)

        return Response(
            {"detail": "Password reset initiated.", "uid": uid, "token": token}
        )

    @action(detail=False, methods=["post"], url_path="password/reset/confirm", permission_classes=[AllowAny])
    def password_reset_confirm(self, request, *args, **kwargs):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            uid = force_str(urlsafe_base64_decode(serializer.validated_data["uid"]))
            user = User.objects.get(pk=uid)
        except (User.DoesNotExist, ValueError, TypeError):
            return Response(
                {"detail": "Invalid reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token = serializer.validated_data["token"]
        if not default_token_generator.check_token(user, token):
            return Response(
                {"detail": "Invalid or expired reset token."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response({"detail": "Password has been reset successfully."})

    @action(detail=False, methods=["post"], url_path="logout")
    def logout(self, request, *args, **kwargs):
        try:
            refresh_token = request.data.get("refresh")
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except (TokenError, InvalidToken, AttributeError):
            pass
        return Response({"detail": "Logged out successfully."})

    @action(
        detail=False,
        methods=["post"],
        url_path="agents/join",
        permission_classes=[IsAuthenticated, IsAgent],
    )
    def join_company(self, request, *args, **kwargs):
        serializer = AgentJoinSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        invitation = serializer.context["invitation"]
        agent_profile = request.user.agent_profile

        membership, created = AgentCompanyMembership.objects.get_or_create(
            agent=agent_profile,
            company=invitation.company,
            defaults={"status": "active", "approved_by": invitation.invited_by},
        )

        if not created and membership.status == "removed":
            membership.status = "active"
            membership.save(update_fields=["status"])

        inviter_company = invitation.invited_by.company
        if inviter_company and inviter_company != invitation.company:
            AgentCompanyMembership.objects.get_or_create(
                agent=agent_profile,
                company=inviter_company,
                defaults={"status": "active", "approved_by": invitation.invited_by},
            )

        invitation.status = "accepted"
        invitation.accepted_by = request.user
        invitation.save(update_fields=["status", "accepted_by"])

        return Response(
            {"detail": f"Successfully joined {invitation.company.name}."},
            status=status.HTTP_200_OK,
        )


class AdminUserViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated, CompanyApproved, CanManageUsers)

    def get_serializer_class(self):
        if self.action == "create_sub_admin":
            return CreateSubAdminSerializer
        return UserAdminSerializer

    def list(self, request, *args, **kwargs):
        if request.user.role == RoleType.SUPER_ADMIN:
            users = User.objects.all()
        else:
            users = User.objects.filter(company=request.user.company)
        serializer = UserAdminSerializer(users, many=True)
        return Response(serializer.data)

    def create_sub_admin(self, request, *args, **kwargs):
        company = request.user.company
        if request.user.role == RoleType.SUPER_ADMIN:
            company_id = request.data.get("company")
            from apps.companies.models import Company
            try:
                company = Company.objects.get(pk=company_id)
            except Company.DoesNotExist:
                return Response(
                    {"detail": "Company not found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer = CreateSubAdminSerializer(
            data=request.data, context={"company": company}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            UserAdminSerializer(user).data, status=status.HTTP_201_CREATED
        )

    def update(self, request, pk=None, *args, **kwargs):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if request.user.role != RoleType.SUPER_ADMIN:
            if user.company_id != request.user.company_id:
                return Response(
                    {"detail": "You can only manage users in your company."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        serializer = UserAdminSerializer(
            user, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(UserAdminSerializer(user).data)

    def destroy(self, request, pk=None, *args, **kwargs):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"detail": "User not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if request.user.role != RoleType.SUPER_ADMIN:
            if user.company_id != request.user.company_id:
                return Response(
                    {"detail": "You can only manage users in your company."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        user.is_active = False
        user.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated, CompanyApproved, IsCompanyAdmin)

    def get_serializer_class(self):
        return None

    def list(self, request, *args, **kwargs):
        invitations = AgentInvitation.objects.filter(
            company=request.user.company
        ).select_related("invited_by").order_by("-created_at")
        data = [
            {
                "id": str(inv.id),
                "email": inv.email,
                "phone": inv.phone,
                "token": inv.token,
                "status": inv.status,
                "delivery_method": inv.delivery_method,
                "expires_at": inv.expires_at,
                "created_at": inv.created_at,
            }
            for inv in invitations
        ]
        return Response(data)

    def create(self, request, *args, **kwargs):
        from django.utils import timezone
        import secrets

        email = request.data.get("email", "")
        phone = request.data.get("phone", "")
        delivery_method = request.data.get("delivery_method", "email")

        if not email and not phone:
            return Response(
                {"detail": "Either email or phone is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        expires_at = timezone.now() + timezone.timedelta(days=7)
        token = secrets.token_urlsafe(32)

        invitation = AgentInvitation.objects.create(
            company=request.user.company,
            invited_by=request.user,
            email=email,
            phone=phone,
            token=token,
            delivery_method=delivery_method,
            expires_at=expires_at,
        )

        return Response(
            {
                "id": str(invitation.id),
                "token": invitation.token,
                "email": invitation.email,
                "phone": invitation.phone,
                "expires_at": invitation.expires_at,
                "status": invitation.status,
            },
            status=status.HTTP_201_CREATED,
        )
