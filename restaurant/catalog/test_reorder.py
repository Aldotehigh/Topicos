from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient
from .models import Card, Category, TableOrder, TableOrderLine


class ReorderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='repeat_customer')
        self.other = User.objects.create_user(username='repeat_other')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.category = Category.objects.create(name='Reorder food', area='sushi')
        self.card = Card.objects.create(title='Sushi four', price='160', category=self.category, removable_ingredients='Onion')
        self.order = TableOrder.objects.create(customer=self.user, table='21', request_key='repeat-original')

    def line(self, **kwargs):
        data = dict(order=self.order, product=self.card, title=self.card.title, quantity=2,
                    unit_price='130', area='sushi', status='served', removals=['Onion'], allergy='Shrimp')
        data.update(kwargs)
        return TableOrderLine.objects.create(**data)

    def preview(self):
        return self.client.post(f'/table-orders/{self.order.pk}/reorder-preview/')

    def test_current_price_customizations_and_no_new_order(self):
        self.line()
        response = self.preview()
        self.assertEqual(response.status_code, 200, response.data)
        line = response.data['lines'][0]
        self.assertEqual((line['cardId'], line['price'], line['quantity']), (self.card.pk, '160.00', 2))
        self.assertTrue(line['price_changed'])
        self.assertEqual(line['removals'], ['Onion'])
        self.assertEqual(line['allergy'], 'Shrimp')
        self.preview()
        self.assertEqual(TableOrder.objects.count(), 1)
        self.assertEqual(TableOrderLine.objects.count(), 1)
        self.assertEqual(str(self.order.lines.get().unit_price), '130.00')

    def test_unavailable_deleted_declined_and_changed_removals(self):
        self.line(status='declined')
        self.line(product=None)
        self.line(removals=['Unlisted ingredient'])
        response = self.preview()
        self.assertEqual(len(response.data['unavailable']), 3)
        self.assertEqual(response.data['lines'], [])
        self.card.is_available = False
        self.card.save()
        self.line()
        self.assertEqual(len(self.preview().data['unavailable']), 4)

    def test_privacy_and_staff_restriction(self):
        self.line()
        self.client.force_authenticate(self.other)
        self.assertEqual(self.preview().status_code, 404)
        self.other.profile.role = 'sushi'
        self.other.profile.save()
        self.assertEqual(self.preview().status_code, 403)
        self.client.force_authenticate(None)
        self.assertIn(self.preview().status_code, (401, 403))

    def test_current_options_restored_and_missing_choices_not_guessed(self):
        self.card.order_kind = 'yaki_udon'
        self.card.save()
        self.line(selections=['Soba', 'Beef'])
        self.line(selections=['Udon', 'Removed protein'])
        response = self.preview().data
        self.assertEqual(response['lines'][0]['choices'], {'noodle': ['soba'], 'protein': ['beef']})
        self.assertEqual(len(response['unavailable']), 1)

    def test_variant_id_price_and_parent_availability(self):
        half = Card.objects.create(title='Half sushi', variant_of=self.card, price='95', presentation='half')
        self.line(product=half)
        line = self.preview().data['lines'][0]
        self.assertEqual(line['cardId'], half.pk)
        self.assertEqual(line['price'], '95.00')
        self.card.is_available = False
        self.card.save()
        self.assertEqual(self.preview().data['lines'], [])

    def test_selected_skewers_use_current_highest_price(self):
        self.category.name = 'Kushi Age'
        self.category.save()
        self.card.order_kind = 'kushi_mix'
        self.card.save()
        items = [Card.objects.create(title=f'Skewer {n}', category=self.category, price=price)
                 for n, price in enumerate(['50', '80', '70'])]
        self.line(selections=[item.title for item in items], removals=[])
        line = self.preview().data['lines'][0]
        self.assertEqual(line['price'], '80.00')
        self.assertEqual(line['choices']['skewers'], [str(item.pk) for item in items])
