from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import UserPreferences

class PreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreferences
        fields = ('theme_mode', 'language')

@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def preferences(request):
    instance = UserPreferences.objects.filter(user=request.user).first()
    if request.method == 'PATCH':
        serializer = PreferencesSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if instance is None:
            instance = serializer.save(user=request.user)
        else:
            instance = serializer.save()
    if instance is None:
        return Response({'theme_mode': 'system', 'language': 'es', 'configured': False})
    return Response({**PreferencesSerializer(instance).data, 'configured': True})
