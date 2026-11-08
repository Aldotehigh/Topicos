from decimal import Decimal
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
import unicodedata

from django.db import transaction
from django.db.models.functions import TruncDate
from django.db.models import Count, Sum, F, Q, DecimalField, ExpressionWrapper, Exists, OuterRef
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from .models import (
    InventoryItem, InventoryMovement, OrderPayment, SupplyRequestItem,
    TableOrder, TableOrderLine,
)
from .roles import can_view_business, get_user_role
from .order_pricing import price_lines, order_price


class BusinessPermission(BasePermission):
    def has_permission(self, request, view):
        return can_view_business(request.user)


def key(text):
    return ''.join(
        char for char in unicodedata.normalize('NFKD', text.strip().casefold())
        if not unicodedata.combining(char)
    )


def inventory_identity(name, unit, area):
    unit_key = key(unit)
    aliases = {
        'kilos': 'kg', 'kilo': 'kg', 'kgs': 'kg',
        'litros': 'l', 'litro': 'l',
        'botellas': 'botella', 'piezas': 'pieza',
    }
    unit_key = aliases.get(unit_key, unit_key)
    return {'area': area, 'name_key': key(name), 'unit_key': unit_key}


def write_movement(item, user, kind, amount, reason, request_key, supply_item=None):
    item = InventoryItem.objects.select_for_update().get(pk=item.pk)
    previous = InventoryMovement.objects.filter(created_by=user, request_key=request_key).first()
    if previous:
        if previous.item_id != item.pk:
            raise ValidationError({'detail': 'This request key belongs to another inventory item.'})
        return previous
    delta = amount - item.quantity if kind == 'count' else -amount if kind == 'out' else amount
    balance = item.quantity + delta
    if balance < 0 or balance > Decimal('999999999.999'):
        raise ValidationError({'detail': 'The movement exceeds the available stock or stock limit.'})
    item.quantity = balance
    item.save(update_fields=['quantity'])
    return InventoryMovement.objects.create(
        item=item, kind=kind, delta=delta, balance=balance, reason=reason,
        created_by=user, request_key=request_key, supply_item=supply_item,
    )


def receive_supply(supply_item, user):
    # The caller changes the supply status and stock within the same transaction.
    if InventoryMovement.objects.filter(supply_item=supply_item).exists():
        return
    identity = inventory_identity(supply_item.name, supply_item.unit, supply_item.request.area)
    item, _ = InventoryItem.objects.get_or_create(
        **identity, defaults={'name': supply_item.name, 'unit': identity['unit_key']},
    )
    write_movement(item, user, 'receipt', supply_item.quantity, '',
                   f'supply-receipt-{supply_item.pk}', supply_item=supply_item)


class InventorySerializer(serializers.ModelSerializer):
    low_stock = serializers.SerializerMethodField()

    class Meta:
        model = InventoryItem
        fields = ('id', 'area', 'name', 'unit', 'quantity', 'minimum', 'low_stock')

    def get_low_stock(self, item):
        return item.quantity <= item.minimum


class InventoryInput(serializers.Serializer):
    area = serializers.ChoiceField(choices=['kitchen', 'bar', 'sushi'])
    name = serializers.CharField(max_length=100)
    unit = serializers.CharField(max_length=30)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal('0'))
    minimum = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal('0'))


class MovementInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=['in', 'out', 'count'])
    amount = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal('0'))
    reason = serializers.CharField(max_length=200, allow_blank=False)
    request_key = serializers.CharField(max_length=64)

    def validate(self, data):
        if data['kind'] != 'count' and data['amount'] == 0:
            raise ValidationError({'detail': 'Enter a quantity greater than zero.'})
        return data


class InventoryViewSet(viewsets.ReadOnlyModelViewSet):
    pagination_class = None
    permission_classes = [IsAuthenticated]
    serializer_class = InventorySerializer

    def get_queryset(self):
        role = get_user_role(self.request.user)
        queryset = InventoryItem.objects.order_by('area', 'name', 'id')
        if can_view_business(self.request.user):
            return queryset
        if role in ('kitchen', 'bar', 'sushi'):
            return queryset.filter(area=role)
        raise PermissionDenied()

    @transaction.atomic
    def create(self, request):
        if not can_view_business(request.user):
            raise PermissionDenied()
        serializer = InventoryInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        identity = inventory_identity(data['name'], data['unit'], data['area'])
        item, created = InventoryItem.objects.get_or_create(
            **identity, defaults={'name': data['name'], 'unit': identity['unit_key'], 'minimum': data['minimum']},
        )
        if not created:
            raise ValidationError({'detail': 'This stock item already exists. Register a movement.'})
        if data['quantity']:
            write_movement(item, request.user, 'opening', data['quantity'], '', f'opening-{item.pk}')
        item.refresh_from_db()
        return Response(self.get_serializer(item).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def movement(self, request, pk=None):
        if not can_view_business(request.user):
            raise PermissionDenied()
        serializer = MovementInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        item = self.get_object()
        write_movement(item, request.user, data['kind'], data['amount'], data['reason'], data['request_key'])
        item.refresh_from_db()
        return Response(self.get_serializer(item).data)

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        item = self.get_object()
        moves = item.movements.select_related('created_by', 'supply_item').order_by('-id')[:50]
        return Response([{
            'id': move.pk, 'kind': move.kind, 'delta': str(move.delta), 'balance': str(move.balance),
            'reason': move.reason, 'author': move.created_by.username, 'created_at': move.created_at,
            'supply_request_id': move.supply_item.request_id if move.supply_item_id else None,
        } for move in moves])

    @action(detail=True, methods=['post'])
    def threshold(self, request, pk=None):
        if not can_view_business(request.user):
            raise PermissionDenied()

        class ThresholdInput(serializers.Serializer):
            minimum = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=Decimal('0'))

        serializer = ThresholdInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = self.get_object()
        item.minimum = serializer.validated_data['minimum']
        item.save(update_fields=['minimum'])
        return Response(self.get_serializer(item).data)


class PaymentInput(serializers.Serializer):
    tip_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'), default=Decimal('0'))
    order_id = serializers.IntegerField(min_value=1)
    expected_total = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    cash_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'))
    card_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'))
    cash_received = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'))


def payment_data(payment):
    return {
        'id': payment.pk, 'order_id': payment.order_id, 'total': str(payment.total), 'tip_amount': str(payment.tip_amount), 'amount_collected': str(payment.total + payment.tip_amount),
        'subtotal': str(payment.subtotal), 'discount': str(payment.discount),
        'cash_amount': str(payment.cash_amount), 'card_amount': str(payment.card_amount),
        'cash_received': str(payment.cash_received),
        'change': str(payment.cash_received - payment.cash_amount), 'paid_at': payment.paid_at,
    }


class BusinessViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated, BusinessPermission]

    @action(detail=False, methods=['get'])
    def bills(self, request):
        payment = OrderPayment.objects.filter(order_id=OuterRef('pk'))
        orders = TableOrder.objects.annotate(paid=Exists(payment)).filter(paid=False).prefetch_related('lines').order_by('table', 'id')
        result = []
        for order in orders:
            lines = [line for line in order.lines.all() if line.status != 'declined']
            if not lines:
                continue
            pricing = order_price(order)
            total = Decimal(pricing['total'])
            result.append({
                'id': order.pk, 'table': order.table, 'created_at': order.created_at,
                'fulfillment': order.fulfillment, 'delivery_status': order.delivery_status, 'delivery_address': order.delivery_address,
                'subtotal': pricing['subtotal'], 'discount': pricing['discount'],
                'total': str(total), 'tip_suggestion': str((total * order.tip_percent / 100).quantize(Decimal('0.01'))), 'can_pay': total > 0 and order.delivery_status == 'accepted' and all(line.status == 'served' for line in lines),
                'lines': [{'title': line.title, 'quantity': line.quantity, 'price': str(line.unit_price), 'status': line.status} for line in lines],
            })
        return Response(result)

    @action(detail=False, methods=['post'])
    @transaction.atomic
    def collect(self, request):
        serializer = PaymentInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        order = TableOrder.objects.select_for_update().filter(pk=data['order_id']).first()
        if not order:
            raise ValidationError({'detail': 'The order does not exist.'})
        previous = OrderPayment.objects.filter(order=order).first()
        if previous:
            return Response(payment_data(previous))
        lines = list(order.lines.exclude(status='declined'))
        if not lines or any(line.status != 'served' for line in lines):
            raise ValidationError({'detail': 'Serve all items before collecting payment.'})
        if order.delivery_status != 'accepted':
            raise ValidationError({'detail': 'Confirm delivery before collecting payment.'})
        subtotal, discount, total, line_discounts = price_lines(lines, order.promotion_active)
        if total <= 0 or data['expected_total'] != total or data['cash_amount'] + data['card_amount'] != total + data['tip_amount']:
            raise ValidationError({'detail': 'The payment amounts must match the current bill.'})
        if data['cash_received'] < data['cash_amount'] or (data['cash_amount'] == 0 and data['cash_received'] != 0):
            raise ValidationError({'detail': 'Check the cash received.'})
        payment = OrderPayment.objects.create(
            order=order, total=total, subtotal=subtotal, discount=discount, tip_amount=data['tip_amount'], cash_amount=data['cash_amount'], card_amount=data['card_amount'],
            cash_received=data['cash_received'], recorded_by=request.user,
        )
        for line in lines:
            line.discount_amount = line_discounts.get(line.pk, Decimal('0'))
        TableOrderLine.objects.bulk_update(lines, ['discount_amount'])
        return Response(payment_data(payment), status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def summary(self, request):
        class RangeInput(serializers.Serializer):
            start = serializers.DateField(required=False)
            end = serializers.DateField(required=False)

        serializer = RangeInput(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        business_zone = ZoneInfo(getattr(settings, 'RESTAURANT_TIME_ZONE', 'America/Mexico_City'))
        today = timezone.now().astimezone(business_zone).date()
        start = serializer.validated_data.get('start', today)
        end = serializer.validated_data.get('end', today)
        if start > end:
            raise ValidationError({'detail': 'The start date must be before the end date.'})
        payments = OrderPayment.objects.filter(
            paid_at__gte=datetime.combine(start, time.min, tzinfo=business_zone),
            paid_at__lt=datetime.combine(end + timedelta(days=1), time.min, tzinfo=business_zone),
        )
        totals = payments.aggregate(total=Sum('total'), cash=Sum('cash_amount'), card=Sum('card_amount'), count=Count('id'), tips=Sum('tip_amount'), discounts=Sum('discount'))
        daily = [{
            'date': str(row['day']), 'total': str(row['total']), 'orders': row['orders'],
        } for row in payments.annotate(day=TruncDate('paid_at', tzinfo=business_zone)).values('day').annotate(
            total=Sum('total'), orders=Count('id'),
        ).order_by('day')]
        count = totals['count']
        revenue = totals['total'] or Decimal('0')
        amount = ExpressionWrapper(F('quantity') * F('unit_price') - F('discount_amount'), output_field=DecimalField(max_digits=14, decimal_places=2))
        lines = TableOrderLine.objects.filter(order__payment__in=payments).exclude(status='declined')
        products = list(lines.values('product_id', 'title').annotate(units=Sum('quantity'), revenue=Sum(amount)).order_by('-units', '-revenue')[:20])
        tables = list(payments.filter(order__table__isnull=False).values('order__table').annotate(total=Sum('total'), bills=Count('id')).order_by('-total'))
        pending_stock = InventoryItem.objects.filter(quantity__lte=F('minimum'))
        return Response({
            'start': str(start), 'end': str(end), 'timezone': str(business_zone), 'total': str(revenue),
            'cash': str(totals['cash'] or Decimal('0')), 'card': str(totals['card'] or Decimal('0')),
            'tip_total': str(totals['tips'] or Decimal('0')), 'collected_total': str(revenue + (totals['tips'] or Decimal('0'))), 'daily': daily,
            'discount_total': str(totals['discounts'] or Decimal('0')),
            'paid_orders': count, 'average_ticket': str((revenue / count).quantize(Decimal('0.01')) if count else Decimal('0')),
            'products': products, 'tables': tables,
            'pending_supplies': SupplyRequestItem.objects.exclude(status='received').count(),
            'low_stock': InventorySerializer(pending_stock.order_by('area', 'name'), many=True).data,
        })
