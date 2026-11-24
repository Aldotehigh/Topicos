from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient
from .models import Card, Category, TableOrderLine


class OrderFoodPreferencesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tampico_customer')
        self.user.profile.food_preferences = {'allergies': '', 'disliked_ingredients': ['No me gusta el Tampico']}
        self.user.profile.save()
        category = Category.objects.create(name='Rice preference test', area='kitchen')
        self.card = Card.objects.create(title='Culichi preference test', category=category, price='220')
        self.client = APIClient(); self.client.force_authenticate(self.user)

    def order(self, key='preference-order'):
        return self.client.post('/table-orders/', {
            'fulfillment': 'pickup', 'request_key': key,
            'lines': [{'card_id': self.card.pk, 'quantity': 1}],
        }, format='json')

    def test_free_text_preferences_reach_kitchen_without_removal_support(self):
        response = self.order()
        self.assertEqual(response.status_code, 201, response.data)
        line = response.data['lines'][0]
        self.assertEqual(line['food_preferences'], ['No me gusta el Tampico'])
        self.assertEqual(line['status'], 'review')
        self.assertEqual(line['removals'], [])
        operator = User.objects.create_user(username='tampico_kitchen')
        operator.profile.role = 'kitchen'; operator.profile.save()
        self.client.force_authenticate(operator)
        queue = self.client.get('/table-orders/').data
        self.assertEqual(queue[0]['lines'][0]['food_preferences'], ['No me gusta el Tampico'])

    def test_allergy_is_separate_and_preferences_are_snapshotted(self):
        self.user.profile.food_preferences['allergies'] = 'Atún'
        self.user.profile.save()
        response = self.order()
        line = response.data['lines'][0]
        self.assertEqual(line['allergy'], 'Atún')
        self.assertEqual(line['food_preferences'], ['No me gusta el Tampico'])
        self.user.profile.food_preferences = {'allergies': '', 'disliked_ingredients': ['Onion']}
        self.user.profile.save()
        again = self.order()
        self.assertEqual(again.data['lines'][0]['food_preferences'], ['No me gusta el Tampico'])
        self.assertEqual(TableOrderLine.objects.count(), 1)
        self.assertEqual(self.order('new-order').data['lines'][0]['food_preferences'], ['Onion'])

    def test_empty_preferences_do_not_require_extra_review(self):
        self.user.profile.food_preferences = {}; self.user.profile.save()
        line = self.order().data['lines'][0]
        self.assertEqual(line['food_preferences'], [])
        self.assertEqual(line['status'], 'received')

    def test_another_customer_does_not_inherit_preferences(self):
        other = User.objects.create_user(username='tampico_other')
        self.client.force_authenticate(other)
        self.assertEqual(self.order().data['lines'][0]['food_preferences'], [])
