from django.contrib import admin
from .models import Building, Listing, SubwayStation, ListingSubway, UserSearch


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ['building_id', 'address', 'neighborhood', 'borough', 'zipcode']
    list_filter = ['borough', 'neighborhood']
    search_fields = ['address', 'building_id', 'zipcode']


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ['listing_id', 'address', 'price', 'bedrooms', 'bathrooms', 
                    'neighborhood', 'status', 'listed_at', 'days_on_market']
    list_filter = ['status', 'property_type', 'bedrooms', 'neighborhood', 'no_fee']
    search_fields = ['address', 'listing_id', 'description']
    date_hierarchy = 'listed_at'
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Identification', {
            'fields': ('listing_id', 'status', 'building')
        }),
        ('Dates', {
            'fields': ('listed_at', 'closed_at', 'available_from', 'days_on_market')
        }),
        ('Location', {
            'fields': ('address', 'borough', 'neighborhood', 'zipcode', 
                      'latitude', 'longitude')
        }),
        ('Property Details', {
            'fields': ('property_type', 'price', 'sqft', 'bedrooms', 
                      'bathrooms', 'built_in')
        }),
        ('Features', {
            'fields': ('amenities', 'no_fee')
        }),
        ('Description & Agents', {
            'fields': ('description', 'agents')
        }),
        ('Media', {
            'fields': ('images', 'videos', 'floorplans')
        }),
        ('AI/Search', {
            'fields': ('description_embedding',),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(SubwayStation)
class SubwayStationAdmin(admin.ModelAdmin):
    list_display = ['station_id', 'line', 'get_routes']
    search_fields = ['station_id', 'line']
    
    def get_routes(self, obj):
        return ', '.join(obj.routes)
    get_routes.short_description = 'Routes'


@admin.register(ListingSubway)
class ListingSubwayAdmin(admin.ModelAdmin):
    list_display = ['listing', 'subway', 'distance']
    list_filter = ['subway__line']
    search_fields = ['listing__address']


@admin.register(UserSearch)
class UserSearchAdmin(admin.ModelAdmin):
    list_display = ['query_preview', 'results_count', 'timestamp']
    list_filter = ['timestamp']
    readonly_fields = ['timestamp']
    
    def query_preview(self, obj):
        return obj.query[:100]
    query_preview.short_description = 'Query'
