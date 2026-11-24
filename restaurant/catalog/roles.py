from .models import Profile


def get_user_role(user):
    if user.is_authenticated:
        try:
            if user.profile.role == 'owner':
                return 'owner'
        except Profile.DoesNotExist:
            pass
    if user.is_staff or user.is_superuser:
        return 'admin'
    try:
        return user.profile.role
    except Profile.DoesNotExist:
        return Profile.Role.CUSTOMER


def can_view_business(user):
    return get_user_role(user) == 'owner' or user.is_superuser
