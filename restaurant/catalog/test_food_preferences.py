from django.contrib.auth.models import User
from rest_framework.test import APITestCase
from .models import Card, Category, Profile, TableOrder


class FoodPreferencesTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user('food-customer',password='Password123')
        self.other = User.objects.create_user('other-customer',password='Password456')
        self.client.force_authenticate(self.user)
        self.card = Card.objects.create(title='Test dish',price='100',category=Category.objects.create(name='Test food'), removable_ingredients='Cebolla')

    def test_preferences_persist_from_mobile_multipart_and_stay_private(self):
        import json
        payload = {'allergies':'Camarón', 'disliked_ingredients':['Cebolla','Pepino']}
        response = self.client.patch('/me', {'food_preferences':json.dumps(payload)}, format='multipart')
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data['food_preferences'],payload)
        self.client.force_authenticate(None)
        login = self.client.post('/api-token-auth/', {'username':'food-customer','password':'Password123'}, format='json')
        self.client.credentials(HTTP_AUTHORIZATION='Token '+login.data['token'])
        self.assertEqual(self.client.get('/me').data['food_preferences'],payload)
        self.client.credentials()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get('/me').data['food_preferences'],{})

    def test_saved_allergy_reaches_kitchen_and_cannot_autostart_preparation(self):
        self.user.profile.food_preferences={'allergies':'Camarón','disliked_ingredients':['Cebolla']}
        self.user.profile.save()
        response=self.client.post('/table-orders/', {'table':'40','request_key':'saved-allergy','lines':[{'card_id':self.card.pk,'quantity':1}]},format='json')
        self.assertEqual(response.status_code,201,response.data)
        order=TableOrder.objects.get(pk=response.data['id'])
        line=order.lines.get()
        self.assertEqual(line.allergy,'Camarón')
        self.assertEqual(line.status,'review')

    def test_invalid_preferences_are_rejected_without_partial_updates(self):
        for payload in [{'allergies':'x'*181},{'disliked_ingredients':['item']*21},{'disliked_ingredients':[' ']},['not-an-object']]:
            response=self.client.patch('/me',{'food_preferences':payload},format='json')
            self.assertEqual(response.status_code,400,response.data)
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.food_preferences,{})
