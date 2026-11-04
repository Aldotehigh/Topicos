from django.contrib.auth.models import Group, User
from rest_framework import permissions, viewsets

from tutorial.quickstart.serializers import GroupSerializer, UserSerializer
from .models import Alumno, Carrera, Inscripcion, Materia, Imagen, Card, Category
from .serializers import AlumnoSerializer, CarreraSerializer, InscripcionSerializer, MateriaSerializer, ImagenSerializer, RegisterSerializer, CardSerializers, CategorySerializer

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters

from rest_framework.authtoken.views import APIView, ObtainAuthToken
from rest_framework.authtoken.models import Token
from rest_framework.response import Response

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework import status

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from .permissions import IsAdminOrReadOnly
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination


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
    permission_classes = [IsAdminOrReadOnly]

class MateriaViewSet(viewsets.ModelViewSet):
    queryset = Materia.objects.all()
    serializer_class = MateriaSerializer
    permission_classes = [IsAdminOrReadOnly]

class AlumnoViewSet(viewsets.ModelViewSet):
    queryset = Alumno.objects.all()
    serializer_class = AlumnoSerializer
    permission_classes = [IsAdminOrReadOnly]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['carrera']
    search_fields = ['user', 'apellido_paterno', 'numero_control']
    ordering_fields = ['user', 'numero_control']

class InscripcionViewSet(viewsets.ModelViewSet):
    queryset = Inscripcion.objects.all()
    serializer_class = InscripcionSerializer

class CustomAuthToken(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        print("Request data:", request.data)  # Debugging line
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

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            user = serializer.save()
            return Response({
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'detail': 'User registered successfully. Log in to obtain the token.'
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def me(request):

    user = request.user
    if request.method == 'GET':
        return Response({
            'id': user.id,
            'email': user.email,
            'username': user.username,
            'is_staff': user.is_staff
        })
    #PATCH method to update user information
    data = request.data
    if 'email' in data:
        if User.objects.filter(email__iexact=data['email']).exclude(id=user.id).exists():
            return Response({'error': 'Email is already in use.'}, status=status.HTTP_400_BAD_REQUEST)
        user.email = data['email']
        if 'username' in data:
            if User.objects.filter(username__iexact=data['username']).exclude(id=user.id).exists():
                return Response({'error': 'Username is already in use.'}, status=status.HTTP_400_BAD_REQUEST)
            user.username = data['username']
    user.save()
    return Response({
        'id': user.id,
        'email': user.email,
        'username': user.username,
        'is_staff': user.is_staff
    })

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request.user.auth_token.delete()
        return Response(
            {'detail': "Sesión cerrada correctamente."},
            status=status.HTTP_200_OK,
        )

class ResetTokenView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        #Elimina el token actual si existe
        Token.objects.filter(user=request.user).delete()
       #Crea el nuevo token
        token = Token.objects.create(user=request.user)
        return Response(
            {
                "token": token.key,
                "detail": "Token reseteado correctamente."
            },
            status=status.HTTP_200_OK
        )
class CardPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 30

class CardViewSet(viewsets.ModelViewSet):
    queryset = Card.objects.select_related('category').order_by('id')
    serializer_class = CardSerializers
    pagination_class = CardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category', 'is_available']
    search_fields = ['title', 'descripcion']
    @action(
        detail=True,
        methods=['get', 'post', 'delete'],
        permission_classes=[IsAuthenticated],
    )
    def favorite(self, request, pk=None):
        card = self.get_object()

        if request.method == 'POST':
            card.favorited_by.add(request.user)
            return Response({'is_favorite': True})

        if request.method == 'DELETE':
            card.favorited_by.remove(request.user)
            return Response({'is_favorite': False})

        is_favorite = card.favorited_by.filter(pk=request.user.pk).exists()
        return Response({'is_favorite': is_favorite})

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[IsAuthenticated],
    )
    def favorites(self, request):
        queryset = self.get_queryset().filter(favorited_by=request.user)
        queryset = self.filter_queryset(queryset)
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Category.objects.order_by('name', 'id')
    serializer_class = CategorySerializer

class ImagenViewSet(viewsets.ModelViewSet):
    queryset = Imagen.objects.all()
    serializer_class = ImagenSerializer