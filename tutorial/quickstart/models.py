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
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = 'Categoría'
        verbose_name_plural = 'Categorías'

    def __str__(self):
        return self.name

class Card(models.Model):
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

    def __str__(self):
        return self.title
    