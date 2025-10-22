from rest_framework.permissions import BasePermission

class HasRolePermission(BasePermission):
    """
    Check if user has a specific role or permission.
    Example usage: permission_classes = [HasRolePermission]
    """

    required_roles = []
    required_perms = []

    def has_permission(self, request, view):
        user = request.user
        if user.is_superuser:
            return True

        if getattr(view, "required_roles", None):
            self.required_roles = view.required_roles
        if getattr(view, "required_perms", None):
            self.required_perms = view.required_perms

        if any(role.name in self.required_roles for role in user.roles.all()):
            return True
        if any(p.codename in self.required_perms for p in user.all_permissions):
            return True
        return False
