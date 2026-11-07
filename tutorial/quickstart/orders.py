from django.db import transaction
from django.db.models import Prefetch
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Card, TableOrder, TableOrderLine
from .roles import get_user_role
from .order_choices import get_order_choice


class OrderLineInput(serializers.Serializer):
    card_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=20)
    removals = serializers.ListField(
        child=serializers.CharField(max_length=80), required=False, max_length=20,
    )
    selections = serializers.ListField(
        child=serializers.CharField(max_length=32), required=False, max_length=3,
    )
    allergy = serializers.CharField(max_length=200, required=False, allow_blank=True)


class OrderInput(serializers.Serializer):
    table = serializers.IntegerField(min_value=1, max_value=999)
    request_key = serializers.CharField(max_length=64)
    lines = OrderLineInput(many=True, allow_empty=False, max_length=30)


class OrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = TableOrderLine
        fields = ('id', 'title', 'quantity', 'unit_price', 'area', 'removals', 'selections', 'allergy', 'status')


class OrderSerializer(serializers.ModelSerializer):
    lines = OrderLineSerializer(many=True)

    class Meta:
        model = TableOrder
        fields = ('id', 'table', 'created_at', 'lines')


class TableOrderViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer

    def get_queryset(self):
        role = get_user_role(self.request.user)
        orders = TableOrder.objects.order_by('-id')
        lines = TableOrderLine.objects.order_by('id')
        if role in ('kitchen', 'bar'):
            orders = orders.filter(lines__area=role).distinct()
            lines = lines.filter(area=role)
        elif role != 'admin':
            orders = orders.filter(customer=self.request.user)
        return orders.prefetch_related(Prefetch('lines', queryset=lines))

    def list(self, request, *args, **kwargs):
        return Response(self.get_serializer(self.get_queryset()[:30], many=True).data)

    @transaction.atomic
    def create(self, request):
        if get_user_role(request.user) != 'customer':
            raise PermissionDenied()
        serializer = OrderInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        order, created = TableOrder.objects.get_or_create(
            customer=request.user, request_key=payload['request_key'],
            defaults={'table': payload['table']},
        )
        if not created:
            return Response(self.get_serializer(order).data)

        cards = Card.objects.select_related('variant_of__category', 'category').in_bulk(
            {line['card_id'] for line in payload['lines']},
        )
        lines = []
        for line in payload['lines']:
            card = cards.get(line['card_id'])
            if not card or not card.is_available:
                raise ValidationError({'detail': 'Una presentación ya no está disponible.'})
            parent = card.variant_of or card
            area = parent.category.area if parent.category else None
            if area not in ('kitchen', 'bar'):
                raise ValidationError({'detail': 'Hay un producto sin área asignada.'})
            removals = list(dict.fromkeys(line.get('removals', [])))
            if set(removals) - set(parent.allowed_removals):
                raise ValidationError({'detail': 'Una personalización ya no está disponible.'})
            selections = line.get('selections', [])
            choice = get_order_choice(parent)
            options = {option['id']: option['label'] for option in choice['options']} if choice else {}
            if len(selections) != (choice['count'] if choice else 0) or set(selections) - options.keys():
                raise ValidationError({'detail': 'Revisa las opciones del platillo.'})
            allergy = line.get('allergy', '')
            lines.append(TableOrderLine(
                order=order, title=card.title, quantity=line['quantity'], unit_price=card.price,
                area=area, removals=removals, allergy=allergy,
                selections=[options[value] for value in selections],
                status=TableOrderLine.Status.REVIEW if allergy else TableOrderLine.Status.RECEIVED,
            ))
        TableOrderLine.objects.bulk_create(lines)
        return Response(self.get_serializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='line-status')
    @transaction.atomic
    def line_status(self, request, pk=None):
        role = get_user_role(request.user)
        if role not in ('admin', 'kitchen', 'bar'):
            raise PermissionDenied()

        class StatusInput(serializers.Serializer):
            line_id = serializers.IntegerField(min_value=1)
            status = serializers.ChoiceField(choices=TableOrderLine.Status.choices)

        serializer = StatusInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = self.get_object()
        line = TableOrderLine.objects.filter(order=order, pk=serializer.validated_data['line_id']).first()
        if not line or (role != 'admin' and role != line.area):
            raise PermissionDenied()
        target = serializer.validated_data['status']
        allowed = {
            'review': ('received', 'declined'),
            'received': ('preparing', 'declined'),
            'preparing': ('ready', 'declined'),
        }
        if target not in allowed.get(line.status, ()) or not TableOrderLine.objects.filter(
            pk=line.pk, status=line.status,
        ).update(status=target):
            raise ValidationError({'detail': 'El estado ya cambió. Actualiza los pedidos.'})
        return Response(self.get_serializer(self.get_object()).data)
