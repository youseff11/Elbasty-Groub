from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0011_supplier_stockmovement_invoice_invoiceitem'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Add variant + product_size to StockMovement
        migrations.AddField(
            model_name='stockmovement',
            name='variant',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='stock_movements',
                to='store.productvariant',
                verbose_name='اللون',
            ),
        ),
        migrations.AddField(
            model_name='stockmovement',
            name='product_size',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='stock_movements',
                to='store.productsize',
                verbose_name='المقاس',
            ),
        ),
        # Add variant + product_size to InvoiceItem
        migrations.AddField(
            model_name='invoiceitem',
            name='variant',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='store.productvariant',
                verbose_name='اللون',
            ),
        ),
        migrations.AddField(
            model_name='invoiceitem',
            name='product_size',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='store.productsize',
                verbose_name='المقاس',
            ),
        ),
        # Create Receivable model
        migrations.CreateModel(
            name='Receivable',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('customer_name', models.CharField(max_length=200, verbose_name='اسم العميل')),
                ('customer_phone', models.CharField(blank=True, max_length=20, null=True, verbose_name='رقم الهاتف')),
                ('description', models.TextField(blank=True, null=True, verbose_name='البيان / الوصف')),
                ('total_amount', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='إجمالي المبلغ')),
                ('amount_paid', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='المبلغ المحصّل')),
                ('amount_remaining', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='المتبقي')),
                ('status', models.CharField(choices=[('pending', 'لم يُسدَّد'), ('partial', 'مسدد جزئياً'), ('paid', 'مسدد بالكامل')], default='pending', max_length=10, verbose_name='الحالة')),
                ('date', models.DateField(verbose_name='تاريخ المديونية')),
                ('due_date', models.DateField(blank=True, null=True, verbose_name='تاريخ الاستحقاق')),
                ('notes', models.TextField(blank=True, null=True, verbose_name='ملاحظات')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='بواسطة')),
            ],
            options={
                'verbose_name': 'مديونية عميل',
                'verbose_name_plural': 'فلوس ليا (مديونيات العملاء)',
                'ordering': ['-created_at'],
            },
        ),
        # Create ReceivablePayment model
        migrations.CreateModel(
            name='ReceivablePayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='المبلغ المحصّل')),
                ('payment_type', models.CharField(choices=[('cash', 'كاش'), ('visa', 'فيزا'), ('transfer', 'تحويل')], default='cash', max_length=20, verbose_name='طريقة الدفع')),
                ('date', models.DateField(verbose_name='تاريخ التحصيل')),
                ('notes', models.TextField(blank=True, null=True, verbose_name='ملاحظات')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='بواسطة')),
                ('receivable', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payments', to='store.receivable', verbose_name='المديونية')),
            ],
            options={
                'verbose_name': 'دفعة تحصيل',
                'verbose_name_plural': 'دفعات التحصيل',
                'ordering': ['-date'],
            },
        ),
        # Create Payable model
        migrations.CreateModel(
            name='Payable',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('supplier_name_manual', models.CharField(blank=True, max_length=200, null=True, verbose_name='اسم المورد (يدوي)')),
                ('description', models.TextField(blank=True, null=True, verbose_name='البيان / الوصف')),
                ('total_amount', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='إجمالي المبلغ')),
                ('amount_paid', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='المبلغ المدفوع')),
                ('amount_remaining', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='المتبقي')),
                ('status', models.CharField(choices=[('pending', 'لم يُسدَّد'), ('partial', 'مسدد جزئياً'), ('paid', 'مسدد بالكامل')], default='pending', max_length=10, verbose_name='الحالة')),
                ('date', models.DateField(verbose_name='تاريخ المديونية')),
                ('due_date', models.DateField(blank=True, null=True, verbose_name='تاريخ الاستحقاق')),
                ('notes', models.TextField(blank=True, null=True, verbose_name='ملاحظات')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='payables_created', to=settings.AUTH_USER_MODEL, verbose_name='بواسطة')),
                ('supplier', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='payables', to='store.supplier', verbose_name='المورد')),
            ],
            options={
                'verbose_name': 'مديونية مورد',
                'verbose_name_plural': 'فلوس عليا (مديونيات الموردين)',
                'ordering': ['-created_at'],
            },
        ),
        # Create PayablePayment model
        migrations.CreateModel(
            name='PayablePayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='المبلغ المدفوع')),
                ('payment_type', models.CharField(choices=[('cash', 'كاش'), ('visa', 'فيزا'), ('transfer', 'تحويل')], default='cash', max_length=20, verbose_name='طريقة الدفع')),
                ('date', models.DateField(verbose_name='تاريخ السداد')),
                ('notes', models.TextField(blank=True, null=True, verbose_name='ملاحظات')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='بواسطة')),
                ('payable', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payments', to='store.payable', verbose_name='المديونية')),
            ],
            options={
                'verbose_name': 'دفعة سداد',
                'verbose_name_plural': 'دفعات السداد',
                'ordering': ['-date'],
            },
        ),
    ]
