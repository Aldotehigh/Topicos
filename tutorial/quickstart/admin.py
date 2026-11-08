from django.contrib import admin
from .models import Carrera, Materia, Alumno, Inscripcion, Imagen, Card, Category

admin.site.register(Carrera)
admin.site.register(Materia)
admin.site.register(Alumno)
admin.site.register(Inscripcion)
admin.site.register(Imagen)
@admin.register(Card)
class CardAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'presentation', 'flavor', 'variant_of', 'price', 'is_available']
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
            'owner': 'Dueño',
            'customer': 'Cliente',
            'kitchen': 'Responsable de cocina',
            'bar': 'Responsable de bebidas',
            'sushi': 'Responsable de sushi',
        }
        return labels[get_user_role(obj.user)]


from .models import SupplyRequest, SupplyRequestItem


class SupplyRequestItemInline(admin.TabularInline):
    model = SupplyRequestItem
    extra = 0
    readonly_fields = ('updated_at',)


@admin.register(SupplyRequest)
class SupplyRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'area', 'required_by', 'author', 'created_at')
    list_filter = ('area', 'required_by')
    search_fields = ('author__username', 'items__name')
    inlines = [SupplyRequestItemInline]


from .models import PromotionDay


@admin.register(PromotionDay)
class PromotionDayAdmin(admin.ModelAdmin):
    readonly_fields = ('updated_by', 'updated_at')
    list_display = ('date', 'eligible', 'reason', 'updated_by')
    list_filter = ('eligible', 'date')

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


from .models import DiningTable, Reservation

@admin.register(DiningTable)
class DiningTableAdmin(admin.ModelAdmin):
    list_display = ('label', 'zone', 'capacity', 'active')
    list_filter = ('zone', 'active')

@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('id', 'contact_name', 'table', 'party_size', 'starts_at', 'ends_at', 'status')
    list_filter = ('status', 'table__zone')
    search_fields = ('contact_name', 'phone')
    # Confirmations must use the API so overlap validation cannot be bypassed.
    readonly_fields = tuple(field.name for field in Reservation._meta.fields)
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
