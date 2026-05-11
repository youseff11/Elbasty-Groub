import requests
import hashlib
import time
import json
from decimal import Decimal
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.mail import send_mail
from django.conf import settings
from django.forms import inlineformset_factory
from django.utils.html import strip_tags
from django.template.loader import render_to_string
from django.db import connection, transaction
from django.db.models import Case, When, Value, IntegerField, Sum, F
from django.db import models as django_models

from .models import (
    Product, Category, ContactMessage, ProductVariant, 
    Order, OrderItem, ProductSize, ProductImage,
    Supplier, StockMovement, Invoice, InvoiceItem, InvoicePayment,
    Receivable, ReceivablePayment, Payable, PayablePayment,
    PaymentSchedule, ProductCollection, CollectionItem
)
from .forms import ProductForm

# --- الدوال المساعدة (Helper Functions) ---

def get_user_cart_key(request):
    """إرجاع مفتاح الجلسة المناسب للسلة بناءً على حالة المستخدم"""
    if request.user.is_authenticated:
        return f"cart_{request.user.id}"
    return "cart_guest"

def is_admin(user):
    """التحقق مما إذا كان المستخدم مسؤولاً"""
    return user.is_authenticated and user.is_staff

# --- طرق العرض العامة (Public Views) ---

def home(request):
    return render(request, 'home.html')

from django.core.paginator import Paginator # تأكد من استيراد الموزع

def shop_view(request, category_slug=None):
    categories = Category.objects.all()
    
    # تحسين الأداء باستخدام prefetch_related لجلب بيانات الألوان والمقاسات في استعلام واحد
    products_list = Product.objects.prefetch_related('variants__sizes', 'variants__additional_images').annotate(
        is_available_group=Case(
            When(stock__gt=0, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
        manual_new_priority=Case(
            When(is_new_arrival=True, then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        )
    ).order_by('is_available_group', '-manual_new_priority', '-created_at')

    selected_category = None
    if category_slug:
        selected_category = get_object_or_404(Category, slug=category_slug)
        products_list = products_list.filter(category=selected_category)

    # --- بداية كود التقسيم (Pagination) ---
    # تقسيم القائمة لعرض 20 منتج فقط في كل صفحة
    paginator = Paginator(products_list, 20) 
    page_number = request.GET.get('page')
    products = paginator.get_page(page_number)
    # --- نهاية كود التقسيم ---

    context = {
        'products': products, # سيحتوي الآن على 20 منتجاً فقط للصفحة الحالية
        'categories': categories,
        'selected_category': selected_category,
    }
    return render(request, 'shop.html', context)

def product_detail(request, id):
    # استخدام prefetch_related لجلب المتغيرات والصور بكفاءة
    product = get_object_or_404(
        Product.objects.prefetch_related('variants__sizes', 'variants__additional_images'), 
        id=id
    )
    return render(request, 'product_detail.html', {'product': product})

def contact_view(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        subject = request.POST.get('subject') or "No Subject"
        message = request.POST.get('message')

        ContactMessage.objects.create(
            name=name, email=email, phone=phone,
            subject=subject, message=message
        )
        
        full_message = f"New message from {name}\nEmail: {email}\nPhone: {phone}\n\nMessage:\n{message}"
        try:
            send_mail(
                subject=f"Elbasty Groub: {subject}",
                message=full_message,
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[settings.EMAIL_HOST_USER],
                fail_silently=False,
            )
            messages.success(request, 'شكراً لتواصلك معنا! تم استلام رسالتك.')
        except Exception:
            messages.warning(request, 'تم حفظ الرسالة بنجاح، ولكن تعذر إرسال إشعار البريد الإلكتروني حالياً.')

        return redirect('contact')

    return render(request, 'contact.html')

# --- منطق سلة المشتريات (Cart Logic) ---

def add_to_cart(request, product_id):
    user_cart_key = get_user_cart_key(request)
    cart = request.session.get(user_cart_key, {})
    
    selected_color = request.GET.get('color', 'Default') 
    selected_size = request.GET.get('size', 'N/A')    
    item_key = f"{product_id}_{selected_color}_{selected_size}"
    
    try:
        # جلب تفاصيل المخزن بدقة
        stock_item = ProductSize.objects.get(
            variant__product_id=product_id,
            variant__color_name=selected_color,
            size_name=selected_size
        )
        
        current_qty = cart.get(item_key, {}).get('quantity', 0)
        
        if current_qty < stock_item.stock:
            if item_key in cart:
                cart[item_key]['quantity'] += 1
            else:
                cart[item_key] = {
                    'product_id': product_id,
                    'quantity': 1,
                    'color': selected_color,
                    'size': selected_size
                }
            
            request.session[user_cart_key] = cart
            request.session.modified = True
            messages.success(request, f'تمت إضافة المنتج ({selected_color} - {selected_size}) إلى السلة!')
        else:
            messages.warning(request, f"نأسف، المخزن يحتوي على {stock_item.stock} قطع فقط من هذا النوع.")
            
    except ProductSize.DoesNotExist:
        messages.error(request, "عذراً، هذا النوع غير متوفر حالياً.")

    return redirect(request.META.get('HTTP_REFERER', 'shop'))
def add_collection_to_cart(request, collection_id):
    user_cart_key = get_user_cart_key(request)
    cart = request.session.get(user_cart_key, {})
    
    collection = get_object_or_404(ProductCollection, id=collection_id)
    item_key = f"col_{collection_id}"
    
    # حساب الكمية المطلوبة (لو الباكدج موجودة في السلة هنزود 1، لو مش موجودة هتبقى 1)
    current_qty = cart.get(item_key, {}).get('quantity', 0)
    requested_qty = current_qty + 1
    
    # فحص المخزون لكل المنتجات داخل الباكدج قبل إضافتها
    can_add = True
    for item in collection.items.all():
        total_required_qty = item.quantity * requested_qty
        
        if item.product_size:
            if item.product_size.stock < total_required_qty:
                messages.warning(request, f"عذراً، المتاح من {item.product.name} (مقاس {item.product_size.size_name}) لا يكفي للباكدج.")
                can_add = False
                break
        else:
            # في حالة إن المنتج ملوش نظام مقاسات
            if item.product.stock < total_required_qty:
                messages.warning(request, f"عذراً، المتاح من {item.product.name} لا يكفي للباكدج.")
                can_add = False
                break

    if can_add:
        if item_key in cart:
            cart[item_key]['quantity'] += 1
        else:
            cart[item_key] = {
                'type': 'collection',
                'collection_id': collection_id,
                'quantity': 1,
                'price': str(collection.offer_price)
            }
        
        request.session[user_cart_key] = cart
        request.session.modified = True
        messages.success(request, f'تمت إضافة الباكدج ({collection.name}) إلى السلة بنجاح!')

    return redirect(request.META.get('HTTP_REFERER', 'offers'))

def cart_view(request):
    user_cart_key = get_user_cart_key(request)
    cart = request.session.get(user_cart_key, {})
    
    if not isinstance(cart, dict):
        cart = {}
        request.session[user_cart_key] = cart

    cart_items = []
    total_price = Decimal('0.00')
    
    for item_key, item_data in cart.items():
        if not isinstance(item_data, dict): continue
            
        quantity = item_data.get('quantity', 1)

        # --- 1. التعامل مع الباكدجات (Collections) ---
        if item_data.get('type') == 'collection':
            try:
                collection = ProductCollection.objects.get(id=item_data.get('collection_id'))
                price = collection.offer_price
                subtotal = price * quantity
                total_price += subtotal
                
                cart_items.append({
                    'item_key': item_key,
                    'is_collection': True, # عشان نقدر نميزه في الـ Template
                    'collection': collection,
                    'quantity': quantity,
                    'display_image': collection.main_image.url if collection.main_image else '',
                    'subtotal': subtotal,
                    'actual_price': price
                })
            except ProductCollection.DoesNotExist:
                continue

        # --- 2. التعامل مع المنتجات العادية ---
        else:
            try:
                product = Product.objects.get(id=item_data.get('product_id'))
                # تحديد السعر بناءً على وجود خصم
                price = product.discount_price if product.discount_price else product.price
                subtotal = price * quantity
                total_price += subtotal
                
                variant = ProductVariant.objects.filter(product=product, color_name=item_data.get('color')).first()
                display_image = variant.variant_image.url if variant and variant.variant_image else product.main_image
                
                cart_items.append({
                    'item_key': item_key,
                    'is_collection': False,
                    'product': product,
                    'quantity': quantity,
                    'color': item_data.get('color'),
                    'size': item_data.get('size', 'N/A'),
                    'display_image': display_image,
                    'subtotal': subtotal,
                    'actual_price': price
                })
            except (Product.DoesNotExist, AttributeError):
                continue
        
    return render(request, 'cart.html', {'cart_items': cart_items, 'total_price': total_price})


def update_cart(request, item_key, action):
    user_cart_key = get_user_cart_key(request)
    cart = request.session.get(user_cart_key, {})
    
    if item_key in cart:
        item_data = cart[item_key]
        
        if action == 'increase':
            # --- زيادة كمية الباكدج ---
            if item_data.get('type') == 'collection':
                try:
                    collection = ProductCollection.objects.get(id=item_data['collection_id'])
                    requested_qty = item_data['quantity'] + 1
                    can_add = True
                    
                    # فحص المخزون لكل المنتجات داخل الباكدج للتأكد من تحمل الزيادة
                    for item in collection.items.all():
                        total_required_qty = item.quantity * requested_qty
                        if item.product_size:
                            if item.product_size.stock < total_required_qty:
                                messages.warning(request, f"عذراً، المتاح من {item.product.name} (مقاس {item.product_size.size_name}) لا يكفي لزيادة الباكدج.")
                                can_add = False
                                break
                        else:
                            if item.product.stock < total_required_qty:
                                messages.warning(request, f"عذراً، المتاح من {item.product.name} لا يكفي لزيادة الباكدج.")
                                can_add = False
                                break
                    
                    if can_add:
                        cart[item_key]['quantity'] += 1
                        
                except ProductCollection.DoesNotExist:
                    messages.error(request, "الباكدج غير موجودة.")
            
            # --- زيادة كمية المنتج العادي ---
            else:
                try:
                    stock_item = ProductSize.objects.get(
                        variant__product_id=item_data['product_id'],
                        variant__color_name=item_data['color'],
                        size_name=item_data['size']
                    )
                    if item_data['quantity'] < stock_item.stock:
                        cart[item_key]['quantity'] += 1
                    else:
                        messages.warning(request, f"عذراً، لا يوجد سوى {stock_item.stock} قطع في المخزن.")
                except ProductSize.DoesNotExist:
                    # التحقق من المخزن العام للمنتج إذا لم توجد تفاصيل مقاسات
                    product = get_object_or_404(Product, id=item_data['product_id'])
                    if item_data['quantity'] < product.stock:
                        cart[item_key]['quantity'] += 1
                    else:
                        messages.warning(request, "تم الوصول للحد الأقصى المتاح في المخزن.")
                
        elif action == 'decrease':
            cart[item_key]['quantity'] -= 1
            if cart[item_key]['quantity'] <= 0: 
                del cart[item_key]
                messages.info(request, "تمت الإزالة من السلة.")
                
        request.session[user_cart_key] = cart
        request.session.modified = True
    else:
        messages.error(request, "تعذر العثور على العنصر في سلتك.")
        
    return redirect('cart_view')

def remove_from_cart(request, item_key):
    user_cart_key = get_user_cart_key(request)
    cart = request.session.get(user_cart_key, {})
    if item_key in cart:
        del cart[item_key]
        request.session[user_cart_key] = cart
        request.session.modified = True
    return redirect('cart_view')

# --- إتمام الشراء (Checkout) ---
def checkout_view(request):
    if request.user.is_authenticated:
        user_cart_key = f"cart_{request.user.id}"
    else:
        user_cart_key = "cart_guest"
        
    cart = request.session.get(user_cart_key, {})
    
    if not cart:
        messages.warning(request, "سلة المشتريات فارغة!")
        return redirect('shop')

    total_price = 0
    checkout_items = []
    
    # --- 1. التحقق من المخزن وحساب الإجمالي ---
    for item_key, item_data in cart.items():
        quantity_requested = item_data['quantity']
        
        # إذا كان العنصر باكدج (Collection)
        if item_data.get('type') == 'collection':
            collection = get_object_or_404(ProductCollection, id=item_data['collection_id'])
            
            # التحقق من مخزون كل منتج داخل الباكدج
            for c_item in collection.items.all():
                total_req_qty = c_item.quantity * quantity_requested
                if c_item.product_size:
                    if c_item.product_size.stock < total_req_qty:
                        messages.error(request, f"عذراً، المتاح من {c_item.product.name} (مقاس {c_item.product_size.size_name}) لا يكفي للباكدج.")
                        return redirect('cart_view')
                else:
                    if c_item.product.stock < total_req_qty:
                        messages.error(request, f"عذراً، المنتج {c_item.product.name} لا يكفي للباكدج.")
                        return redirect('cart_view')

            subtotal = collection.offer_price * quantity_requested
            total_price += subtotal
            
            domain = "www.elbasty-groub.com"
            protocol = "https" # لأننا فعلنا الـ SSL خلاص
            image_url = f"{protocol}://{domain}{img_path}"

            checkout_items.append({
                'is_collection': True,
                'collection': collection,
                'subtotal': subtotal,
                'data': item_data,
                'unit_price': collection.offer_price,
                'image_url': image_url
            })

        # إذا كان العنصر منتج عادي
        else:
            product = get_object_or_404(Product, id=item_data['product_id'])
            color_name = item_data.get('color')
            size_name = item_data.get('size')
            
            variant_size = ProductSize.objects.filter(
                variant__product=product, 
                variant__color_name=color_name, 
                size_name=size_name
            ).first()
            
            if variant_size:
                if variant_size.stock < quantity_requested:
                    messages.error(request, f"عذراً، المتاح فقط {variant_size.stock} من {product.name} ({color_name} - {size_name}).")
                    return redirect('cart_view')
            else:
                if product.stock < quantity_requested:
                    messages.error(request, f"عذراً، المنتج {product.name} غير متوفر حالياً.")
                    return redirect('cart_view')

            price = product.discount_price if product.discount_price else product.price
            subtotal = price * quantity_requested
            total_price += subtotal

            variant = ProductVariant.objects.filter(product=product, color_name=color_name).first()
            img_path = variant.variant_image.url if variant and variant.variant_image else product.main_image
            
            domain = request.get_host()
            protocol = 'https' if request.is_secure() else 'http'
            image_url = f"{protocol}://{domain}{img_path}"

            checkout_items.append({
                'is_collection': False,
                'product': product, 
                'subtotal': subtotal, 
                'data': item_data, 
                'variant_size': variant_size,
                'unit_price': price,
                'image_url': image_url
            })

    # --- 2. معالجة الطلب (POST) ---
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        governorate = request.POST.get('governorate')
        address = request.POST.get('address')

        order = Order.objects.create(
            name=name, email=email, phone=phone,
            governorate=governorate, address=address,
            total_price=total_price
        )
        
        if request.user.is_authenticated:
            order.user = request.user
            order.save()

        email_items_html = ""
        
        for item in checkout_items:
            qty_requested = item['data']['quantity']

            # تسجيل الباكدج في قاعدة البيانات والإيميل
            if item.get('is_collection'):
                collection = item['collection']
                bundle_original_price = collection.original_total_price
                
                email_items_html += f"""
                    <tr>
                        <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; vertical-align: middle; text-align:right;" dir="rtl">
                            <img src="{item['image_url']}" width="60" height="60" style="border-radius:8px; margin-left:12px; vertical-align:middle; border:1px solid #cbd5e1; object-fit: cover;">
                            <div style="display: inline-block; vertical-align: middle;">
                                <strong style="font-size: 15px; color: #00e5ff;">باكدج: {collection.name}</strong><br>
                                <span style="font-size: 12px; color: #64748b;">مجموعة مكونة من {collection.items.count()} أصناف</span>
                            </div>
                        </td>
                        <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; text-align:center; color: #334155;">{qty_requested}</td>
                        <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; text-align:left; font-weight: bold; color: #0f172a;">{int(item['subtotal'])} ج.م</td>
                    </tr>
                """

                # تسجيل المنتجات اللي جوه الباكدج وخصمها من المخزن
                for c_item in collection.items.all():
                    # التوزيع النسبي للسعر عشان الأرباح
                    item_orig_price = Decimal(str(c_item.product.get_effective_price)) * c_item.quantity
                    ratio = item_orig_price / bundle_original_price if bundle_original_price > 0 else 0
                    proportional_unit_price = (collection.offer_price * ratio) / c_item.quantity

                    variant_color = c_item.variant.color_name if c_item.variant else 'Default'
                    size_name = c_item.product_size.size_name if c_item.product_size else 'N/A'
                    total_item_qty = c_item.quantity * qty_requested

                    OrderItem.objects.create(
                        order=order, product=c_item.product, color=variant_color, size=size_name,
                        quantity=total_item_qty, price_at_purchase=proportional_unit_price
                    )

                    # الخصم من المخزن
                    if c_item.product_size:
                        c_item.product_size.stock -= total_item_qty
                        c_item.product_size.save()
                    else:
                        c_item.product.stock -= total_item_qty
                        c_item.product.save()

            # تسجيل المنتج العادي في قاعدة البيانات والإيميل
            else:
                product = item['product']
                variant_size = item['variant_size']
                color = item['data']['color']
                size = item['data']['size']
                price_each = item['unit_price']
                sku = product.sku if hasattr(product, 'sku') and product.sku else "N/A"

                OrderItem.objects.create(
                    order=order, product=product, color=color, size=size,
                    quantity=qty_requested, price_at_purchase=price_each
                )

                email_items_html += f"""
                    <tr>
                        <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; vertical-align: middle; text-align:right;" dir="rtl">
                            <img src="{item['image_url']}" width="60" height="60" style="border-radius:8px; margin-left:12px; vertical-align:middle; border:1px solid #cbd5e1; object-fit: cover;">
                            <div style="display: inline-block; vertical-align: middle;">
                                <strong style="font-size: 15px; color: #0f172a;">{product.name}</strong><br>
                                <span style="font-size: 12px; color: #64748b;">كود: {sku}</span><br>
                                <span style="font-size: 12px; color: #475569;">اللون: {color} | المقاس: {size}</span>
                            </div>
                        </td>
                        <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; text-align:center; color: #334155;">{qty_requested}</td>
                        <td style="padding: 12px; border-bottom: 1px solid #e2e8f0; text-align:left; font-weight: bold; color: #0f172a;">{int(item['subtotal'])} ج.م</td>
                    </tr>
                """

                # الخصم من المخزن
                if variant_size:
                    variant_size.stock -= qty_requested
                    variant_size.save()
                else:
                    product.stock -= qty_requested
                    product.save()

        # إرسال الإيميل
        html_message = f"""
        <div dir="rtl" style="font-family: 'Cairo', Tahoma, Arial, sans-serif; max-width: 600px; margin: auto; border: 1px solid #00e5ff; border-radius: 12px; overflow: hidden; background-color: #ffffff; text-align: right; box-shadow: 0 4px 20px rgba(0, 229, 255, 0.1);">
            <div style="background-color: #020617; padding: 30px; text-align: center; border-bottom: 3px solid #00e5ff;">
                <h1 style="margin: 0; font-size: 28px; font-weight: 800; color: #00e5ff;">الباسطى جروب</h1>
                <p style="margin: 5px 0 0; font-size: 14px; color: #94a3b8;">تأكيد طلب رقم #{order.id}</p>
            </div>
            <div style="padding: 30px;">
                <h2 style="color: #0f172a; margin-top: 0;">أهلاً {name}،</h2>
                <p style="color: #475569; line-height: 1.6; font-size: 15px;">لقد استلمنا طلبك بنجاح وجاري العمل على تجهيزه لإرساله في أسرع وقت.</p>
                <table style="width: 100%; border-collapse: collapse; margin-top: 25px;">
                    <thead>
                        <tr style="background-color: #0f172a; color: #ffffff;">
                            <th style="text-align: right; padding: 12px; font-weight: 600;">المنتج</th>
                            <th style="text-align: center; padding: 12px; font-weight: 600;">الكمية</th>
                            <th style="text-align: left; padding: 12px; font-weight: 600;">الإجمالي</th>
                        </tr>
                    </thead>
                    <tbody>{email_items_html}</tbody>
                    <tfoot>
                        <tr>
                            <td colspan="2" style="padding: 20px 10px; text-align: left; font-size: 16px; color: #64748b;">الإجمالي النهائي:</td>
                            <td style="padding: 20px 0; text-align: left; font-size: 22px; font-weight: bold; color: #00e5ff; text-shadow: 0 0 1px #00e5ff;">{int(total_price)} ج.م</td>
                        </tr>
                    </tfoot>
                </table>
                <div style="margin-top: 30px; padding: 20px; background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; border-right: 4px solid #00e5ff;">
                    <h4 style="margin: 0 0 15px 0; color: #0f172a; font-size: 16px;">بيانات الشحن والتواصل</h4>
                    <p style="margin: 5px 0; font-size: 14px; color: #475569;"><strong>العنوان:</strong> {address}</p>
                    <p style="margin: 5px 0; font-size: 14px; color: #475569;"><strong>المحافظة:</strong> {governorate}</p>
                    <p style="margin: 5px 0; font-size: 14px; color: #475569;"><strong>الهاتف:</strong> {phone}</p>
                </div>
            </div>
            <div style="background-color: #f1f5f9; padding: 20px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #e2e8f0;">
                هذه رسالة تلقائية، يرجى عدم الرد عليها مباشرة.<br><br>
                © 2026 الباسطى جروب. جميع الحقوق محفوظة.
            </div>
        </div>
        """

        subject = f"تأكيد طلبك من الباسطى جروب - طلب رقم #{order.id}"
        plain_message = strip_tags(html_message)
        
        try:
            send_mail(
                subject, 
                plain_message, 
                settings.EMAIL_HOST_USER, 
                [email, settings.EMAIL_HOST_USER], 
                html_message=html_message,
                fail_silently=True
            )
        except Exception as e:
            print(f"Error sending email: {e}")

        # تصفير السلة بعد نجاح الطلب
        request.session[user_cart_key] = {}
        request.session.modified = True
        return render(request, 'order_success.html', {'order': order})

    return render(request, 'checkout.html', {'total_price': total_price, 'checkout_items': checkout_items})

def is_admin(user):
    return user.is_authenticated and user.is_staff

# --- لوحة التحكم والإدارة (Dashboard & Admin) ---

@user_passes_test(is_admin, login_url='login')
def dashboard_view(request):
    orders = Order.objects.all().order_by('-created_at')
    products = Product.objects.all().order_by('-created_at')
    messages_list = ContactMessage.objects.all().order_by('-created_at')
    
    # استخدام التجميع (Aggregation) لحساب الإجمالي بكفاءة
    total_revenue = orders.filter(status='Delivered').aggregate(Sum('total_price'))['total_price__sum'] or 0
    
    context = {
        'orders': orders,
        'products': products,
        'messages': messages_list,
        'orders_count': orders.count(),
        'pending_orders': orders.filter(status='Pending').count(),
        'shipped_orders': orders.filter(status='Shipped').count(),
        'delivered_orders': orders.filter(status='Delivered').count(),
        'products_count': products.count(),
        'total_revenue': total_revenue,
    }
    return render(request, 'dashboard.html', context)

@user_passes_test(is_admin, login_url='login')
def add_product(request):
    # ملاحظة: استدعاء VariantFormSet يتطلب استيراده من ملف forms.py
    from .forms import VariantFormSet # استيراد محلي لتجنب التعارض
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES)
        formset = VariantFormSet(request.POST, request.FILES)
        
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                product = form.save()
                for i, v_form in enumerate(formset.forms):
                    if v_form.cleaned_data and not v_form.cleaned_data.get('DELETE', False):
                        variant = v_form.save(commit=False)
                        variant.product = product
                        variant.save()
                        v_form.save_m2m()
                        
                        # معالجة المقاسات الديناميكية
                        size_names = request.POST.getlist(f'size_name_{i}[]')
                        size_quantities = request.POST.getlist(f'size_qty_{i}[]')
                        for name, qty in zip(size_names, size_quantities):
                            if name.strip():
                                ProductSize.objects.create(
                                    variant=variant, size_name=name.strip(),
                                    stock=int(qty) if qty else 0
                                )
                        # معالجة الصور الإضافية
                        extra_images = request.FILES.getlist(f'images_custom_{i}')
                        for img in extra_images:
                            ProductImage.objects.create(variant=variant, image=img)

            messages.success(request, 'تمت إضافة المنتج وجميع المتغيرات بنجاح! ✅')
            return redirect('dashboard')
    else:
        form = ProductForm()
        formset = VariantFormSet()
    
    return render(request, 'manage_product.html', {'form': form, 'formset': formset, 'title': 'Add New Product'})

@user_passes_test(is_admin, login_url='login')
def edit_product(request, pk):
    from .forms import VariantFormSet
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, request.FILES, instance=product)
        formset = VariantFormSet(request.POST, request.FILES, instance=product)
        
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                for i, v_form in enumerate(formset.forms):
                    if v_form.cleaned_data and not v_form.cleaned_data.get('DELETE', False):
                        variant = v_form.save(commit=False)
                        variant.product = product
                        variant.save()
                        v_form.save_m2m()
                        
                        # تحديث المقاسات (حذف القديم وإضافة الجديد للتعديل السريع)
                        size_names = request.POST.getlist(f'size_name_{i}[]')
                        size_quantities = request.POST.getlist(f'size_qty_{i}[]')
                        if size_names:
                            variant.sizes.all().delete() # استبدال المقاسات القديمة
                            for name, qty in zip(size_names, size_quantities):
                                if name.strip():
                                    ProductSize.objects.create(
                                        variant=variant, size_name=name.strip(),
                                        stock=int(qty) if qty else 0
                                    )
                        # إضافة صور جديدة
                        for img in request.FILES.getlist(f'images_custom_{i}'):
                            ProductImage.objects.create(variant=variant, image=img)
                    elif v_form.cleaned_data.get('DELETE', False) and v_form.instance.pk:
                        v_form.instance.delete()

            messages.success(request, 'تم تحديث المنتج بنجاح! ✨')
            return redirect('dashboard')
    else:
        form = ProductForm(instance=product)
        formset = VariantFormSet(instance=product)
    
    return render(request, 'manage_product.html', {'form': form, 'formset': formset, 'title': f'Edit: {product.name}'})

@user_passes_test(is_admin, login_url='login')
def delete_product(request, pk):
    product = get_object_or_404(Product, pk=pk)
    product.delete()
    messages.error(request, 'تم حذف المنتج بنجاح! 🗑️')
    return redirect('dashboard')

@user_passes_test(is_admin, login_url='login')
def update_order_status(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id)
        new_status = request.POST.get('status')
        old_status = order.status # حفظ الحالة القديمة للمقارنة

        if new_status in dict(Order.STATUS_CHOICES):
            # التأكد من أننا نغير الحالة إلى ملغي ولم يكن ملغياً من قبل (لتجنب تكرار الإرجاع)
            if new_status == 'Canceled' and old_status != 'Canceled':
                with transaction.atomic(): # استخدام الترانزاكشن لضمان سلامة البيانات
                    for item in order.items.all():
                        # محاولة العثور على المقاس المحدد للمنتج
                        variant_size = ProductSize.objects.filter(
                            variant__product=item.product,
                            variant__color_name=item.color,
                            size_name=item.size
                        ).first()

                        if variant_size:
                            variant_size.stock += item.quantity
                            variant_size.save()
                        elif item.product:
                            # إذا لم يكن هناك نظام مقاسات، نعدل مخزن المنتج العام
                            item.product.stock += item.quantity
                            item.product.save()

            order.status = new_status
            order.save() 
            messages.success(request, f'تم تحديث حالة الطلب #{order.id} إلى {new_status}')
        else:
            messages.error(request, 'حالة طلب غير صالحة.')
            
    return redirect('dashboard')

@user_passes_test(is_admin, login_url='login')
def update_item_quantity(request, item_id):
    if request.method == 'POST':
        item = get_object_or_404(OrderItem, id=item_id)
        order = item.order
        action = request.POST.get('action', 'update') 
        product_name = item.product.name if item.product else "منتج"

        if action == 'delete':
            item.delete()
            if not order.items.exists():
                order.status = 'Canceled'
                order.total_price = 0
            else:
                order.total_price = sum(i.quantity * i.price_at_purchase for i in order.items.all())
            order.save()
            messages.success(request, f'تم حذف {product_name} من الطلب.')
            subject, email_content = "تحديث طلبك", f"تمت إزالة {product_name} من طلبك رقم #{order.id}."
        else:
            new_qty = int(request.POST.get('quantity', 1))
            if new_qty > 0:
                item.quantity = new_qty
                item.save()
                order.total_price = sum(Decimal(str(i.quantity * i.price_at_purchase)) for i in order.items.all())
                order.save()
                messages.success(request, f'تم تحديث كمية {product_name}.')
                subject, email_content = "تحديث كمية الطلب", f"تم تحديث الكمية لـ {product_name} في الطلب #{order.id}."
            else:
                messages.error(request, 'الكمية غير صالحة.')
                return redirect('dashboard')

        try: send_mail(subject, email_content, settings.EMAIL_HOST_USER, [order.email], fail_silently=True)
        except Exception: pass
        
    return redirect('dashboard')

@user_passes_test(is_admin, login_url='login')
def apply_order_discount(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id)
        try:
            discount_amount = Decimal(request.POST.get('discount_amount', '0'))
            # حساب الإجمالي الأصلي
            original_total = sum(Decimal(str(i.quantity * i.price_at_purchase)) for i in order.items.all())
            
            if 0 <= discount_amount <= original_total:
                new_total = original_total - discount_amount
                order.total_price = new_total
                order.save()

                # --- بناء صفوف المنتجات للجدول ---
                items_html = ""
                domain = request.get_host()
                protocol = 'https' if request.is_secure() else 'http'

                for item in order.items.all():
                    variant = ProductVariant.objects.filter(product=item.product, color_name=item.color).first()
                    img_path = variant.variant_image.url if variant and variant.variant_image else item.product.main_image
                    image_url = f"{protocol}://{domain}{img_path}"
                    
                    items_html += f"""
                    <tr>
                        <td style="padding: 12px; border-bottom: 1px solid #eee; text-align:right;">
                            <img src="{image_url}" width="50" height="50" style="border-radius:5px; vertical-align:middle; margin-left:10px; object-fit:cover;">
                            <span style="color:#333; font-weight:bold;">{item.product.name}</span>
                        </td>
                        <td style="padding: 12px; border-bottom: 1px solid #eee; text-align:center;">{item.quantity}</td>
                        <td style="padding: 12px; border-bottom: 1px solid #eee; text-align:left;">{int(item.quantity * item.price_at_purchase)} ج.م</td>
                    </tr>
                    """

                # --- التصميم الاحترافي للرسالة ---
                html_message = f"""
                <div dir="rtl" style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: auto; border: 1px solid #e2d1b0; border-radius: 15px; overflow: hidden; background-color: #ffffff;">
                    <div style="background: linear-gradient(135deg, #c5a059 0%, #b8860b 100%); color: #ffffff; padding: 25px; text-align: center;">
                        <h2 style="margin: 0;">الباسطى جروب</h2>
                        <p style="margin: 5px 0 0; opacity: 0.9;">تحديث السعر للطلب #{order.id}</p>
                    </div>
                    
                    <div style="padding: 30px; line-height: 1.6; color: #444; text-align: right;">
                        <h3 style="color: #b8860b;">أهلاً {order.name}،</h3>
                        <p>يسعدنا إبلاغك بأنه تم تطبيق <strong>خصم خاص</strong> على طلبك. أدناه تفاصيل الفاتورة المحدثة:</p>
                        
                        <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">
                            <thead>
                                <tr style="background-color: #f9f6f0; color: #333;">
                                    <th style="padding: 10px; text-align: right; border-bottom: 2px solid #c5a059;">المنتج</th>
                                    <th style="padding: 10px; text-align: center; border-bottom: 2px solid #c5a059;">الكمية</th>
                                    <th style="padding: 10px; text-align: left; border-bottom: 2px solid #c5a059;">السعر</th>
                                </tr>
                            </thead>
                            <tbody>
                                {items_html}
                            </tbody>
                        </table>

                        <div style="margin-top: 20px; padding: 15px; background-color: #fcfaf5; border-radius: 10px;">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 8px; color: #777;">
                                <span>الإجمالي الأصلي:</span>
                                <span>{int(original_total)} ج.م</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 8px; color: #d9534f; font-weight: bold;">
                                <span>قيمة الخصم:</span>
                                <span>- {int(discount_amount)} ج.م</span>
                            </div>
                            <div style="display: flex; justify-content: space-between; border-top: 1px solid #e2d1b0; pt-10px; margin-top: 10px; font-size: 20px; color: #b8860b; font-weight: bold;">
                                <span>الإجمالي الجديد:</span>
                                <span>{int(new_total)} ج.م</span>
                            </div>
                        </div>

                        <p style="margin-top: 25px; font-size: 14px; color: #666; border-right: 3px solid #c5a059; padding-right: 10px;">
                            سيتم التواصل معكم قريباً لتأكيد موعد التسليم النهائي 
                        </p>
                    </div>

                    <div style="background-color: #f4f4f4; padding: 15px; text-align: center; font-size: 12px; color: #999;">
                        © 2026 جميع الحقوق محفوظةالباسطى جروب
                    </div>
                </div>
                """

                subject = f"هدية من الباسطى جروب: تم تطبيق خصم على طلبك #{order.id}"
                plain_message = f"تم تطبيق خصم بقيمة {discount_amount} ج.م. الإجمالي الجديد: {new_total} ج.م"

                send_mail(
                    subject=subject,
                    message=plain_message,
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[order.email],
                    html_message=html_message,
                    fail_silently=False  # غيرتها لـ False عشان لو فيه مشكلة في الإعدادات تظهرلك
                )

                messages.success(request, f'تم تطبيق خصم بقيمة {discount_amount} ج.م وإرسال البريد بنجاح.')
            else:
                messages.error(request, 'قيمة الخصم غير منطقية (أكبر من الإجمالي أو أقل من صفر).')
        except Exception as e:
            messages.error(request, f'خطأ في معالجة الخصم: {e}')
            
    return redirect('dashboard')
# --- دوال الحسابات والسياسات ---

def login_view(request):
    if request.method == 'POST':
        u, p = request.POST.get('username'), request.POST.get('password')
        user = authenticate(request, username=u, password=p)
        if user:
            login(request, user)
            messages.success(request, f'أهلاً بك مجدداً {u}!')
            return redirect('home')
        messages.error(request, 'اسم المستخدم أو كلمة المرور غير صحيحة.')
    return render(request, 'login.html')

def signup_view(request):
    if request.method == 'POST':
        u, e, p = request.POST.get('username'), request.POST.get('email'), request.POST.get('password')
        if User.objects.filter(username=u).exists():
            messages.error(request, 'اسم المستخدم مأخوذ بالفعل.')
        else:
            User.objects.create_user(username=u, email=e, password=p)
            messages.success(request, 'تم إنشاء الحساب! سجل دخولك الآن.')
            return redirect('login')
    return render(request, 'signup.html')

def logout_view(request):
    logout(request)
    messages.info(request, "تم تسجيل الخروج.")
    return redirect('home')

def about_view(request):
    return render(request, 'about.html')

def offers_view(request):
    # 1. جلب المنتجات اللي عليها خصم (نفس الكود الأصلي بتاعك مع تحسين الأداء)
    products_list = Product.objects.filter(
        discount_price__gt=0
    ).prefetch_related(
        'variants__sizes', 
        'variants__additional_images'
    ).annotate(
        is_available_group=Case(
            When(stock__gt=0, then=Value(0)), 
            default=Value(1), 
            output_field=IntegerField()
        ),
        manual_new_priority=Case(
            When(is_new_arrival=True, then=Value(1)), 
            default=Value(0), 
            output_field=IntegerField()
        )
    ).order_by('is_available_group', '-manual_new_priority', '-created_at')

    # 💡 2. الإضافة الجديدة: جلب الباكدجات (Collections) المفعلة
    # بنستخدم prefetch_related عشان نجلب المنتجات اللي جوه الباكدج بطلبة واحدة لقاعدة البيانات
    collections = ProductCollection.objects.filter(is_active=True).prefetch_related(
        'items__product', 
        'items__variant',
        'items__product_size'
    )

    # --- إعداد نظام التقسيم للمنتجات ---
    paginator = Paginator(products_list, 20) 
    page_number = request.GET.get('page')
    products = paginator.get_page(page_number)

    context = {
        'products': products, 
        'collections': collections, # <-- ضفنا الباكدجات هنا عشان تظهر في الـ Template
        'title': 'Exclusive Offers & Packages'
    }
    return render(request, 'offers.html', context)

def policies(request):
    return render(request, 'policies.html')

@user_passes_test(is_admin, login_url='login')
def reset_orders(request):
    """حذف جميع الطلبات وتصفير العداد (لأغراض الصيانة فقط)"""
    if request.method == "POST":
        try:
            Order.objects.all().delete()            
            with connection.cursor() as cursor:
                # تصفير عداد الـ ID في قاعدة بيانات SQLite
                cursor.execute("DELETE FROM sqlite_sequence WHERE name='store_order'")
            messages.success(request, "تم حذف جميع الطلبات وتصفير السجل بنجاح.")
        except Exception as e:
            messages.error(request, f"خطأ أثناء المسح: {e}")
    return redirect('dashboard')

# ============================================================
# إدارة المخزن - Inventory Management
# ============================================================

@user_passes_test(is_admin, login_url='login')
def inventory_dashboard(request):
    """الصفحة الرئيسية لإدارة المخزن"""
    products = Product.objects.all().order_by('name')
    recent_movements = StockMovement.objects.select_related('product', 'supplier', 'variant', 'product_size').order_by('-created_at')[:20]
    recent_invoices = Invoice.objects.order_by('-created_at')[:10]
    suppliers = Supplier.objects.all()
    total_stock_value = sum(p.get_effective_price * p.stock for p in products)
    total_purchases_cost = StockMovement.objects.filter(movement_type='in').aggregate(
        total=Sum(django_models.ExpressionWrapper(
            django_models.F('quantity') * django_models.F('unit_price'),
            output_field=django_models.DecimalField()
        ))
    )['total'] or 0

    total_sales_revenue = Invoice.objects.aggregate(total=Sum('total_amount'))['total'] or Decimal(0)
    # إضافة إيرادات الأوردرات الـ Delivered من الموقع
    delivered_orders_revenue = Order.objects.filter(status='Delivered').aggregate(
        total=Sum('total_price'))['total'] or Decimal(0)
    total_sales_revenue = total_sales_revenue + delivered_orders_revenue
    try:
        from .models import InvoiceItem
        # حساب تكلفة البضاعة المباعة من خلال متوسط سعر الشراء من حركات المخزن الواردة
        # نحسب متوسط سعر الشراء لكل منتج
        from django.db.models import FloatField
        purchase_data = StockMovement.objects.filter(movement_type='in').values('product').annotate(
            total_cost=Sum(django_models.ExpressionWrapper(
                django_models.F('quantity') * django_models.F('unit_price'),
                output_field=django_models.DecimalField()
            )),
            total_qty=Sum('quantity')
        )
        # بناء dict: product_id -> average_cost_per_unit
        avg_cost_map = {}
        for row in purchase_data:
            if row['total_qty'] and row['total_qty'] > 0:
                avg_cost_map[row['product']] = row['total_cost'] / row['total_qty']

        # حساب إجمالي تكلفة البضاعة المباعة (من الفواتير)
        invoice_items = InvoiceItem.objects.select_related('product').all()
        cost_of_goods_sold = Decimal(0)
        for item in invoice_items:
            avg_cost = avg_cost_map.get(item.product_id, Decimal(0))
            cost_of_goods_sold += Decimal(str(avg_cost)) * item.quantity

        # إضافة تكلفة الأوردرات الـ Delivered من الموقع
        delivered_order_items = OrderItem.objects.filter(
            order__status='Delivered'
        ).select_related('product')
        for oi in delivered_order_items:
            avg_cost = avg_cost_map.get(oi.product_id, Decimal(0))
            cost_of_goods_sold += Decimal(str(avg_cost)) * oi.quantity
    except Exception as e:
        print(f"Error calculating COGS: {e}")
        cost_of_goods_sold = 0
    net_profit = total_sales_revenue - cost_of_goods_sold
    total_in = StockMovement.objects.filter(movement_type='in').aggregate(
        total_qty=Sum('quantity'))['total_qty'] or 0
    total_out = StockMovement.objects.filter(movement_type='out').aggregate(
        total_qty=Sum('quantity'))['total_qty'] or 0
    pending_payments_in = StockMovement.objects.filter(
        movement_type='in', amount_remaining__gt=0
    ).aggregate(total=Sum('amount_remaining'))['total'] or 0
    pending_payments_inv = Invoice.objects.filter(
        amount_remaining__gt=0
    ).aggregate(total=Sum('amount_remaining'))['total'] or 0
    total_receivables = Receivable.objects.filter(status__in=['pending', 'partial']).aggregate(
        total=Sum('amount_remaining'))['total'] or 0
    total_payables = Payable.objects.filter(status__in=['pending', 'partial']).aggregate(
        total=Sum('amount_remaining'))['total'] or 0

    context = {
        'products': products,
        'recent_movements': recent_movements,
        'recent_invoices': recent_invoices,
        'suppliers': suppliers,
        'total_stock_value': total_stock_value,
        'total_in': total_in,
        'total_out': total_out,
        'pending_payments_in': pending_payments_in,
        'pending_payments_inv': pending_payments_inv,
        'net_profit': net_profit, # تم التعديل
        'total_purchases_cost': total_purchases_cost,
        'total_sales_revenue': total_sales_revenue,
        'delivered_orders_revenue': delivered_orders_revenue,
        'total_receivables': total_receivables,
        'total_payables': total_payables,
    }
    return render(request, 'inventory/dashboard.html', context)

@user_passes_test(is_admin, login_url='login')
def add_stock_movement(request):
    """إضافة حركة مخزن (وارد أو صادر)"""
    products = Product.objects.prefetch_related('variants__sizes').order_by('name')
    suppliers = Supplier.objects.all().order_by('name')

    if request.method == 'POST':
        movement_type = request.POST.get('movement_type')
        product_id = request.POST.get('product')
        variant_id = request.POST.get('variant')
        size_id = request.POST.get('product_size')
        quantity = int(request.POST.get('quantity', 0))
        unit_price = Decimal(request.POST.get('unit_price', 0))
        payment_type = request.POST.get('payment_type', 'cash')
        amount_paid = Decimal(request.POST.get('amount_paid', 0))
        date = request.POST.get('date')
        notes = request.POST.get('notes', '')
        supplier_id = request.POST.get('supplier')

        new_supplier_name = request.POST.get('new_supplier_name', '').strip()
        new_supplier_phone = request.POST.get('new_supplier_phone', '').strip()

        product = get_object_or_404(Product, pk=product_id)
        variant = ProductVariant.objects.filter(pk=variant_id).first() if variant_id else None
        product_size = ProductSize.objects.filter(pk=size_id).first() if size_id else None

        total = quantity * unit_price
        remaining = total - amount_paid
        if remaining < 0:
            remaining = Decimal(0)

        # ✅ Validation: المتبقي لازم يكون صفر لو مش آجل
        if payment_type != 'credit' and remaining > 0:
            import json as _json
            products_data_err = {}
            for p in products:
                variants_data = {}
                for v in p.variants.all():
                    sizes_data = {str(s.pk): {'name': s.size_name, 'stock': s.stock} for s in v.sizes.all()}
                    variants_data[str(v.pk)] = {'color': v.color_name, 'sizes': sizes_data}
                products_data_err[str(p.pk)] = {'variants': variants_data}
            messages.error(request, '⚠️ لا يمكن أن يكون هناك مبلغ متبقٍ إلا إذا كانت طريقة الدفع "آجل". يرجى تعديل المبلغ المدفوع أو تغيير طريقة الدفع إلى آجل.')
            context = {
                'products': products,
                'suppliers': suppliers,
                'today': timezone.now().date(),
                'products_data_json': _json.dumps(products_data_err, ensure_ascii=False),
            }
            return render(request, 'inventory/add_movement.html', context)

        # مواعيد الدفع الآجل
        schedule_dates = request.POST.getlist('schedule_date[]')
        schedule_amounts = request.POST.getlist('schedule_amount[]')

        supplier = None
        if movement_type == 'in':
            if new_supplier_name:
                supplier = Supplier.objects.create(
                    name=new_supplier_name,
                    phone=new_supplier_phone if new_supplier_phone else None,
                )
            elif supplier_id:
                supplier = get_object_or_404(Supplier, pk=supplier_id)

        movement = StockMovement(
            movement_type=movement_type,
            product=product,
            variant=variant,
            product_size=product_size,
            quantity=quantity,
            unit_price=unit_price,
            payment_type=payment_type,
            amount_paid=amount_paid,
            amount_remaining=remaining,
            supplier=supplier,
            date=date,
            notes=notes,
            created_by=request.user,
        )
        movement.save()

        if product_size and movement_type == 'in':
            ProductSize.objects.filter(pk=product_size.pk).update(stock=F('stock') + quantity)
            product.update_total_stock()
        elif product_size and movement_type == 'out':
            ProductSize.objects.filter(pk=product_size.pk).update(stock=F('stock') - quantity)
            product.update_total_stock()

        # ✅ تسجيل تلقائي في جدول الديون مع حفظ الدفعة الأولى في السجل
        if remaining > 0:
            if movement_type == 'in':
                # شراء من مورد بمبلغ آجل → فلوس عليا
                supplier_name = supplier.name if supplier else (new_supplier_name or 'مورد غير محدد')
                payable = Payable.objects.create(
                    supplier=supplier,
                    supplier_name_manual=None if supplier else supplier_name,
                    description=f"متبقي مشتريات: {product.name}" + (f" - {variant.color_name}" if variant else "") + (f" - {product_size.size_name}" if product_size else ""),
                    total_amount=total,
                    amount_paid=amount_paid,
                    amount_remaining=remaining, # 💡 تمت الإضافة
                    status='partial' if amount_paid > 0 else 'pending', # 💡 تمت الإضافة
                    date=date,
                    notes=notes or None,
                    created_by=request.user,
                )
                
                # 💡 تسجيل الدفعة المبدئية لكي تظهر في السجل
                if amount_paid > 0:
                    PayablePayment.objects.create(
                        payable=payable,
                        amount=amount_paid,
                        payment_type=payment_type,
                        date=date,
                        notes='دفعة مقدمة أثناء تسجيل الوارد (حركة مخزن)',
                        created_by=request.user,
                    )

            elif movement_type == 'out':
                # بيع بدون تسديد كامل → فلوس ليا
                receivable = Receivable.objects.create(
                    customer_name='عميل نقدي',
                    description=f"متبقي مبيعات: {product.name}" + (f" - {variant.color_name}" if variant else "") + (f" - {product_size.size_name}" if product_size else ""),
                    total_amount=total,
                    amount_paid=amount_paid,
                    amount_remaining=remaining, # 💡 تمت الإضافة
                    status='partial' if amount_paid > 0 else 'pending', # 💡 تمت الإضافة
                    date=date,
                    notes=notes or None,
                    created_by=request.user,
                )
                
                # 💡 تسجيل الدفعة المبدئية لكي تظهر في السجل
                if amount_paid > 0:
                    ReceivablePayment.objects.create(
                        receivable=receivable,
                        amount=amount_paid,
                        payment_type=payment_type,
                        date=date,
                        notes='دفعة مقدمة أثناء تسجيل الصادر (حركة مخزن)',
                        created_by=request.user,
                    )

        # ✅ حفظ مواعيد الدفع الآجل
        if payment_type == 'credit' and remaining > 0 and schedule_dates:
            for i, (sdate, samount) in enumerate(zip(schedule_dates, schedule_amounts)):
                try:
                    samount_dec = Decimal(str(samount))
                    if samount_dec > 0 and sdate:
                        PaymentSchedule.objects.create(
                            source_type='movement',
                            movement=movement,
                            installment_number=i + 1,
                            due_date=sdate,
                            amount=samount_dec,
                            created_by=request.user,
                        )
                except Exception:
                    pass

        messages.success(request, f"تم تسجيل حركة {'وارد' if movement_type == 'in' else 'صادر'} بنجاح")
        return redirect('inventory_dashboard')

    products_data = {}
    for p in products:
        variants_data = {}
        for v in p.variants.all():
            sizes_data = {str(s.pk): {'name': s.size_name, 'stock': s.stock} for s in v.sizes.all()}
            variants_data[str(v.pk)] = {'color': v.color_name, 'sizes': sizes_data}
        products_data[str(p.pk)] = {'variants': variants_data}

    import json as _json
    context = {
        'products': products,
        'suppliers': suppliers,
        'today': timezone.now().date(),
        'products_data_json': _json.dumps(products_data, ensure_ascii=False),
    }
    return render(request, 'inventory/add_movement.html', context)


@user_passes_test(is_admin, login_url='login')
def suppliers_list(request):
    """قائمة الموردين"""
    suppliers = Supplier.objects.all().order_by('name')
    return render(request, 'inventory/suppliers.html', {'suppliers': suppliers})


@user_passes_test(is_admin, login_url='login')
def add_supplier(request):
    """إضافة مورد جديد"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        phone = request.POST.get('phone', '').strip()
        email = request.POST.get('email', '').strip()
        address = request.POST.get('address', '').strip()
        notes = request.POST.get('notes', '').strip()

        if not name:
            messages.error(request, 'اسم المورد مطلوب')
            return redirect('add_supplier')

        Supplier.objects.create(
            name=name,
            phone=phone or None,
            email=email or None,
            address=address or None,
            notes=notes or None,
        )
        messages.success(request, f'تم إضافة المورد "{name}" بنجاح ✅')
        return redirect('suppliers_list')

    return render(request, 'inventory/add_supplier.html')


@user_passes_test(is_admin, login_url='login')
def supplier_detail(request, pk):
    """تفاصيل المورد وسجل حركاته"""
    supplier = get_object_or_404(Supplier, pk=pk)
    movements = supplier.stock_movements.select_related('product').order_by('-created_at')

    if request.method == 'POST':
        # تعديل بيانات المورد
        supplier.name = request.POST.get('name', supplier.name)
        supplier.phone = request.POST.get('phone', '')
        supplier.email = request.POST.get('email', '')
        supplier.address = request.POST.get('address', '')
        supplier.notes = request.POST.get('notes', '')
        supplier.save()
        messages.success(request, 'تم تحديث بيانات المورد ✅')
        return redirect('supplier_detail', pk=pk)

    context = {
        'supplier': supplier,
        'movements': movements,
    }
    return render(request, 'inventory/supplier_detail.html', context)

@user_passes_test(is_admin, login_url='login')
def create_invoice(request):
    """إنشاء فاتورة بيع جديدة"""
    products = Product.objects.prefetch_related('variants__sizes').order_by('name')

    if request.method == 'POST':
        customer_name = request.POST.get('customer_name', '').strip()
        customer_phone = request.POST.get('customer_phone', '').strip()
        date = request.POST.get('date')
        payment_type = request.POST.get('payment_type', 'cash')
        amount_paid = Decimal(request.POST.get('amount_paid', 0))
        notes = request.POST.get('notes', '').strip()

        product_ids = request.POST.getlist('product_id[]')
        variant_ids = request.POST.getlist('variant[]')
        size_ids = request.POST.getlist('product_size[]')
        quantities = request.POST.getlist('quantity[]')
        unit_prices = request.POST.getlist('unit_price[]')
        discount_value = Decimal(request.POST.get('discount_value', 0) or 0)
        grand_total_after_discount = request.POST.get('grand_total_after_discount', '')

        if not product_ids or not customer_name:
            messages.error(request, 'يرجى إدخال اسم العميل وإضافة منتج على الأقل')
            return render(request, 'inventory/create_invoice.html', {'products': products, 'today': timezone.now().date(), 'products_data_json': '{}' })

        subtotal = sum(int(quantities[i]) * Decimal(unit_prices[i]) for i in range(len(product_ids)))

        # استخدام الإجمالي بعد الخصم المحسوب من الـ frontend
        if grand_total_after_discount:
            total = Decimal(grand_total_after_discount)
            discount_amount = max(Decimal(0), subtotal - total)
        else:
            discount_amount = min(discount_value, subtotal)
            total = subtotal - discount_amount
        total = max(Decimal(0), total)
        discount_amount = max(Decimal(0), discount_amount)

        remaining = max(Decimal(0), total - amount_paid)

        # ✅ Validation: المتبقي لازم يكون صفر لو مش آجل
        if payment_type != 'credit' and remaining > 0:
            import json as _json
            products_data_err = {}
            for p in products:
                variants_data = {}
                for v in p.variants.all():
                    sizes_data = {str(s.pk): {'name': s.size_name, 'stock': s.stock} for s in v.sizes.all()}
                    variants_data[str(v.pk)] = {'color': v.color_name, 'sizes': sizes_data}
                products_data_err[str(p.pk)] = {'variants': variants_data}
            messages.error(request, '⚠️ لا يمكن أن يكون هناك مبلغ متبقٍ إلا إذا كانت طريقة الدفع "آجل". يرجى تعديل المبلغ المدفوع أو تغيير طريقة الدفع إلى آجل.')
            context = {
                'products': products,
                'today': timezone.now().date(),
                'products_data_json': _json.dumps(products_data_err, ensure_ascii=False),
            }
            return render(request, 'inventory/create_invoice.html', context)

        # مواعيد الدفع الآجل
        schedule_dates = request.POST.getlist('schedule_date[]')
        schedule_amounts = request.POST.getlist('schedule_amount[]')

        invoice = Invoice.objects.create(
            customer_name=customer_name,
            customer_phone=customer_phone or None,
            date=date,
            payment_type=payment_type,
            subtotal_before_discount=subtotal,
            discount_amount=discount_amount,
            total_amount=total,
            amount_paid=amount_paid,
            amount_remaining=remaining,
            notes=notes or None,
            created_by=request.user,
        )

        # 💡 الإضافة الجديدة: تسجيل الدفعة المبدئية في الفاتورة نفسها لتظهر في صفحة التفاصيل
        if amount_paid > 0:
            InvoicePayment.objects.create(
                invoice=invoice,
                amount=amount_paid,
                payment_type=payment_type,
                date=date,
                notes='دفعة مقدمة أثناء إنشاء الفاتورة',
                created_by=request.user,
            )

        for i in range(len(product_ids)):
            product = get_object_or_404(Product, pk=product_ids[i])
            qty = int(quantities[i])
            price = Decimal(unit_prices[i])
            variant_id = variant_ids[i] if i < len(variant_ids) else None
            size_id = size_ids[i] if i < len(size_ids) else None
            variant = ProductVariant.objects.filter(pk=variant_id).first() if variant_id else None
            product_size = ProductSize.objects.filter(pk=size_id).first() if size_id else None

            InvoiceItem.objects.create(
                invoice=invoice,
                product=product,
                variant=variant,
                product_size=product_size,
                quantity=qty,
                unit_price=price,
            )
            # تخفيض مخزن المقاس المحدد أو المنتج العام
            if product_size:
                ProductSize.objects.filter(pk=product_size.pk).update(stock=F('stock') - qty)
                product.update_total_stock()
            else:
                Product.objects.filter(pk=product.pk).update(stock=F('stock') - qty)

        # ✅ تسجيل تلقائي في فلوس ليا لو فيه مبلغ متبقي على العميل
        if remaining > 0:
            receivable = Receivable.objects.create(
                customer_name=customer_name,
                customer_phone=customer_phone or None,
                description=f"متبقي فاتورة #{invoice.invoice_number}",
                total_amount=total,
                amount_paid=amount_paid,
                amount_remaining=remaining,
                status='partial' if amount_paid > 0 else 'pending',
                date=date,
                notes=notes or None,
                created_by=request.user,
            )
            
            # تسجيل الدفعة المبدئية في سجل دفعات العميل لتظهر الفاتورة بشكل صحيح
            if amount_paid > 0:
                ReceivablePayment.objects.create(
                    receivable=receivable,
                    amount=amount_paid,
                    payment_type=payment_type,
                    date=date,
                    notes=f"دفعة مقدمة أثناء إنشاء فاتورة #{invoice.invoice_number}",
                    created_by=request.user,
                )

        # ✅ حفظ مواعيد الدفع الآجل للفاتورة
        if payment_type == 'credit' and remaining > 0 and schedule_dates:
            for i, (sdate, samount) in enumerate(zip(schedule_dates, schedule_amounts)):
                try:
                    samount_dec = Decimal(str(samount))
                    if samount_dec > 0 and sdate:
                        PaymentSchedule.objects.create(
                            source_type='invoice',
                            invoice=invoice,
                            installment_number=i + 1,
                            due_date=sdate,
                            amount=samount_dec,
                            created_by=request.user,
                        )
                except Exception:
                    pass

        messages.success(request, f'تم إنشاء الفاتورة #{invoice.invoice_number} بنجاح ✅')
        return redirect('invoice_detail', pk=invoice.pk)

    products_data = {}
    for p in products:
        variants_data = {}
        for v in p.variants.all():
            sizes_data = {str(s.pk): {'name': s.size_name, 'stock': s.stock} for s in v.sizes.all()}
            variants_data[str(v.pk)] = {'color': v.color_name, 'sizes': sizes_data}
        products_data[str(p.pk)] = {'variants': variants_data}

    import json as _json
    context = {
        'products': products,
        'today': timezone.now().date(),
        'products_data_json': _json.dumps(products_data, ensure_ascii=False),
    }
    return render(request, 'inventory/create_invoice.html', context)


@user_passes_test(is_admin, login_url='login')
def invoice_detail(request, pk):
    """تفاصيل الفاتورة"""
    invoice = get_object_or_404(Invoice, pk=pk)
    items = invoice.items.select_related('product').all()
    payments = invoice.payments.all()
    return render(request, 'inventory/invoice_detail.html', {
        'invoice': invoice,
        'items': items,
        'payments': payments,
    })


@user_passes_test(is_admin, login_url='login')
def add_invoice_payment(request, pk):
    """إضافة دفعة على فاتورة (وتسميعها في مديونيات العملاء لو موجودة)"""
    invoice = get_object_or_404(Invoice, pk=pk)

    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount', 0))
        payment_type = request.POST.get('payment_type', 'cash')
        date = request.POST.get('date')
        notes = request.POST.get('notes', '').strip()

        if amount > 0:
            # 1. تسجيل الدفعة في الفاتورة
            InvoicePayment.objects.create(
                invoice=invoice,
                amount=amount,
                payment_type=payment_type,
                date=date,
                notes=notes or None,
                created_by=request.user,
            )

            # تحديث رصيد الفاتورة
            total_paid = invoice.payments.aggregate(total=Sum('amount'))['total'] or 0
            invoice.amount_paid = total_paid
            invoice.amount_remaining = max(Decimal(0), invoice.total_amount - total_paid)
            invoice.save()

            # 2. 💡 التسميع التلقائي في المديونيات (فلوس ليا)
            # نبحث عن المديونية المرتبطة برقم الفاتورة في حقل البيان
            receivable = Receivable.objects.filter(description__contains=f"#{invoice.invoice_number}").first()
            if receivable:
                ReceivablePayment.objects.create(
                    receivable=receivable,
                    amount=amount,
                    payment_type=payment_type,
                    date=date,
                    notes=f"سداد من شاشة الفاتورة: {notes}",
                    created_by=request.user,
                )
                # تحديث رصيد المديونية
                rec_paid = receivable.payments.aggregate(total=Sum('amount'))['total'] or 0
                receivable.amount_paid = rec_paid
                receivable.amount_remaining = max(Decimal(0), receivable.total_amount - rec_paid)
                receivable.status = 'paid' if receivable.amount_remaining <= 0 else 'partial'
                receivable.save()

            messages.success(request, 'تم تسجيل الدفعة بنجاح ✅')
            
        return redirect('invoice_detail', pk=pk)

    return redirect('invoice_detail', pk=pk)


@user_passes_test(is_admin, login_url='login')
def invoices_list(request):
    """قائمة الفواتير"""
    invoices = Invoice.objects.select_related('created_by').order_by('-created_at')
    return render(request, 'inventory/invoices_list.html', {'invoices': invoices})


@user_passes_test(is_admin, login_url='login')
def movements_list(request):
    """قائمة حركات المخزن"""
    movements = StockMovement.objects.select_related('product', 'supplier', 'created_by').order_by('-created_at')
    movement_type = request.GET.get('type', '')
    if movement_type in ('in', 'out'):
        movements = movements.filter(movement_type=movement_type)
    return render(request, 'inventory/movements_list.html', {
        'movements': movements,
        'movement_type': movement_type,
    })


# ============================================================
# جداول الديون - فلوس ليا وفلوس عليا
# ============================================================

@user_passes_test(is_admin, login_url='login')
def receivables_list(request):
    """فلوس ليا - مديونيات العملاء"""
    receivables = Receivable.objects.all().order_by('-created_at')
    total_amount = receivables.aggregate(t=Sum('total_amount'))['t'] or 0
    total_paid = receivables.aggregate(t=Sum('amount_paid'))['t'] or 0
    total_remaining = receivables.aggregate(t=Sum('amount_remaining'))['t'] or 0
    context = {
        'receivables': receivables,
        'total_amount': total_amount,
        'total_paid': total_paid,
        'total_remaining': total_remaining,
    }
    return render(request, 'inventory/receivables.html', context)


@user_passes_test(is_admin, login_url='login')
def add_receivable(request):
    """إضافة مديونية عميل جديدة"""
    if request.method == 'POST':
        customer_name = request.POST.get('customer_name', '').strip()
        customer_phone = request.POST.get('customer_phone', '').strip()
        description = request.POST.get('description', '').strip()
        total_amount = Decimal(request.POST.get('total_amount', 0))
        amount_paid = Decimal(request.POST.get('amount_paid', 0))
        payment_type = request.POST.get('payment_type', 'cash')
        date = request.POST.get('date')
        due_date = request.POST.get('due_date') or None
        notes = request.POST.get('notes', '').strip()

        if not customer_name or not total_amount:
            messages.error(request, 'اسم العميل والمبلغ مطلوبان')
            return redirect('add_receivable')

        amount_remaining = total_amount - amount_paid
        status = 'paid' if amount_remaining <= 0 else ('partial' if amount_paid > 0 else 'pending')

        receivable = Receivable.objects.create(
            customer_name=customer_name,
            customer_phone=customer_phone or None,
            description=description or None,
            total_amount=total_amount,
            amount_paid=amount_paid,
            amount_remaining=amount_remaining,
            status=status,
            date=date,
            due_date=due_date,
            notes=notes or None,
            created_by=request.user,
        )

        # تسجيل الدفعة المبدئية في سجل الدفعات عشان الحسابات تظبط وتظهر في الجدول
        if amount_paid > 0:
            ReceivablePayment.objects.create(
                receivable=receivable,
                amount=amount_paid,
                payment_type=payment_type,
                date=date,
                notes='دفعة مقدمة عند الإنشاء',
                created_by=request.user,
            )
        messages.success(request, f'تم إضافة مديونية {customer_name} بنجاح')
        return redirect('receivables_list')

    return render(request, 'inventory/add_receivable.html', {'today': timezone.now().date()})


@user_passes_test(is_admin, login_url='login')
def receivable_detail(request, pk):
    """تفاصيل مديونية عميل + إضافة دفعة (وتسميعها في الفاتورة لو مرتبطة بها)"""
    receivable = get_object_or_404(Receivable, pk=pk)

    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount', 0))
        payment_type = request.POST.get('payment_type', 'cash')
        date = request.POST.get('date')
        notes = request.POST.get('notes', '').strip()
        from_list = request.POST.get('from_list', '')

        if amount > 0:
            # 1. تسجيل الدفعة في المديونية
            ReceivablePayment.objects.create(
                receivable=receivable,
                amount=amount,
                payment_type=payment_type,
                date=date,
                notes=notes or None,
                created_by=request.user,
            )
            
            # تحديث رصيد المديونية
            rec_paid = receivable.payments.aggregate(total=Sum('amount'))['total'] or 0
            receivable.amount_paid = rec_paid
            receivable.amount_remaining = max(Decimal(0), receivable.total_amount - rec_paid)
            receivable.status = 'paid' if receivable.amount_remaining <= 0 else 'partial'
            receivable.save()

            # 2. 💡 التسميع التلقائي في الفاتورة لو المديونية جاية من فاتورة
            if receivable.description and "فاتورة #" in receivable.description:
                # استخراج رقم الفاتورة من البيان
                inv_number = receivable.description.split("فاتورة #")[1].strip()
                invoice = Invoice.objects.filter(invoice_number=inv_number).first()
                
                if invoice:
                    InvoicePayment.objects.create(
                        invoice=invoice,
                        amount=amount,
                        payment_type=payment_type,
                        date=date,
                        notes=f"تحصيل من شاشة المديونيات: {notes}",
                        created_by=request.user,
                    )
                    # تحديث رصيد الفاتورة
                    inv_paid = invoice.payments.aggregate(total=Sum('amount'))['total'] or 0
                    invoice.amount_paid = inv_paid
                    invoice.amount_remaining = max(Decimal(0), invoice.total_amount - inv_paid)
                    invoice.save()

            messages.success(request, f'تم تسجيل دفعة {int(amount)} ج بنجاح ✅')

        if from_list:
            return redirect('receivables_list')
        return redirect('receivable_detail', pk=pk)

    payments = receivable.payments.all()
    context = {'receivable': receivable, 'payments': payments, 'today': timezone.now().date()}
    return render(request, 'inventory/receivable_detail.html', context)


@user_passes_test(is_admin, login_url='login')
def payables_list(request):
    """فلوس عليا - مديونيات الموردين"""
    payables = Payable.objects.select_related('supplier').prefetch_related('payments').order_by('-created_at')
    
    total_amount = payables.aggregate(t=Sum('total_amount'))['t'] or 0
    total_paid = payables.aggregate(t=Sum('amount_paid'))['t'] or 0
    total_remaining = payables.aggregate(t=Sum('amount_remaining'))['t'] or 0
    
    for p in payables:
        payments = list(p.payments.all().order_by('date', 'id'))
        
        # مجموع الدفعات الموجودة في السجل
        total_payments_amount = sum(pay.amount for pay in payments)
        
        # حساب الدفعة المقدمة (عشان المديونيات القديمة اللي متسجلتش فيها الدفعة الأولى)
        initial_paid_not_in_payments = p.amount_paid - total_payments_amount
        if initial_paid_not_in_payments < 0:
            initial_paid_not_in_payments = 0
            
        current_remaining = p.total_amount - initial_paid_not_in_payments
        
        # حساب التراكمي لكل دفعة
        for pay in payments:
            pay.before_payment = current_remaining
            pay.after_payment = current_remaining - pay.amount
            current_remaining = pay.after_payment # نحدث الرصيد
            
        p.calculated_payments = reversed(payments)
        
    context = {
        'payables': payables,
        'total_amount': total_amount,
        'total_paid': total_paid,
        'total_remaining': total_remaining,
    }
    return render(request, 'inventory/payables.html', context)


@user_passes_test(is_admin, login_url='login')
def add_payable(request):
    """إضافة مديونية مورد جديدة (شراء جزئي أو آجل)"""
    suppliers = Supplier.objects.all().order_by('name')
    if request.method == 'POST':
        supplier_id = request.POST.get('supplier')
        supplier_name_manual = request.POST.get('supplier_name_manual', '').strip()
        description = request.POST.get('description', '').strip()
        total_amount = Decimal(request.POST.get('total_amount', 0))
        amount_paid = Decimal(request.POST.get('amount_paid', 0))
        payment_type = request.POST.get('payment_type', 'cash')
        date = request.POST.get('date')
        due_date = request.POST.get('due_date') or None
        notes = request.POST.get('notes', '').strip()

        supplier = Supplier.objects.filter(pk=supplier_id).first() if supplier_id else None

        if not supplier and not supplier_name_manual:
            messages.error(request, 'يجب تحديد المورد')
            return redirect('add_payable')

        # حساب المتبقي والحالة وقت الإنشاء بدقة
        amount_remaining = total_amount - amount_paid
        status = 'paid' if amount_remaining <= 0 else ('partial' if amount_paid > 0 else 'pending')

        payable = Payable.objects.create(
            supplier=supplier,
            supplier_name_manual=supplier_name_manual or None,
            description=description or None,
            total_amount=total_amount,
            amount_paid=amount_paid,
            amount_remaining=amount_remaining, # تسجيل المتبقي
            status=status,                     # تسجيل الحالة
            date=date,
            due_date=due_date,
            notes=notes or None,
            created_by=request.user,
        )
        
        # 💡 الإصلاح الأهم للمشكلة: تسجيل الدفعة المقدمة فوراً في سجل الدفعات لتظهر تحت السجل
        if amount_paid > 0:
            PayablePayment.objects.create(
                payable=payable,
                amount=amount_paid,
                payment_type=payment_type,
                date=date,
                notes='دفعة مقدمة أثناء عملية الشراء',
                created_by=request.user,
            )

        messages.success(request, 'تم إضافة المديونية بنجاح')
        return redirect('payables_list')

    return render(request, 'inventory/add_payable.html', {'suppliers': suppliers, 'today': timezone.now().date()})


@user_passes_test(is_admin, login_url='login')
def payable_detail(request, pk):
    """تفاصيل مديونية مورد + إضافة دفعة"""
    payable = get_object_or_404(Payable, pk=pk)
    
    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount', 0))
        payment_type = request.POST.get('payment_type', 'cash')
        date = request.POST.get('date')
        notes = request.POST.get('notes', '').strip()
        from_list = request.POST.get('from_list', '')
        
        if amount > 0:
            # إنشاء الدفعة في السجل — PayablePayment.save() يحدث amount_paid و amount_remaining تلقائياً
            PayablePayment.objects.create(
                payable=payable,
                amount=amount,
                payment_type=payment_type,
                date=date,
                notes=notes or None,
                created_by=request.user,
            )
            messages.success(request, f'تم تسجيل دفعة {int(amount)} ج بنجاح ✅')
            
        if from_list:
            return redirect('payables_list')
        return redirect('payable_detail', pk=pk)

    payments = payable.payments.all()
    context = {'payable': payable, 'payments': payments, 'today': timezone.now().date()}
    return render(request, 'inventory/payable_detail.html', context)


@user_passes_test(is_admin, login_url='login')
def get_product_variants(request, product_id):
    """API endpoint: يرجع variants + sizes لمنتج معين"""
    import json
    product = get_object_or_404(Product, pk=product_id)
    data = []
    for v in product.variants.prefetch_related('sizes').all():
        sizes = [{'id': s.pk, 'name': s.size_name, 'stock': s.stock} for s in v.sizes.all()]
        data.append({'id': v.pk, 'color': v.color_name, 'sizes': sizes})
    from django.http import JsonResponse
    return JsonResponse({'variants': data})

    
def collection_detail(request, id):
    collection = get_object_or_404(
        ProductCollection.objects.prefetch_related('items__product', 'items__variant', 'items__product_size'), 
        id=id, 
        is_active=True
    )
    return render(request, 'collection_detail.html', {'collection': collection})