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
        BAR = 'bar', 'Barra'

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
                fields=['variant_of', 'presentation'],
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
            if not self.presentation or not parent.presentation or self.presentation == parent.presentation:
                raise ValidationError({'presentation': 'La presentación debe ser distinta a la principal.'})
        elif self.pk and self.variants.exists():
            if not self.presentation or self.variants.filter(presentation=self.presentation).exists():
                raise ValidationError({'presentation': 'Elige una presentación principal distinta a las demás.'})

    def __str__(self):
        return self.title
    

class Profile(models.Model):
    class Role(models.TextChoices):
        CUSTOMER = 'customer', 'Cliente'
        KITCHEN = 'kitchen', 'Responsable de cocina'
        BAR = 'bar', 'Responsable de barra'

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
    customer = models.ForeignKey(User, on_delete=models.PROTECT, related_name='table_orders')
    table = models.PositiveSmallIntegerField()
    request_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['customer', 'request_key'], name='unique_table_order_request'),
        ]


class TableOrderLine(models.Model):
    class Status(models.TextChoices):
        REVIEW = 'review', 'Pendiente de revisión'
        RECEIVED = 'received', 'Recibido'
        PREPARING = 'preparing', 'En preparación'
        READY = 'ready', 'Listo'
        DECLINED = 'declined', 'Rechazado'

    order = models.ForeignKey(TableOrder, on_delete=models.CASCADE, related_name='lines')
    title = models.CharField(max_length=100)
    area = models.CharField(max_length=10)
    quantity = models.PositiveSmallIntegerField()
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    removals = models.JSONField(default=list)
    selections = models.JSONField(default=list, blank=True)
    allergy = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices)
