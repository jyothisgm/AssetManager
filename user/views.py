from django.shortcuts import render
from rest_framework import viewsets, permissions
from django.contrib.auth import get_user_model
from .models import Role
from .serializers import UserSerializer, UserCreateSerializer, RoleSerializer
from .permissions import HasRolePermission
from common.logging_config import logger

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
