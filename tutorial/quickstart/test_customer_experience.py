from decimal import Decimal
from io import BytesIO
import shutil
import tempfile

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import Card, Category, OrderPayment, TableOrder, TableOrderLine


class CustomerExperienceTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='profile_client', email='profile@example.test', password='ValidAccount882!')
        self.owner = User.objects.create_user(username='experience_owner')
        self.owner.profile.role = 'owner'
        self.owner.profile.save()
        self.category = Category.objects.create(name='Cerveza', area='bar')
        self.card = Card.objects.create(title='Corona', category=self.category, price='53')

    def client_for(self, user=None):
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def image(self):
        file = BytesIO()
        Image.new('RGB', (8, 8), 'green').save(file, format='PNG')
        return SimpleUploadedFile('avatar.png', file.getvalue(), content_type='image/png')

    def registration(self, **kwargs):
        return {
            'username': 'new_customer', 'email': 'new_customer@example.test',
            'first_name': 'Aldo', 'last_name': 'Flores',
            'password': 'SakuraProfile882!', 'password_confirm': 'SakuraProfile882!',
            **kwargs,
        }

    def test_registration_creates_customer_with_photo_and_token(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media)
        with override_settings(MEDIA_ROOT=media):
            response = self.client_for().post('/register/', self.registration(
                avatar=self.image(), role='owner', is_staff='true',
            ), format='multipart')
            self.assertEqual(response.status_code, 201, response.data)
            user = User.objects.get(pk=response.data['id'])
            self.assertEqual(user.profile.role, 'customer')
            self.assertFalse(user.is_staff)
            self.assertTrue(user.check_password('SakuraProfile882!'))
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION='Token ' + response.data['token'])
            profile = client.get('/me').data
            self.assertEqual(profile['first_name'], 'Aldo')
            self.assertTrue(profile['avatar'].endswith('.png'))

    def test_registration_validates_password_and_duplicate_email(self):
        for data in (
            self.registration(password_confirm='different'),
            self.registration(password='12345678', password_confirm='12345678'),
            self.registration(email='PROFILE@example.test'),
        ):
            response = self.client_for().post('/register/', data, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(User.objects.filter(username='new_customer').exists())

    def test_profile_update_and_invalid_photo_keep_permissions(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media)
        client = self.client_for(self.customer)
        with override_settings(MEDIA_ROOT=media):
            response = client.patch('/me', {'first_name': 'New name', 'avatar': self.image()}, format='multipart')
            self.assertEqual(response.status_code, 200, response.data)
            self.assertTrue(response.data['avatar'].endswith('.png'))
            bad = SimpleUploadedFile('avatar.png', b'not an image', content_type='image/png')
            self.assertEqual(client.patch('/me', {'first_name': 'Invalid', 'avatar': bad}, format='multipart').status_code, 400)
            self.customer.refresh_from_db()
            self.assertEqual(self.customer.first_name, 'New name')
            self.assertEqual(client.patch('/me', {'role': 'owner'}, format='json').status_code, 403)
            self.assertEqual(self.customer.profile.role, 'customer')

    def test_tip_suggestion_and_collection_keep_sales_separate(self):
        customer = self.client_for(self.customer)
        submitted = customer.post('/table-orders/', {
            'table': '40', 'request_key': 'tip', 'tip_percent': 15,
            'lines': [{'card_id': self.card.pk, 'quantity': 2}],
        }, format='json')
        self.assertEqual(submitted.status_code, 201, submitted.data)
        self.assertEqual(submitted.data['tip_percent'], 15)
        order = TableOrder.objects.get(pk=submitted.data['id'])
        order.lines.update(status='served')
        owner = self.client_for(self.owner)
        bill = owner.get('/business/bills/').data[0]
        self.assertEqual(Decimal(bill['tip_suggestion']), Decimal('15.90'))
        result = owner.post('/business/collect/', {
            'order_id': order.pk, 'expected_total': '106.00', 'tip_amount': '15.90',
            'cash_amount': '50.00', 'card_amount': '71.90', 'cash_received': '100.00',
        }, format='json')
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(result.data['change'], '50.00')
        self.assertEqual(result.data['amount_collected'], '121.90')
        report = owner.get('/business/summary/').data
        self.assertEqual(Decimal(report['total']), Decimal('106'))
        self.assertEqual(Decimal(report['tip_total']), Decimal('15.90'))
        self.assertEqual(Decimal(report['collected_total']), Decimal('121.90'))
        self.assertEqual(Decimal(report['daily'][0]['total']), Decimal('106'))
        self.assertEqual(report['products'][0]['units'], 2)

    def test_tip_is_optional_and_invalid_tip_does_not_charge(self):
        client = self.client_for(self.customer)
        self.assertEqual(client.post('/table-orders/', {
            'table': '40', 'request_key': 'invalid', 'tip_percent': 90,
            'lines': [{'card_id': self.card.pk, 'quantity': 1}],
        }, format='json').status_code, 400)
        self.assertFalse(TableOrder.objects.exists())
        order = TableOrder.objects.create(customer=self.customer, table=4, request_key='zero')
        TableOrderLine.objects.create(order=order, title='Dish', quantity=1, unit_price='100', area='kitchen', status='served')
        owner = self.client_for(self.owner)
        payload = {'order_id': order.pk, 'expected_total': '100', 'cash_amount': '100', 'card_amount': '0', 'cash_received': '100'}
        invalid = owner.post('/business/collect/', {**payload, 'tip_amount': '-1'}, format='json')
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(OrderPayment.objects.exists())
        paid = owner.post('/business/collect/', payload, format='json')
        self.assertEqual(paid.status_code, 201)
        self.assertEqual(Decimal(paid.data['tip_amount']), Decimal('0'))
