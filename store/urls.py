from django.urls import path 
from . import views

urlpatterns = [
    # --- الصفحات العامة ---
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('logout/', views.logout_view, name='logout'),
    path('about/', views.about_view, name='about'),
    path('contact/', views.contact_view, name='contact'), 
    path('offers/', views.offers_view, name='offers'),
    
    # --- لوحة تحكم المسؤول (Dashboard) ---
    # هذا الرابط مخصص للسوبر يوزر فقط كما صممنا في الـ views
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('dashboard/add-product/', views.add_product, name='add_product'),
    path('dashboard/delete-product/<int:pk>/', views.delete_product, name='delete_product'),
    path('dashboard/edit-product/<int:pk>/', views.edit_product, name='edit_product'),
    path('order/update/<int:order_id>/', views.update_order_status, name='update_order_status'),
    path('reset-orders/', views.reset_orders, name='reset_orders'),
    path('admin-dashboard/update-item/<int:item_id>/', views.update_item_quantity, name='update_item_quantity'),
    path('admin-dashboard/apply-discount/<int:order_id>/', views.apply_order_discount, name='apply_order_discount'),

    # --- المتجر والمنتجات ---
    path('shop/', views.shop_view, name='shop'),     
    path('shop/<slug:category_slug>/', views.shop_view, name='shop_by_category'),
    path('product/<int:id>/', views.product_detail, name='product_detail'),

    # --- عربة التسوق (Cart) ---
    path('cart/', views.cart_view, name='cart_view'),
    
    # إضافة للمنتج
    path('add-to-cart/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    
    # التعامل مع مفاتيح السلة النصية (مثل 1_Black)
    path('remove-from-cart/<str:item_key>/', views.remove_from_cart, name='remove_from_cart'), 
    path('cart/update/<str:item_key>/<str:action>/', views.update_cart, name='update_cart'),

    # --- إتمام الطلب ---
    path('checkout/', views.checkout_view, name='checkout'),

    path('policies/', views.policies, name='policies'),

    # --- إدارة المخزن ---
    path('inventory/', views.inventory_dashboard, name='inventory_dashboard'),
    path('inventory/movement/add/', views.add_stock_movement, name='add_stock_movement'),
    path('inventory/movements/', views.movements_list, name='movements_list'),
    path('inventory/suppliers/', views.suppliers_list, name='suppliers_list'),
    path('inventory/suppliers/add/', views.add_supplier, name='add_supplier'),
    path('inventory/suppliers/<int:pk>/', views.supplier_detail, name='supplier_detail'),
    path('inventory/invoices/', views.invoices_list, name='invoices_list'),
    path('inventory/invoices/create/', views.create_invoice, name='create_invoice'),
    path('inventory/invoices/<int:pk>/', views.invoice_detail, name='invoice_detail'),
    path('inventory/invoices/<int:pk>/payment/', views.add_invoice_payment, name='add_invoice_payment'),

    # --- فلوس ليا (مديونيات العملاء) ---
    path('inventory/receivables/', views.receivables_list, name='receivables_list'),
    path('inventory/receivables/add/', views.add_receivable, name='add_receivable'),
    path('inventory/receivables/<int:pk>/', views.receivable_detail, name='receivable_detail'),

    # --- فلوس عليا (مديونيات الموردين) ---
    path('inventory/payables/', views.payables_list, name='payables_list'),
    path('inventory/payables/add/', views.add_payable, name='add_payable'),
    path('inventory/payables/<int:pk>/', views.payable_detail, name='payable_detail'),

    # --- API للـ variants ---
    path('api/product/<int:product_id>/variants/', views.get_product_variants, name='get_product_variants'),
]