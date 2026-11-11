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

def validate_profile_photo(value):
    if value and value.size > 5 * 1024 * 1024:
        raise serializers.ValidationError('Choose an image smaller than 5 MB.')
    return value


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8, max_length=128)
    password_confirm = serializers.CharField(write_only=True, required=False)
    email = serializers.EmailField(required=True, allow_blank=False)
    avatar = serializers.ImageField(source='profile.avatar', required=False, allow_null=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password_confirm', 'first_name', 'last_name', 'avatar']

    def validate_avatar(self, value):
        return validate_profile_photo(value)

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('Username is already in use.')
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('Email is already in use.')
        return value

    def validate(self, data):
        if data.get('password_confirm', data['password']) != data['password']:
            raise serializers.ValidationError({'detail': 'The passwords do not match.'})
        password = data['password']
        if not any(char.isdigit() for char in password) or not any(char.isalpha() for char in password):
            raise serializers.ValidationError({'detail': 'Choose a stronger password with at least 8 characters, letters and numbers.'})
        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            validate_password(password, User(username=data['username'], email=data['email']))
        except DjangoValidationError:
            raise serializers.ValidationError({'detail': 'Choose a stronger password with at least 8 characters, letters and numbers.'})
        return data

    @transaction.atomic
    def create(self, validated_data):
        profile_data = validated_data.pop('profile', {})
        validated_data.pop('password_confirm', None)
        user = User.objects.create_user(**validated_data)
        profile, _ = Profile.objects.get_or_create(user=user)
        if 'avatar' in profile_data:
            profile.avatar = profile_data['avatar']
            profile.save(update_fields=['avatar'])
        return user

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'area']

class CardPresentationSerializer(serializers.ModelSerializer):
    order_profile = serializers.SerializerMethodField()

    def get_order_profile(self, card):
        return get_order_profile(card if card.presentation == 'combo' else card.variant_of or card)

    image = serializers.ImageField(source='imagen', read_only=True)
    description = serializers.CharField(source='descripcion', read_only=True)

    class Meta:
        model = Card
        fields = ['id', 'title', 'flavor', 'presentation', 'price', 'is_available', 'image', 'description', 'description_en', 'order_profile']


from .order_choices import get_order_choice, get_order_profile


class CardSerializers(serializers.ModelSerializer):
    order_choice = serializers.SerializerMethodField()
    order_profile = serializers.SerializerMethodField()
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
        fields = ['id', 'title', 'image', 'description', 'description_en', 'price', 'is_available', 'category', 'category_id', 'presentations', 'display_title', 'allowed_removals', 'order_choice', 'order_profile']
        read_only_fields = ['id']

    def get_order_profile(self, card):
        return get_order_profile(card if card.presentation == 'combo' else card.variant_of or card)

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
    address = serializers.JSONField(source='profile.address', required=False)

    def validate_address(self, value):
        if value == {}:
            return {}
        from .addresses import AddressSerializer
        serializer = AddressSerializer(data=value)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    avatar = serializers.ImageField(source='profile.avatar', required=False, allow_null=True)

    def validate_avatar(self, value):
        return validate_profile_photo(value)

    @transaction.atomic
    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})
        instance = super().update(instance, validated_data)
        if profile_data:
            profile, _ = Profile.objects.get_or_create(user=instance)
            for key, value in profile_data.items():
                setattr(profile, key, value)
            profile.save(update_fields=list(profile_data))
        return instance

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'avatar', 'address']
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
