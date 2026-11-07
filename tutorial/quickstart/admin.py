from django.contrib import admin
from .models import Carrera, Materia, Alumno, Inscripcion, Imagen, Card, Category

admin.site.register(Carrera)
admin.site.register(Materia)
admin.site.register(Alumno)
admin.site.register(Inscripcion)
admin.site.register(Imagen)
@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'presentation', 'variant_of', 'price', 'is_available']
    list_filter = ['category', 'presentation', 'is_available']
    search_fields = ['title']
    autocomplete_fields = ['variant_of']

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'area']
    list_filter = ['area']
    search_fields = ['name']

from .models import Profile

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'effective_role']
    list_filter = ['role']
    search_fields = ['user__username', 'user__email']
    autocomplete_fields = ['user']

    @admin.display(description='Acceso efectivo')
    def effective_role(self, obj):
        from .roles import get_user_role
        labels = {
            'admin': 'Administrador',
            'customer': 'Cliente',
            'kitchen': 'Responsable de cocina',
            'bar': 'Responsable de barra',
        }
        return labels[get_user_role(obj.user)]
