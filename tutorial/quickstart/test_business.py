from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (
    Card, Category, InventoryItem, InventoryMovement, OrderPayment, Profile,
    SupplyRequest, SupplyRequestItem, TableOrder, TableOrderLine,
)
from .business import inventory_identity


class BusinessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for role in ('owner', 'admin', 'kitchen', 'bar', 'customer'):
            user = User.objects.create_user(username='business_' + role, is_staff=role == 'admin')
            user.profile.role = role if role != 'admin' else 'customer'
            user.profile.save()
            cls.users[role] = user
        cls.category = Category.objects.create(name='Entradas', area='kitchen')
        cls.product = Card.objects.create(title='Edamame', category=cls.category, price='80')

    def client_for(self, role='owner'):
        client = APIClient()
        client.force_authenticate(self.users[role])
        return client

    def order(self, price='80', quantity=1, line_status='served', table=4):
        order = TableOrder.objects.create(customer=self.users['customer'], table=table, request_key=str(TableOrder.objects.count()))
        TableOrderLine.objects.create(
            order=order, product=self.product, title=self.product.title,
            unit_price=price, quantity=quantity, area='kitchen', status=line_status,
        )
        return order

    def payment(self, order, total='80.00', cash='30.00', card='50.00', received='50.00'):
        return self.client_for().post('/business/collect/', {
            'order_id': order.pk, 'expected_total': total,
            'cash_amount': cash, 'card_amount': card, 'cash_received': received,
        }, format='json')

    def inventory(self, area='kitchen', name='Limón', unit='kg', amount='5'):
        response = self.client_for().post('/inventory/', {
            'area': area, 'name': name, 'unit': unit, 'quantity': amount, 'minimum': '2',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def movement(self, item, kind, amount, key='move'):
        return self.client_for().post(f"/inventory/{item['id']}/movement/", {
            'kind': kind, 'amount': amount, 'reason': 'Service count',
            'request_key': key,
        }, format='json')

    def test_owner_is_distinct_and_does_not_require_staff_flag(self):
        data = self.client_for().get('/me').data
        self.assertEqual(data['role'], 'owner')
        self.assertTrue(data['can_view_business'])
        self.assertTrue(data['can_manage_menu'])
        self.assertTrue(data['can_edit_menu'])
        self.assertFalse(self.users['owner'].is_staff)
        self.users['owner'].is_staff = True
        self.users['owner'].save()
        self.assertEqual(self.client_for().get('/me').data['role'], 'owner')
        for role in ('admin', 'kitchen', 'bar', 'customer'):
            self.assertEqual(self.client_for(role).get('/business/summary/').status_code, 403)

    def test_customer_cannot_self_promote(self):
        self.assertEqual(self.client_for('customer').patch('/me', {'role': 'owner'}, format='json').status_code, 403)
        self.users['customer'].profile.refresh_from_db()
        self.assertEqual(self.users['customer'].profile.role, Profile.Role.CUSTOMER)

    def test_owner_manages_both_areas_and_supply_purchase(self):
        self.assertEqual(self.client_for().patch(f'/cards/{self.product.pk}/availability/', {'is_available': False}, format='json').status_code, 200)
        report = SupplyRequest.objects.create(
            author=self.users['bar'], area='bar', required_by=timezone.localdate(), request_key='report',
        )
        item = SupplyRequestItem.objects.create(request=report, name='Water', unit='bottles', quantity='2')
        self.assertEqual(self.client_for().get('/supply-requests/').status_code, 200)
        response = self.client_for().post(f'/supply-requests/{report.pk}/item-status/', {
            'item_id': item.pk, 'status': 'purchased',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)

    def test_mixed_payment_and_retry_keep_exact_amounts(self):
        order = self.order()
        result = self.payment(order)
        self.assertEqual(result.status_code, 201, result.data)
        self.assertEqual(result.data['change'], '20.00')
        self.assertEqual(result.data['total'], '80.00')
        repeated = self.payment(order)
        self.assertEqual(repeated.data['id'], result.data['id'])
        self.assertEqual(OrderPayment.objects.count(), 1)
        summary = self.client_for().get('/business/summary/').data
        self.assertEqual(Decimal(summary['total']), Decimal('80'))
        self.assertEqual(Decimal(summary['cash']), Decimal('30'))
        self.assertEqual(Decimal(summary['card']), Decimal('50'))
        self.assertEqual(summary['paid_orders'], 1)

    def test_unpaid_orders_and_declined_items_are_not_sales(self):
        self.order(price='200')
        order = self.order(price='80', quantity=2)
        TableOrderLine.objects.create(order=order, title='Declined', unit_price='500', quantity=1, area='bar', status='declined')
        self.assertEqual(self.payment(order, total='160', cash='160', card='0', received='200').status_code, 201)
        summary = self.client_for().get('/business/summary/').data
        self.assertEqual(Decimal(summary['total']), Decimal('160'))
        self.assertEqual(summary['products'][0]['units'], 2)
        self.assertEqual(summary['products'][0]['product_id'], self.product.pk)
        self.assertEqual(len(self.client_for().get('/business/bills/').data), 1)

    def test_service_and_payment_amounts_are_validated(self):
        pending = self.order(line_status='preparing')
        self.assertEqual(self.payment(pending).status_code, 400)
        order = self.order()
        self.assertEqual(self.payment(order, cash='20').status_code, 400)
        self.assertEqual(self.payment(order, received='10').status_code, 400)
        self.assertEqual(self.payment(order, total='90').status_code, 400)
        self.assertFalse(OrderPayment.objects.exists())
        self.assertEqual(self.client_for('bar').post('/business/collect/', {}, format='json').status_code, 403)

    def test_metrics_respect_date_range_and_empty_periods(self):
        result = self.payment(self.order())
        old = timezone.now() - timedelta(days=5)
        OrderPayment.objects.filter(pk=result.data['id']).update(paid_at=old)
        today = self.client_for().get('/business/summary/').data
        self.assertEqual(today['paid_orders'], 0)
        day = str(old.date())
        past = self.client_for().get('/business/summary/', {'start': day, 'end': day}).data
        self.assertEqual(past['paid_orders'], 1)
        self.assertEqual(self.client_for().get('/business/summary/', {'start': '2026-12-31', 'end': '2026-01-01'}).status_code, 400)

    def test_inventory_movements_are_audited_and_idempotent(self):
        item = self.inventory()
        first = self.movement(item, 'out', '2')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(Decimal(first.data['quantity']), Decimal('3'))
        again = self.movement(item, 'out', '2')
        self.assertEqual(Decimal(again.data['quantity']), Decimal('3'))
        self.assertEqual(InventoryMovement.objects.count(), 2)
        self.assertEqual(self.movement(item, 'out', '4', key='invalid').status_code, 400)
        self.assertEqual(self.movement(item, 'count', '1', key='count').status_code, 200)
        balance = InventoryItem.objects.get(pk=item['id'])
        self.assertEqual(balance.quantity, Decimal('1'))
        self.assertEqual(self.client_for().get('/inventory/').data[0]['low_stock'], True)

    def test_inventory_is_scoped_and_only_owner_can_change_it(self):
        food = self.inventory()
        self.inventory(area='bar', name='Soda', unit='bottles')
        self.assertEqual({item['area'] for item in self.client_for('bar').get('/inventory/').data}, {'bar'})
        self.assertEqual(self.client_for('customer').get('/inventory/').status_code, 403)
        self.assertEqual(self.client_for('kitchen').post(f"/inventory/{food['id']}/movement/", {}, format='json').status_code, 403)
        duplicate = self.client_for().post('/inventory/', {
            'area': 'kitchen', 'name': 'limon', 'unit': 'kilos', 'quantity': '10', 'minimum': '0',
        }, format='json')
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(InventoryItem.objects.filter(area='kitchen').count(), 1)

    def test_supply_receipt_adds_stock_once_and_rolls_back_on_failure(self):
        item = self.inventory(area='bar')
        report = SupplyRequest.objects.create(
            author=self.users['bar'], area='bar', required_by=timezone.localdate(), request_key='receipt',
        )
        supply = SupplyRequestItem.objects.create(request=report, name='limon', unit='kilos', quantity='2.5', status='purchased')
        url = f'/supply-requests/{report.pk}/item-status/'
        payload = {'item_id': supply.pk, 'status': 'received'}
        response = self.client_for('bar').post(url, payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(InventoryItem.objects.get(pk=item['id']).quantity, Decimal('7.5'))
        self.assertEqual(self.client_for('bar').post(url, payload, format='json').status_code, 400)
        self.assertEqual(InventoryMovement.objects.filter(supply_item=supply).count(), 1)
        InventoryItem.objects.filter(pk=item['id']).update(quantity='999999999.999')
        another = SupplyRequestItem.objects.create(request=report, name='Limón', unit='kg', quantity='1', status='purchased')
        response = self.client_for('bar').post(url, {'item_id': another.pk, 'status': 'received'}, format='json')
        self.assertEqual(response.status_code, 400)
        another.refresh_from_db()
        self.assertEqual(another.status, 'purchased')

    def test_sales_dates_follow_restaurant_timezone(self):
        paid = self.payment(self.order())
        late = datetime(2026, 11, 7, 23, 30, tzinfo=ZoneInfo('America/Mexico_City'))
        OrderPayment.objects.filter(pk=paid.data['id']).update(paid_at=late)
        response = self.client_for().get('/business/summary/', {'start': '2026-11-07', 'end': '2026-11-07'})
        self.assertEqual(response.data['paid_orders'], 1)
        response = self.client_for().get('/business/summary/', {'start': '2026-11-08', 'end': '2026-11-08'})
        self.assertEqual(response.data['paid_orders'], 0)
