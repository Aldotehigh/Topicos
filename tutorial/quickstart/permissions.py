from rest_framework import permissions

class IsAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user and request.user.is_staff

class IsOwnerOrReadOnly(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user.is_staff:
            return True

        if hasattr(obj, 'user'):
            return obj.user == request.user
        return obj == request.user



class CanManageMenu(permissions.BasePermission):
    message = 'Solo puedes gestionar los platillos de tu área.'

    def has_permission(self, request, view):
        from .roles import get_user_role
        if request.method in permissions.SAFE_METHODS:
            return True
        role = get_user_role(request.user)
        return role in ('admin', 'owner') or (
            role in ('kitchen', 'bar', 'sushi') and request.method in ('POST', 'PATCH', 'PUT')
        )

    def has_object_permission(self, request, view, obj):
        from .roles import get_user_role
        if request.method in permissions.SAFE_METHODS or get_user_role(request.user) in ('admin', 'owner'):
            return True
        category = (obj.variant_of or obj).category
        return bool(category and category.area == get_user_role(request.user))
