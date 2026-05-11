from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse # <--- ضيف السطر ده

# استيراد الـ sitemap اللي أنت عملتها
from django.contrib.sitemaps.views import sitemap 
from store.sitemaps import ProductSitemap, CollectionSitemap

sitemaps = {
    'products': ProductSitemap,
    'collections': CollectionSitemap,
}

# الفنكشن بتاعة الـ robots.txt ضيفها هنا قبل الـ urlpatterns
def robots_txt(request):
    content = "User-agent: *\nAllow: /\nSitemap: https://www.elbasty-group.com/sitemap.xml"
    return HttpResponse(content, content_type="text/plain")

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('store.urls')), 
    path('_nested_admin/', include('nested_admin.urls')),   
    
    # رابط السايت ماب
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    
    # رابط الـ robots.txt الجديد
    path('robots.txt', robots_txt),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)