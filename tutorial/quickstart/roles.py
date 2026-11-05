from .models import Profile


def get_user_role(user):
    if user.is_staff or user.is_superuser:
        return 'admin'
    try:
        return user.profile.role
    except Profile.DoesNotExist:
        return Profile.Role.CUSTOMER
