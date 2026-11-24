from io import BytesIO
from decimal import Decimal
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from PIL import Image
from .models import Card, Category, DiningTable, TableOrder, TableOrderLine, OrderPayment


class CheckoutTests(TestCase):
    def setUp(self):
        self.users = {}
        for role in ['customer', 'owner', 'kitchen', 'bar', 'sushi']:
            user = User.objects.create_user(username=role)
            user.profile.role = role
            user.profile.save()
            self.users[role] = user
        self.category = Category.objects.create(name='Food', area='kitchen')
        self.product = Card.objects.create(title='Rice', category=self.category, price='100')
        self.table = DiningTable.objects.get(label='70B')

    def client_for(self, role):
        client = APIClient()
        client.force_authenticate(self.users[role])
        return client

    def order(self, method='transfer', fulfillment='delivery'):
        order = TableOrder.objects.create(customer=self.users['customer'], request_key=str(TableOrder.objects.count()),
            payment_method=method, fulfillment=fulfillment)
        TableOrderLine.objects.create(order=order, product=self.product, title='Rice', quantity=1,
            unit_price='100', area='kitchen', status='received')
        return order

    def image(self):
        data = BytesIO()
        Image.new('RGB', (8,8)).save(data, 'PNG')
        return SimpleUploadedFile('proof.png', data.getvalue(), content_type='image/png')

    def upload(self, order):
        return self.client_for('customer').post(f'/checkout/{order.pk}/proof/', {
            'receipt': self.image(), 'reference': 'BANK-123', 'expected_amount': '100',
        }, format='multipart')

    def test_qr_resolves_actual_table_and_routing(self):
        code = str(self.table.ordering_code)
        result = self.client_for('customer').post('/table-access/resolve/', {'code': code}, format='json')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data['label'], '70B')
        result = self.client_for('customer').post('/table-orders/', {
            'table_code': code, 'table': '999', 'request_key': 'qr',
            'payment_method': 'on_receipt', 'lines': [{'card_id':self.product.pk,'quantity':1}],
        }, format='json')
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(result.data['table'], '70B')
        self.table.active = False
        self.table.save()
        self.assertEqual(self.client_for('customer').post('/table-access/resolve/', {'code':code},format='json').status_code,400)
        self.assertEqual(self.client_for('customer').get('/table-access/').status_code,403)

    def test_bank_permissions_and_disabled_checkout(self):
        disabled = self.client_for('customer').get('/checkout/bank/')
        self.assertFalse(disabled.data['enabled'])
        self.assertEqual(self.client_for('customer').put('/checkout/bank/', {'enabled': False}, format='json').status_code,403)
        self.assertEqual(self.client_for('owner').put('/checkout/bank/', {'enabled': False}, format='json').status_code,200)
        result = self.client_for('customer').post('/table-orders/', {
            'fulfillment':'pickup', 'payment_method':'transfer', 'request_key':'bank',
            'lines':[{'card_id':self.product.pk,'quantity':1}],
        }, format='json')
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.client_for('owner').put('/checkout/bank/', {
            'enabled':True,'bank':'Bank','beneficiary':'Restaurant','clabe':'123',
        },format='json').status_code,400)

    def test_proof_private_manual_confirmation_and_idempotency(self):
        order = self.order()
        result = self.upload(order)
        self.assertEqual(result.status_code,200,result.data)
        self.assertEqual(result.data['transfer']['status'],'pending')
        self.assertFalse(result.data['pricing']['paid'])
        self.assertEqual(self.upload(order).status_code,400)
        for role in ['kitchen','bar','sushi']:
            self.assertEqual(self.client_for(role).get(f'/checkout/{order.pk}/proof-image/').status_code,403)
        result = self.client_for('owner').get(f'/checkout/{order.pk}/proof-image/')
        self.assertTrue(result.data['image'].startswith('data:image/png;base64,'))
        for fulfillment in ['dine_in','pickup','delivery']:
            current = order if fulfillment=='delivery' else self.order(fulfillment=fulfillment)
            if current != order:
                self.assertEqual(self.upload(current).status_code,200)
            reviewed = self.client_for('owner').post(f'/checkout/{current.pk}/review/',{'accept':True},format='json')
            self.assertEqual(reviewed.status_code,200,reviewed.data)
            self.assertTrue(reviewed.data['pricing']['paid'])
            self.assertEqual(self.client_for('owner').post(f'/checkout/{current.pk}/review/',{'accept':True},format='json').status_code,200)
            payment = OrderPayment.objects.get(order=current)
            self.assertEqual(payment.transfer_amount, Decimal('100'))
            self.assertEqual(payment.cash_amount,Decimal('0'))
            self.assertEqual(payment.card_amount,Decimal('0'))
        self.assertEqual(OrderPayment.objects.count(),3)
        line = order.lines.first()
        self.assertEqual(self.client_for('kitchen').post(f'/table-orders/{order.pk}/line-status/',{'line_id':line.pk,'status':'declined'},format='json').status_code,400)

    def test_amount_change_requires_rejection_and_new_proof(self):
        order = self.order()
        self.assertEqual(self.upload(order).status_code,200)
        order.lines.update(quantity=2)
        self.assertEqual(self.client_for('owner').post(f'/checkout/{order.pk}/review/',{'accept':True},format='json').status_code,400)
        self.assertFalse(OrderPayment.objects.exists())
        self.assertEqual(self.client_for('owner').post(f'/checkout/{order.pk}/review/',{'accept':False,'note':'Amount changed'},format='json').status_code,200)
        result = self.client_for('customer').post(f'/checkout/{order.pk}/proof/',{
            'receipt':self.image(),'reference':'NEW','expected_amount':'200',
        },format='multipart')
        self.assertEqual(result.status_code,200,result.data)

    def test_payment_link_is_per_order_and_validated(self):
        order = self.order(method='payment_link')
        url = f'/checkout/{order.pk}/link/'
        for value in ['http://mpago.la/abc','https://evil.example/pay','https://mpago.la.evil.example/pay']:
            self.assertEqual(self.client_for('owner').post(url,{'url':value},format='json').status_code,400)
        self.assertEqual(self.client_for('customer').post(url,{'url':'https://mpago.la/abc'},format='json').status_code,403)
        self.assertEqual(self.client_for('owner').post(url,{'url':'https://mpago.la/abc'},format='json').status_code,200)
        self.assertEqual(self.upload(order).status_code,200)
        self.assertEqual(self.client_for('owner').post(f'/checkout/{order.pk}/review/',{'accept':True},format='json').status_code,200)
        self.assertEqual(OrderPayment.objects.get(order=order).online_amount, Decimal('100'))
        self.assertEqual(OrderPayment.objects.get(order=order).transfer_amount, Decimal('0'))


    def test_tip_is_recorded_separately_and_another_customer_cannot_view_proof(self):
        order = self.order()
        uploaded = self.client_for('customer').post(f'/checkout/{order.pk}/proof/', {
            'receipt': self.image(), 'reference': 'TIP', 'expected_amount': '120', 'tip_amount': '20',
        }, format='multipart')
        self.assertEqual(uploaded.status_code, 200, uploaded.data)
        outsider = User.objects.create_user(username='another_customer')
        client = APIClient()
        client.force_authenticate(outsider)
        self.assertEqual(client.get(f'/checkout/{order.pk}/proof-image/').status_code, 403)
        confirmed = self.client_for('owner').post(f'/checkout/{order.pk}/review/', {'accept': True}, format='json')
        self.assertEqual(confirmed.status_code, 200, confirmed.data)
        self.assertEqual(confirmed.data['pricing']['grand_total'], '120.00')
        payment = OrderPayment.objects.get(order=order)
        self.assertEqual(payment.total, Decimal('100'))
        self.assertEqual(payment.tip_amount, Decimal('20'))
        self.assertEqual(payment.transfer_amount, Decimal('120'))
