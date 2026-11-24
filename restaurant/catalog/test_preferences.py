from django.contrib.auth.models import User
from rest_framework.test import APITestCase
from .models import Card, Category

class RestaurantPreferencesTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('customer', password='Test-password123')
        self.other = User.objects.create_user('other', password='Test-password456')

    def test_preferences_require_authentication(self):
        self.assertEqual(self.client.get('/preferences/').status_code, 401)

    def test_two_settings_persist_and_are_isolated(self):
        self.client.force_authenticate(self.user)
        self.assertFalse(self.client.get('/preferences/').data['configured'])
        response = self.client.patch('/preferences/', {'theme_mode':'dark', 'language':'ja'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/preferences/').data['language'], 'ja')
        self.assertEqual(self.client.patch('/preferences/', {'language':'invalid'}, format='json').status_code,400)
        self.client.force_authenticate(self.other)
        self.assertFalse(self.client.get('/preferences/').data['configured'])
        self.assertEqual(self.client.get('/preferences/').data['language'], 'es')

    def test_english_description_is_searchable(self):
        category = Category.objects.create(name='Food')
        card = Card.objects.create(title='Example', price='100',category=category,description='Verduras', description_en='Grilled vegetables')
        self.client.force_authenticate(self.user)
        response = self.client.get('/cards/', {'search':'Grilled'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data['results'][0]['id'],card.id)

    def test_school_endpoints_are_removed(self):
        self.client.force_authenticate(self.user)
        for endpoint in ['alumnos','carreras','materias','inscripciones','imagenes']:
            self.assertEqual(self.client.get('/'+endpoint+'/').status_code,404)
