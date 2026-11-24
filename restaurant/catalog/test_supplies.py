from datetime import timedelta
from io import BytesIO
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from .models import Card, Category, SupplyRequest, SupplyRequestItem


class SuppliesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for role in ('customer', 'kitchen', 'bar', 'admin'):
            user = User.objects.create_user(username='supplies_' + role, is_staff=role == 'admin')
            user.profile.role = role if role != 'admin' else 'customer'
            user.profile.save()
            cls.users[role] = user
        cls.food_category = Category.objects.create(name='Entradas', area='kitchen')
        cls.bar_category = Category.objects.create(name='Bebidas', area='bar')
        cls.food = Card.objects.create(title='Soup', category=cls.food_category, price='90')
        cls.drink = Card.objects.create(title='Lemonade', category=cls.bar_category, price='40')

    def client_for(self, role):
        client = APIClient()
        client.force_authenticate(self.users[role])
        return client

    def payload(self, key='request'):
        return {
            'required_by': str(timezone.localdate() + timedelta(days=1)),
            'request_key': key,
            'notes': 'For service',
            'items': [{'name': 'Lemons', 'quantity': '2.50', 'unit': 'kg', 'urgent': True}],
        }

    def report(self, role='bar', key='request'):
        response = self.client_for(role).post('/supply-requests/', self.payload(key), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def step(self, role, report, status):
        return self.client_for(role).post(f"/supply-requests/{report['id']}/item-status/", {
            'item_id': report['items'][0]['id'], 'status': status,
        }, format='json')

    def test_area_is_assigned_by_server_and_owner_receives_both(self):
        bar_payload = self.payload()
        bar_payload.update({'area': 'kitchen', 'author': self.users['admin'].pk})
        bar = self.client_for('bar').post('/supply-requests/', bar_payload, format='json')
        self.assertEqual(bar.status_code, 201)
        self.assertEqual(bar.data['area'], 'bar')
        self.assertEqual(bar.data['author_name'], self.users['bar'].username)
        self.report('kitchen')
        for role in ('kitchen', 'bar'):
            response = self.client_for(role).get('/supply-requests/')
            self.assertEqual({report['area'] for report in response.data}, {role})
        self.assertEqual(len(self.client_for('admin').get('/supply-requests/').data), 2)
        self.assertEqual(self.client_for('customer').get('/supply-requests/').status_code, 403)

    def test_submission_is_idempotent_and_rejects_invalid_input(self):
        report = self.report()
        repeated = self.client_for('bar').post('/supply-requests/', self.payload(), format='json')
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data['id'], report['id'])
        self.assertEqual(SupplyRequest.objects.count(), 1)
        self.assertEqual(SupplyRequestItem.objects.count(), 1)
        for role in ('customer', 'admin'):
            self.assertEqual(self.client_for(role).post('/supply-requests/', self.payload('forbidden'), format='json').status_code, 403)
        payload = self.payload('invalid')
        payload['items'][0]['quantity'] = '-1'
        self.assertEqual(self.client_for('bar').post('/supply-requests/', payload, format='json').status_code, 400)
        self.assertEqual(SupplyRequest.objects.count(), 1)

    def test_date_and_empty_lists_are_validated(self):
        for edits in (
            {'items': []},
            {'required_by': str(timezone.localdate() - timedelta(days=1))},
            {'required_by': '2026-99-99'},
        ):
            payload = {**self.payload(), **edits}
            self.assertEqual(self.client_for('kitchen').post('/supply-requests/', payload, format='json').status_code, 400)
        self.assertFalse(SupplyRequest.objects.exists())

    def test_purchase_and_receipt_enforce_roles_and_transitions(self):
        report = self.report()
        self.assertEqual(self.step('bar', report, 'purchased').status_code, 403)
        self.assertEqual(self.step('bar', report, 'received').status_code, 400)
        self.assertEqual(self.step('admin', report, 'purchased').status_code, 200)
        self.assertEqual(self.step('kitchen', report, 'received').status_code, 404)
        self.assertEqual(self.step('bar', report, 'received').status_code, 200)
        self.assertEqual(self.step('admin', report, 'purchased').status_code, 400)
        self.assertEqual(SupplyRequestItem.objects.get().updated_by_id, self.users['bar'].pk)

    def test_bar_can_manage_its_drinks_with_image_but_not_kitchen(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media)
        client = self.client_for('bar')
        self.assertTrue(client.get('/me').data['can_edit_menu'])
        with override_settings(MEDIA_ROOT=media):
            response = client.post('/cards/', {
                'title': 'Drink of the day', 'category_id': self.bar_category.pk, 'price': '85.00',
            }, format='json')
            self.assertEqual(response.status_code, 201, response.data)
            image = BytesIO()
            Image.new('RGB', (4, 4), 'blue').save(image, format='PNG')
            updated = client.patch(f"/cards/{response.data['id']}/", {
                'price': '95.00',
                'image': SimpleUploadedFile('drink.png', image.getvalue(), content_type='image/png'),
            }, format='multipart')
            self.assertEqual(updated.status_code, 200, updated.data)
            self.assertEqual(updated.data['price'], '95.00')
            self.assertTrue(updated.data['image'])
        self.assertEqual(client.patch(f'/cards/{self.food.pk}/', {'price': '1.00'}, format='json').status_code, 403)
        self.assertEqual(client.patch(f'/cards/{self.drink.pk}/', {'category_id': self.food_category.pk}, format='json').status_code, 403)
        self.assertEqual(self.client_for('kitchen').patch(f'/cards/{self.drink.pk}/', {'price': '1.00'}, format='json').status_code, 403)
