from decimal import Decimal

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from .models import SupplyRequest, SupplyRequestItem
from .roles import get_user_role


class CanAccessSupplies(BasePermission):
    def has_permission(self, request, view):
        return get_user_role(request.user) in ('admin', 'owner', 'kitchen', 'bar', 'sushi')


class SupplyItemInput(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    quantity = serializers.DecimalField(max_digits=9, decimal_places=2, min_value=Decimal('0.01'))
    unit = serializers.CharField(max_length=30)
    urgent = serializers.BooleanField(default=False)


class SupplyInput(serializers.Serializer):
    required_by = serializers.DateField()
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    request_key = serializers.CharField(max_length=64)
    items = SupplyItemInput(many=True, allow_empty=False, max_length=30)

    def validate_required_by(self, value):
        if value < timezone.localdate():
            raise ValidationError('Choose today or a future service date.')
        return value


class SupplyItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplyRequestItem
        fields = ('id', 'name', 'quantity', 'unit', 'urgent', 'status', 'updated_at')


class SupplySerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source='author.username', read_only=True)
    items = SupplyItemSerializer(many=True)

    class Meta:
        model = SupplyRequest
        fields = ('id', 'author_name', 'area', 'required_by', 'notes', 'created_at', 'items')


class SupplyRequestViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated, CanAccessSupplies]
    serializer_class = SupplySerializer

    def get_queryset(self):
        role = get_user_role(self.request.user)
        pending = SupplyRequestItem.objects.filter(request_id=OuterRef('pk')).exclude(status='received')
        queryset = SupplyRequest.objects.select_related('author').prefetch_related('items').annotate(
            has_pending=Exists(pending),
        ).order_by('-has_pending', 'required_by', 'id')
        if role in ('kitchen', 'bar', 'sushi'):
            queryset = queryset.filter(area=role)
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        recent_closed = queryset.filter(has_pending=False).order_by('-id').values('pk')[:30]
        queryset = queryset.filter(Q(has_pending=True) | Q(pk__in=recent_closed))
        return Response(self.get_serializer(queryset, many=True).data)

    @transaction.atomic
    def create(self, request):
        role = get_user_role(request.user)
        if role not in ('kitchen', 'bar', 'sushi'):
            raise PermissionDenied()
        serializer = SupplyInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        report, created = SupplyRequest.objects.get_or_create(
            author=request.user, request_key=data['request_key'],
            defaults={'area': role, 'required_by': data['required_by'], 'notes': data.get('notes', '')},
        )
        if created:
            SupplyRequestItem.objects.bulk_create([
                SupplyRequestItem(request=report, **item) for item in data['items']
            ])
        return Response(self.get_serializer(report).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='item-status')
    @transaction.atomic
    def item_status(self, request, pk=None):
        role = get_user_role(request.user)

        class StatusInput(serializers.Serializer):
            item_id = serializers.IntegerField(min_value=1)
            status = serializers.ChoiceField(choices=SupplyRequestItem.Status.choices)

        serializer = StatusInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        visible = self.get_object()
        report = SupplyRequest.objects.select_for_update().get(pk=visible.pk)
        item = report.items.filter(pk=serializer.validated_data['item_id']).first()
        if not item:
            raise ValidationError({'detail': 'This item is not in the supply request.'})
        target = serializer.validated_data['status']
        if target == 'purchased' and role not in ('admin', 'owner'):
            raise PermissionDenied()
        if target == 'received' and role not in ('admin', 'owner', report.area):
            raise PermissionDenied()
        transitions = {'pending': 'purchased', 'purchased': 'received'}
        if target != transitions.get(item.status):
            raise ValidationError({'detail': 'The supply status has changed. Refresh the list.'})
        item.status = target
        item.updated_by = request.user
        item.save(update_fields=['status', 'updated_by', 'updated_at'])
        if target == 'received':
            from .business import receive_supply
            receive_supply(item, request.user)
        return Response(self.get_serializer(self.get_object()).data)
