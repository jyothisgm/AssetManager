from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, permissions
from django.contrib.auth import get_user_model
from .models import Role
from .serializers import UserSerializer, UserCreateSerializer, RoleSerializer
from .permissions import HasRolePermission

User = get_user_model()


class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [permissions.IsAdminUser]


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    permission_classes = [permissions.IsAuthenticated, HasRolePermission]

    def get_serializer_class(self):
        if self.action in ["create", "update"]:
            return UserCreateSerializer
        return UserSerializer

    def get_queryset(self):
        user = self.request.user
        # Regular users see only themselves; admins see everyone
        if user.is_superuser:
            return User.objects.all()
        return User.objects.filter(id=user.id)
