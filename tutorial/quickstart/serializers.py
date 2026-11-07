from django.db import transaction
from .models import Profile
from django.contrib.auth.models import Group, User
from rest_framework import serializers
from .models import Alumno, Carrera, Imagen, Inscripcion, Materia, Card, Category

from django.contrib.auth.password_validation import validate_password



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

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    email = serializers.EmailField(required=True
    )
    class Meta:
        model = User
        fields = ['username', 'email', 'password']

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email is already in use.")
        return value

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Username is already in use.")
        return value

    def password_must_have_number(value):
        if not any(char.isdigit() for char in value):
            raise serializers.ValidationError(
            "La contraseña debe contener al menos un número."
        )
        return value
    
    password = serializers.CharField(
        write_only=True,
        min_length=6,
        validators=[password_must_have_number]
)
    
    @transaction.atomic
    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )
        Profile.objects.get_or_create(user=user)
        return user

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'area']

class CardPresentationSerializer(serializers.ModelSerializer):
    image = serializers.ImageField(source='imagen', read_only=True)
    description = serializers.CharField(source='descripcion', read_only=True)

    class Meta:
        model = Card
        fields = ['id', 'title', 'presentation', 'price', 'is_available', 'image', 'description']


from .order_choices import get_order_choice


class CardSerializers(serializers.ModelSerializer):
    order_choice = serializers.SerializerMethodField()
    allowed_removals = serializers.ListField(child=serializers.CharField(), read_only=True)
    presentations = serializers.SerializerMethodField()
    display_title = serializers.SerializerMethodField()
    image = serializers.ImageField(
        source='imagen',
        required=False,
        allow_null=True,
    )
    description = serializers.CharField(
        source='descripcion',
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    category = CategorySerializer(read_only=True)

    category_id = serializers.PrimaryKeyRelatedField(
        source='category',
        queryset=Category.objects.all(),
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = Card
        fields = ['id', 'title', 'image', 'description', 'price', 'is_available', 'category', 'category_id', 'presentations', 'display_title', 'allowed_removals', 'order_choice']
        read_only_fields = ['id']

    def get_order_choice(self, card):
        return get_order_choice(card)

    def get_display_title(self, card):
        if card.menu_title:
            return card.menu_title
        suffix = {'glass': ' (copa)', 'thin': ' (corte delgado)'}.get(card.presentation)
        if suffix and card.title.lower().endswith(suffix):
            return card.title[:-len(suffix)]
        return card.title

    def get_presentations(self, card):
        if card.variant_of_id:
            return []
        variants = list(card.variants.all())
        if not variants:
            return []
        return CardPresentationSerializer(
            [card, *variants], many=True, context=self.context,
        ).data


class CardAvailabilitySerializer(serializers.Serializer):
    is_available = serializers.BooleanField()


class CurrentUserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['username', 'email']
        extra_kwargs = {
            'username': {'required': False},
            'email': {'required': False, 'allow_blank': False},
        }

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError('Este usuario ya está registrado.')
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError('Este correo ya está registrado.')
        return value
