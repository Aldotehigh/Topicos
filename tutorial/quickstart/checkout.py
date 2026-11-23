import base64
from io import BytesIO
from urllib.parse import urlparse
from decimal import Decimal
from django.db import transaction
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import BankTransferSettings, DiningTable, TableOrder, TransferSubmission, OrderPayment
from .roles import can_view_business, get_user_role
from .order_pricing import order_price, price_lines
from .orders import OrderSerializer


class BankSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankTransferSettings
        fields = ('enabled', 'bank', 'beneficiary', 'clabe', 'instructions')

    def validate(self, data):
        instance = BankTransferSettings(**data)
        try:
            instance.full_clean(exclude=['id'])
        except Exception as error:
            from django.core.exceptions import ValidationError as DjangoValidationError
            if isinstance(error, DjangoValidationError):
                raise ValidationError(error.message_dict)
            raise
        return data


class CheckoutViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def visible_order(self, pk):
        order = TableOrder.objects.select_for_update().filter(pk=pk).first()
        if not order:
            raise ValidationError({'detail': 'The order does not exist.'})
        if not can_view_business(self.request.user) and order.customer_id != self.request.user.pk:
            raise PermissionDenied()
        return order

    def result(self, order):
        order.refresh_from_db()
        return Response(OrderSerializer(order, context={'request': self.request}).data)

    @action(detail=False, methods=['get', 'put'], url_path='bank')
    def bank(self, request):
        settings = BankTransferSettings.objects.first()
        if request.method == 'PUT':
            if not can_view_business(request.user):
                raise PermissionDenied()
            serializer = BankSettingsSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            settings = BankTransferSettings.objects.update_or_create(
                pk=settings.pk if settings else 1, defaults=serializer.validated_data,
            )[0]
        if not settings or (not settings.enabled and not can_view_business(request.user)):
            return Response({'enabled': False})
        return Response(BankSettingsSerializer(settings).data)

    @action(detail=True, methods=['post'], url_path='proof')
    @transaction.atomic
    def proof(self, request, pk=None):
        order = self.visible_order(pk)
        if order.customer_id != request.user.pk:
            raise PermissionDenied()
        if order.payment_method not in ('transfer', 'payment_link') or hasattr(order, 'payment'):
            raise ValidationError({'detail': 'This order cannot accept another payment proof.'})

        class ProofInput(serializers.Serializer):
            receipt = serializers.ImageField()
            reference = serializers.CharField(max_length=100)
            tip_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'), default=Decimal('0'))
            expected_amount = serializers.DecimalField(max_digits=12, decimal_places=2)

            def validate_receipt(self, image):
                if image.size > 5 * 1024 * 1024 or image.image.format not in ('JPEG', 'PNG'):
                    raise ValidationError('Upload a JPEG or PNG smaller than 5 MB.')
                return image

        payload = ProofInput(data=request.data)
        payload.is_valid(raise_exception=True)
        total = Decimal(order_price(order)['total'])
        if total <= 0 or total + payload.validated_data['tip_amount'] != payload.validated_data['expected_amount']:
            raise ValidationError({'detail': 'The order amount changed. Refresh before sending proof.'})
        current = getattr(order, 'transfer_submission', None)
        if current and current.status != 'rejected':
            raise ValidationError({'detail': 'Your payment proof is already awaiting review.'})
        TransferSubmission.objects.update_or_create(order=order, defaults={
            'receipt': payload.validated_data['receipt'], 'reference': payload.validated_data['reference'],
            'amount': total + payload.validated_data['tip_amount'], 'tip_amount': payload.validated_data['tip_amount'], 'status': 'pending', 'note': '', 'reviewed_by': None,
        })
        return self.result(order)

    @action(detail=True, methods=['get'], url_path='proof-image')
    @transaction.atomic
    def proof_image(self, request, pk=None):
        order = self.visible_order(pk)
        proof = getattr(order, 'transfer_submission', None)
        if not proof:
            raise ValidationError({'detail': 'No payment proof has been uploaded.'})
        with proof.receipt.open('rb') as image:
            content = image.read()
        media = 'image/png' if content.startswith(b'\x89PNG') else 'image/jpeg'
        return Response({'image': 'data:' + media + ';base64,' + base64.b64encode(content).decode()})

    @action(detail=True, methods=['post'], url_path='review')
    @transaction.atomic
    def review(self, request, pk=None):
        if not can_view_business(request.user):
            raise PermissionDenied()
        order = self.visible_order(pk)

        class ReviewInput(serializers.Serializer):
            accept = serializers.BooleanField()
            note = serializers.CharField(max_length=300, required=False, allow_blank=True, default='')

        payload = ReviewInput(data=request.data)
        payload.is_valid(raise_exception=True)
        proof = TransferSubmission.objects.select_for_update().filter(order=order).first()
        if not proof:
            raise ValidationError({'detail': 'No payment proof has been uploaded.'})
        if proof.status == 'approved' and payload.validated_data['accept']:
            return self.result(order)
        if proof.status != 'pending' or hasattr(order, 'payment'):
            raise ValidationError({'detail': 'This payment has already been reviewed.'})
        if payload.validated_data['accept']:
            lines = list(order.lines.exclude(status='declined'))
            subtotal, discount, total, discounts = price_lines(lines, order.promotion_active)
            if not lines or proof.amount != total + proof.tip_amount:
                raise ValidationError({'detail': 'The order amount changed. Ask for a new proof.'})
            OrderPayment.objects.create(
                order=order, subtotal=subtotal, discount=discount, total=total, tip_amount=proof.tip_amount,
                cash_amount=Decimal('0'), card_amount=Decimal('0'), cash_received=Decimal('0'),
                transfer_amount=proof.amount if order.payment_method == 'transfer' else Decimal('0'),
                online_amount=proof.amount if order.payment_method == 'payment_link' else Decimal('0'),
                recorded_by=request.user,
            )
            for line in lines:
                line.discount_amount = discounts.get(line.pk, Decimal('0'))
            from .models import TableOrderLine
            TableOrderLine.objects.bulk_update(lines, ['discount_amount'])
            proof.status = 'approved'
        else:
            proof.status = 'rejected'
        proof.note = payload.validated_data['note']
        proof.reviewed_by = request.user
        proof.save(update_fields=['status', 'note', 'reviewed_by', 'updated_at'])
        return self.result(order)

    @action(detail=True, methods=['post'], url_path='link')
    @transaction.atomic
    def link(self, request, pk=None):
        if not can_view_business(request.user):
            raise PermissionDenied()
        order = self.visible_order(pk)

        class LinkInput(serializers.Serializer):
            url = serializers.URLField(max_length=500)

            def validate_url(self, value):
                parsed = urlparse(value)
                providers = ('mercadopago.com.mx', 'mercadopago.com', 'mpago.la', 'buy.stripe.com',
                             'checkout.stripe.com', 'paypal.com', 'paypal.me')
                if parsed.scheme != 'https' or parsed.username or parsed.password or not any(
                    parsed.hostname == domain or parsed.hostname.endswith('.' + domain)
                    for domain in providers
                ):
                    raise ValidationError('Use an HTTPS payment link from Mercado Pago, Stripe or PayPal.')
                return value

        serializer = LinkInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        if order.payment_method != 'payment_link' or hasattr(order, 'payment'):
            raise ValidationError({'detail': 'This order cannot accept a payment link.'})
        order.checkout_url = serializer.validated_data['url']
        order.save(update_fields=['checkout_url'])
        return self.result(order)


class TableAccessViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'], url_path='resolve')
    def resolve(self, request):
        class CodeInput(serializers.Serializer):
            code = serializers.UUIDField()
        payload = CodeInput(data=request.data)
        payload.is_valid(raise_exception=True)
        table = DiningTable.objects.filter(ordering_code=payload.validated_data['code'], active=True).first()
        if not table:
            raise ValidationError({'detail': 'This table code is no longer available.'})
        return Response({'label': table.label, 'zone': table.zone, 'code': str(table.ordering_code)})

    def list(self, request):
        if not can_view_business(request.user):
            raise PermissionDenied()
        try:
            import qrcode
            import qrcode.image.svg
        except ImportError:
            raise ValidationError({'detail': 'Install the backend requirements to generate table QR codes.'})
        tables = []
        for table in DiningTable.objects.filter(active=True).order_by('zone', 'label'):
            url = 'myapp://join-table?code=' + str(table.ordering_code)
            qr = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
            output = BytesIO()
            qr.save(output)
            tables.append({'label': table.label, 'zone': table.zone,
                           'code': str(table.ordering_code), 'url': url, 'svg': output.getvalue().decode()})
        return Response(tables)
