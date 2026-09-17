from django.contrib.auth.models import Group, User
from rest_framework import serializers
from .models import Alumno, Carrera, Imagen, Inscripcion, Materia


class UserSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = User
        fields = ["url", "username", "email", "groups"]


class GroupSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Group
        fields = ["url", "name"]

class MateriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Materia
        fields = '__all__'

class CarreraSerializer(serializers.ModelSerializer):
    materias = MateriaSerializer(many=True, read_only=True)
    class Meta:
        model = Carrera
        fields = 'id', 'nombre', 'clave', 'descripcion', 'materias'

class AlumnoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Alumno
        fields = '__all__' 

class InscripcionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inscripcion
        fields = '__all__'

class ImagenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Imagen
        fields = '__all__'
