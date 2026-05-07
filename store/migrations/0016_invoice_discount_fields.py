from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0015_remove_invoice_discount'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='subtotal_before_discount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='إجمالي المنتجات قبل الخصم'),
        ),
        migrations.AddField(
            model_name='invoice',
            name='discount_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='قيمة الخصم'),
        ),
    ]
