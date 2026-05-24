/**
 * admin_image_swap.js  v3
 * ===================================================
 * Drag-and-drop image swapping for ProductVariant admin.
 * ===================================================
 */
(function () {
  "use strict";

  const SWAP_URL = '/api/admin/swap-images/';

  /* ---- State ---- */
  let dragSrc = null;

  /* ---- Helpers ---- */
  function getCsrfToken() {
    const el = document.querySelector('[name=csrfmiddlewaretoken]');
    if (el) return el.value;
    const cookie = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
    return cookie ? cookie.trim().split('=')[1] : '';
  }

  function highlight(el, on) {
    if (!el) return;
    el.style.border = on ? '2px dashed #4caf50'
      : el.classList.contains('variant-main-preview') ? '2px solid #ddd' : '2px solid transparent';
    el.style.opacity = on ? '0.6' : '1';
  }

  function highlightZone(zone, on) {
    if (!zone) return;
    zone.style.border = on ? '2px dashed #4caf50' : '2px dashed #aaa';
    zone.style.background = on ? 'rgba(76,175,80,0.08)' : '';
  }

  function highlightAdditionalZone(zone, on) {
    if (!zone) return;
    zone.style.border = on ? '2px dashed #4caf50' : '2px dashed #aaa';
    zone.style.background = on ? 'rgba(76,175,80,0.08)' : '';
  }

  function flash(el, color) {
    if (!el) return;
    el.style.transition = 'box-shadow 0.3s';
    el.style.boxShadow = `0 0 0 3px ${color}`;
    setTimeout(() => { el.style.boxShadow = ''; }, 700);
  }

  function findFileInput(imgEl) {
    const row = imgEl.closest('tr') || imgEl.closest('.form-row') || imgEl.closest('.inline-related');
    return row ? row.querySelector('input[type="file"]') : null;
  }

  function findVariantFileInput(zoneEl) {
    const block = zoneEl.closest('.inline-related');
    return block ? block.querySelector('input[type="file"][name*="variant_image"]') : null;
  }

  function findAdditionalFileInput(zoneEl) {
    const row = zoneEl.closest('tr') || zoneEl.closest('.form-row') || zoneEl.closest('.inline-related');
    return row ? row.querySelector('input[type="file"]') : null;
  }

  function swapFileInputs(a, b) {
    if (!a || !b) return;
    try {
      const dtA = new DataTransfer(), dtB = new DataTransfer();
      if (a.files && a.files[0]) dtA.items.add(a.files[0]);
      if (b.files && b.files[0]) dtB.items.add(b.files[0]);
      a.files = dtB.files;
      b.files = dtA.files;
    } catch (e) { console.warn('DataTransfer not supported', e); }
  }

  function moveFileToInput(srcInput, dstInput) {
    if (!srcInput || !dstInput) return;
    if (srcInput.files && srcInput.files.length > 0) {
      try {
        const dt = new DataTransfer();
        dt.items.add(srcInput.files[0]);
        dstInput.files = dt.files;
        srcInput.files = new DataTransfer().files;
      } catch (e) { console.warn('DataTransfer not supported', e); }
    }
  }

  /* ---- AJAX swap (للصور المحفوظة) ---- */
  function ajaxSwap(srcImg, dstImg, onSuccess, onError) {
    fetch(SWAP_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrfToken(),
      },
      body: JSON.stringify({
        src_type: srcImg.dataset.imgType,
        src_id:   srcImg.dataset.imgId,
        dst_type: dstImg.dataset.imgType,
        dst_id:   dstImg.dataset.imgId,
      }),
    })
    .then(r => r.json())
    .then(data => {
      if (data.ok) onSuccess(data);
      else onError(data.error);
    })
    .catch(onError);
  }

  /* ---- Core swap logic ---- */
  function doSwap(srcImg, dstImg) {
    if (!srcImg || !dstImg || srcImg === dstImg) return;

    const srcSaved = !!srcImg.dataset.imgId && srcImg.dataset.imgId !== '0';
    const dstSaved = !!dstImg.dataset.imgId && dstImg.dataset.imgId !== '0';

    if (srcSaved && dstSaved) {
      ajaxSwap(srcImg, dstImg,
        (data) => {
          srcImg.src = data.src_new_url;
          dstImg.src = data.dst_new_url;
          const tmpId   = srcImg.dataset.imgId;
          const tmpType = srcImg.dataset.imgType;
          srcImg.dataset.imgId   = dstImg.dataset.imgId;
          srcImg.dataset.imgType = dstImg.dataset.imgType;
          dstImg.dataset.imgId   = tmpId;
          dstImg.dataset.imgType = tmpType;
          flash(srcImg, '#4caf50');
          flash(dstImg, '#4caf50');
        },
        (err) => {
          console.error('Swap failed:', err);
          flash(srcImg, '#f44336');
          flash(dstImg, '#f44336');
          alert('فشل تبديل الصور: ' + err);
        }
      );
    } else {
      const tmpSrc = srcImg.src;
      srcImg.src = dstImg.src;
      dstImg.src = tmpSrc;
      swapFileInputs(findFileInput(srcImg), findFileInput(dstImg));
      flash(srcImg, '#4caf50');
      flash(dstImg, '#4caf50');
    }
  }

  /* ---- Drop on empty VARIANT zone ---- */
  function doMoveToZone(srcImg, dstZone) {
    const srcSaved = !!srcImg.dataset.imgId && srcImg.dataset.imgId !== '0';
    const variantId = dstZone.dataset.variantId;

    const newImg = document.createElement('img');
    newImg.src              = srcImg.src;
    newImg.dataset.imgUrl   = srcImg.dataset.imgUrl || srcImg.src;
    newImg.dataset.imgType  = 'variant';
    newImg.dataset.imgId    = variantId;
    newImg.className        = 'draggable-preview variant-main-preview';
    newImg.draggable        = true;
    newImg.title            = 'اسحب لتبديل الصورة';
    newImg.style.cssText    = 'width:100px;height:100px;border-radius:8px;border:2px solid #ddd;object-fit:cover;cursor:grab;transition:border 0.2s;';

    if (srcSaved) {
      fetch(SWAP_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({
          src_type: srcImg.dataset.imgType,
          src_id:   srcImg.dataset.imgId,
          dst_type: 'variant',
          dst_id:   variantId,
        }),
      })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          dstZone.replaceWith(newImg);
          srcImg.style.opacity = '0.25';
          srcImg.title = 'الصورة نُقلت — يمكنك حذف هذا الصف';
          flash(newImg, '#4caf50');
        } else {
          alert('فشل نقل الصورة: ' + data.error);
        }
      })
      .catch(e => alert('خطأ: ' + e));
    } else {
      const srcInput = findFileInput(srcImg);
      const dstInput = findVariantFileInput(dstZone);
      moveFileToInput(srcInput, dstInput);
      dstZone.replaceWith(newImg);
      srcImg.style.opacity = '0.25';
      flash(newImg, '#4caf50');
    }
  }

  /* ---- Drop on empty ADDITIONAL zone (الإضافة الجديدة) ---- */
  async function doMoveToAdditionalZone(dragSrc, dstZone) {
    const srcSaved = !!dragSrc.dataset.imgId && dragSrc.dataset.imgId !== '0';
    const dstInput = findAdditionalFileInput(dstZone);

    if (!dstInput) return;

    // تجهيز الصورة التي ستظهر في المكان الجديد
    const newImg = document.createElement('img');
    newImg.src = dragSrc.src;
    newImg.dataset.imgUrl = dragSrc.dataset.imgUrl || dragSrc.src;
    newImg.dataset.imgType = 'additional';
    newImg.dataset.imgId = '0'; // لتبدو كصورة جديدة غير محفوظة حتى يقوم المستخدم بحفظ الصفحة
    newImg.className = 'draggable-preview';
    newImg.draggable = true;
    newImg.title = 'اسحب لتبديل الصورة';
    newImg.style.cssText = 'width: 70px; height: 70px; border-radius: 5px; object-fit: contain; background: #ffffff; border: 1px solid #eee; padding: 5px; cursor: grab; transition: border 0.2s;';

    // مساعدة لتغيير المكان الأصلي إلى مساحة فارغة بعد النقل
    const revertSrcToEmpty = () => {
        const srcWrap = dragSrc.closest('.variant-main-img-wrap');
        if (srcWrap) {
            const emptyDiv = document.createElement('div');
            emptyDiv.className = 'variant-main-img-wrap variant-empty-drop';
            emptyDiv.dataset.variantId = dragSrc.dataset.imgId || '0';
            emptyDiv.title = 'اسحب صورة من الأسفل وضعها هنا لتصبح الصورة الرئيسية';
            emptyDiv.style.cssText = 'width:100px;height:100px;border-radius:8px;border:2px dashed #aaa;display:flex;align-items:center;justify-content:center;color:#aaa;font-size:11px;text-align:center;cursor:pointer;transition: border 0.2s, background 0.2s;';
            emptyDiv.innerHTML = '⬆️<br>اسحب هنا';
            dragSrc.replaceWith(emptyDiv);
        } else {
            const emptyDiv = document.createElement('div');
            emptyDiv.className = 'additional-empty-drop';
            emptyDiv.title = 'اسحب صورة وضعها هنا';
            emptyDiv.style.cssText = 'width: 70px; height: 70px; border-radius: 5px; border: 2px dashed #aaa; display: flex; align-items: center; justify-content: center; color: #aaa; font-size: 11px; text-align: center; cursor: pointer; transition: border 0.2s, background 0.2s;';
            emptyDiv.innerHTML = '➕<br>اسحب هنا';
            dragSrc.replaceWith(emptyDiv);
        }
    };

    if (srcSaved) {
        try {
            // جلب بيانات الصورة الأصلية كملف وتحويله لخانة الرفع الجديدة
            const res = await fetch(dragSrc.src);
            const blob = await res.blob();
            const filename = dragSrc.src.split('/').pop().split('?')[0] || 'image.webp';
            const file = new File([blob], filename, { type: blob.type });
            const dt = new DataTransfer();
            dt.items.add(file);
            dstInput.files = dt.files;

            // تحديد خيار المسح (Clear) للصورة الأصلية لكي يتم حذفها عند الحفظ
            const td = dragSrc.closest('td, .form-row, .inline-related');
            if (td) {
                const clearCb = td.querySelector('input[type="checkbox"][name$="-clear"]');
                if (clearCb) clearCb.checked = true;
            }

            dstZone.replaceWith(newImg);
            revertSrcToEmpty();
            flash(newImg, '#4caf50');
        } catch (e) {
            alert('فشل نقل الصورة المحفوظة: ' + e);
        }
    } else {
        // في حالة إن الصورة مش محفوظة أصلا فبنقل الملف بسهولة
        const srcInput = findFileInput(dragSrc);
        moveFileToInput(srcInput, dstInput);
        dstZone.replaceWith(newImg);
        revertSrcToEmpty();
        flash(newImg, '#4caf50');
    }
  }

  /* ---- Drag events (delegated) ---- */
  function onDragStart(e) {
    const img = e.target.closest('img.draggable-preview');
    if (!img) return;
    dragSrc = img;
    highlight(img, true);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', img.dataset.imgUrl || img.src);
  }

  function onDragEnd(e) {
    const img = e.target.closest('img.draggable-preview');
    if (img) highlight(img, false);
    dragSrc = null;
    document.querySelectorAll('.draggable-preview').forEach(i => highlight(i, false));
    document.querySelectorAll('.variant-empty-drop').forEach(z => highlightZone(z, false));
    document.querySelectorAll('.additional-empty-drop').forEach(z => highlightAdditionalZone(z, false));
  }

  function onDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const img  = e.target.closest('img.draggable-preview');
    const variantZone = e.target.closest('.variant-empty-drop');
    const additionalZone = e.target.closest('.additional-empty-drop');

    if (img  && img  !== dragSrc) highlight(img, true);
    if (variantZone) highlightZone(variantZone, true);
    if (additionalZone) highlightAdditionalZone(additionalZone, true);
  }

  function onDragLeave(e) {
    const img  = e.target.closest('img.draggable-preview');
    const variantZone = e.target.closest('.variant-empty-drop');
    const additionalZone = e.target.closest('.additional-empty-drop');

    if (img  && img  !== dragSrc) highlight(img, false);
    if (variantZone) highlightZone(variantZone, false);
    if (additionalZone) highlightAdditionalZone(additionalZone, false);
  }

  function onDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    const dstImg  = e.target.closest('img.draggable-preview');
    const variantZone = e.target.closest('.variant-empty-drop');
    const additionalZone = e.target.closest('.additional-empty-drop');
    
    if (!dragSrc) return;

    if (dstImg && dstImg !== dragSrc) {
      doSwap(dragSrc, dstImg);
    } else if (variantZone) {
      doMoveToZone(dragSrc, variantZone);
    } else if (additionalZone) {
      doMoveToAdditionalZone(dragSrc, additionalZone);
    }

    highlight(dragSrc, false);
    dragSrc = null;
  }

  /* ---- Bootstrap ---- */
  function init() {
    const root = document.getElementById('content-main') || document;
    root.addEventListener('dragstart',  onDragStart);
    root.addEventListener('dragend',    onDragEnd);
    root.addEventListener('dragover',   onDragOver);
    root.addEventListener('dragleave',  onDragLeave);
    root.addEventListener('drop',       onDrop);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();