import json # for reading json file
from django.core.management.base import BaseCommand # for creating management command in django
from django.db import transaction
from app.models import Building, Listing, SubwayStation, ListingSubway # need to pull models to here
from decimal import Decimal
from datetime import datetime
" Usage examples in terminal to import data "
# python manage.py import_manhattan --file path/to/data.json --limit 100 
# python manage.py import_manhattan --clear  #### Wipe DB and reimport all


class Command(BaseCommand):
    help = """Import Manhattan listings from StreetEasy from JSON file, will likely
    resuse this file when we have to update the database with new listings from streeteasy"""

    def add_arguments(self, parser):
        parser.add_argument(
            '--file', # aka which file to import
            type=str, # then some more args about the files
            default='../../../EDA/Datasets/StreetEasy/manhattan_details.json',
            help='Path to the JSON file to import'
        )
        parser.add_argument(
            '--limit', # how many to import
            type=int,
            default=None,
            help='Limit number of listings to import (for testing)'
        )
        parser.add_argument(
            '--clear', # delete existing data before import so we don't have duplicates or stale apts
            action='store_true',
            help='Clear existing data before import'
        )

    def handle(self, *args, **options):
        " Loadd the json file, parses into list of hashmaps, creates or updates, some error logic stuff too "
        file_path = options['file']
        limit = options['limit']
        clear_data = options['clear']

        self.stdout.write(self.style.WARNING(f'Loading data from: {file_path}')) # just printing to terminal

        # Load JSON file (since it's one big file)
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'File not found: {file_path}'))
            return
        except json.JSONDecodeError as e:
            self.stdout.write(self.style.ERROR(f'Invalid JSON: {e}'))
            return

        if limit:
            data = data[:limit]
            self.stdout.write(self.style.WARNING(f'Limiting import to {limit} listings'))

        # Clear existing data if requested (ie stale old data)
        if clear_data:
            self.stdout.write(self.style.WARNING('Clearing existing data...'))
            ListingSubway.objects.all().delete()
            SubwayStation.objects.all().delete()
            Listing.objects.all().delete()
            Building.objects.all().delete()
            self.stdout.write(self.style.SUCCESS('Data cleared'))

        # Counters: plan to return these at the end (if needed)
        buildings_created = 0
        listings_created = 0
        listings_updated = 0
        subways_created = 0
        listing_subway_created = 0
        errors = 0

        self.stdout.write(self.style.SUCCESS(f'Processing {len(data)} listings...'))

        # Process each listing
        for idx, item in enumerate(data, 1):
            try:
                with transaction.atomic():
                    # 1. Create or get Building
                    building = None
                    if item.get('building') and item['building'].get('id'):
                        building, created = Building.objects.get_or_create(
                            building_id=item['building']['id'],
                            defaults={
                                'address': item.get('address', '').split('#')[0].strip(),
                                'borough': item.get('borough', 'manhattan'),
                                'neighborhood': item.get('neighborhood', ''),
                                'zipcode': item.get('zipcode', ''),
                                'latitude': Decimal(str(item.get('latitude', 0))) if item.get('latitude') else None,
                                'longitude': Decimal(str(item.get('longitude', 0))) if item.get('longitude') else None,
                                'built_in': item.get('builtIn'),
                            }
                        )
                        if created:
                            buildings_created += 1

                    # 2. Create or update Listing
                    listing, created = Listing.objects.update_or_create(
                        listing_id=item['id'],
                        defaults={
                            'status': item.get('status', 'open'),
                            'listed_at': item.get('listedAt') or datetime.now().date(),
                            'closed_at': item.get('closedAt'),
                            'available_from': item.get('availableFrom'),
                            'days_on_market': item.get('daysOnMarket', 0),
                            'building': building,
                            'address': item.get('address', ''),
                            'price': Decimal(str(item.get('price', 0))),
                            'borough': item.get('borough', 'manhattan'),
                            'neighborhood': item.get('neighborhood', ''),
                            'zipcode': item.get('zipcode', ''),
                            'property_type': item.get('propertyType', 'rental'),
                            'sqft': item.get('sqft') if item.get('sqft') else None,
                            'bedrooms': item.get('bedrooms', 0),
                            'bathrooms': Decimal(str(item.get('bathrooms', 0))),
                            'latitude': Decimal(str(item.get('latitude', 0))) if item.get('latitude') else None,
                            'longitude': Decimal(str(item.get('longitude', 0))) if item.get('longitude') else None,
                            'amenities': item.get('amenities', []),
                            'built_in': item.get('builtIn'),
                            'description': item.get('description', ''),
                            'agents': item.get('agents', []),
                            'no_fee': item.get('noFee', False),
                            'images': item.get('images', []),
                            'videos': item.get('videos', []),
                            'floorplans': item.get('floorplans', []),
                        }
                    )
                    
                    if created:
                        listings_created += 1
                    else:
                        listings_updated += 1

                    # 3. Process Subway Stations
                    if item.get('subways'):
                        for subway_data in item['subways']:
                            # Create or get subway station
                            subway, created = SubwayStation.objects.get_or_create(
                                station_id=subway_data['id'],
                                defaults={
                                    'line': subway_data.get('line', ''),
                                    'routes': subway_data.get('routes', []),
                                }
                            )
                            if created:
                                subways_created += 1

                            # Create listing-subway relationship
                            _, created = ListingSubway.objects.get_or_create(
                                listing=listing,
                                subway=subway,
                                defaults={
                                    'distance': Decimal(str(subway_data.get('distance', 0)))
                                }
                            )
                            if created:
                                listing_subway_created += 1

                # Progress indicator
                if idx % 100 == 0:
                    self.stdout.write(f'Processed {idx}/{len(data)} listings...')

            except Exception as e:
                errors += 1
                self.stdout.write(
                    self.style.ERROR(f'Error processing listing {item.get("id", "unknown")}: {str(e)}')
                )

        # Summary
        self.stdout.write(self.style.SUCCESS('\n' + '='*60))
        self.stdout.write(self.style.SUCCESS('IMPORT COMPLETE'))
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write(f'Buildings created:        {buildings_created}')
        self.stdout.write(f'Listings created:         {listings_created}')
        self.stdout.write(f'Listings updated:         {listings_updated}')
        self.stdout.write(f'Subway stations created:  {subways_created}')
        self.stdout.write(f'Listing-subway links:     {listing_subway_created}')
        self.stdout.write(self.style.ERROR(f'Errors:                   {errors}'))
        self.stdout.write(self.style.SUCCESS('='*60))
