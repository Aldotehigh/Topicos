from decimal import Decimal
from types import SimpleNamespace

from django.db import transaction
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Card, PromotionDay
from .roles import can_view_business
from .orders import OrderLineInput
from .order_choices import resolve_order_options
from .order_pricing import business_date, current_promotion, eligible_product, price_lines


class PromotionInput(serializers.Serializer):
    date = serializers.DateField()
    eligible = serializers.BooleanField()
    reason = serializers.CharField(max_length=200, allow_blank=True, required=False, default='')

    def validate(self, data):
        if data['date'].weekday() != 0:
            raise ValidationError({'detail': 'The promotion calendar only accepts Mondays.'})
        if not data['eligible'] and not data['reason'].strip():
            raise ValidationError({'detail': 'Explain the holiday or school closure.'})
        return data


class PromotionViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        result = current_promotion()
        if can_view_business(request.user):
            result['calendar'] = list(PromotionDay.objects.filter(date__gte=business_date()).order_by('date').values('date', 'eligible', 'reason'))
        return Response(result)

    @transaction.atomic
    def create(self, request):
        if not can_view_business(request.user):
            raise PermissionDenied()
        serializer = PromotionInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        PromotionDay.objects.update_or_create(
            date=data['date'], defaults={'eligible': data['eligible'], 'reason': data['reason'], 'updated_by': request.user},
        )
        return Response(current_promotion())

    @action(detail=False, methods=['post'])
    def quote(self, request):
        class QuoteInput(serializers.Serializer):
            lines = OrderLineInput(many=True, allow_empty=False, max_length=30)
            tip_percent = serializers.ChoiceField(choices=[0, 10, 15, 20], default=0)

        serializer = QuoteInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        cards = Card.objects.select_related('category', 'variant_of__category').in_bulk({line['card_id'] for line in data['lines']})
        lines = []
        for index, item in enumerate(data['lines']):
            card = cards.get(item['card_id'])
            if not card or not card.is_available:
                raise ValidationError({'detail': 'A presentation is no longer available.'})
            parent = card if card.presentation == 'combo' else card.variant_of or card
            profile, _, special_price, _ = resolve_order_options(parent, item.get('choices', {}), item.get('selections', []))
            lines.append(SimpleNamespace(
                id=index, quantity=item['quantity'],
                unit_price=special_price if profile['highest_price'] else card.price,
                promotion_eligible=eligible_product(card), status='received',
            ))
        promotion = current_promotion()
        subtotal, discount, total, _ = price_lines(lines, promotion['active'])
        tip = (total * data['tip_percent'] / 100).quantize(Decimal('0.01'))
        return Response({
            'subtotal': str(subtotal), 'discount': str(discount), 'total': str(total),
            'tip': str(tip), 'grand_total': str(total + tip), 'promotion_applied': discount > 0,
            'promotion': promotion,
        })
