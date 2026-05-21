(function($) {
    $(document).ready(function() {
        // عند تغيير اختيار "المنتج" في أي صف داخل الجدول
        $(document).on('change', 'select[name$="-product"]', function() {
            var $productSelect = $(this);
            var productId = $productSelect.val();
            
            // تحديد الصف الحالي عشان نغير الخانات اللي جواه هو بس
            var $row = $productSelect.closest('tr.form-row, div.inline-related');
            var $variantSelect = $row.find('select[name$="-variant"]');
            var $sizeSelect = $row.find('select[name$="-product_size"]');

            // تصفير الخانات
            $variantSelect.empty().append('<option value="">---------</option>');
            $sizeSelect.empty().append('<option value="">---------</option>');
            $row.removeData('variants'); // مسح الداتا القديمة من الذاكرة

            if (productId) {
                // استدعاء الـ API اللي أنت عامله في views.py
                $.ajax({
                    url: '/api/product/' + productId + '/variants/',
                    method: 'GET',
                    success: function(response) {
                        var variants = response.variants;
                        
                        // حفظ البيانات في الصف عشان نستخدمها لما يختار اللون
                        $row.data('variants', variants);

                        // تعبئة خانة الألوان
                        $.each(variants, function(index, variant) {
                            $variantSelect.append('<option value="' + variant.id + '">' + variant.color + '</option>');
                        });
                    },
                    error: function() {
                        alert('حدث خطأ أثناء جلب بيانات المنتج. تأكد من اتصالك.');
                    }
                });
            }
        });

        // عند تغيير اختيار "اللون" في أي صف
        $(document).on('change', 'select[name$="-variant"]', function() {
            var $variantSelect = $(this);
            var variantId = $variantSelect.val();
            var $row = $variantSelect.closest('tr.form-row, div.inline-related');
            var $sizeSelect = $row.find('select[name$="-product_size"]');
            
            // تصفير خانة المقاسات
            $sizeSelect.empty().append('<option value="">---------</option>');

            // استدعاء البيانات اللي حفظناها في الخطوة اللي فاتت
            var variants = $row.data('variants');
            
            if (variants && variantId) {
                // البحث عن اللون المحدد لاستخراج مقاساته
                var selectedVariant = variants.find(v => v.id == parseInt(variantId));
                if (selectedVariant && selectedVariant.sizes) {
                    $.each(selectedVariant.sizes, function(index, size) {
                        // إضافة المقاس مع توضيح المخزن المتاح
                        var stockInfo = size.stock > 0 ? ' (' + size.stock + ' متاح)' : ' (نفذ المخزون)';
                        $sizeSelect.append('<option value="' + size.id + '">' + size.name + stockInfo + '</option>');
                    });
                }
            }
        });
    });
})(django.jQuery); // استخدام نسخة jQuery المدمجة مع Django Admin لتجنب التعارض