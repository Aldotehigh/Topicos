from datetime import timedelta
from zoneinfo import ZoneInfo
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .addresses import AddressSerializer
from .models import DiningTable, Reservation
from .roles import get_user_role

# Reservations use the restaurant's local time regardless of the phone's zone.
RESTAURANT_ZONE = ZoneInfo('America/Mexico_City')


def manager(user):
    return get_user_role(user) in ('owner', 'admin')


class DiningTableSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiningTable
        fields = ('id', 'label', 'zone', 'capacity')


class DiningTableViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = DiningTableSerializer
    pagination_class = None
    queryset = DiningTable.objects.filter(active=True).order_by('zone', 'label')


class ReservationSerializer(serializers.ModelSerializer):
    table = DiningTableSerializer()
    class Meta:
        model = Reservation
        fields = ('id', 'table', 'party_size', 'contact_name', 'phone', 'starts_at', 'ends_at', 'status', 'notes', 'response_note')


class ReservationInput(serializers.Serializer):
    table_id = serializers.PrimaryKeyRelatedField(queryset=DiningTable.objects.filter(active=True), source='table')
    party_size = serializers.IntegerField(min_value=1, max_value=15)
    contact_name = serializers.CharField(min_length=2, max_length=100)
    phone = serializers.CharField(max_length=25)
    starts_at = serializers.DateTimeField(default_timezone=RESTAURANT_ZONE)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True, default='')
    request_key = serializers.CharField(max_length=64)

    def validate_phone(self, value):
        return AddressSerializer().validate_phone(value)

    def validate(self, data):
        if data['starts_at'] <= timezone.now():
            raise ValidationError({'detail': 'Choose a future time. Same-day reservations are allowed.'})
        if data['party_size'] > data['table'].capacity:
            raise ValidationError({'detail': 'The party exceeds this table capacity.'})
        return data


class ReservationViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ReservationSerializer
    pagination_class = None

    def get_queryset(self):
        queryset = Reservation.objects.select_related('table')
        if manager(self.request.user):
            return queryset
        if get_user_role(self.request.user) == 'customer':
            return queryset.filter(customer=self.request.user)
        raise PermissionDenied()

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        # Keep every active request, plus a bounded history.
        history = queryset.filter(status__in=['completed', 'cancelled', 'rejected']).order_by('-starts_at').values('pk')[:50]
        from django.db.models import Q
        return Response(self.get_serializer(queryset.filter(Q(status__in=['pending', 'confirmed', 'arrived']) | Q(pk__in=history)), many=True).data)

    @transaction.atomic
    def create(self, request):
        if get_user_role(request.user) != 'customer':
            raise PermissionDenied()
        key = request.data.get('request_key')
        previous = Reservation.objects.filter(customer=request.user, request_key=key).first() if isinstance(key, str) else None
        if previous:
            return Response(self.get_serializer(previous).data)
        serializer = ReservationInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking, created = Reservation.objects.get_or_create(customer=request.user, request_key=serializer.validated_data['request_key'], defaults={k:v for k,v in serializer.validated_data.items() if k!='request_key'})
        return Response(self.get_serializer(booking).data, status=201 if created else 200)

    @action(detail=True, methods=['post'], url_path='status')
    @transaction.atomic
    def change_status(self, request, pk=None):
        class StatusInput(serializers.Serializer):
            status = serializers.ChoiceField(choices=['confirmed', 'arrived', 'completed', 'cancelled', 'rejected'])
            duration_minutes = serializers.IntegerField(min_value=1, max_value=1440, required=False)
            response_note = serializers.CharField(max_length=300, required=False, allow_blank=True)
        payload = StatusInput(data=request.data)
        payload.is_valid(raise_exception=True)
        visible = self.get_object()
        # Serialize competing confirmations on the table, including SQLite writes.
        table = DiningTable.objects.select_for_update().get(pk=visible.table_id)
        DiningTable.objects.filter(pk=table.pk).update(capacity=F('capacity'))
        booking = Reservation.objects.select_for_update().get(pk=visible.pk)
        target = payload.validated_data['status']
        if booking.status == target:
            return Response(self.get_serializer(booking).data)
        is_manager = manager(request.user)
        if not is_manager and (target != 'cancelled' or booking.customer_id != request.user.pk):
            raise PermissionDenied()
        allowed = {'pending': ['confirmed', 'cancelled', 'rejected'], 'confirmed': ['arrived', 'cancelled'], 'arrived': ['completed']}
        if target not in allowed.get(booking.status, []):
            raise ValidationError({'detail': 'The reservation status has changed. Refresh the list.'})
        if not is_manager and booking.starts_at <= timezone.now():
            raise ValidationError({'detail': 'Contact the restaurant to change this reservation.'})
        if target == 'confirmed':
            duration = payload.validated_data.get('duration_minutes')
            if not duration:
                raise ValidationError({'detail': 'Enter the agreed table duration in minutes.'})
            if not table.active or booking.party_size > table.capacity or booking.starts_at <= timezone.now():
                raise ValidationError({'detail': 'Check the table capacity and reservation time.'})
            booking.ends_at = booking.starts_at + timedelta(minutes=duration)
            if Reservation.objects.filter(table=table, status__in=['confirmed', 'arrived'], starts_at__lt=booking.ends_at, ends_at__gt=booking.starts_at).exclude(pk=booking.pk).exists():
                raise ValidationError({'detail': 'This table already has a confirmed reservation at that time.'})
        if 'response_note' in payload.validated_data and is_manager:
            booking.response_note = payload.validated_data['response_note']
        booking.status = target
        booking.save(update_fields=['status', 'ends_at', 'response_note', 'updated_at'])
        return Response(self.get_serializer(booking).data)
