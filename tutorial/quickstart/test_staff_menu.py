from io import BytesIO
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from .models import Card, Category
from .order_choices import get_order_profile


class StaffMenuTests(TestCase):
    def setUp(self):
        self.kitchen_user = User.objects.create_user(username='kitchen_editor')
        self.kitchen_user.profile.role = 'kitchen'
        self.kitchen_user.profile.save()
        self.kitchen = APIClient()
        self.kitchen.force_authenticate(self.kitchen_user)
        self.food_category = Category.objects.create(name='Entradas', area='kitchen')
        self.bar_category = Category.objects.create(name='Cerveza', area='bar')
        self.food = Card.objects.create(title='Sopa', category=self.food_category, price='90')
        self.beer = Card.objects.create(title='Corona', category=self.bar_category, price='53')

    def test_kitchen_can_create_and_edit_food_with_photo(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media)
        with override_settings(MEDIA_ROOT=media):
            response = self.kitchen.post('/cards/', {
                'title': 'Nueva entrada', 'description': 'Descripción',
                'price': '123.00', 'category_id': self.food_category.pk,
            }, format='json')
            self.assertEqual(response.status_code, 201, response.data)
            stream = BytesIO()
            Image.new('RGB', (4, 4), 'red').save(stream, format='PNG')
            response = self.kitchen.patch(f"/cards/{response.data['id']}/", {
                'title': 'Entrada editada', 'price': '150.00',
                'image': SimpleUploadedFile('dish.png', stream.getvalue(), content_type='image/png'),
            }, format='multipart')
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['price'], '150.00')
            self.assertTrue(response.data['image'].endswith('.png'))
            profile = self.kitchen.get('/me').data
            self.assertTrue(profile['can_edit_menu'])
            self.assertFalse(profile['can_manage_menu'])

    def test_kitchen_cannot_write_bar_move_category_or_delete(self):
        self.assertEqual(self.kitchen.patch(f'/cards/{self.beer.pk}/', {'price': '1'}, format='json').status_code, 403)
        self.assertEqual(self.kitchen.patch(f'/cards/{self.food.pk}/', {
            'category_id': self.bar_category.pk,
        }, format='json').status_code, 403)
        self.assertEqual(self.kitchen.post('/cards/', {
            'title': 'Invalid beer', 'category_id': self.bar_category.pk,
        }, format='json').status_code, 403)
        self.assertEqual(self.kitchen.delete(f'/cards/{self.food.pk}/').status_code, 403)
        self.food.refresh_from_db()
        self.assertEqual(self.food.category_id, self.food_category.pk)

    def test_alcohol_free_is_only_offered_for_cocktails(self):
        for name, enabled in [
            ('Cerveza', False), ('Ron', False), ('Whisky', False),
            ('Bebidas sin Alcohol', False), ('Cocteleria sin Alcohol', False),
            ('Cocteleria Tradicional', True),
        ]:
            category, _ = Category.objects.get_or_create(name=name, defaults={'area': 'bar'})
            item = Card.objects.create(title='Drink ' + name, category=category, price='100')
            profile = get_order_profile(item)
            self.assertEqual(profile['alcohol_free'], enabled)
            self.assertEqual(any(group['key'] == 'alcohol' for group in profile['groups']), enabled)

    def test_new_protein_joins_existing_group(self):
        category = Category.objects.create(name='Nigiris', area='kitchen')
        root = Card.objects.create(title='Shiromi', menu_title='Nigiris', flavor='Shiromi',
                                   category=category, price='39')
        response = self.kitchen.post('/cards/', {
            'title': 'Salmón especial', 'price': '65.00', 'category_id': category.pk,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        added = Card.objects.get(pk=response.data['id'])
        self.assertEqual(added.variant_of_id, root.pk)
        self.assertEqual(added.flavor, 'Salmón especial')
        self.assertEqual(Card.objects.filter(category=category, variant_of__isnull=True).count(), 1)
        duplicate = self.kitchen.post('/cards/', {
            'title': 'Salmón especial', 'price': '65.00', 'category_id': category.pk,
        }, format='json')
        self.assertEqual(duplicate.status_code, 400)
