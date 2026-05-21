import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import models, transaction
from django.db.models import Sum
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.models import User  # إضافة استيراد موديل المستخدمين
from colorfield.fields import ColorField
from django_resized import ResizedImageField

# --- Categories ---

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True, null=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


# --- Products ---

class Product(models.Model):
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50, unique=True, blank=True, null=True, verbose_name="SKU")
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, related_name='products', null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2) 
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True) 
    stock = models.PositiveIntegerField(default=0, verbose_name="Total Stock", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    is_new_arrival = models.BooleanField(default=False, verbose_name="New Arrival?")
    new_arrival_updated_at = models.DateTimeField(null=True, blank=True, editable=False)

    def __str__(self):
        return f"{self.name} ({self.sku or 'No SKU'})"

    def save(self, *args, **kwargs):
        if self.pk:
            old_instance = Product.objects.filter(pk=self.pk).first()
            if old_instance and self.is_new_arrival and not old_instance.is_new_arrival:
                self.new_arrival_updated_at = timezone.now()
        elif self.is_new_arrival:
            self.new_arrival_updated_at = timezone.now()

        if not self.sku:
            prefix = self.name[:3].upper() if self.name else "FUR"
            self.sku = f"{prefix}-{uuid.uuid4().hex[:6].upper()}"
        
        super().save(*args, **kwargs)

    def update_total_stock(self):
        total = ProductSize.objects.filter(variant__product=self).aggregate(total=Sum('stock'))['total'] or 0
        Product.objects.filter(pk=self.pk).update(stock=total)

    @property
    def get_effective_price(self):
        return self.discount_price if self.discount_price else self.price
        
    @property
    def discount_percentage(self):
        if self.price and self.discount_price and self.price > self.discount_price:
            discount = self.price - self.discount_price
            percentage = (discount / self.price) * 100
            return int(percentage)  # إرجاع الرقم كعدد صحيح (مثلاً 20 بدلاً من 20.0)
        return 0

    @property
    def is_new(self):
        if self.is_new_arrival and self.new_arrival_updated_at:
            return timezone.now() < self.new_arrival_updated_at + timedelta(days=7)
        return False

    @property
    def main_image(self):
        variant = self.variants.first()
        if variant and variant.variant_image:
            return variant.variant_image.url
        return None

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('product_detail', args=[self.id])


# --- Product Specifications (الجدول الجديد للمواصفات) ---

class ProductSpecification(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='specifications')
    spec_name = models.CharField(max_length=255, verbose_name="اسم المواصفة (مثال: الألوان)")
    # تم تغيير الحقل إلى TextField ليسمح بإدخال قيم كثيرة جداً ومفصلة
    spec_value = models.TextField(verbose_name="القيم (يمكنك إدخال أكثر من قيمة مفصولة بفاصلة)")

    def __str__(self):
        return f"{self.spec_name}: {self.spec_value}"


# --- Variants & Inventory ---

class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    color_name = models.CharField(max_length=50)
    color_code = ColorField(default='#000000') 
    variant_image = ResizedImageField(
        size=[800, 1000], quality=75, upload_to='variants/', 
        force_format='WEBP'
    )
    @property
    def total_stock(self):
        """حساب مجموع المخزن لكل المقاسات التابعة لهذا اللون"""
        return self.sizes.aggregate(total=models.Sum('stock'))['total'] or 0
    def __str__(self):
        return f"{self.product.name} - {self.color_name}"


class ProductImage(models.Model):
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='additional_images')
    image = ResizedImageField(
        size=[800, 1000], quality=75, upload_to='variants/extra/', 
        force_format='WEBP'
    )
    alt_text = models.CharField(max_length=200, blank=True, null=True)


class ProductSize(models.Model):
    variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='sizes')
    size_name = models.CharField(max_length=20)
    stock = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.variant} - {self.size_name}"


@receiver([post_save, post_delete], sender=ProductSize)
def update_product_stock_signal(sender, instance, **kwargs):
    instance.variant.product.update_total_stock()


# --- Orders ---

class Order(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending ⏳'),
        ('Shipped', 'Shipped 🚚'),
        ('Delivered', 'Delivered ✅'),
        ('Canceled', 'Canceled ❌'),
    ]
    
    # إضافة حقل المستخدم لحل مشكلة TypeError في الـ Checkout
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    governorate = models.CharField(max_length=100)
    address = models.TextField()
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)
    is_completed = models.BooleanField(default=False)

    __original_status = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__original_status = self.status

    def save(self, *args, **kwargs):
        if self.pk and self.status != self.__original_status:
            self.send_status_notification()
            if self.status == 'Delivered':
                self.is_completed = True
        super().save(*args, **kwargs)

    def send_status_notification(self):
        subject = f"تحديث بخصوص طلبك رقم #{self.id} - الباسطى جروب"
        messages_map = {
            'Shipped': "طلبك في طريقه إليك الآن! 🚚",
            'Delivered': "تم توصيل طلبك بنجاح. نتمنى أن ينال إعجابك! ✅",
            'Canceled': "للأسف، تم إلغاء طلبك. تواصل معنا لمزيد من التفاصيل. ❌",
        }
        msg = messages_map.get(self.status, f"تم تحديث حالة طلبك إلى: {self.status}")
        try:
            send_mail(subject, msg, settings.EMAIL_HOST_USER, [self.email], fail_silently=True)
        except Exception: pass

    class Meta:
        ordering = ['-created_at']

    @property
    def get_items_total(self):
        """حساب مجموع أسعار جميع المنتجات في الطلب قبل الخصم اليدوي"""
        return sum(item.subtotal for item in self.items.all())

    @property
    def get_discount_amount(self):
        """حساب قيمة الخصم اليدوي المطبق"""
        total_items = self.get_items_total
        discount = total_items - self.total_price
        return discount if discount > 0 else 0


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True)
    color = models.CharField(max_length=50)
    size = models.CharField(max_length=20, null=True, blank=True) 
    quantity = models.PositiveIntegerField(default=1)
    price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2)

    @property
    def subtotal(self):
        return self.quantity * self.price_at_purchase


# --- Contact ---

class ContactMessage(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True, null=True) 
    subject = models.CharField(max_length=200)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

# --- Inventory Management ---

class Supplier(models.Model):
    name = models.CharField(max_length=200, verbose_name="اسم المورد")
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="رقم الهاتف")
    email = models.EmailField(blank=True, null=True, verbose_name="البريد الإلكتروني")
    address = models.TextField(blank=True, null=True, verbose_name="العنوان")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "مورد"
        verbose_name_plural = "الموردون"
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def total_purchases(self):
        from django.db.models import Sum
        result = self.stock_movements.filter(movement_type='in').aggregate(
            total=Sum('unit_price')
        )['total'] or 0
        return result


class StockMovement(models.Model):
    MOVEMENT_TYPES = [
        ('in', 'وارد (شراء)'),
        ('out', 'صادر (بيع)'),
    ]
    PAYMENT_TYPES = [
        ('cash', 'كاش'),
        ('visa', 'فيزا'),
        ('credit', 'آجل'),
    ]

    movement_type = models.CharField(max_length=10, choices=MOVEMENT_TYPES, verbose_name="نوع الحركة")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_movements', verbose_name="المنتج")
    variant = models.ForeignKey('ProductVariant', on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_movements', verbose_name="اللون")
    product_size = models.ForeignKey('ProductSize', on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_movements', verbose_name="المقاس")
    quantity = models.PositiveIntegerField(verbose_name="الكمية")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="سعر الوحدة")
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPES, verbose_name="طريقة الدفع")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="المبلغ المدفوع")
    amount_remaining = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="المتبقي")
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_movements', verbose_name="المورد")
    date = models.DateField(verbose_name="التاريخ")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="بواسطة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "حركة مخزن"
        verbose_name_plural = "حركات المخزن"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_movement_type_display()} - {self.product.name} - {self.quantity}"

    @property
    def total_value(self):
        return self.quantity * self.unit_price

    def save(self, *args, **kwargs):
        total = self.quantity * self.unit_price
        self.amount_remaining = total - self.amount_paid
        if self.amount_remaining < 0:
            self.amount_remaining = 0
        super().save(*args, **kwargs)
        # Update product stock
        if self.movement_type == 'in':
            Product.objects.filter(pk=self.product.pk).update(stock=models.F('stock') + self.quantity)
        else:
            Product.objects.filter(pk=self.product.pk).update(stock=models.F('stock') - self.quantity)


class Invoice(models.Model):
    PAYMENT_TYPES = [
        ('cash', 'كاش'),
        ('visa', 'فيزا'),
        ('credit', 'آجل'),
    ]

    invoice_number = models.CharField(max_length=50, unique=True, verbose_name="رقم الفاتورة")
    customer_name = models.CharField(max_length=200, verbose_name="اسم العميل")
    customer_phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="رقم العميل")
    date = models.DateField(verbose_name="التاريخ")
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPES, verbose_name="طريقة الدفع")
    subtotal_before_discount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="إجمالي المنتجات قبل الخصم")
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="قيمة الخصم")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="إجمالي الفاتورة بعد الخصم")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="المبلغ المدفوع")
    amount_remaining = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="المتبقي")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="بواسطة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "فاتورة"
        verbose_name_plural = "الفواتير"
        ordering = ['-created_at']

    def __str__(self):
        return f"فاتورة #{self.invoice_number} - {self.customer_name}"

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            import uuid
            self.invoice_number = f"INV-{uuid.uuid4().hex[:8].upper()}"
        self.amount_remaining = self.total_amount - self.amount_paid
        if self.amount_remaining < 0:
            self.amount_remaining = 0
        super().save(*args, **kwargs)

    def recalculate_total(self):
        from django.db.models import Sum
        total = self.items.aggregate(
            total=Sum(models.ExpressionWrapper(
                models.F('quantity') * models.F('unit_price'),
                output_field=models.DecimalField()
            ))
        )['total'] or 0
        self.total_amount = total
        self.amount_remaining = total - self.amount_paid
        if self.amount_remaining < 0:
            self.amount_remaining = 0
        Invoice.objects.filter(pk=self.pk).update(
            total_amount=self.total_amount,
            amount_remaining=self.amount_remaining
        )


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items', verbose_name="الفاتورة")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, verbose_name="المنتج")
    variant = models.ForeignKey('ProductVariant', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="اللون")
    product_size = models.ForeignKey('ProductSize', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المقاس")
    quantity = models.PositiveIntegerField(verbose_name="الكمية")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="سعر الوحدة")

    class Meta:
        verbose_name = "بند فاتورة"
        verbose_name_plural = "بنود الفواتير"

    def __str__(self):
        return f"{self.product.name} x{self.quantity}"

    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Deduct from stock when invoice item is saved
        Product.objects.filter(pk=self.product.pk).update(
            stock=models.F('stock') - self.quantity
        )
        # Recalculate invoice total
        self.invoice.recalculate_total()


class InvoicePayment(models.Model):
    PAYMENT_TYPES = [
        ('cash', 'كاش'),
        ('visa', 'فيزا'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments', verbose_name="الفاتورة")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="المبلغ")
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPES, verbose_name="طريقة الدفع")
    date = models.DateField(verbose_name="تاريخ الدفع")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="بواسطة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "دفعة فاتورة"
        verbose_name_plural = "دفعات الفواتير"
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Recalculate invoice paid amount
        from django.db.models import Sum
        total_paid = self.invoice.payments.aggregate(total=Sum('amount'))['total'] or 0
        self.invoice.amount_paid = total_paid
        self.invoice.amount_remaining = self.invoice.total_amount - total_paid
        if self.invoice.amount_remaining < 0:
            self.invoice.amount_remaining = 0
        Invoice.objects.filter(pk=self.invoice.pk).update(
            amount_paid=self.invoice.amount_paid,
            amount_remaining=self.invoice.amount_remaining
        )


# --- جدول الفلوس اللي ليا (مديونيات العملاء) ---

class Receivable(models.Model):
    """فلوس ليا - عملاء مدينون"""
    STATUS_CHOICES = [
        ('pending', 'لم يُسدَّد'),
        ('partial', 'مسدد جزئياً'),
        ('paid', 'مسدد بالكامل'),
    ]
    customer_name = models.CharField(max_length=200, verbose_name="اسم العميل")
    customer_phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="رقم الهاتف")
    description = models.TextField(blank=True, null=True, verbose_name="البيان / الوصف")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="إجمالي المبلغ")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="المبلغ المحصّل")
    amount_remaining = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="المتبقي")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending', verbose_name="الحالة")
    date = models.DateField(verbose_name="تاريخ المديونية")
    due_date = models.DateField(blank=True, null=True, verbose_name="تاريخ الاستحقاق")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="بواسطة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "مديونية عميل"
        verbose_name_plural = "فلوس ليا (مديونيات العملاء)"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.customer_name} - {self.total_amount} ج"

    def save(self, *args, **kwargs):
        self.amount_remaining = self.total_amount - self.amount_paid
        if self.amount_remaining < 0:
            self.amount_remaining = Decimal(0)
        if self.amount_remaining == 0:
            self.status = 'paid'
        elif self.amount_paid > 0:
            self.status = 'partial'
        else:
            self.status = 'pending'
        super().save(*args, **kwargs)


class ReceivablePayment(models.Model):
    """دفعات تحصيل المديونيات"""
    PAYMENT_TYPES = [('cash', 'كاش'), ('visa', 'فيزا'), ('transfer', 'تحويل')]
    receivable = models.ForeignKey(Receivable, on_delete=models.CASCADE, related_name='payments', verbose_name="المديونية")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="المبلغ المحصّل")
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPES, default='cash', verbose_name="طريقة الدفع")
    date = models.DateField(verbose_name="تاريخ التحصيل")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="بواسطة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "دفعة تحصيل"
        verbose_name_plural = "دفعات التحصيل"
        ordering = ['-date']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # مجموع الدفعات من السجل
        total_paid_from_log = self.receivable.payments.aggregate(total=Sum('amount'))['total'] or 0
        Receivable.objects.filter(pk=self.receivable.pk).update(amount_paid=total_paid_from_log)
        self.receivable.refresh_from_db()
        self.receivable.save()


# --- جدول الفلوس اللي عليا (مديونيات للموردين) ---

class Payable(models.Model):
    """فلوس عليا - مديونيات للموردين"""
    STATUS_CHOICES = [
        ('pending', 'لم يُسدَّد'),
        ('partial', 'مسدد جزئياً'),
        ('paid', 'مسدد بالكامل'),
    ]
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='payables', verbose_name="المورد")
    supplier_name_manual = models.CharField(max_length=200, blank=True, null=True, verbose_name="اسم المورد (يدوي)")
    description = models.TextField(blank=True, null=True, verbose_name="البيان / الوصف")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="إجمالي المبلغ")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="المبلغ المدفوع")
    amount_remaining = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="المتبقي")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending', verbose_name="الحالة")
    date = models.DateField(verbose_name="تاريخ المديونية")
    due_date = models.DateField(blank=True, null=True, verbose_name="تاريخ الاستحقاق")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="بواسطة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "مديونية مورد"
        verbose_name_plural = "فلوس عليا (مديونيات الموردين)"
        ordering = ['-created_at']

    def __str__(self):
        name = self.supplier.name if self.supplier else self.supplier_name_manual or "غير محدد"
        return f"{name} - {self.total_amount} ج"

    @property
    def creditor_name(self):
        return self.supplier.name if self.supplier else self.supplier_name_manual or "غير محدد"

    def save(self, *args, **kwargs):
        self.amount_remaining = self.total_amount - self.amount_paid
        if self.amount_remaining < 0:
            self.amount_remaining = Decimal(0)
        if self.amount_remaining == 0:
            self.status = 'paid'
        elif self.amount_paid > 0:
            self.status = 'partial'
        else:
            self.status = 'pending'
        super().save(*args, **kwargs)


class PayablePayment(models.Model):
    """دفعات سداد المديونيات للموردين"""
    PAYMENT_TYPES = [('cash', 'كاش'), ('visa', 'فيزا'), ('transfer', 'تحويل')]
    payable = models.ForeignKey(Payable, on_delete=models.CASCADE, related_name='payments', verbose_name="المديونية")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="المبلغ المدفوع")
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPES, default='cash', verbose_name="طريقة الدفع")
    date = models.DateField(verbose_name="تاريخ السداد")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="بواسطة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "دفعة سداد"
        verbose_name_plural = "دفعات السداد"
        ordering = ['-date']

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        total_paid = self.payable.payments.aggregate(total=Sum('amount'))['total'] or 0
        Payable.objects.filter(pk=self.payable.pk).update(amount_paid=total_paid)
        self.payable.refresh_from_db()
        self.payable.save()


# --- جدول مواعيد الدفع الآجل ---

class PaymentSchedule(models.Model):
    """مواعيد تسديد الدفعات الآجلة"""
    SOURCE_TYPES = [
        ('movement', 'حركة مخزن'),
        ('invoice', 'فاتورة بيع'),
    ]
    STATUS_CHOICES = [
        ('pending', 'لم يُسدَّد'),
        ('partial', 'مسدد جزئياً'),
        ('paid', 'مسدد بالكامل'),
    ]

    source_type = models.CharField(max_length=20, choices=SOURCE_TYPES, verbose_name="نوع المستند")
    movement = models.ForeignKey('StockMovement', on_delete=models.CASCADE, null=True, blank=True, related_name='payment_schedules', verbose_name="حركة المخزن")
    invoice = models.ForeignKey('Invoice', on_delete=models.CASCADE, null=True, blank=True, related_name='payment_schedules', verbose_name="الفاتورة")
    installment_number = models.PositiveIntegerField(verbose_name="رقم الدفعة")
    due_date = models.DateField(verbose_name="موعد الدفع")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="المبلغ المستحق")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="المبلغ المدفوع")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending', verbose_name="الحالة")
    reminder_sent = models.BooleanField(default=False, verbose_name="تم إرسال التذكير")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="بواسطة")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "موعد دفعة"
        verbose_name_plural = "مواعيد الدفعات الآجلة"
        ordering = ['due_date']

    def __str__(self):
        return f"دفعة {self.installment_number} - {self.amount} ج - {self.due_date}"

    @property
    def amount_remaining(self):
        return max(Decimal(0), self.amount - self.amount_paid)

    def send_reminder_email(self, admin_email):
        """إرسال إيميل تذكير لموعد الدفعة"""
        days_left = (self.due_date - timezone.now().date()).days
        if self.source_type == 'invoice':
            ref = f"فاتورة #{self.invoice.invoice_number} - {self.invoice.customer_name}" if self.invoice else "فاتورة"
            direction = "فلوس ليا (عميل مدين)"
        else:
            ref = f"حركة مخزن - {self.movement.product.name}" if self.movement else "حركة مخزن"
            direction = "فلوس عليا (مستحقة للمورد)" if self.movement and self.movement.movement_type == 'in' else "فلوس ليا"

        subject = f"⏰ تذكير: موعد دفعة بعد {days_left} أيام - {ref}"
        message = f"""
تذكير بموعد دفعة آجلة

المستند: {ref}
النوع: {direction}
رقم الدفعة: {self.installment_number}
موعد الاستحقاق: {self.due_date}
المبلغ المستحق: {self.amount_remaining} ج
الأيام المتبقية: {days_left} يوم

يرجى المتابعة لضمان التسديد في الموعد المحدد.
        """.strip()
        try:
            send_mail(subject, message, settings.EMAIL_HOST_USER, [admin_email], fail_silently=True)
            PaymentSchedule.objects.filter(pk=self.pk).update(reminder_sent=True)
        except Exception as e:
            print(f"Email error: {e}")

# ============================================================
# Product Collections (Bundles / Packages)
# ============================================================

class ProductCollection(models.Model):
    name = models.CharField(max_length=200, verbose_name="اسم الباكدج / الكوليكشن")
    description = models.TextField(blank=True, null=True, verbose_name="وصف الباكدج")
    main_image = ResizedImageField(
        size=[800, 1000], quality=75, upload_to='collections/', 
        force_format='WEBP', blank=True, null=True, verbose_name="صورة الباكدج"
    )
    
    # --- التسعير والأرباح ---
    offer_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="سعر البيع للباكدج (في العرض)")
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="التكلفة الفعلية للباكدج (لحساب صافي الربح)")
    
    is_active = models.BooleanField(default=True, verbose_name="متاح للبيع؟")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "باكدج / كوليكشن"
        verbose_name_plural = "الباكدجات والكوليكشنز"
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    @property
    def original_total_price(self):
        """دالة بتحسب السعر الطبيعي للمنتجات الفردية المضافة داخل الباكدج تلقائياً"""
        total = Decimal('0.00')
        for item in self.items.all():
            if item.product:
                # بنستخدم get_effective_price عشان لو المنتج نفسه عليه خصم يحسبه صح
                price = item.product.get_effective_price 
                total += Decimal(str(price)) * item.quantity
        return total

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('collection_detail', args=[self.id])


class CollectionItem(models.Model):
    collection = models.ForeignKey(ProductCollection, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('Product', on_delete=models.CASCADE, verbose_name="المنتج")
    variant = models.ForeignKey('ProductVariant', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="اللون")
    product_size = models.ForeignKey('ProductSize', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="المقاس")
    quantity = models.PositiveIntegerField(default=1, verbose_name="الكمية")

    class Meta:
        verbose_name = "منتج داخل الباكدج"
        verbose_name_plural = "المنتجات داخل الباكدج"

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"