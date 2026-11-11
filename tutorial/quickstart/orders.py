from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.db.models import Prefetch, Case, When, IntegerField, Exists, OuterRef, Q
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Card, TableOrder, TableOrderLine, DiningTable
from .roles import get_user_role
from .order_choices import resolve_order_options
from .order_pricing import current_promotion, eligible_product, order_price
from .addresses import AddressSerializer
from .roles import can_view_business


class OrderLineInput(serializers.Serializer):
    card_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=20)
    removals = serializers.ListField(
        child=serializers.CharField(max_length=80), required=False, max_length=20,
    )
    selections = serializers.ListField(
        child=serializers.CharField(max_length=32), required=False, max_length=3,
    )
    choices = serializers.DictField(child=serializers.ListField(child=serializers.CharField(max_length=32), max_length=3), required=False)
    allergy = serializers.CharField(max_length=200, required=False, allow_blank=True)


class OrderInput(serializers.Serializer):
    allergy_notice = serializers.CharField(max_length=180, required=False, allow_blank=True)
    tip_percent = serializers.ChoiceField(choices=[0, 10, 15, 20], default=0)
    fulfillment = serializers.ChoiceField(choices=['dine_in', 'pickup', 'delivery'], default='dine_in')
    address_confirmed = serializers.BooleanField(default=False)
    expected_total = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    table = serializers.CharField(max_length=8, required=False, allow_null=True)
    request_key = serializers.CharField(max_length=64)
    lines = OrderLineInput(many=True, allow_empty=False, max_length=30)

    def validate(self, data):
        if data['fulfillment'] == 'dine_in' and not data.get('table'):
            raise ValidationError({'detail': 'Enter a table number.'})
        if data['fulfillment'] == 'dine_in':
            data['table'] = data['table'].upper().strip()
            if not DiningTable.objects.filter(label=data['table'], active=True).exists():
                raise ValidationError({'detail': 'Choose an existing restaurant table.'})
        if data['fulfillment'] != 'dine_in':
            data['table'] = None
        data['delivery_address'] = {}
        if data['fulfillment'] == 'delivery':
            if not data['address_confirmed']:
                raise ValidationError({'detail': 'Confirm the delivery address before sending.'})
            profile = getattr(self.context['request'].user, 'profile', None)
            address = AddressSerializer(data=profile.address if profile else {})
            address.is_valid(raise_exception=True)
            data['delivery_address'] = address.validated_data
        return data


class OrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = TableOrderLine
        fields = ('id', 'title', 'quantity', 'unit_price', 'area', 'removals', 'selections', 'allergy', 'status', 'course')


class OrderSerializer(serializers.ModelSerializer):
    delivery_address = serializers.SerializerMethodField()
    pricing = serializers.SerializerMethodField()

    def get_delivery_address(self, order):
        role = get_user_role(self.context['request'].user)
        return order.delivery_address if role not in ('kitchen', 'bar', 'sushi') else {}

    def get_pricing(self, order):
        if get_user_role(self.context['request'].user) in ('kitchen', 'bar', 'sushi'):
            return None
        return order_price(order)

    lines = OrderLineSerializer(many=True)

    class Meta:
        model = TableOrder
        fields = ('id', 'table', 'created_at', 'lines', 'tip_percent', 'fulfillment', 'delivery_status', 'delivery_address', 'dispatched_at', 'pricing')


class TableOrderViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer

    def get_queryset(self):
        role = get_user_role(self.request.user)
        active_lines = TableOrderLine.objects.filter(
            order_id=OuterRef('pk'), status__in=['review', 'received', 'preparing', 'ready'],
        )
        if role in ('kitchen', 'bar', 'sushi'):
            active_lines = active_lines.filter(area=role)
        orders = TableOrder.objects.annotate(has_active_lines=Exists(active_lines)).order_by('-has_active_lines', 'id')
        lines = TableOrderLine.objects.annotate(
            course_priority=Case(When(course='starter', then=0), When(course='drink', then=1),
                                 When(course='main', then=2), default=3, output_field=IntegerField()),
        ).order_by('course_priority', 'id')
        if role in ('kitchen', 'bar', 'sushi'):
            orders = orders.filter(lines__area=role).distinct()
            lines = lines.filter(area=role)
        elif role not in ('admin', 'owner'):
            orders = orders.filter(customer=self.request.user)
        return orders.prefetch_related(Prefetch('lines', queryset=lines))

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        recent_closed = queryset.filter(has_active_lines=False).order_by('-id').values('pk')[:30]
        visible = queryset.filter(Q(has_active_lines=True) | Q(pk__in=recent_closed))
        return Response(self.get_serializer(visible, many=True).data)

    @transaction.atomic
    def create(self, request):
        if get_user_role(request.user) != 'customer':
            raise PermissionDenied()
        request_key = request.data.get('request_key') if hasattr(request.data, 'get') else None
        previous = TableOrder.objects.filter(customer=request.user, request_key=request_key).first() if isinstance(request_key, str) else None
        if previous:
            return Response(self.get_serializer(previous).data)
        serializer = OrderInput(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        order, created = TableOrder.objects.get_or_create(
            customer=request.user, request_key=payload['request_key'],
            defaults={
                'table': payload.get('table'), 'tip_percent': payload['tip_percent'],
                'fulfillment': payload['fulfillment'], 'delivery_address': payload['delivery_address'],
                'delivery_status': 'pending' if payload['fulfillment'] == 'delivery' else 'accepted',
                'promotion_active': current_promotion()['active'],
            },
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
                raise ValidationError({'detail': 'A presentation is no longer available.'})
            parent = card.variant_of or card
            area = parent.category.area if parent.category else None
            if area not in ('kitchen', 'bar', 'sushi'):
                raise ValidationError({'detail': 'An item has no assigned area.'})
            removals = list(dict.fromkeys(line.get('removals', [])))
            if set(removals) - set(card.allowed_removals or parent.allowed_removals):
                raise ValidationError({'detail': 'A customization is no longer available.'})
            profile, labels, price, needs_confirmation = resolve_order_options(
                card if card.presentation == 'combo' else parent, line.get('choices', {}), line.get('selections', []),
            )
            # A grouped presentation keeps its own price.
            if not profile['highest_price']:
                price = card.price
            if removals and not profile['show_removals']:
                raise ValidationError({'detail': 'This item does not allow ingredient removal.'})
            allergy = ' · '.join(filter(None, [line.get('allergy', ''), payload.get('allergy_notice', '')]))
            if len(allergy) > 200:
                raise ValidationError({'detail': 'Shorten the allergy notice to 200 characters.'})
            lines.append(TableOrderLine(
                order=order, product=card, title=card.title, promotion_eligible=eligible_product(card), quantity=line['quantity'], unit_price=price,
                area=area, removals=removals, allergy=allergy,
                selections=labels, course=profile['course'],
                status=TableOrderLine.Status.REVIEW if allergy or needs_confirmation else TableOrderLine.Status.RECEIVED,
            ))
        TableOrderLine.objects.bulk_create(lines)
        if 'expected_total' in payload and payload['expected_total'] != Decimal(order_price(order)['total']):
            raise ValidationError({'detail': 'Menu or promotion changed. Review the current total.'})
        return Response(self.get_serializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='line-status')
    @transaction.atomic
    def line_status(self, request, pk=None):
        role = get_user_role(request.user)
        if role not in ('admin', 'owner', 'kitchen', 'bar', 'sushi'):
            raise PermissionDenied()

        class StatusInput(serializers.Serializer):
            line_id = serializers.IntegerField(min_value=1)
            status = serializers.ChoiceField(choices=TableOrderLine.Status.choices)

        serializer = StatusInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        visible_order = self.get_object()
        order = TableOrder.objects.select_for_update().get(pk=visible_order.pk)
        line = TableOrderLine.objects.filter(order=order, pk=serializer.validated_data['line_id']).first()
        if not line or (role not in ('admin', 'owner') and role != line.area):
            raise PermissionDenied()
        target = serializer.validated_data['status']
        if order.fulfillment == 'delivery' and order.delivery_status != 'accepted' and target == 'served':
            raise ValidationError({'detail': 'The owner must confirm the delivery address first.'})
        if order.fulfillment == 'delivery' and target == 'served':
            raise ValidationError({'detail': 'The owner must complete delivery from the order.'})
        if order.fulfillment == 'dine_in' and target == 'preparing' and line.course in ('main', 'dessert') and order.lines.filter(
            course='starter',
        ).exclude(status__in=['served', 'declined']).exists():
            raise ValidationError({'detail': 'Serve the starters in this order first.'})
        allowed = {
            'review': ('received', 'declined'),
            'received': ('preparing', 'declined'),
            'preparing': ('ready', 'declined'),
            'ready': ('served',),
        }
        if target not in allowed.get(line.status, ()) or not TableOrderLine.objects.filter(
            pk=line.pk, status=line.status,
        ).update(status=target):
            raise ValidationError({'detail': 'The status has changed. Refresh the orders.'})
        return Response(self.get_serializer(self.get_object()).data)


    @action(detail=True, methods=['post'], url_path='confirm-delivery')
    @transaction.atomic
    def confirm_delivery(self, request, pk=None):
        if not can_view_business(request.user):
            raise PermissionDenied()

        class DeliveryInput(serializers.Serializer):
            accept = serializers.BooleanField()

        serializer = DeliveryInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        visible = self.get_object()
        order = TableOrder.objects.select_for_update().get(pk=visible.pk)
        if order.fulfillment != 'delivery':
            raise ValidationError({'detail': 'This order is not for delivery.'})
        target = 'accepted' if serializer.validated_data['accept'] else 'rejected'
        if order.delivery_status == target:
            return Response(self.get_serializer(order).data)
        if order.delivery_status != 'pending':
            raise ValidationError({'detail': 'This delivery has already been reviewed.'})
        if target == 'rejected' and order.lines.exclude(status__in=['review', 'received', 'declined']).exists():
            raise ValidationError({'detail': 'Preparation has started. Contact the customer before changing this delivery.'})
        order.delivery_status = target
        order.save(update_fields=['delivery_status'])
        if target == 'rejected':
            order.lines.update(status='declined')
        return Response(self.get_serializer(order).data)


    @action(detail=True, methods=['post'], url_path='delivery-progress')
    @transaction.atomic
    def delivery_progress(self, request, pk=None):
        if not can_view_business(request.user):
            raise PermissionDenied()
        visible = self.get_object()
        order = TableOrder.objects.select_for_update().get(pk=visible.pk)
        if order.fulfillment != 'delivery' or order.delivery_status != 'accepted':
            raise ValidationError({'detail': 'The owner must confirm the delivery address first.'})
        items = order.lines.exclude(status='declined')
        target = request.data.get('status')
        if target == 'dispatched':
            if not order.dispatched_at:
                if not items.filter(status='ready').exists() or items.exclude(status__in=['ready', 'served']).exists():
                    raise ValidationError({'detail': 'Wait until every available item is ready.'})
                order.dispatched_at = timezone.now()
                order.save(update_fields=['dispatched_at'])
        elif target == 'delivered':
            if not order.dispatched_at:
                raise ValidationError({'detail': 'Mark the order as dispatched first.'})
            items.filter(status='ready').update(status='served')
        else:
            raise ValidationError({'detail': 'Choose a valid delivery status.'})
        return Response(self.get_serializer(self.get_object()).data)
