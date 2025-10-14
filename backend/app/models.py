from django.db import models
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator


class Building(models.Model):
    """
    Represents a building that may contain multiple listings
    """
    building_id = models.CharField(max_length=50, unique=True, db_index=True)
    address = models.CharField(max_length=255)
    borough = models.CharField(max_length=50, db_index=True)
    neighborhood = models.CharField(max_length=100, db_index=True)
    zipcode = models.CharField(max_length=10, db_index=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    built_in = models.IntegerField(null=True, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'buildings'
        indexes = [
            models.Index(fields=['neighborhood', 'zipcode']),
            models.Index(fields=['latitude', 'longitude']),
        ]
    
    def __str__(self):
        return f"{self.address} - {self.neighborhood}"


class Listing(models.Model):
    """
    Represents an apartment listing in Manhattan
    """
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('closed', 'Closed'),
        ('pending', 'Pending'),
    ]
    
    PROPERTY_TYPE_CHOICES = [
        ('rental', 'Rental'),
        ('sale', 'Sale'),
    ]
    
    # Primary identifiers
    listing_id = models.CharField(max_length=50, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open', db_index=True)
    
    # Dates
    listed_at = models.DateField()
    closed_at = models.DateField(null=True, blank=True)
    available_from = models.DateField(null=True, blank=True)
    days_on_market = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    
    # Property details
    building = models.ForeignKey(
        Building, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='listings'
    )
    address = models.CharField(max_length=255, db_index=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    borough = models.CharField(max_length=50, default='manhattan')
    neighborhood = models.CharField(max_length=100, db_index=True)
    zipcode = models.CharField(max_length=10, db_index=True)
    property_type = models.CharField(max_length=20, choices=PROPERTY_TYPE_CHOICES, default='rental')
    
    # Physical characteristics
    sqft = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(0)])
    bedrooms = models.IntegerField(validators=[MinValueValidator(0)], db_index=True)
    bathrooms = models.DecimalField(max_digits=3, decimal_places=1, validators=[MinValueValidator(0)])
    
    # Location
    latitude = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    longitude = models.DecimalField(max_digits=11, decimal_places=8, null=True, blank=True)
    
    # Amenities and features
    amenities = ArrayField(
        models.CharField(max_length=100),
        default=list,
        blank=True
    )
    
    # Building info
    built_in = models.IntegerField(null=True, blank=True)
    
    # Description and agents
    description = models.TextField(blank=True)
    agents = ArrayField(
        models.CharField(max_length=200),
        default=list,
        blank=True
    )
    no_fee = models.BooleanField(default=False)
    
    # Media
    images = ArrayField(
        models.URLField(max_length=500),
        default=list,
        blank=True
    )
    videos = ArrayField(
        models.URLField(max_length=500),
        default=list,
        blank=True
    )
    floorplans = ArrayField(
        models.URLField(max_length=500),
        default=list,
        blank=True
    )
    
    # For RAG/embedding-based search (to be implemented)
    description_embedding = ArrayField(
        models.FloatField(),
        null=True,
        blank=True,
        help_text="Vector embedding of the description for semantic search"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'listings'
        ordering = ['-listed_at', '-created_at']
        indexes = [
            models.Index(fields=['status', 'price']),
            models.Index(fields=['bedrooms', 'price']),
            models.Index(fields=['neighborhood', 'bedrooms', 'price']),
            models.Index(fields=['listed_at']),
            models.Index(fields=['days_on_market']),
        ]
    
    def __str__(self):
        return f"{self.address} - ${self.price} ({self.bedrooms}BR/{self.bathrooms}BA)"
    
    @property
    def price_per_sqft(self):
        """Calculate price per square foot"""
        if self.sqft and self.sqft > 0:
            return float(self.price) / self.sqft
        return None
    
    def is_active(self):
        """Check if listing is currently active"""
        return self.status == 'open'


class SubwayStation(models.Model):
    """
    Represents subway stations near listings
    """
    station_id = models.CharField(max_length=50, unique=True)
    line = models.CharField(max_length=100)
    routes = ArrayField(
        models.CharField(max_length=10),
        default=list
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'subway_stations'
    
    def __str__(self):
        return f"{self.line} - {', '.join(self.routes)}"


class ListingSubway(models.Model):
    """
    Many-to-many relationship between listings and subway stations
    with distance information
    """
    listing = models.ForeignKey(
        Listing, 
        on_delete=models.CASCADE, 
        related_name='nearby_subways'
    )
    subway = models.ForeignKey(
        SubwayStation, 
        on_delete=models.CASCADE, 
        related_name='nearby_listings'
    )
    distance = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        help_text="Distance in miles"
    )
    
    class Meta:
        db_table = 'listing_subway'
        unique_together = ['listing', 'subway']
        ordering = ['distance']
    
    def __str__(self):
        return f"{self.listing.address} - {self.subway.line} ({self.distance}mi)"


class UserSearch(models.Model):
    """
    Track user searches for analytics and improvement
    """
    query = models.TextField()
    results_count = models.IntegerField(default=0)
    filters_applied = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    # Optional: link to authenticated user if implementing auth
    # user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    class Meta:
        db_table = 'user_searches'
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"Search: {self.query[:50]} ({self.timestamp})"
