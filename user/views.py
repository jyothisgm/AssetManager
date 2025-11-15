from rest_framework import viewsets, permissions
from django.contrib.auth import get_user_model

from main.settings import GOOGLE_CLIENT_SECRET_FILE
from .models import Role
from .serializers import UserSerializer, UserCreateSerializer, RoleSerializer
from .permissions import HasRolePermission
from common.logging_config import logger
import os, asyncio
from django.views import View
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from .models import GmailAccount
from .utils import fetch_all_user_emails
from asgiref.sync import sync_to_async

User = get_user_model()


class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [permissions.IsAdminUser]

    def list(self, request, *args, **kwargs):
        func_name = f"{self.__class__.__name__}.list"
        try:
            logger.debug(f"[{func_name}] {request.user.email} requested role list")
            return super().list(request, *args, **kwargs)
        except Exception as e:
            logger.exception(f"[{func_name}] Error fetching role list for {request.user.email}")
            raise e

    def create(self, request, *args, **kwargs):
        func_name = f"{self.__class__.__name__}.create"
        try:
            logger.info(f"[{func_name}] {request.user.email} creating a new role with data={request.data}")
            return super().create(request, *args, **kwargs)
        except Exception as e:
            logger.exception(f"[{func_name}] Error creating role by {request.user.email}")
            raise e


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    permission_classes = [permissions.IsAuthenticated, HasRolePermission]

    def get_serializer_class(self):
        func_name = f"{self.__class__.__name__}.get_serializer_class"
        try:
            if self.action in ["create", "update"]:
                logger.debug(f"[{func_name}] Using UserCreateSerializer for action '{self.action}'")
                return UserCreateSerializer
            logger.debug(f"[{func_name}] Using UserSerializer for action '{self.action}'")
            return UserSerializer
        except Exception as e:
            logger.exception(f"[{func_name}] Error determining serializer for action '{self.action}'")
            raise e

    def get_queryset(self):
        func_name = f"{self.__class__.__name__}.get_queryset"
        try:
            user = self.request.user
            if user.is_superuser:
                logger.debug(f"[{func_name}] Superuser {user.email} accessing all users")
                return User.objects.all()
            logger.debug(f"[{func_name}] {user.email} restricted to own user record")
            return User.objects.filter(id=user.id)
        except Exception as e:
            logger.exception(f"[{func_name}] Error building queryset for {getattr(self.request.user, 'email', None)}")
            raise e

    def create(self, request, *args, **kwargs):
        func_name = f"{self.__class__.__name__}.create"
        try:
            logger.info(f"[{func_name}] {request.user.email} creating a new user: {request.data.get('email')}")
            response = super().create(request, *args, **kwargs)
            logger.debug(f"[{func_name}] User creation response status={response.status_code}")
            return response
        except Exception as e:
            logger.exception(f"[{func_name}] Error creating user by {request.user.email}")
            raise e

    def update(self, request, *args, **kwargs):
        func_name = f"{self.__class__.__name__}.update"
        try:
            logger.info(f"[{func_name}] {request.user.email} updating user {kwargs.get('pk')}")
            response = super().update(request, *args, **kwargs)
            logger.debug(f"[{func_name}] Update response status={response.status_code}")
            return response
        except Exception as e:
            logger.exception(f"[{func_name}] Error updating user {kwargs.get('pk')} by {request.user.email}")
            raise e


os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # ⚠️ Dev only
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CALLBACK_PATH = "/user/gmail_callback/"
# -------------------------------------------------------------------
@method_decorator(login_required, name="dispatch")
class GmailConnectView(View):
    """Starts the Gmail OAuth flow."""
    async def get(self, request):
        current_url = request.META.get("HTTP_REFERER", "/admin/")  # fallback if none
        request.session["gmail_return_to"] = current_url  # store where to return
        flow = Flow.from_client_secrets_file(
            GOOGLE_CLIENT_SECRET_FILE,
            scopes=SCOPES,
            redirect_uri=request.build_absolute_uri(CALLBACK_PATH),
        )
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        request.session["gmail_oauth_state"] = state
        return redirect(auth_url)


class GmailCallbackView(View):
    """Handles OAuth callback and stores credentials."""

    async def get(self, request):
        state = request.session.pop("gmail_oauth_state", None)
        return_to = request.session.pop("gmail_return_to", "/admin/")

        if not state:
            return HttpResponse("Missing OAuth state", status=400)

        # ---- run Google API sync code in a background thread ----
        def fetch_credentials():
            flow = Flow.from_client_secrets_file(
                GOOGLE_CLIENT_SECRET_FILE,
                scopes=SCOPES,
                state=state,
                redirect_uri=request.build_absolute_uri(CALLBACK_PATH),
            )
            flow.fetch_token(authorization_response=request.build_absolute_uri())
            creds = flow.credentials

            # Fetch user profile
            service = build("gmail", "v1", credentials=creds)
            profile = service.users().getProfile(userId="me").execute()
            email_address = profile.get("emailAddress")

            creds_dict = {
                "token": creds.token,
                "refresh_token": creds.refresh_token,
                "token_uri": creds.token_uri,
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "scopes": creds.scopes,
            }
            return email_address, creds_dict

        email_address, creds_dict = await asyncio.to_thread(fetch_credentials)

        # ---- run Django ORM safely inside async context ----
        await sync_to_async(GmailAccount.objects.update_or_create)(
            created_by=request.user,
            email_address=email_address,
            defaults={"creds": creds_dict, "active": True},
        )

        return redirect(return_to)
