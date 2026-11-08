from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from .models import DiningTable, Reservation, Category, Card, TableOrder, TableOrderLine, InventoryItem


class ReservationsSushiTests(TestCase):
    def setUp(self):
        self.users = {}
        for role in ['customer', 'owner', 'kitchen', 'bar', 'sushi']:
            user = User.objects.create_user(username=role)
            user.profile.role = role; user.profile.save()
            self.users[role] = user
        self.other = User.objects.create_user(username='other')
        self.table = DiningTable.objects.get(label='60')
        self.starts = timezone.now() + timedelta(days=1)

    def client_for(self, role):
        client = APIClient(); client.force_authenticate(self.users[role]); return client

    def payload(self, key='first', **extra):
        return {'table_id': self.table.pk, 'party_size': 15, 'contact_name': 'Aldo Flores', 'phone': '5512345678', 'starts_at': self.starts.isoformat(), 'request_key': key, **extra}

    def reserve(self, key='first', **extra):
        return self.client_for('customer').post('/reservations/', self.payload(key, **extra), format='json')

    def step(self, pk, status, **extra):
        return self.client_for('owner').post(f'/reservations/{pk}/status/', {'status': status, **extra}, format='json')

    def test_tables_and_same_day_capacity(self):
        tables = self.client_for('customer').get('/dining-tables/').data
        self.assertEqual(len(tables), 24)
        self.assertEqual({row['label'] for row in tables if row['zone']=='terrace'}, {'40','41','42','52','73','70B','50','70A','80','81','72','51','71','60'})
        self.assertEqual(DiningTable.objects.get(label='21A').capacity, 4)
        now = timezone.make_aware(timezone.datetime(2026,11,8,12), timezone.get_current_timezone())
        with patch('tutorial.quickstart.reservations.timezone.now', return_value=now):
            result = self.reserve(starts_at=(now+timedelta(hours=1)).isoformat())
            self.assertEqual(result.status_code, 201, result.data)
            self.assertEqual(self.reserve('past', starts_at=(now-timedelta(minutes=1)).isoformat()).status_code, 400)
        self.assertEqual(self.reserve('too-many', party_size=16).status_code, 400)
        self.assertEqual(self.reserve('small', table_id=DiningTable.objects.get(label='40').pk).status_code, 400)
        self.assertEqual(self.reserve('phone', phone='123').status_code, 400)

    def test_confirmation_conflicts_and_adjacent_times(self):
        first = self.reserve().data['id']
        second = self.reserve('second').data['id']
        self.assertEqual(self.step(first,'confirmed').status_code,400)
        self.assertEqual(self.step(first,'confirmed',duration_minutes=90).status_code,200)
        self.assertEqual(self.step(second,'confirmed',duration_minutes=60).status_code,400)
        third = self.reserve('third', starts_at=(self.starts+timedelta(minutes=90)).isoformat()).data['id']
        self.assertEqual(self.step(third,'confirmed',duration_minutes=60).status_code,200)
        self.assertEqual(self.client_for('customer').post(f'/reservations/{first}/status/', {'status':'cancelled'},format='json').status_code,200)
        self.assertEqual(self.step(second,'confirmed',duration_minutes=60).status_code,200)
        self.assertEqual(self.step(second,'arrived').status_code,200)
        self.assertEqual(self.step(second,'completed').status_code,200)
        self.assertEqual(self.step(second,'confirmed',duration_minutes=60).status_code,400)

    def test_privacy_and_retry(self):
        result = self.reserve(); self.assertEqual(self.reserve().data['id'],result.data['id'])
        self.assertEqual(Reservation.objects.count(),1)
        client=APIClient();client.force_authenticate(self.other)
        self.assertEqual(client.get('/reservations/').data,[])
        self.assertEqual(client.get(f"/reservations/{result.data['id']}/").status_code,404)
        for role in ['sushi','kitchen','bar']:
            self.assertEqual(self.client_for(role).get('/reservations/').status_code,403)
        self.assertEqual(self.client_for('customer').post(f"/reservations/{result.data['id']}/status/",{'status':'confirmed','duration_minutes':60},format='json').status_code,403)

    def test_sushi_menu_permissions_queue_and_food_filter(self):
        sushi=Category.objects.create(name='Nigiris',area='sushi')
        kitchen=Category.objects.create(name='Hot food',area='kitchen')
        bar=Category.objects.create(name='Drinks',area='bar')
        food=Card.objects.create(title='Rice',category=kitchen,price='50')
        drink=Card.objects.create(title='Water',category=bar,price='20')
        client=self.client_for('sushi')
        created=client.post('/cards/',{'title':'Salmon','category_id':sushi.pk,'price':'70'},format='json')
        self.assertEqual(created.status_code,201,created.data)
        self.assertEqual(client.patch(f"/cards/{created.data['id']}/",{'price':'75'},format='json').status_code,200)
        self.assertEqual(client.patch(f'/cards/{food.pk}/',{'price':'1'},format='json').status_code,403)
        self.assertEqual(self.client_for('kitchen').patch(f"/cards/{created.data['id']}/",{'price':'1'},format='json').status_code,403)
        self.assertEqual(client.get('/me').data['area'],'sushi')
        menu=self.client_for('customer').get('/cards/?food_only=true').data['results']
        self.assertEqual({row['category']['area'] for row in menu},{'kitchen','sushi'})
        order=self.client_for('customer').post('/table-orders/',{'table':'70B','request_key':'areas','lines':[{'card_id':created.data['id'],'quantity':1},{'card_id':food.pk,'quantity':1},{'card_id':drink.pk,'quantity':1}]},format='json')
        self.assertEqual(order.status_code,201,order.data)
        for role in ['sushi','kitchen','bar']:
            queue=self.client_for(role).get('/table-orders/').data
            self.assertEqual({line['area'] for row in queue for line in row['lines']},{role})
            self.assertEqual(queue[0]['delivery_address'],{})
        line=client.get('/table-orders/').data[0]['lines'][0]
        self.assertEqual(client.post(f"/table-orders/{order.data['id']}/line-status/",{'line_id':line['id'],'status':'preparing'},format='json').status_code,200)
        self.assertEqual(self.client_for('customer').post('/table-orders/',{'table':'999','request_key':'bad','lines':[{'card_id':food.pk,'quantity':1}]},format='json').status_code,400)

    def test_sushi_supplies_and_inventory_are_private(self):
        client=self.client_for('sushi')
        result=client.post('/supply-requests/',{'area':'bar','required_by':timezone.localdate().isoformat(),'request_key':'sushi','items':[{'name':'Salmon','quantity':'2','unit':'kg','urgent':False}]},format='json')
        self.assertEqual(result.status_code,201,result.data)
        self.assertEqual(result.data['area'],'sushi')
        self.assertEqual(self.client_for('bar').get('/supply-requests/').data,[])
        InventoryItem.objects.create(area='sushi',name='Salmon',name_key='salmon',unit='kg',unit_key='kg')
        self.assertEqual({row['area'] for row in client.get('/inventory/').data},{'sushi'})
        self.assertEqual(self.client_for('bar').get('/inventory/').data,[])

    def test_delivery_and_pickup_do_not_wait_for_starters(self):
        for fulfillment in ['delivery','pickup']:
            order=TableOrder.objects.create(customer=self.users['customer'],request_key=fulfillment,fulfillment=fulfillment,delivery_status='pending' if fulfillment=='delivery' else 'accepted')
            TableOrderLine.objects.create(order=order,title='Starter',area='kitchen',course='starter',quantity=1,unit_price='20',status='received')
            main=TableOrderLine.objects.create(order=order,title='Sushi',area='sushi',quantity=1,unit_price='50',status='received')
            client=self.client_for('sushi')
            self.assertEqual(client.post(f'/table-orders/{order.pk}/line-status/',{'line_id':main.pk,'status':'preparing'},format='json').status_code,200)
            if fulfillment=='delivery':
                self.assertEqual(self.client_for('owner').post(f'/table-orders/{order.pk}/confirm-delivery/',{'accept':False},format='json').status_code,400)
                self.assertEqual(client.post(f'/table-orders/{order.pk}/line-status/',{'line_id':main.pk,'status':'ready'},format='json').status_code,200)
                self.assertEqual(client.post(f'/table-orders/{order.pk}/line-status/',{'line_id':main.pk,'status':'served'},format='json').status_code,400)

    def test_migration_routes_open_sushi_without_changing_history(self):
        from django.apps import apps
        from importlib import import_module
        from types import SimpleNamespace
        category = Category.objects.create(name='Sashimi', area='kitchen')
        product = Card.objects.create(title='Sashimi salmon', category=category, price='100')
        order = TableOrder.objects.create(customer=self.users['customer'], table='70A', request_key='legacy')
        def line(status, linked=True):
            return TableOrderLine.objects.create(order=order, product=product if linked else None, title=product.title, area='kitchen', quantity=1, unit_price='100', status=status)
        active = line('received'); historical = line('served'); legacy = line('review',False)
        import_module('tutorial.quickstart.migrations.0022_restaurant_tables').seed_restaurant(apps, SimpleNamespace(connection=SimpleNamespace(alias='default')))
        active.refresh_from_db();historical.refresh_from_db();legacy.refresh_from_db();category.refresh_from_db()
        self.assertEqual(category.area,'sushi')
        self.assertEqual(active.area,'sushi');self.assertEqual(legacy.area,'sushi')
        self.assertEqual(historical.area,'kitchen')
        self.assertEqual(DiningTable.objects.count(),24)
