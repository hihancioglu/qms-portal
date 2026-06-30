# QMS Portal - Minimum Modül Başlangıç Projesi

Bu proje Linux Docker üzerinde host edilecek şekilde hazırlanmış minimum QMS kalite doküman yönetim portalıdır.

## İçerik

- FastAPI web uygulaması
- PostgreSQL veritabanı
- ONLYOFFICE Document Server entegrasyon iskeleti
- Doküman kartı
- Revizyon yönetimi
- Taslak → İnceleme → Onay → Yayın akışı
- Audit log
- Okudum/anladım takibi
- Basit kullanıcı ve rol yönetimi
- Active Directory / LDAP login ve kullanıcı senkronizasyonu

## Roller

- `admin`: tüm işlemler
- `quality`: kalite sorumlusu; onay/yayın/audit
- `editor`: doküman oluşturma/düzenleme/revizyon
- `approver`: onay adımı
- `viewer`: yayınlanan dokümanları görüntüleme ve okudum kaydı

## Kurulum

```bash
cd qms-portal
cp docker-compose.yml docker-compose.prod.yml
# docker-compose.prod.yml içinde şifreleri ve URL'leri değiştirin.
docker compose up -d --build
```

Varsayılan erişim:

- QMS Portal: http://localhost:8080
- ONLYOFFICE: http://localhost:8082

İlk kullanıcı:

```text
admin / admin123
```

LDAP/AD entegrasyonu için `qms-web` ortam değişkenleri:

```text
LDAP_SERVER=ldap://10.0.0.201
LDAP_DOMAIN=BAYLAN
LDAP_USER=servis_kullanici
LDAP_PASSWORD=servis_kullanici_sifresi
LDAP_BASE_DN=DC=baylan,DC=local
LDAP_SEARCH_FILTER=(&(objectClass=user)(objectCategory=person)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))
```

AD ile giriş yapan kullanıcı yerel kullanıcı tablosuna otomatik eklenir. İlk rolü `viewer` olur; admin kullanıcı rolü daha sonra Kullanıcılar ekranından yönetir. Adminler aynı ekrandaki AD senkronizasyon butonu ile aktif AD kullanıcılarını toplu olarak içeri alabilir.

İlk iş olarak `docker-compose.yml` içindeki şu değerleri değiştirin:

```text
POSTGRES_PASSWORD
DATABASE_URL içindeki şifre
APP_SECRET
INITIAL_ADMIN_PASSWORD
LDAP_PASSWORD
PUBLIC_BASE_URL
ONLYOFFICE_PUBLIC_URL
```

## Reverse proxy arkasında kullanım

Örnek dış adresler:

```text
PUBLIC_BASE_URL=https://qms.baylan.info.tr
ONLYOFFICE_PUBLIC_URL=https://qms-office.baylan.info.tr
```

ONLYOFFICE container'ı, QMS portalın `/files/revision/{id}` adresine erişebilmelidir. Bu nedenle `PUBLIC_BASE_URL`, ONLYOFFICE container tarafından da erişilebilir bir adres olmalıdır. İç DNS/reverse proxy buna göre ayarlanmalıdır.

## Pilot test akışı

1. Admin ile giriş yapın.
2. Kullanıcılar menüsünden `quality`, `editor`, `approver`, `viewer` rolleriyle test kullanıcıları oluşturun.
3. Yeni doküman oluşturun.
4. DOCX/XLSX/PDF dosyası yükleyin.
5. Revizyonu online editörde açın.
6. İncelemeye gönderin.
7. Onay adımlarını tamamlayın.
8. Kalite rolüyle yayınlayın.
9. Viewer kullanıcısı ile dokümanı indirip `Okudum` işaretleyin.
10. Audit Log ekranından izleri kontrol edin.

## Bilinçli MVP sınırlamaları

Bu ilk sürüm üretim kullanımına doğrudan alınacak nihai sistem değildir. Şu alanlar sonraki fazda güçlendirilmelidir:

- Departman bazlı yetki matrisi
- ONLYOFFICE JWT güvenliği
- PDF'e otomatik dönüştürme
- Elektronik imza / e-imza entegrasyonu
- Zorunlu okuma grupları
- Yedekleme ve restore prosedürü
- Versiyonlu dosya immutable storage politikası
- CAPA / DÖF / iç tetkik / eğitim matrisi modülleri

## Veritabanı modeli özeti

- `users`: kullanıcılar ve roller
- `documents`: doküman kartları
- `revisions`: doküman revizyonları
- `approvals`: onay adımları
- `audit_logs`: işlem geçmişi
- `read_receipts`: okudum/anladım kayıtları

## Güvenlik notları

- Varsayılan şifreler production ortamda kesinlikle kullanılmamalıdır.
- Reverse proxy üzerinde HTTPS zorunlu yapılmalıdır.
- ONLYOFFICE için production'da JWT etkinleştirilmelidir.
- QMS volume düzenli yedeklenmelidir: PostgreSQL dump + `qms_storage` volume.
