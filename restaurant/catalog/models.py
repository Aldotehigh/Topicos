from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.validators import MinValueValidator
from decimal import Decimal
import uuid
from pathlib import Path
from django.conf import settings
from django.core.files.storage import FileSystemStorage


def private_receipt_storage():
    return FileSystemStorage(location=Path(settings.BASE_DIR) / 'private-payment-receipts')


class Category(models.Model):
    class Area(models.TextChoices):
        KITCHEN = 'kitchen', 'Kitchen'
        BAR = 'bar', 'Drinks bar'
        SUSHI = 'sushi', 'Sushi'

    area = models.CharField(
        'Area',
        max_length=10,
        choices=Area.choices,
        default=Area.KITCHEN,
    )
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = 'Category'
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name

class Card(models.Model):
    description_en = models.TextField('English description', blank=True)
    class Presentation(models.TextChoices):
        FULL = 'full', 'Full order'
        HALF = 'half', 'Half order'
        GLASS = 'glass', 'Glass'
        BOTTLE = 'bottle', 'Bottle'
        THIN = 'thin', 'Thin cut'
        THICK = 'thick', 'Thick cut'
        VEGETABLES = 'vegetables', 'Vegetables only'
        BEEF = 'beef', 'Beef fillet'
        CHICKEN = 'chicken', 'Chicken'
        WHITE_FISH = 'white_fish', 'White fish'
        SHRIMP = 'shrimp', 'Shrimp'
        OCTOPUS = 'octopus', 'Octopus'
        SALMON = 'salmon', 'Salmon'
        RIBEYE = 'ribeye', 'Thin-cut ribeye'
        COMBO = 'combo', 'Combination'
        GYO_BEEF = 'gyo_beef', 'Beef'
        EBI = 'ebi', 'Ebi (shrimp)'
        MIXED = 'mixed', 'Mixed'

    removable_ingredients = models.TextField(
        'Removable ingredients', blank=True, help_text='One ingredient per line.',
    )

    @property
    def allowed_removals(self):
        return list(dict.fromkeys(
            ingredient.strip() for ingredient in self.removable_ingredients.splitlines()
            if ingredient.strip()
        ))

    monday_promotion_excluded = models.BooleanField('Exclude from Monday two-for-one', default=False)
    order_kind = models.CharField(
        'Order customization type', max_length=12, blank=True,
        choices=[
            ('steak', 'Steak doneness'), ('bites_mix', 'Mixed bites'),
            ('kushi_mix', 'Mixed skewers'), ('edamame', 'Edamame preparation'),
            ('ramen', 'Ramen broth'), ('topping', 'Dessert topping'),
            ('yaki_udon', 'Yaki Udon noodles and protein'),
        ],
    )
    flavor = models.CharField('Flavor or protein', max_length=100, blank=True)
    menu_title = models.CharField('Menu name', max_length=100, blank=True)
    variant_of = models.ForeignKey(
        'self',
        verbose_name='Main menu item',
        null=True,
        blank=True,
        related_name='variants',
        on_delete=models.PROTECT,
        limit_choices_to={'variant_of__isnull': True},
    )
    presentation = models.CharField(
        'Presentation', max_length=10, choices=Presentation.choices, blank=True,
    )
    title = models.CharField(max_length=100)

    price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='cards',
        null=True,
        blank=True,
    )

    is_available = models.BooleanField(default=True)
    image = models.ImageField(upload_to='cards/', blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    favorited_by = models.ManyToManyField(User,
    related_name='favorite_cards',
    blank=True,
)

    class Meta:
        verbose_name = 'Menu item'
        verbose_name_plural = 'Menu items'
        constraints = [
            models.UniqueConstraint(
                fields=['variant_of', 'flavor', 'presentation'],
                name='unique_card_presentation_per_parent',
            ),
        ]

    def clean(self):
        super().clean()
        if self.variant_of_id is not None:
            parent = self.variant_of
            if parent.pk == self.pk or parent.variant_of_id:
                raise ValidationError({'variant_of': 'Choose a valid main menu item.'})
            if self.pk and self.variants.exists():
                raise ValidationError({'variant_of': 'This menu item already has presentations.'})
            if (self.presentation, self.flavor) == (parent.presentation, parent.flavor):
                raise ValidationError({'presentation': 'The presentation must differ from the main item.'})
        elif self.pk and self.variants.exists():
            if self.variants.filter(presentation=self.presentation, flavor=self.flavor).exists():
                raise ValidationError({'presentation': 'Choose a main presentation that differs from its variants.'})

    def __str__(self):
        return self.title
    

class Profile(models.Model):
    food_preferences = models.JSONField(default=dict, blank=True)
    class Role(models.TextChoices):
        OWNER = 'owner', 'Owner'
        CUSTOMER = 'customer', 'Customer'
        KITCHEN = 'kitchen', 'Kitchen manager'
        BAR = 'bar', 'Bar manager'
        SUSHI = 'sushi', 'Sushi manager'

    address = models.JSONField(default=dict, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(
        'Role', max_length=10, choices=Role.choices, default=Role.CUSTOMER,
        help_text='For administrator access, enable staff status on the user account.',
    )

    class Meta:
        verbose_name = 'Profile'
        verbose_name_plural = 'Profiles'

    def __str__(self):
        return self.user.username


@receiver(post_save, sender=User, dispatch_uid='catalog.create_user_profile')
def create_user_profile(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        Profile.objects.get_or_create(user=instance)


class TableOrder(models.Model):
    checkout_url = models.URLField(max_length=500, blank=True)
    payment_method = models.CharField(max_length=12, default='on_receipt', choices=[
        ('on_receipt', 'On receipt or at the register'), ('transfer', 'Bank transfer'),
        ('payment_link', 'Payment link'),
    ])

    dispatched_at = models.DateTimeField(null=True, blank=True)
    fulfillment = models.CharField(max_length=10, default='dine_in', choices=[
        ('dine_in', 'Dine-in'), ('pickup', 'Pickup'), ('delivery', 'Delivery'),
    ])
    delivery_status = models.CharField(max_length=8, default='accepted', choices=[
        ('pending', 'Pending confirmation'), ('accepted', 'Confirmed'), ('rejected', 'Rejected'),
    ])
    delivery_address = models.JSONField(default=dict, blank=True)
    promotion_active = models.BooleanField(default=False)
    tip_percent = models.PositiveSmallIntegerField(default=0, choices=[
        (0, 'No suggested tip'), (10, '10%'), (15, '15%'), (20, '20%'),
    ])
    customer = models.ForeignKey(User, on_delete=models.PROTECT, related_name='table_orders')
    table = models.CharField(max_length=8, null=True, blank=True)
    request_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['customer', 'request_key'], name='unique_table_order_request'),
        ]


class TableOrderLine(models.Model):
    food_preferences = models.JSONField(default=list, blank=True)
    promotion_eligible = models.BooleanField(default=False)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    class Status(models.TextChoices):
        REVIEW = 'review', 'Pending review'
        RECEIVED = 'received', 'Received'
        PREPARING = 'preparing', 'Preparing'
        READY = 'ready', 'Ready'
        DECLINED = 'declined', 'Rejected'
        SERVED = 'served', 'Served'

    product = models.ForeignKey(Card, null=True, blank=True, on_delete=models.SET_NULL)
    order = models.ForeignKey(TableOrder, on_delete=models.CASCADE, related_name='lines')
    title = models.CharField(max_length=100)
    area = models.CharField(max_length=10)
    course = models.CharField(max_length=10, default='main')
    quantity = models.PositiveSmallIntegerField()
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    removals = models.JSONField(default=list)
    selections = models.JSONField(default=list, blank=True)
    allergy = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)


class SupplyRequest(models.Model):
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='supply_requests')
    area = models.CharField(max_length=10, choices=[('kitchen', 'Kitchen'), ('bar', 'Drinks'), ('sushi', 'Sushi')])
    required_by = models.DateField()
    notes = models.TextField(blank=True)
    request_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['author', 'request_key'], name='unique_supply_request_key'),
        ]


class SupplyRequestItem(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PURCHASED = 'purchased', 'Purchased'
        RECEIVED = 'received', 'Received by department'

    request = models.ForeignKey(SupplyRequest, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=9, decimal_places=2)
    unit = models.CharField(max_length=30)
    urgent = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)


class OrderPayment(models.Model):
    online_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    transfer_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tip_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    order = models.OneToOneField(TableOrder, on_delete=models.PROTECT, related_name='payment')
    total = models.DecimalField(max_digits=12, decimal_places=2)
    cash_amount = models.DecimalField(max_digits=12, decimal_places=2)
    card_amount = models.DecimalField(max_digits=12, decimal_places=2)
    cash_received = models.DecimalField(max_digits=12, decimal_places=2)
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT)
    paid_at = models.DateTimeField(auto_now_add=True)


class InventoryItem(models.Model):
    area = models.CharField(max_length=10, choices=[('kitchen', 'Kitchen'), ('bar', 'Drinks'), ('sushi', 'Sushi')])
    name = models.CharField(max_length=100)
    name_key = models.CharField(max_length=150)
    unit = models.CharField(max_length=30)
    unit_key = models.CharField(max_length=60)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    minimum = models.DecimalField(max_digits=12, decimal_places=3, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['area', 'name_key', 'unit_key'], name='unique_inventory_item_unit'),
            models.CheckConstraint(check=models.Q(quantity__gte=0), name='inventory_nonnegative'),
        ]


class InventoryMovement(models.Model):
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name='movements')
    kind = models.CharField(max_length=10, choices=[
        ('opening', 'Opening balance'), ('in', 'Stock in'), ('out', 'Stock out'),
        ('count', 'Physical count'), ('receipt', 'Supply receipt'),
    ])
    delta = models.DecimalField(max_digits=12, decimal_places=3)
    balance = models.DecimalField(max_digits=12, decimal_places=3)
    reason = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT)
    request_key = models.CharField(max_length=64)
    supply_item = models.OneToOneField(SupplyRequestItem, null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['created_by', 'request_key'], name='unique_inventory_movement_request'),
        ]


class PromotionDay(models.Model):
    def clean(self):
        super().clean()
        if self.date and self.date.weekday() != 0:
            raise ValidationError({'date': 'This promotion is only available on Mondays.'})
        if not self.eligible and not self.reason.strip():
            raise ValidationError({'reason': 'Enter the holiday or school closure reason.'})

    date = models.DateField(unique=True)
    eligible = models.BooleanField(default=False)
    reason = models.CharField(max_length=200, blank=True)
    updated_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)


class DiningTable(models.Model):
    ordering_code = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    label = models.CharField(max_length=8, unique=True)
    zone = models.CharField(max_length=10, choices=[('terrace', 'Terrace'), ('salon', 'Dining room')])
    capacity = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    active = models.BooleanField(default=True)

    def __str__(self):
        return f'{self.get_zone_display()} · {self.label} · {self.capacity}'


class Reservation(models.Model):
    customer = models.ForeignKey(User, on_delete=models.PROTECT, related_name='reservations')
    table = models.ForeignKey(DiningTable, on_delete=models.PROTECT, related_name='reservations')
    party_size = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    contact_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=25)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, default='pending', choices=[
        ('pending', 'Pending confirmation'), ('confirmed', 'Confirmed'), ('arrived', 'Dine-in'),
        ('completed', 'Completed'), ('cancelled', 'Cancelled'), ('rejected', 'Rejected'),
    ])
    notes = models.CharField(max_length=300, blank=True)
    response_note = models.CharField(max_length=300, blank=True)
    request_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['customer', 'request_key'], name='unique_reservation_request'),
            models.CheckConstraint(check=models.Q(ends_at__isnull=True) | models.Q(ends_at__gt=models.F('starts_at')), name='reservation_positive_duration'),
        ]
        ordering = ['starts_at', 'id']


class BankTransferSettings(models.Model):
    enabled = models.BooleanField(default=False)
    bank = models.CharField(max_length=100, blank=True)
    beneficiary = models.CharField(max_length=150, blank=True)
    clabe = models.CharField(max_length=18, blank=True)
    instructions = models.CharField(max_length=300, blank=True)

    def clean(self):
        super().clean()
        if self.enabled:
            if not self.bank.strip() or not self.beneficiary.strip():
                raise ValidationError('Enter the bank and beneficiary.')
            digits = self.clabe.strip()
            if not digits.isdigit() or len(digits) != 18:
                raise ValidationError({'clabe': 'Enter an 18-digit CLABE.'})
            checksum = (10 - sum(int(digit) * (3, 7, 1)[index % 3] % 10 for index, digit in enumerate(digits[:17])) % 10) % 10
            if checksum != int(digits[-1]):
                raise ValidationError({'clabe': 'The CLABE check digit is invalid.'})

    def __str__(self):
        return self.bank


class TransferSubmission(models.Model):
    tip_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    order = models.OneToOneField(TableOrder, on_delete=models.PROTECT, related_name='transfer_submission')
    receipt = models.ImageField(upload_to='receipts/', storage=private_receipt_storage)
    reference = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, default='pending', choices=[
        ('pending', 'Pending verification'), ('approved', 'Verified'), ('rejected', 'Rejected'),
    ])
    note = models.CharField(max_length=300, blank=True)
    reviewed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)


class UserPreferences(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='restaurant_preferences')
    theme_mode = models.CharField(max_length=10, choices=[('system', 'System'), ('light', 'Light'), ('dark', 'Dark')], default='system')
    language = models.CharField(max_length=2, choices=[('es', 'Spanish'), ('en', 'English'), ('ja', 'Japanese')], default='es')
