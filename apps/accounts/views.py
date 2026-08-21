from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.tokens import default_token_generator
from django.db.models import (
    Avg,
    Case,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    FloatField,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Extract, TruncMonth
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.timezone import now
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
    IsAdmin,
    IsAgent,
    IsCompanyAdminOrAbove,
    IsSuperAdmin,
)
from apps.accounts.serializers import (
    AdminAnalyticsSerializer,
    AdminDashboardSerializer,
    AgentJoinSerializer,
    AgentRegisterSerializer,
    CreateSubAdminSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
    SetupBankSerializer,
    SetupInvoiceSerializer,
    SetupNotificationSerializer,
    SetupProfileSerializer,
    SetupTaxSettingsSerializer,
    SignupSerializer,
    SuperAdminDashboardSerializer,
    UserAdminSerializer,
    UserProfileSerializer,
    UserProfileUpdateSerializer,
)
from apps.agents.models import (
    AgentCompanyMembership,
    AgentInvitation,
    AgentProfile,
)
from apps.commissions.models import CommissionEntry
from apps.companies.models import Company, CompanySettings
from apps.customers.models import CustomerProfile
from apps.dispatch.models import Dispatch
from apps.invoices.models import Invoice
from apps.orders.models import Order, OrderItem, OrderStatus
from apps.products.models import Product, VariantSize
from apps.subscriptions.models import Subscription, SubscriptionEvent


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

    @action(
        detail=False,
        methods=["post"],
        url_path="password/reset",
        permission_classes=[AllowAny],
    )
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

    @action(
        detail=False,
        methods=["post"],
        url_path="password/reset/confirm",
        permission_classes=[AllowAny],
    )
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
            defaults={
                "status": AgentCompanyMembership.MembershipStatus.PENDING,
                "invitation_method": invitation.delivery_method,
            },
        )

        if not created and membership.status == "removed":
            membership.status = AgentCompanyMembership.MembershipStatus.PENDING
            membership.invitation_method = invitation.delivery_method
            membership.save(update_fields=["status", "invitation_method"])

        inviter_company = invitation.invited_by.company
        if inviter_company and inviter_company != invitation.company:
            AgentCompanyMembership.objects.get_or_create(
                agent=agent_profile,
                company=inviter_company,
                defaults={
                    "status": AgentCompanyMembership.MembershipStatus.PENDING,
                    "invitation_method": invitation.delivery_method,
                },
            )

        invitation.used_count = F("used_count") + 1
        invitation.save(update_fields=["used_count"])

        return Response(
            {
                "detail": f"Successfully joined {invitation.company.name}.",
                "membership_status": membership.status,
            },
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
        return Response(UserAdminSerializer(user).data, status=status.HTTP_201_CREATED)

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

        serializer = UserAdminSerializer(user, data=request.data, partial=True)
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
    permission_classes = (IsAuthenticated, CompanyApproved, IsAdmin)

    def get_serializer_class(self):
        return None

    def list(self, request, *args, **kwargs):
        invitations = (
            AgentInvitation.objects.filter(company=request.user.company)
            .select_related("invited_by")
            .order_by("-created_at")
        )
        data = [
            {
                "id": str(inv.id),
                "email": inv.email,
                "phone": inv.phone,
                "token": inv.token,
                "status": inv.status,
                "max_uses": inv.max_uses,
                "used_count": inv.used_count,
                "expires_at": inv.expires_at,
                "created_at": inv.created_at,
            }
            for inv in invitations
        ]
        return Response(data)

    def create(self, request, *args, **kwargs):
        import secrets

        from django.utils import timezone

        email = request.data.get("email", "")
        phone = request.data.get("phone", "")
        max_uses = request.data.get("max_uses", 1)

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
            max_uses=max_uses,
            expires_at=expires_at,
        )

        return Response(
            {
                "id": str(invitation.id),
                "token": invitation.token,
                "email": invitation.email,
                "phone": invitation.phone,
                "max_uses": invitation.max_uses,
                "used_count": invitation.used_count,
                "expires_at": invitation.expires_at,
                "status": invitation.status,
            },
            status=status.HTTP_201_CREATED,
        )


class SuperAdminDashboardViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsSuperAdmin,)
    serializer_class = SuperAdminDashboardSerializer

    def list(self, request, *args, **kwargs):
        today = now()
        month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        company_stats = Company.objects.aggregate(
            total_companies=Count("id"),
            active_companies=Count("id", filter=Q(status="active")),
            trial_companies=Count("id", filter=Q(status="trial")),
            expired_companies=Count("id", filter=Q(status="expired")),
        )

        active_subs = Subscription.objects.filter(status="active")
        mrr_agg = active_subs.aggregate(
            mrr=Coalesce(
                Sum(
                    Case(
                        When(
                            billing_cycle="monthly",
                            then=F("price_paid"),
                        ),
                        When(
                            billing_cycle="yearly",
                            then=F("price_paid") / 12,
                        ),
                        When(billing_cycle="trial", then=Value(0)),
                        default=Value(0),
                        output_field=DecimalField(),
                    )
                ),
                Value(0),
                output_field=DecimalField(),
            )
        )
        mrr = mrr_agg["mrr"] or 0
        arr = mrr * 12

        churned_count = (
            SubscriptionEvent.objects.filter(
                event_type__in=["expired", "cancelled"],
                created_at__gte=month_start,
            )
            .values("subscription__company")
            .distinct()
            .count()
        )
        total_at_start = Company.objects.filter(created_at__lt=month_start).count()
        churn_rate = churned_count / max(total_at_start, 1)

        ltv_agg = Subscription.objects.exclude(status="trial").aggregate(
            ltv=Avg("price_paid")
        )
        ltv = ltv_agg["ltv"] or 0

        return Response(
            SuperAdminDashboardSerializer(
                {
                    **company_stats,
                    "mrr": mrr,
                    "arr": arr,
                    "churn_rate": churn_rate,
                    "ltv": ltv,
                }
            ).data
        )


class AdminDashboardViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated, CompanyApproved, IsCompanyAdminOrAbove)
    serializer_class = AdminDashboardSerializer

    def list(self, request, *args, **kwargs):
        company = request.company
        today = now()
        today_date = today.date()

        base_orders = Order.objects.filter(company=company)

        orders_pending = base_orders.filter(
            status__in=[OrderStatus.CONFIRMED, OrderStatus.PROCESSING]
        ).count()

        sales_total = (
            base_orders.filter(
                status__in=[
                    OrderStatus.CONFIRMED,
                    OrderStatus.PROCESSING,
                    OrderStatus.DELIVERED,
                ],
            ).aggregate(total=Sum("total_amount"))["total"]
            or 0
        )

        invoices = Invoice.objects.filter(company=company)
        outstanding_total = (
            invoices.filter(status__in=["issued", "partial", "overdue"]).aggregate(
                total=Sum("amount_due")
            )["total"]
            or 0
        )

        overdue_total = (
            invoices.filter(
                due_date__lt=today_date,
                status__in=["issued", "partial", "overdue"],
            ).aggregate(total=Sum("amount_due"))["total"]
            or 0
        )

        ageing_0_30 = (
            invoices.filter(
                due_date__gte=today_date - timedelta(days=30),
                due_date__lte=today_date,
            ).aggregate(total=Sum("amount_due"))["total"]
            or 0
        )

        ageing_31_60 = (
            invoices.filter(
                due_date__gte=today_date - timedelta(days=60),
                due_date__lt=today_date - timedelta(days=30),
            ).aggregate(total=Sum("amount_due"))["total"]
            or 0
        )

        ageing_60_plus = (
            invoices.filter(
                due_date__lt=today_date - timedelta(days=60),
            ).aggregate(total=Sum("amount_due"))["total"]
            or 0
        )

        tally_sync = {
            "status": "synced",
            "last_synced_at": None,
        }

        return Response(
            AdminDashboardSerializer(
                {
                    "sales_total": sales_total,
                    "orders_pending": orders_pending,
                    "outstanding_total": outstanding_total,
                    "overdue_total": overdue_total,
                    "receivables_ageing": {
                        "0_30": ageing_0_30,
                        "31_60": ageing_31_60,
                        "60_plus": ageing_60_plus,
                    },
                    "tally_sync": tally_sync,
                }
            ).data
        )

    @action(detail=False, methods=["get"], url_path="recent-orders")
    def recent_orders(self, request, *args, **kwargs):
        company = request.user.company
        orders = Order.objects.filter(company=company).order_by("-created_at")[:3]
        data = []
        for o in orders:
            data.append({
                "order_name": o.order_number,
                "customer_name": o.customer.trade_name if getattr(o, "customer", None) else None,
                "payment": o.total_amount,
                "status": o.status
            })
        return Response(data)

    @action(detail=False, methods=["get"], url_path="low-stock-items")
    def low_stock_items(self, request, *args, **kwargs):
        company = request.user.company
        items = VariantSize.objects.filter(
            color_variant__product__company=company,
            stock_quantity__lte=F("reorder_level") + F("reserved_qty")
        )
        data = []
        for item in items:
            name = f"{item.color_variant.product.name} - {item.color_variant.color_name} - {item.size}"
            data.append({
                "name": name,
                "units": item.available_qty,
                "minimum_stock": item.reorder_level,
            })
        return Response({
            "total_low_stock_items": items.count(),
            "items": data
        })

    @action(detail=False, methods=["get"], url_path="top-agents")
    def top_agents(self, request, *args, **kwargs):
        company = request.user.company
        today = now().date()
        
        # Get orders submitted today by agents
        agent_stats = Order.objects.filter(
            company=company,
            agent__isnull=False,
            submitted_at__date=today
        ).values("agent_id").annotate(
            orders_today=Count("id"),
            payment_today=Sum("total_amount")
        ).order_by("-payment_today")[:2]

        data = []
        for stat in agent_stats:
            try:
                agent = AgentProfile.objects.get(id=stat["agent_id"])
                name = agent.user.full_name
                # Agent Profile doesn't have an image field, returning null
                image = None
            except AgentProfile.DoesNotExist:
                continue

            data.append({
                "image": image,
                "name": name,
                "number_of_orders_today": stat["orders_today"],
                "total_order_payment_today": stat["payment_today"]
            })
            
        return Response(data)

class AdminAnalyticsViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated, CompanyApproved, IsCompanyAdminOrAbove)
    serializer_class = AdminAnalyticsSerializer

    def list(self, request, *args, **kwargs):
        company = request.company
        today = now()
        today_date = today.date()
        month_start = today_date.replace(day=1)

        orders = Order.objects.filter(company=company, submitted_at__isnull=False)

        sales_trend = (
            orders.filter(submitted_at__gte=today_date - timedelta(days=365))
            .annotate(month=TruncMonth("submitted_at"))
            .values("month")
            .annotate(total=Sum("total_amount"))
            .order_by("month")
        )

        top_products = (
            OrderItem.objects.filter(
                order__company=company,
                order__submitted_at__isnull=False,
            )
            .values("product_name")
            .annotate(total=Sum("line_total"))
            .order_by("-total")[:10]
        )

        agent_sales = (
            orders.filter(
                agent__isnull=False,
                submitted_at__date__gte=month_start,
            )
            .values(
                agent_name=F("agent__user__full_name"),
            )
            .annotate(total=Sum("total_amount"))
            .order_by("-total")
        )

        invoices = Invoice.objects.filter(
            company=company,
            status__in=["issued", "partial", "overdue"],
        )
        aging = invoices.aggregate(
            current=Sum(
                "amount_due",
                filter=Q(due_date__gte=today_date - timedelta(days=30))
                | Q(due_date__isnull=True),
            ),
            days_31_60=Sum(
                "amount_due",
                filter=Q(
                    due_date__lt=today_date - timedelta(days=30),
                    due_date__gte=today_date - timedelta(days=60),
                ),
            ),
            days_61_90=Sum(
                "amount_due",
                filter=Q(
                    due_date__lt=today_date - timedelta(days=60),
                    due_date__gte=today_date - timedelta(days=90),
                ),
            ),
            days_90_plus=Sum(
                "amount_due",
                filter=Q(due_date__lt=today_date - timedelta(days=90)),
            ),
        )
        for k, v in aging.items():
            if v is None:
                aging[k] = 0

        total_customers = CustomerProfile.objects.filter(company=company).count()
        customers_with_orders = (
            CustomerProfile.objects.filter(company=company, orders__isnull=False)
            .distinct()
            .count()
        )

        return Response(
            AdminAnalyticsSerializer(
                {
                    "sales_trend": list(sales_trend),
                    "top_products": list(top_products),
                    "agent_comparison": list(agent_sales),
                    "outstanding_aging": aging,
                    "customer_acquisition": {
                        "total_customers": total_customers,
                        "customers_with_orders": customers_with_orders,
                    },
                }
            ).data
        )


class CompanySetupViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated, CompanyApproved, IsAdmin)

    def _get_settings(self, company):
        settings, _ = CompanySettings.objects.get_or_create(company=company)
        return settings

    @action(detail=False, methods=["patch"], url_path="setup/profile")
    def update_profile(self, request):
        serializer = SetupProfileSerializer(
            request.company, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=["patch"], url_path="setup/bank")
    def update_bank(self, request):
        serializer = SetupBankSerializer(
            request.company, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=["patch"], url_path="setup/invoice")
    def update_invoice(self, request):
        serializer = SetupInvoiceSerializer(
            request.company, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=["patch"], url_path="setup/tax")
    def update_tax(self, request):
        settings = self._get_settings(request.company)
        serializer = SetupTaxSettingsSerializer(
            settings, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=["patch"], url_path="setup/notifications")
    def update_notifications(self, request):
        settings = self._get_settings(request.company)
        serializer = SetupNotificationSerializer(
            settings, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        request.company.setup_completed = True
        request.company.save(update_fields=["setup_completed"])
        return Response(serializer.data)
