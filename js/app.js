    /**
     * Canlı ortam uyumlu API Base belirleme:
     * file:// veya Live Server (örn: 5500) kullanılıyorsa API localhost:8000'e gider.
     * FastAPI kendi adresi (8000) üzerinden açıldıysa veya yayınlanmış (canlı) sunucudaysa sayfayla aynı domaine ("") gider.
     */
    const API_BASE = 
        window.location.protocol === "file:" || (window.location.hostname === "127.0.0.1" && window.location.port !== "8000")
            ? "http://127.0.0.1:8000"
            : "";

    // Modalı kapatma işlemleri
    const modal = document.getElementById('aiModal');
    const modalClose = document.getElementById('modal-close');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    const modalDot = document.getElementById('modal-dot');

    modalClose.addEventListener('click', () => modal.classList.remove('show'));
    modal.addEventListener('click', (e) => { if(e.target === modal) modal.classList.remove('show'); });

    // Sol menüde derse tıklanınca Popup açılsın ve ilgili kart görünür alana kaysın
    const navToDataMap = {
        'nav-matematik': { base: 'mat', color: '#0F6E56', dotColor: '#1D9E75', lessonId: 'ders-matematik' },
        'nav-fizik': { base: 'fiz', color: '#A32D2D', dotColor: '#E24B4A', lessonId: 'ders-fizik' },
        'nav-kimya': { base: 'kim', color: '#854F0B', dotColor: '#BA7517', lessonId: 'ders-kimya' },
        'nav-uyku': { base: 'uyku', color: '#6D28D9', dotColor: '#8B5CF6', lessonId: 'ders-uyku' },
        'nav-calisma': { base: 'calisma', color: '#B45309', dotColor: '#F59E0B', lessonId: 'ders-calisma' }
    };

    Object.keys(navToDataMap).forEach(navId => {
        const navItem = document.getElementById(navId);
        if(!navItem) return;
        
        navItem.style.cursor = 'pointer';
        navItem.addEventListener('click', () => {
            const data = navToDataMap[navId];
            
            // Arkadaki kartı hala hizala ki deneyim bozulmasın
            const lessonCard = document.getElementById(data.lessonId);
            if(lessonCard) lessonCard.scrollIntoView({ behavior: 'smooth', block: 'start' });

            // Popup için verileri çekip göster
            const baslikElement = document.getElementById(`ui-${data.base}-baslik`);
            const bodyElement = document.getElementById(`ui-${data.base}-tavsiyeler`);
            
            if(baslikElement && bodyElement) {
                 modalTitle.innerText = baslikElement.innerText || baslikElement.textContent;
                 modalTitle.style.color = data.color;
                 modalDot.style.backgroundColor = data.dotColor;
                 modalBody.innerHTML = bodyElement.innerHTML;
                 
                 modal.classList.add('show');
            }
        });
    });

    // Önceki analiz değerlerini saklamak ve fark hesaplamak için basit depolama
    const trendStorageKey = 'eduai_prev_ders_performans';

    function getPreviousPerformance() {
        try {
            const raw = localStorage.getItem(trendStorageKey);
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            console.warn('Önceki performans okunamadı:', e);
            return null;
        }
    }

    function setPreviousPerformance(obj) {
        try {
            localStorage.setItem(trendStorageKey, JSON.stringify(obj));
        } catch (e) {
            console.warn('Önceki performans kaydedilemedi:', e);
        }
    }

    function formatTrend(current, previous) {
        if (previous === null || previous === undefined) {
            return '—';
        }
        const diff = current - previous;
        if (diff > 0) {
            return `+${diff} ↑`;
        } else if (diff < 0) {
            return `${diff} ↓`;
        }
        return '0 →';
    }

    const navIlerleme = document.getElementById('nav-ilerleme');
    if (navIlerleme) {
        navIlerleme.addEventListener('click', () => {
            const sgrid = document.getElementById('ui-ilerleme-sgrid');
            const dcard = document.getElementById('ui-ilerleme-dcard');
            
            if (sgrid && dcard) {
                modalTitle.innerText = "İlerleme Raporu";
                modalTitle.style.color = '#185FA5';
                modalDot.style.backgroundColor = '#378ADD';
                
                modalBody.innerHTML = `
                    <div style="display:flex; flex-direction:column; gap:16px;">
                        ${sgrid.outerHTML}
                        ${dcard.outerHTML}
                    </div>
                `;
                
                modal.classList.add('show');
            }
        });
    }

    // Kutucuklardaki sayılar değiştikçe renkleri güncelleyen fonksiyon
    document.querySelectorAll('.grow').forEach(row => {
        const input = row.querySelector('.ginput');
        const scoreBox = row.querySelector('.gscore');
        
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') e.preventDefault();
        });
        input.addEventListener('input', (e) => {
            let val = parseInt(e.target.value) || 0;
            if (input.id === 'uyku-saati' || input.id === 'calisma-saati') {
                 if (val > 24) val = 24; if(val < 0) val = 0;
                 scoreBox.innerText = val;
                 if (input.id === 'uyku-saati') {
                     scoreBox.className = 'gscore ' + (val < 6 ? 'sl' : (val <= 8 ? 'sh' : 'sm'));
                 } else {
                     scoreBox.className = 'gscore ' + (val < 2 ? 'sl' : (val < 4 ? 'sm' : 'sh'));
                 }
            } else {
                if(val > 100) val = 100; if(val < 0) val = 0;
                scoreBox.innerText = val;
                scoreBox.className = 'gscore ' + (val < 60 ? 'sl' : (val < 80 ? 'sm' : 'sh'));
            }
        });
    });

    document.getElementById('analizBtn').addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const btn = document.getElementById('analizBtn');
        const alan = document.getElementById('ai-sonuc-alani');
        
        try {
            const notlar = {
                mat: [Number(document.getElementById('mat1').value), Number(document.getElementById('mat2').value), Number(document.getElementById('mat3').value)],
                fiz: [Number(document.getElementById('fiz1').value), Number(document.getElementById('fiz2').value), Number(document.getElementById('fiz3').value)],
                kim: [Number(document.getElementById('kim1').value), Number(document.getElementById('kim2').value), Number(document.getElementById('kim3').value)]
            };

            const allGrades = [...notlar.mat, ...notlar.fiz, ...notlar.kim];
            const areAllSame = allGrades.every(val => val === allGrades[0]);
            const hasZero = allGrades.includes(0);

            if (areAllSame || hasZero) {
                alert("Tüm notlar aynı olamaz veya '0' not girilemez. Lütfen bir kez daha girin.");
                return;
            }

            const rutinler = {
                uyku: Number(document.getElementById('uyku-saati').value),
                calisma: Number(document.getElementById('calisma-saati').value)
            };

            const ortalamalar = {
                mat: Math.round((notlar.mat[0] + notlar.mat[1] + notlar.mat[2]) / 3),
                fiz: Math.round((notlar.fiz[0] + notlar.fiz[1] + notlar.fiz[2]) / 3),
                kim: Math.round((notlar.kim[0] + notlar.kim[1] + notlar.kim[2]) / 3)
            };

            btn.disabled = true;
            btn.innerText = "Sunucuya bağlanılıyor...";
            alan.style.opacity = "0.4";

            btn.innerText = "Analiz Ediliyor...";

            const response = await fetch(`${API_BASE}/api/analyze`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ notlar, rutinler })
            });

            if (!response.ok) {
                let msg = `Sunucu hatası (${response.status})`;
                try {
                    const errData = await response.json();
                    if (typeof errData.detail === "string") {
                        msg = errData.detail;
                    } else if (Array.isArray(errData.detail)) {
                        msg = errData.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
                    }
                } catch (_) { /* ignore */ }
                throw new Error(msg);
            }

            const payload = await response.json();
            const aiSonuc = payload.ai;
            if (!aiSonuc || typeof aiSonuc !== "object") {
                throw new Error("Sunucudan geçersiz yanıt alındı.");
            }

            const genelOrt = Math.round((ortalamalar.mat + ortalamalar.fiz + ortalamalar.kim) / 3);
            document.getElementById('ui-genel-ort').innerText = genelOrt;

            const derslerArr = [
                {isim: 'Matematik', ort: ortalamalar.mat, id: 'mat', color: '#1D9E75'},
                {isim: 'Fizik', ort: ortalamalar.fiz, id: 'fiz', color: '#378ADD'},
                {isim: 'Kimya', ort: ortalamalar.kim, id: 'kim', color: '#D85A30'}
            ];

            const onceki = getPreviousPerformance() || { mat: null, fiz: null, kim: null, uyku: null, calisma: null };
            const trMat = formatTrend(ortalamalar.mat, onceki.mat);
            const trFiz = formatTrend(ortalamalar.fiz, onceki.fiz);
            const trKim = formatTrend(ortalamalar.kim, onceki.kim);
            const trUyku = formatTrend(rutinler.uyku, onceki.uyku);
            const trCalisma = formatTrend(rutinler.calisma, onceki.calisma);
            derslerArr.sort((a, b) => b.ort - a.ort);
            
            const guclu = derslerArr[0];
            const zayif = derslerArr[2];

            document.getElementById('ui-guclu-isim').innerText = guclu.isim.substring(0,3);
            document.getElementById('ui-guclu-alt').innerText = `Ort. ${guclu.ort} / 100`;
            document.getElementById('ui-guclu-bar').style.width = guclu.ort + '%';
            document.getElementById('ui-guclu-bar').style.backgroundColor = guclu.color;
            document.getElementById('ui-guclu-isim').style.color = guclu.color;

            document.getElementById('ui-zayif-isim').innerText = zayif.isim.substring(0,3);
            document.getElementById('ui-zayif-alt').innerText = `Ort. ${zayif.ort} / 100`;
            document.getElementById('ui-zayif-bar').style.width = zayif.ort + '%';
            document.getElementById('ui-zayif-bar').style.backgroundColor = zayif.color;
            document.getElementById('ui-zayif-isim').style.color = zayif.color;

            ['mat', 'fiz', 'kim'].forEach(ders => {
                document.getElementById(`ui-${ders}-score`).innerText = ortalamalar[ders];
                document.getElementById(`ui-${ders}-bar`).style.width = ortalamalar[ders] + '%';
            });
            const uykuPercent = Math.max(0, Math.min(100, Math.round((rutinler.uyku / 24) * 100)));
            const calismaPercent = Math.max(0, Math.min(100, Math.round((rutinler.calisma / 24) * 100)));

            document.getElementById('ui-uyku-score').innerText = rutinler.uyku;
            document.getElementById('ui-uyku-bar').style.width = uykuPercent + '%';
            document.getElementById('ui-uyku-trend').innerText = trUyku;

            document.getElementById('ui-calisma-score').innerText = rutinler.calisma;
            document.getElementById('ui-calisma-bar').style.width = calismaPercent + '%';
            document.getElementById('ui-calisma-trend').innerText = trCalisma;

            // Önceki analiz değerlerine göre trendleri güncelle
            document.getElementById('ui-mat-trend').innerText = trMat;
            document.getElementById('ui-fiz-trend').innerText = trFiz;
            document.getElementById('ui-kim-trend').innerText = trKim;

            // GÜNCELLENEN KISIM: Ders isimleri sabit, AI yanıtı temizlenerek ekleniyor.
            // AI bazen "Matematik - Güçlü" diyebilir, replace ile baştaki tekrarı engelliyoruz.
            let matOzet = (aiSonuc.matematikDurum || aiSonuc.matematikBaslik || "").replace(/Matematik\s*[-—:]\s*/i, '');
            document.getElementById('ui-mat-baslik').innerText = `Matematik — ${matOzet}`;
            document.getElementById('ui-mat-tavsiyeler').innerHTML = aiSonuc.matematikTavsiyeler.map(t => 
                `<div class="aitem"><div class="adot" style="background:#1D9E75;"></div><div class="atext">${t}</div></div>`
            ).join('');

            let fizOzet = (aiSonuc.fizikDurum || aiSonuc.fizikBaslik || "").replace(/Fizik\s*[-—:]\s*/i, '');
            document.getElementById('ui-fiz-baslik').innerText = `Fizik — ${fizOzet}`;
            document.getElementById('ui-fiz-tavsiyeler').innerHTML = aiSonuc.fizikTavsiyeler.map(t => 
                `<div class="aitem"><div class="adot" style="background:#E24B4A;"></div><div class="atext">${t}</div></div>`
            ).join('');

            let kimOzet = (aiSonuc.kimyaDurum || aiSonuc.kimyaBaslik || "").replace(/Kimya\s*[-—:]\s*/i, '');
            document.getElementById('ui-kim-baslik').innerText = `Kimya — ${kimOzet}`;
            document.getElementById('ui-kim-tavsiyeler').innerHTML = aiSonuc.kimyaTavsiyeler.map(t => 
                `<div class="aitem"><div class="adot" style="background:#BA7517;"></div><div class="atext">${t}</div></div>`
            ).join('');

            let uykuOzet = (aiSonuc.uykuDurum || aiSonuc.uykuBaslik || "");
            document.getElementById('ui-uyku-baslik').innerText = `Uyku Düzeni — ${uykuOzet}`;
            document.getElementById('ui-uyku-tavsiyeler').innerHTML = (aiSonuc.uykuTavsiyeler || []).map(t => 
                `<div class="aitem"><div class="adot" style="background:#8B5CF6;"></div><div class="atext">${t}</div></div>`
            ).join('');

            let calismaOzet = (aiSonuc.calismaDurum || aiSonuc.calismaBaslik || "");
            document.getElementById('ui-calisma-baslik').innerText = `Ders Çalışma Saati — ${calismaOzet}`;
            document.getElementById('ui-calisma-tavsiyeler').innerHTML = (aiSonuc.calismaTavsiyeler || []).map(t => 
                `<div class="aitem"><div class="adot" style="background:#F59E0B;"></div><div class="atext">${t}</div></div>`
            ).join('');

            setPreviousPerformance({
                mat: ortalamalar.mat,
                fiz: ortalamalar.fiz,
                kim: ortalamalar.kim,
                uyku: rutinler.uyku,
                calisma: rutinler.calisma
            });

            alan.style.opacity = "1";
            alan.style.pointerEvents = "auto";
            document.getElementById('pdfBtn').style.display = "block";

        } catch (error) {
            alert("İşlem sırasında bir hata oluştu:\n" + error.message);
        } finally {
            btn.disabled = false;
            btn.innerText = "Tekrar Analiz Et";
        }
    });

    document.getElementById('pdfBtn').addEventListener('click', () => {
        const btn = document.getElementById('pdfBtn');
        const alan = document.getElementById('ai-sonuc-alani');
        const opt = {
            margin:       0.4,
            filename:     'EduAI_Tavsiye_Raporum.pdf',
            image:        { type: 'jpeg', quality: 0.98 },
            html2canvas:  { scale: 2 },
            jsPDF:        { unit: 'in', format: 'a4', orientation: 'portrait' }
        };
        btn.innerText = "İndiriliyor...";
        html2pdf().set(opt).from(alan).save().then(() => {
            btn.innerText = "📄 PDF İndir";
        });
    });