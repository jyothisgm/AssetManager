from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Role

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


class UserCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["email", "password", "first_name", "last_name"]

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user
