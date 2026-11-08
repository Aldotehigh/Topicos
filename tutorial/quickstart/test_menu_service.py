from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Card, Category, TableOrder, TableOrderLine


class MenuServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = User.objects.create_user(username='service_customer')
        cls.other = User.objects.create_user(username='service_other')
        cls.kitchen = User.objects.create_user(username='service_kitchen')
        cls.kitchen.profile.role = 'kitchen'
        cls.kitchen.profile.save()
        cls.bar = User.objects.create_user(username='service_bar')
        cls.bar.profile.role = 'bar'
        cls.bar.profile.save()
        cls.categories = {
            name: Category.objects.create(name=name, area=area)
            for name, area in [
                ('Entradas', 'kitchen'), ('Sopas y Ramen', 'kitchen'),
                ('Postres', 'kitchen'), ('Nigiris', 'kitchen'),
                ('Kushi Age', 'kitchen'), ('Cocteleria Tradicional', 'bar'),
                ('Ceviches', 'kitchen'),
            ]
        }
        cls.edamame = cls.card('Edamame', 'Entradas', '109')
        cls.ramen = cls.card('Ramen', 'Sopas y Ramen', '249')
        cls.dessert = cls.card('Tempura Helado', 'Postres', '130')
        cls.nigiri = cls.card('Ebi', 'Nigiris', '49')
        cls.drink = cls.card('Margarita', 'Cocteleria Tradicional', '120')
        cls.mix = cls.card('Mix Kushi Age', 'Kushi Age', '100')
        cls.skewers = [
            cls.card('Cheese Ebi Kushi Age', 'Kushi Age', '159', descripcion='Queso gouda y camarón'),
            cls.card('Ebi Kushi Age', 'Kushi Age', '149'),
            cls.card('Niku Kushi Age', 'Kushi Age', '169'),
        ]

    @classmethod
    def card(cls, title, category, price, **kwargs):
        return Card.objects.create(
            title=title, category=cls.categories[category], price=Decimal(price), order_kind={
                'Edamame': 'edamame', 'Ramen': 'ramen', 'Tempura Helado': 'topping',
                'Mix Kushi Age': 'kushi_mix',
            }.get(title, ''), **kwargs,
        )

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def submit(self, lines, key='request', **kwargs):
        return self.client_for(self.customer).post('/table-orders/', {
            'table': '40', 'request_key': key, 'lines': lines, **kwargs,
        }, format='json')

    def line(self, card, **kwargs):
        return {'card_id': card.pk, 'quantity': 1, **kwargs}

    def step(self, user, order_id, line_id, status):
        return self.client_for(user).post(f'/table-orders/{order_id}/line-status/', {
            'line_id': line_id, 'status': status,
        }, format='json')

    def test_edamame_and_ramen_require_real_choices(self):
        self.assertEqual(self.submit([self.line(self.edamame)]).status_code, 400)
        self.assertFalse(TableOrder.objects.exists())
        result = self.submit([
            self.line(self.edamame, choices={'cooking': ['grilled']}),
            self.line(self.ramen, choices={'broth': ['tonkotsu']}),
        ])
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(result.data['lines'][0]['selections'], ['Grilled'])
        self.assertEqual(result.data['lines'][1]['selections'], ['Tonkotsu'])

    def test_toppings_and_simple_item_profiles(self):
        client = self.client_for(self.customer)
        for card in (self.dessert, self.nigiri, self.drink):
            profile = client.get(f'/cards/{card.pk}/').data['order_profile']
            self.assertFalse(profile['show_allergy'])
            self.assertFalse(profile['show_removals'])
        result = self.submit([self.line(self.dessert, choices={'topping': ['none']})])
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.data['lines'][0]['selections'], ['No topping'])

    def test_skewer_mix_is_distinct_and_uses_highest_price(self):
        ids = [str(card.pk) for card in self.skewers]
        invalid = self.submit([self.line(self.mix, choices={'skewers': [ids[0]] * 3})])
        self.assertEqual(invalid.status_code, 400)
        result = self.submit([self.line(self.mix, choices={
            'skewers': ids, 'cheese': ['cream'],
        }, unit_price='0.01')])
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(result.data['lines'][0]['unit_price'], '169.00')
        self.assertIn('Replace gouda with cream cheese', result.data['lines'][0]['selections'])

    def test_unavailable_skewer_and_invalid_substitution_fail_atomically(self):
        self.skewers[0].is_available = False
        self.skewers[0].save()
        ids = [str(card.pk) for card in self.skewers]
        result = self.submit([self.line(self.mix, choices={'skewers': ids})])
        self.assertEqual(result.status_code, 400)
        self.assertFalse(TableOrder.objects.exists())
        result = self.submit([self.line(self.ramen, choices={'broth': ['miso'], 'cheese': ['cream']})])
        self.assertEqual(result.status_code, 400)

    def test_alcohol_free_request_waits_for_bar_confirmation(self):
        result = self.submit([self.line(self.drink, choices={'alcohol': ['without']})])
        self.assertEqual(result.status_code, 201)
        line = result.data['lines'][0]
        self.assertEqual(line['status'], 'review')
        self.assertEqual(line['unit_price'], '120.00')
        self.assertEqual(self.step(self.bar, result.data['id'], line['id'], 'preparing').status_code, 400)
        self.assertEqual(self.step(self.bar, result.data['id'], line['id'], 'received').status_code, 200)
        self.assertEqual(self.step(self.kitchen, result.data['id'], line['id'], 'preparing').status_code, 404)

    def test_starters_must_be_served_before_main_preparation(self):
        result = self.submit([
            self.line(self.ramen, choices={'broth': ['miso']}),
            self.line(self.edamame, choices={'cooking': ['steamed']}),
        ])
        order_id = result.data['id']
        main, starter = result.data['lines']
        self.assertEqual(self.step(self.kitchen, order_id, main['id'], 'preparing').status_code, 400)
        for target in ('preparing', 'ready'):
            self.assertEqual(self.step(self.kitchen, order_id, starter['id'], target).status_code, 200)
        self.assertEqual(self.step(self.kitchen, order_id, main['id'], 'preparing').status_code, 400)
        self.assertEqual(self.step(self.kitchen, order_id, starter['id'], 'served').status_code, 200)
        self.assertEqual(self.step(self.kitchen, order_id, main['id'], 'preparing').status_code, 200)
        self.assertEqual(self.step(self.customer, order_id, main['id'], 'ready').status_code, 403)

    def test_role_queues_are_private_unique_and_keep_old_active_orders(self):
        result = self.submit([
            self.line(self.ramen, choices={'broth': ['shoyu']}),
            self.line(self.drink),
        ], allergy_notice='Milk')
        self.assertEqual(result.status_code, 201)
        self.assertTrue(all(line['status'] == 'review' for line in result.data['lines']))
        for user, area in ((self.kitchen, 'kitchen'), (self.bar, 'bar')):
            queue = self.client_for(user).get('/table-orders/').data
            self.assertEqual(len(queue), 1)
            self.assertEqual({line['area'] for line in queue[0]['lines']}, {area})
        self.assertEqual(self.client_for(self.other).get('/table-orders/').data, [])
        repeat = self.submit([self.line(self.drink)], allergy_notice='Milk')
        self.assertEqual(repeat.data['id'], result.data['id'])
        self.assertEqual(TableOrder.objects.count(), 1)
        for index in range(31):
            self.submit([self.line(self.drink)], key=f'queue-{index}')
        queue = self.client_for(self.bar).get('/table-orders/').data
        self.assertEqual(len(queue), 32)
        self.assertEqual(len({order['id'] for order in queue}), 32)


    def test_two_dimensional_variants_keep_prices_and_favorites(self):
        category = self.categories['Ceviches']
        root = Card.objects.create(title='Pescado', menu_title='Ceviches', category=category,
                                   price='179', flavor='pescado', presentation='full')
        child = Card.objects.create(title='Camarón media', category=category, price='149',
                                    flavor='camarón', presentation='half', variant_of=root)
        child.full_clean()
        client = self.client_for(self.customer)
        items = client.get('/cards/', {'category': category.pk}).data['results']
        self.assertEqual(len(items), 1)
        self.assertEqual(len(items[0]['presentations']), 2)
        result = self.submit([self.line(child)])
        self.assertEqual(result.data['lines'][0]['unit_price'], '149.00')
        client.post(f'/cards/{child.pk}/favorite/')
        self.assertTrue(root.favorited_by.filter(pk=self.customer.pk).exists())
