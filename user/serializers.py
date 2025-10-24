from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Role
from common.logging_config import logger

User = get_user_model()


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "name", "description", "permissions"]


class UserSerializer(serializers.ModelSerializer):
    roles = RoleSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "roles", "is_active", "is_verified"]

    def to_representation(self, instance):
        func_name = f"{self.__class__.__name__}.to_representation"
        try:
            logger.debug(f"[{func_name}] Serializing user: {instance.email}")
            return super().to_representation(instance)
        except Exception as e:
            logger.exception(f"[{func_name}] Error serializing user {getattr(instance, 'email', None)}")
            raise e


class UserCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["email", "password", "first_name", "last_name"]

    def create(self, validated_data):
        func_name = f"{self.__class__.__name__}.create"
        try:
            logger.info(f"[{func_name}] Creating user with email: {validated_data.get('email')}")
            user = User.objects.create_user(**validated_data)
            logger.debug(f"[{func_name}] User created successfully: {user.email}")
            return user
        except Exception as e:
            logger.exception(f"[{func_name}] Error creating user with data: {validated_data}")
            raise e
