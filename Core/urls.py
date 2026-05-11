from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# السطر اللي ناقصك هو ده:
from django.contrib.sitemaps.views import sitemap 
from store.sitemaps import ProductSitemap, CollectionSitemap

sitemaps = {
    'products': ProductSitemap,
    'collections': CollectionSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('store.urls')), 
    path('_nested_admin/', include('nested_admin.urls')),   
    
    # السطر ده اللي كان مطلع الخطأ
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)