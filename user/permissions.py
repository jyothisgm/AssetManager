from rest_framework.permissions import BasePermission
from common.logging_config import logger


class HasRolePermission(BasePermission):
    """
    Check if user has a specific role or permission.
    Example usage: permission_classes = [HasRolePermission]
    """

    required_roles = []
    required_perms = []

    def has_permission(self, request, view):
        func_name = f"{self.__class__.__name__}.has_permission"
        try:
            user = request.user
            logger.debug(f"[{func_name}] Checking permissions for user={user}")

            if user.is_superuser:
                logger.debug(f"[{func_name}] Superuser access granted")
                return True

            # Collect required roles and permissions from the view if present
            if getattr(view, "required_roles", None):
                self.required_roles = view.required_roles
                logger.debug(f"[{func_name}] Required roles from view: {self.required_roles}")
            if getattr(view, "required_perms", None):
                self.required_perms = view.required_perms
                logger.debug(f"[{func_name}] Required perms from view: {self.required_perms}")

            # Role-based permission check
            if any(role.name in self.required_roles for role in user.roles.all()):
                logger.info(f"[{func_name}] Role-based access granted to {user}")
                return True

            # Permission-based check
            if any(p.codename in self.required_perms for p in getattr(user, 'all_permissions', [])):
                logger.info(f"[{func_name}] Permission-based access granted to {user}")
                return True

            logger.warning(f"[{func_name}] Access denied for user={user}")
            return False

        except Exception as e:
            logger.exception(f"[{func_name}] Error checking permissions for user={getattr(request.user, 'email', None)}")
            raise e
