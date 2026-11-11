from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Card, Category, PromotionDay, TableOrder, OrderPayment, TableOrderLine
from .order_pricing import eligible_product


MONDAY = date(2026, 11, 9)


class PromotionsDeliveryTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='delivery_customer')
        self.owner = User.objects.create_user(username='promo_owner')
        self.owner.profile.role = 'owner'
        self.owner.profile.save()
        self.kitchen = User.objects.create_user(username='promo_kitchen')
        self.kitchen.profile.role = 'kitchen'
        self.kitchen.profile.save()
        self.maki = Category.objects.create(name='Makimonos Especiales', area='kitchen')
        self.teppan = Category.objects.create(name='Teppanyaki and Teriyaki', area='kitchen')
        self.expensive = Card.objects.create(title='Tokyo Roll', price='300', category=self.maki, presentation='full')
        self.cheap = Card.objects.create(title='Avocado Roll', price='200', category=self.maki, presentation='full')
        self.half = Card.objects.create(title='Tokyo Roll (media orden)', price='170', category=self.maki, presentation='half')
        self.combo = Card.objects.create(title='Combinado', price='319', category=self.teppan, presentation='combo')
        for code in ('beef', 'chicken', 'shrimp'):
            Card.objects.create(title=code, category=self.teppan, presentation=code, price='250')
        self.promotion_day = PromotionDay.objects.create(date=MONDAY, eligible=True, updated_by=self.owner)
        self.address = {
            'recipient': 'Aldo Flores', 'phone': '5512345678', 'street': 'Calle Central',
            'number': '12', 'neighborhood': 'Centro', 'city': 'Ciudad de México',
            'state': 'Ciudad de México', 'postal_code': '06000', 'references': 'Puerta azul',
        }

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def line(self, card, quantity=1, **extra):
        return {'card_id': card.pk, 'quantity': quantity, **extra}

    def submit(self, lines, **extra):
        return self.client_for(self.customer).post('/table-orders/', {
            'table': '40', 'request_key': str(TableOrder.objects.count()), 'lines': lines, **extra,
        }, format='json')

    def quote(self, lines):
        return self.client_for(self.customer).post('/promotions/quote/', {'lines': lines}, format='json')

    @patch('tutorial.quickstart.order_pricing.business_date', return_value=MONDAY)
    def test_quote_mixes_rolls_and_excludes_half_orders(self, _):
        result = self.quote([self.line(self.expensive), self.line(self.cheap), self.line(self.half)])
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(Decimal(result.data['subtotal']), Decimal('670'))
        self.assertEqual(Decimal(result.data['discount']), Decimal('200'))
        self.assertEqual(Decimal(result.data['total']), Decimal('470'))
        result = self.quote([self.line(self.expensive, 3)])
        self.assertEqual(Decimal(result.data['discount']), Decimal('300'))

    def test_excluded_names_flags_and_calendar_policy(self):
        for title in ('Coco Roll', 'Don Jorge Roll', 'Roca Roll', 'Rocca Roll', 'Tesoro Roll', 'Crunchy Roll'):
            self.assertFalse(eligible_product(Card.objects.create(title=title, category=self.maki, price='250')))
        self.expensive.monday_promotion_excluded = True
        self.expensive.title = 'Changed restaurant name'
        self.assertFalse(eligible_product(self.expensive))
        for day in (date(2026, 11, 10), date(2026, 11, 16)):
            with patch('tutorial.quickstart.order_pricing.business_date', return_value=day):
                result = self.quote([self.line(self.expensive, 2)])
                self.assertEqual(Decimal(result.data['discount']), Decimal('0'))
        self.promotion_day.eligible = False
        self.promotion_day.reason = 'School closure'
        self.promotion_day.save()
        with patch('tutorial.quickstart.order_pricing.business_date', return_value=MONDAY):
            self.assertEqual(Decimal(self.quote([self.line(self.cheap, 2)]).data['discount']), Decimal('0'))

    @patch('tutorial.quickstart.order_pricing.business_date', return_value=MONDAY)
    def test_discount_reaches_bill_payment_and_net_sales(self, _):
        result = self.submit([self.line(self.expensive), self.line(self.cheap)], tip_percent=10, expected_total='300')
        self.assertEqual(result.status_code, 201, result.data)
        order = TableOrder.objects.get(pk=result.data['id'])
        order.lines.update(status='served')
        self.promotion_day.eligible = False
        self.promotion_day.save()
        owner = self.client_for(self.owner)
        bill = owner.get('/business/bills/').data[0]
        self.assertEqual(Decimal(bill['total']), Decimal('300'))
        self.assertEqual(Decimal(bill['discount']), Decimal('200'))
        self.assertEqual(Decimal(bill['tip_suggestion']), Decimal('30'))
        payment = owner.post('/business/collect/', {
            'order_id': order.pk, 'expected_total': '300', 'cash_amount': '330',
            'card_amount': '0', 'cash_received': '400', 'tip_amount': '30',
        }, format='json')
        self.assertEqual(payment.status_code, 201, payment.data)
        self.assertEqual(payment.data['discount'], '200.00')
        self.assertEqual(payment.data['change'], '70.00')
        saved = OrderPayment.objects.get()
        self.assertEqual(saved.subtotal, Decimal('500'))
        self.assertEqual(sum(order.lines.values_list('discount_amount', flat=True)), Decimal('200'))
        report = owner.get('/business/summary/').data
        self.assertEqual(Decimal(report['total']), Decimal('300'))
        self.assertEqual(sum(Decimal(str(row['revenue'])) for row in report['products']), Decimal('300'))
        history = self.client_for(self.customer).get(f'/table-orders/{order.pk}/').data
        self.assertTrue(history['pricing']['paid'])
        self.assertEqual(Decimal(history['pricing']['tip']), Decimal('30'))

    @patch('tutorial.quickstart.order_pricing.business_date', return_value=MONDAY)
    def test_stale_quote_rolls_back_order(self, _):
        result = self.submit([self.line(self.expensive), self.line(self.cheap)], expected_total='500')
        self.assertEqual(result.status_code, 400)
        self.assertFalse(TableOrder.objects.exists())

    def test_only_owner_can_confirm_school_calendar(self):
        payload = {'date': str(MONDAY), 'eligible': True}
        self.assertEqual(self.client_for(self.customer).post('/promotions/', payload, format='json').status_code, 403)
        self.assertEqual(self.client_for(self.owner).post('/promotions/', payload, format='json').status_code, 200)
        self.assertEqual(self.client_for(self.owner).post('/promotions/', {
            'date': '2026-11-10', 'eligible': True,
        }, format='json').status_code, 400)
        self.assertEqual(self.client_for(self.owner).post('/promotions/', {
            'date': str(MONDAY), 'eligible': False,
        }, format='json').status_code, 400)
        self.assertNotIn('calendar', self.client_for(self.customer).get('/promotions/').data)

    def test_combined_proteins_require_two_or_three_valid_choices(self):
        client = self.client_for(self.customer)
        profile = client.get(f'/cards/{self.combo.pk}/').data['order_profile']
        # Direct detail of a combined presentation must expose its protein choices.
        self.assertTrue(any(group['key'] == 'proteins' for group in profile['groups']))
        for proteins, expected in [(['beef'], 400), (['beef', 'ribeye'], 400), (['beef', 'chicken'], 201)]:
            result = self.submit([self.line(self.combo, choices={'proteins': proteins})])
            self.assertEqual(result.status_code, expected, result.data)
        result = self.submit([self.line(self.combo, choices={'proteins': ['beef', 'chicken', 'shrimp']})])
        self.assertEqual(result.status_code, 201, result.data)
        self.assertIn('Three proteins share the same portion; each portion may be smaller.', result.data['lines'][0]['selections'])
        self.assertEqual(result.data['lines'][0]['unit_price'], '319.00')

    def test_pickup_needs_no_table_and_address_validation_is_required(self):
        response = self.submit([self.line(self.cheap)], fulfillment='pickup')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(response.data['table'])
        self.assertEqual(self.submit([self.line(self.cheap)], fulfillment='delivery', address_confirmed=True).status_code, 400)
        invalid = {**self.address, 'phone': '123'}
        self.assertEqual(self.client_for(self.customer).patch('/me', {'address': invalid}, format='json').status_code, 400)

    def test_delivery_preparation_can_start_while_address_is_pending(self):
        client = self.client_for(self.customer)
        self.assertEqual(client.patch('/me', {'address': self.address}, format='json').status_code, 200)
        self.assertEqual(self.submit([self.line(self.cheap)], fulfillment='delivery').status_code, 400)
        created = self.submit([self.line(self.cheap)], fulfillment='delivery', address_confirmed=True)
        self.assertEqual(created.status_code, 201, created.data)
        order_id = created.data['id']
        self.assertEqual(created.data['delivery_status'], 'pending')
        client.patch('/me', {'address': {**self.address, 'street': 'New street'}}, format='json')
        self.assertEqual(client.get(f'/table-orders/{order_id}/').data['delivery_address']['street'], 'Calle Central')
        kitchen = self.client_for(self.kitchen)
        self.assertEqual(kitchen.get(f'/table-orders/{order_id}/').data['delivery_address'], {})
        line_id = created.data['lines'][0]['id']
        self.assertEqual(kitchen.post(f'/table-orders/{order_id}/line-status/', {'line_id': line_id, 'status': 'preparing'}, format='json').status_code, 200)
        owner = self.client_for(self.owner)
        self.assertEqual(owner.post(f'/table-orders/{order_id}/confirm-delivery/', {'accept': True}, format='json').status_code, 200)
        self.assertEqual(kitchen.post(f'/table-orders/{order_id}/line-status/', {'line_id': line_id, 'status': 'ready'}, format='json').status_code, 200)

    def test_owner_dispatches_ready_delivery_and_customer_tracks_it(self):
        customer = self.client_for(self.customer)
        customer.patch('/me', {'address': self.address}, format='json')
        created = self.submit([self.line(self.cheap)], fulfillment='delivery', address_confirmed=True)
        order_id = created.data['id']
        owner = self.client_for(self.owner)
        url = f'/table-orders/{order_id}/delivery-progress/'
        owner.post(f'/table-orders/{order_id}/confirm-delivery/', {'accept': True}, format='json')
        self.assertEqual(owner.post(url, {'status': 'dispatched'}, format='json').status_code, 400)
        TableOrder.objects.get(pk=order_id).lines.update(status='ready')
        self.assertEqual(customer.post(url, {'status': 'dispatched'}, format='json').status_code, 403)
        self.assertEqual(owner.post(url, {'status': 'delivered'}, format='json').status_code, 400)
        dispatched = owner.post(url, {'status': 'dispatched'}, format='json')
        self.assertEqual(dispatched.status_code, 200)
        order = customer.get(f'/table-orders/{order_id}/').data
        self.assertTrue(order['dispatched_at'])
        self.assertEqual(order['lines'][0]['status'], 'ready')
        self.assertEqual(owner.post(url, {'status': 'delivered'}, format='json').status_code, 200)
        self.assertEqual(customer.get(f'/table-orders/{order_id}/').data['lines'][0]['status'], 'served')

    def test_delivery_rejection_cancels_items(self):
        self.client_for(self.customer).patch('/me', {'address': self.address}, format='json')
        created = self.submit([self.line(self.cheap)], fulfillment='delivery', address_confirmed=True)
        owner = self.client_for(self.owner)
        response = owner.post(f"/table-orders/{created.data['id']}/confirm-delivery/", {'accept': False}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(line['status'] == 'declined' for line in response.data['lines']))
        self.assertFalse(owner.get('/business/bills/').data)

    def test_combo_choices_are_exposed_inside_grouped_presentations(self):
        root = Card.objects.create(title='Solo verduras', category=self.teppan, price='149',
                                   menu_title='Teppanyaki / Teriyaki', presentation='vegetables')
        self.combo.variant_of = root
        self.combo.save()
        client = self.client_for(self.customer)
        result = client.get(f'/cards/{root.pk}/').data
        combo = next(option for option in result['presentations'] if option['presentation'] == 'combo')
        self.assertEqual(combo['order_profile']['groups'][0]['min_count'], 2)
        detail = client.get(f'/cards/{self.combo.pk}/').data
        self.assertEqual(detail['order_profile']['groups'][0]['key'], 'proteins')

    def test_profile_accepts_address_from_mobile_multipart_form(self):
        import json
        response = self.client_for(self.customer).patch('/me', {
            'address': json.dumps({**self.address, 'phone': '+52 55 1234 5678'}),
            'first_name': 'Aldo',
        }, format='multipart')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['address']['phone'], '5512345678')
        self.assertEqual(response.data['address']['postal_code'], '06000')
