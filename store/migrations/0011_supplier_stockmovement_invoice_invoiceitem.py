from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('store', '0010_productsize_discount_price_productsize_price_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Supplier',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='اسم المورد')),
                ('phone', models.CharField(blank=True, max_length=20, null=True, verbose_name='رقم الهاتف')),
                ('email', models.EmailField(blank=True, max_length=254, null=True, verbose_name='البريد الإلكتروني')),
                ('address', models.TextField(blank=True, null=True, verbose_name='العنوان')),
                ('notes', models.TextField(blank=True, null=True, verbose_name='ملاحظات')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'مورد',
                'verbose_name_plural': 'الموردون',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='StockMovement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('movement_type', models.CharField(choices=[('in', 'وارد (شراء)'), ('out', 'صادر (بيع)')], max_length=10, verbose_name='نوع الحركة')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='stock_movements', to='store.product', verbose_name='المنتج')),
                ('quantity', models.PositiveIntegerField(verbose_name='الكمية')),
                ('unit_price', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='سعر الوحدة')),
                ('payment_type', models.CharField(choices=[('cash', 'كاش'), ('visa', 'فيزا'), ('credit', 'آجل')], max_length=20, verbose_name='طريقة الدفع')),
                ('amount_paid', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='المبلغ المدفوع')),
                ('amount_remaining', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='المتبقي')),
                ('supplier', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='stock_movements', to='store.supplier', verbose_name='المورد')),
                ('date', models.DateField(verbose_name='التاريخ')),
                ('notes', models.TextField(blank=True, null=True, verbose_name='ملاحظات')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='بواسطة')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'حركة مخزن',
                'verbose_name_plural': 'حركات المخزن',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='Invoice',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('invoice_number', models.CharField(max_length=50, unique=True, verbose_name='رقم الفاتورة')),
                ('customer_name', models.CharField(max_length=200, verbose_name='اسم العميل')),
                ('customer_phone', models.CharField(blank=True, max_length=20, null=True, verbose_name='رقم العميل')),
                ('date', models.DateField(verbose_name='التاريخ')),
                ('payment_type', models.CharField(choices=[('cash', 'كاش'), ('visa', 'فيزا'), ('credit', 'آجل')], max_length=20, verbose_name='طريقة الدفع')),
                ('total_amount', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='إجمالي الفاتورة')),
                ('amount_paid', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='المبلغ المدفوع')),
                ('amount_remaining', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='المتبقي')),
                ('notes', models.TextField(blank=True, null=True, verbose_name='ملاحظات')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='بواسطة')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'فاتورة',
                'verbose_name_plural': 'الفواتير',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='InvoiceItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('invoice', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='store.invoice', verbose_name='الفاتورة')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='store.product', verbose_name='المنتج')),
                ('quantity', models.PositiveIntegerField(verbose_name='الكمية')),
                ('unit_price', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='سعر الوحدة')),
            ],
            options={
                'verbose_name': 'بند فاتورة',
                'verbose_name_plural': 'بنود الفواتير',
            },
        ),
        migrations.CreateModel(
            name='InvoicePayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('invoice', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payments', to='store.invoice', verbose_name='الفاتورة')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='المبلغ')),
                ('payment_type', models.CharField(choices=[('cash', 'كاش'), ('visa', 'فيزا')], max_length=20, verbose_name='طريقة الدفع')),
                ('date', models.DateField(verbose_name='تاريخ الدفع')),
                ('notes', models.TextField(blank=True, null=True, verbose_name='ملاحظات')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='بواسطة')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'دفعة فاتورة',
                'verbose_name_plural': 'دفعات الفواتير',
                'ordering': ['-created_at'],
            },
        ),
    ]
