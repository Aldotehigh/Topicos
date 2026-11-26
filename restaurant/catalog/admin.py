from django.contrib import admin
from django.contrib.auth.models import Group
from .models import (Card, Category, Profile, SupplyRequest, SupplyRequestItem,
                     PromotionDay, DiningTable, Reservation, UserPreferences)

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


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'role', 'effective_role']
    list_filter = ['role']
    search_fields = ['user__username', 'user__email']
    autocomplete_fields = ['user']

    @admin.display(description='Effective access')
    def effective_role(self, obj):
        from .roles import get_user_role
        labels = {
            'admin': 'Administrator',
            'owner': 'Owner',
            'customer': 'Customer',
            'kitchen': 'Kitchen manager',
            'bar': 'Bar manager',
            'sushi': 'Sushi manager',
        }
        return labels[get_user_role(obj.user)]




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




@admin.register(PromotionDay)
class PromotionDayAdmin(admin.ModelAdmin):
    readonly_fields = ('updated_by', 'updated_at')
    list_display = ('date', 'eligible', 'reason', 'updated_by')
    list_filter = ('eligible', 'date')

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)



@admin.register(DiningTable)
class DiningTableAdmin(admin.ModelAdmin):
    list_display = ('label', 'zone', 'capacity', 'active')
    list_filter = ('zone', 'active')

@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('id', 'contact_name', 'table', 'party_size', 'starts_at', 'ends_at', 'status')
    list_filter = ('status', 'table__zone')
    search_fields = ('contact_name', 'phone')

    readonly_fields = tuple(field.name for field in Reservation._meta.fields)
    def has_add_permission(self, request):
        return False
    def has_delete_permission(self, request, obj=None):
        return False



if admin.site.is_registered(Group):
    admin.site.unregister(Group)

admin.site.site_header = 'MyRestaurant — Administration'
admin.site.site_title = 'MyRestaurant'
admin.site.index_title = 'Restaurant administration'


@admin.register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
    list_display = ('user', 'theme_mode', 'language')
    list_filter = ('theme_mode', 'language')
    search_fields = ('user__username', 'user__email')
    autocomplete_fields = ('user',)
