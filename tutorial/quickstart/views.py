from django.contrib.auth.models import Group, User
from rest_framework import permissions, viewsets

from tutorial.quickstart.serializers import GroupSerializer, UserSerializer
from .models import Alumno, Carrera, Inscripcion, Materia, Imagen
from .serializers import AlumnoSerializer, CarreraSerializer, InscripcionSerializer, MateriaSerializer, ImagenSerializer

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters

from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token
from rest_framework.response import Response


class UserViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows users to be viewed or edited.
    """
    queryset = User.objects.all().order_by("-date_joined")
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]


class GroupViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows groups to be viewed or edited.
    """
    queryset = Group.objects.all().order_by("name")
    serializer_class = GroupSerializer
    permission_classes = [permissions.IsAuthenticated]

class CarreraViewSet(viewsets.ModelViewSet):
    queryset = Carrera.objects.all()
    serializer_class = CarreraSerializer

class MateriaViewSet(viewsets.ModelViewSet):
    queryset = Materia.objects.all()
    serializer_class = MateriaSerializer

class AlumnoViewSet(viewsets.ModelViewSet):
    queryset = Alumno.objects.all()
    serializer_class = AlumnoSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['carrera']
    search_fields = ['user', 'apellido_paterno', 'numero_control']
    ordering_fields = ['user', 'numero_control']

class InscripcionViewSet(viewsets.ModelViewSet):
    queryset = Inscripcion.objects.all()
    serializer_class = InscripcionSerializer

class CustomAuthToken(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data,
                                           context={'request': request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, created = Token.objects.get_or_create(user=user)
        return Response({
            'token': token.key,
            'user_id': user.pk,
            'email': user.email
        })

class ImagenViewSet(viewsets.ModelViewSet):
    queryset = Imagen.objects.all()
    serializer_class = ImagenSerializer