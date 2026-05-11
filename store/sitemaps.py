from django.contrib.sitemaps import Sitemap
from .models import Product, ProductCollection

class ProductSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8
    def items(self):
        return Product.objects.all()

class CollectionSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.9
    def items(self):
        return ProductCollection.objects.filter(is_active=True)