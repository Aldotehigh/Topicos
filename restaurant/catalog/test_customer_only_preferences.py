from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient


class CustomerOnlyPreferencesTests(TestCase):
    def test_customer_can_save_and_read_food_preferences(self):
        user = User.objects.create_user(username='food_customer')
        client = APIClient(); client.force_authenticate(user)
        preferences = {'allergies': 'Shrimp', 'disliked_ingredients': ['Onion']}
        response = client.patch('/me', {'food_preferences': preferences}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['food_preferences'], preferences)

    def test_operators_have_no_food_preferences_and_can_edit_profile(self):
        for role in ['kitchen', 'bar', 'sushi', 'owner', 'admin']:
            with self.subTest(role=role):
                user = User.objects.create_user(username='food_'+role, is_staff=role == 'admin')
                user.profile.role = role if role != 'admin' else 'customer'
                user.profile.food_preferences = {'allergies': 'Previous value'}
                user.profile.save()
                client = APIClient(); client.force_authenticate(user)
                self.assertEqual(client.get('/me').data['food_preferences'], {})
                response = client.patch('/me', {'food_preferences': {'allergies': 'Shrimp'}}, format='json')
                self.assertEqual(response.status_code, 400)
                response = client.patch('/me', {'first_name': 'Updated operator'}, format='json')
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data['first_name'], 'Updated operator')
                self.assertEqual(response.data['food_preferences'], {})
                user.profile.refresh_from_db()
                self.assertEqual(user.profile.food_preferences, {'allergies': 'Previous value'})
