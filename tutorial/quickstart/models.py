from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from decimal import Decimal

class Carrera(models.Model):
    nombre = models.CharField(max_length=100)
    clave = models.CharField(max_length=10, unique=True)
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nombre

class Materia(models.Model):
    nombre = models.CharField(max_length=100)
    clave = models.CharField(max_length=10, unique=True)
    creditos = models.IntegerField()
    carrera = models.ForeignKey(Carrera, on_delete=models.CASCADE, related_name='materias')

    def __str__(self):
        return self.nombre

class Alumno(models.Model):
    user = models.CharField(max_length=100)
    apellido_paterno = models.CharField(max_length=100, blank=True, null=True)
    apellido_materno = models.CharField(max_length=100, blank=True, null=True)
    numero_control = models.CharField(max_length=20, unique=True)
    email = models.EmailField(unique=True)
    carrera = models.ForeignKey(Carrera, on_delete=models.CASCADE, related_name='alumnos')

    def __str__(self):
        return self.user

class Imagen(models.Model):
    id_imagen = models.AutoField(primary_key=True)
    titulo = models.CharField(max_length=100)
    descripcion = models.TextField()
    imagen = models.ImageField(upload_to='imagenes/')


class Inscripcion(models.Model):
    alumno = models.ForeignKey(Alumno, on_delete=models.CASCADE, related_name='inscripciones')
    materia = models.ForeignKey(Materia, on_delete=models.CASCADE, related_name='inscripciones')
    fecha_inscripcion = models.DateTimeField(auto_now_add=True)
    calificacion = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    ciclo = models.CharField(max_length=11)

    class Meta:
        unique_together = ('alumno', 'materia')

    def __str__(self):
        return f"{self.alumno} - {self.materia}"

class Category(models.Model):
    class Area(models.TextChoices):
        KITCHEN = 'kitchen', 'Cocina'
        BAR = 'bar', 'Barra de bebidas'
        SUSHI = 'sushi', 'Sushi'

    area = models.CharField(
        'Área',
        max_length=10,
        choices=Area.choices,
        default=Area.KITCHEN,
    )
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = 'Categoría'
        verbose_name_plural = 'Categorías'

    def __str__(self):
        return self.name

class Card(models.Model):
    description_en = models.TextField('Descripción en inglés', blank=True)
    class Presentation(models.TextChoices):
        FULL = 'full', 'Orden completa'
        HALF = 'half', 'Media orden'
        GLASS = 'glass', 'Copa'
        BOTTLE = 'bottle', 'Botella'
        THIN = 'thin', 'Corte delgado'
        THICK = 'thick', 'Corte grueso'
        VEGETABLES = 'vegetables', 'Solo verduras'
        BEEF = 'beef', 'Filete de res'
        CHICKEN = 'chicken', 'Pollo'
        WHITE_FISH = 'white_fish', 'Pescado blanco'
        SHRIMP = 'shrimp', 'Camarón'
        OCTOPUS = 'octopus', 'Pulpo'
        SALMON = 'salmon', 'Salmón'
        RIBEYE = 'ribeye', 'Rib-eye corte fino'
        COMBO = 'combo', 'Combinado'
        GYO_BEEF = 'gyo_beef', 'Res'
        EBI = 'ebi', 'Ebi (camarón)'
        MIXED = 'mixed', 'Mixtas'

    removable_ingredients = models.TextField(
        'Ingredientes que se pueden quitar', blank=True, help_text='Un ingrediente por línea.',
    )

    @property
    def allowed_removals(self):
        return list(dict.fromkeys(
            ingredient.strip() for ingredient in self.removable_ingredients.splitlines()
            if ingredient.strip()
        ))

    monday_promotion_excluded = models.BooleanField('Excluir del 2x1 de lunes', default=False)
    order_kind = models.CharField(
        'Tipo de opciones para pedir', max_length=12, blank=True,
        choices=[
            ('steak', 'Término de carne'), ('bites_mix', 'Mix de bocadillos'),
            ('kushi_mix', 'Mix de brochetas'), ('edamame', 'Preparación de edamame'),
            ('ramen', 'Caldo de ramen'), ('topping', 'Topping de postre'),
            ('yaki_udon', 'Fideo y proteína de Yaki Udon'),
        ],
    )
    flavor = models.CharField('Sabor o proteína', max_length=100, blank=True)
    menu_title = models.CharField('Nombre en el menú', max_length=100, blank=True)
    variant_of = models.ForeignKey(
        'self',
        verbose_name='Platillo principal',
        null=True,
        blank=True,
        related_name='variants',
        on_delete=models.PROTECT,
        limit_choices_to={'variant_of__isnull': True},
    )
    presentation = models.CharField(
        'Presentación', max_length=10, choices=Presentation.choices, blank=True,
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
    imagen = models.ImageField(upload_to='cards/', blank=True, null=True)
    descripcion = models.TextField(blank=True, null=True)
    favorited_by = models.ManyToManyField(User,
    related_name='favorite_cards',
    blank=True,
)

    class Meta:
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
                raise ValidationError({'variant_of': 'Elige un platillo principal válido.'})
            if self.pk and self.variants.exists():
                raise ValidationError({'variant_of': 'Este platillo ya tiene presentaciones.'})
            if (self.presentation, self.flavor) == (parent.presentation, parent.flavor):
                raise ValidationError({'presentation': 'La presentación debe ser distinta a la principal.'})
        elif self.pk and self.variants.exists():
            if self.variants.filter(presentation=self.presentation, flavor=self.flavor).exists():
                raise ValidationError({'presentation': 'Elige una presentación principal distinta a las demás.'})

    def __str__(self):
        return self.title
    

class Profile(models.Model):
    class Role(models.TextChoices):
        OWNER = 'owner', 'Dueño'
        CUSTOMER = 'customer', 'Cliente'
        KITCHEN = 'kitchen', 'Responsable de cocina'
        BAR = 'bar', 'Responsable de bebidas'
        SUSHI = 'sushi', 'Responsable de sushi'

    address = models.JSONField(default=dict, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(
        'Rol', max_length=10, choices=Role.choices, default=Role.CUSTOMER,
        help_text='Para administrador, activa Es staff en la cuenta de usuario.',
    )

    class Meta:
        verbose_name = 'Perfil'
        verbose_name_plural = 'Perfiles'

    def __str__(self):
        return self.user.username


from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=User, dispatch_uid='quickstart.create_user_profile')
def create_user_profile(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        Profile.objects.get_or_create(user=instance)


class TableOrder(models.Model):
    dispatched_at = models.DateTimeField(null=True, blank=True)
    fulfillment = models.CharField(max_length=10, default='dine_in', choices=[
        ('dine_in', 'En mesa'), ('pickup', 'Para recoger'), ('delivery', 'A domicilio'),
    ])
    delivery_status = models.CharField(max_length=8, default='accepted', choices=[
        ('pending', 'Por confirmar'), ('accepted', 'Confirmado'), ('rejected', 'Rechazado'),
    ])
    delivery_address = models.JSONField(default=dict, blank=True)
    promotion_active = models.BooleanField(default=False)
    tip_percent = models.PositiveSmallIntegerField(default=0, choices=[
        (0, 'Sin propina sugerida'), (10, '10%'), (15, '15%'), (20, '20%'),
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
    promotion_eligible = models.BooleanField(default=False)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    class Status(models.TextChoices):
        REVIEW = 'review', 'Pendiente de revisión'
        RECEIVED = 'received', 'Recibido'
        PREPARING = 'preparing', 'En preparación'
        READY = 'ready', 'Listo'
        DECLINED = 'declined', 'Rechazado'
        SERVED = 'served', 'Servido'

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
    area = models.CharField(max_length=10, choices=[('kitchen', 'Cocina'), ('bar', 'Bebidas'), ('sushi', 'Sushi')])
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
        PENDING = 'pending', 'Pendiente'
        PURCHASED = 'purchased', 'Comprado'
        RECEIVED = 'received', 'Recibido en el área'

    request = models.ForeignKey(SupplyRequest, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=100)
    quantity = models.DecimalField(max_digits=9, decimal_places=2)
    unit = models.CharField(max_length=30)
    urgent = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)


class OrderPayment(models.Model):
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
    area = models.CharField(max_length=10, choices=[('kitchen', 'Cocina'), ('bar', 'Bebidas'), ('sushi', 'Sushi')])
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
        ('opening', 'Saldo inicial'), ('in', 'Entrada'), ('out', 'Salida'),
        ('count', 'Conteo físico'), ('receipt', 'Recepción de faltantes'),
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
            raise ValidationError({'date': 'La promoción solo aplica en lunes.'})
        if not self.eligible and not self.reason.strip():
            raise ValidationError({'reason': 'Indica el festivo o la suspensión de clases.'})

    date = models.DateField(unique=True)
    eligible = models.BooleanField(default=False)
    reason = models.CharField(max_length=200, blank=True)
    updated_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)


class DiningTable(models.Model):
    label = models.CharField(max_length=8, unique=True)
    zone = models.CharField(max_length=10, choices=[('terrace', 'Terraza'), ('salon', 'Salón')])
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
        ('pending', 'Por confirmar'), ('confirmed', 'Confirmada'), ('arrived', 'En mesa'),
        ('completed', 'Terminada'), ('cancelled', 'Cancelada'), ('rejected', 'Rechazada'),
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
