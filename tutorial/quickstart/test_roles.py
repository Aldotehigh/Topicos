from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import Card, Category, Profile


class RolePermissionsTests(TestCase):
    def setUp(self):
        self.users = {}
        for role in ['customer', 'kitchen', 'bar', 'admin']:
            user = User.objects.create_user(
                username=role,
                password='Password123',
                is_staff=role == 'admin',
            )
            profile = user.profile
            profile.role = role if role != 'admin' else Profile.Role.CUSTOMER
            profile.save(update_fields=['role'])
            self.users[role] = user
        self.kitchen_category = Category.objects.create(name='Entradas', area='kitchen')
        self.bar_category = Category.objects.create(name='Bebidas', area='bar')
        self.food = Card.objects.create(title='Sopa', category=self.kitchen_category, price='95.00')
        self.drink = Card.objects.create(title='Limonada', category=self.bar_category, price='45.00')
        self.unassigned = Card.objects.create(title='Sin categoría', price='20.00')

    def client_for(self, role):
        client = APIClient()
        token, _ = Token.objects.get_or_create(user=self.users[role])
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        return client

    def test_profile_reports_effective_role(self):
        for role in self.users:
            with self.subTest(role=role):
                response = self.client_for(role).get('/me')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data['role'], role)
                self.assertEqual(response.data['can_manage_menu'], role == 'admin')

    def test_missing_profile_defaults_to_customer(self):
        self.users['customer'].profile.delete()
        response = self.client_for('customer').get('/me')
        self.assertEqual(response.data['role'], 'customer')

    def test_unauthenticated_requests_are_rejected(self):
        client = APIClient()
        for url in ['/me', '/cards/', '/categories/', '/cards/favorites/']:
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 401)

    def test_customer_and_bar_cannot_create_edit_or_delete_menu(self):
        for role in ['customer', 'bar']:
            client = self.client_for(role)
            with self.subTest(role=role):
                self.assertEqual(client.post('/cards/', {'title': 'New'}, format='json').status_code, 403)
                self.assertEqual(client.patch(f'/cards/{self.food.pk}/', {'price': '1.00'}, format='json').status_code, 403)
                self.assertEqual(client.delete(f'/cards/{self.food.pk}/').status_code, 403)
        self.food.refresh_from_db()
        self.assertEqual(str(self.food.price), '95.00')

    def test_admin_can_create_edit_and_delete(self):
        client = self.client_for('admin')
        response = client.post('/cards/', {
            'title': 'Nuevo', 'price': '80.00',
            'category_id': self.kitchen_category.pk,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        card_id = response.data['id']
        response = client.patch(f'/cards/{card_id}/', {'price': '90.00'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(client.delete(f'/cards/{card_id}/').status_code, 204)

    def test_staff_can_change_only_their_area(self):
        for role, allowed, denied in [
            ('kitchen', self.food, self.drink),
            ('bar', self.drink, self.food),
        ]:
            client = self.client_for(role)
            with self.subTest(role=role):
                response = client.patch(
                    f'/cards/{allowed.pk}/availability/',
                    {'is_available': False, 'title': 'Attempted rename'},
                    format='json',
                )
                self.assertEqual(response.status_code, 200, response.data)
                allowed.refresh_from_db()
                self.assertFalse(allowed.is_available)
                self.assertNotEqual(allowed.title, 'Attempted rename')
                self.assertEqual(client.patch(
                    f'/cards/{denied.pk}/availability/', {'is_available': False}, format='json',
                ).status_code, 403)
                self.assertEqual(client.patch(
                    f'/cards/{self.unassigned.pk}/availability/', {'is_available': False}, format='json',
                ).status_code, 403)

    def test_customer_cannot_change_availability(self):
        response = self.client_for('customer').patch(
            f'/cards/{self.food.pk}/availability/', {'is_available': False}, format='json',
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_can_change_any_area_and_availability_is_validated(self):
        client = self.client_for('admin')
        for card in [self.food, self.drink, self.unassigned]:
            response = client.patch(
                f'/cards/{card.pk}/availability/', {'is_available': False}, format='json',
            )
            self.assertEqual(response.status_code, 200)
        for payload in [{}, {'is_available': 'not-a-boolean'}]:
            response = client.patch(f'/cards/{self.food.pk}/availability/', payload, format='json')
            self.assertEqual(response.status_code, 400)

    def test_profile_cannot_escalate_privileges(self):
        client = self.client_for('customer')
        for field, value in [('role', 'admin'), ('is_staff', True), ('is_superuser', True), ('groups', [])]:
            response = client.patch('/me', {field: value}, format='json')
            self.assertEqual(response.status_code, 403)
        for url in ['/users/', '/groups/']:
            self.assertEqual(client.get(url).status_code, 403)
        self.users['customer'].refresh_from_db()
        self.assertFalse(self.users['customer'].is_staff)

    def test_registration_always_creates_customer(self):
        response = APIClient().post('/register/', {
            'username': 'newclient', 'email': 'new@example.test',
            'password': 'SakuraProfile882!', 'role': 'admin', 'is_staff': True,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        user = User.objects.get(username='newclient')
        self.assertEqual(user.profile.role, 'customer')
        self.assertFalse(user.is_staff)

    def test_favorites_remain_private_for_every_role(self):
        for role in self.users:
            client = self.client_for(role)
            self.assertEqual(client.post(f'/cards/{self.food.pk}/favorite/').status_code, 200)
            response = client.get('/cards/favorites/')
            self.assertEqual(response.data['count'], 1)
            self.assertEqual(client.delete(f'/cards/{self.food.pk}/favorite/').status_code, 200)
        self.client_for('customer').post(f'/cards/{self.food.pk}/favorite/')
        self.assertEqual(self.client_for('bar').get('/cards/favorites/').data['count'], 0)

    def test_profile_username_can_be_updated_without_email(self):
        response = self.client_for('customer').patch('/me', {'username': 'updated'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['username'], 'updated')
