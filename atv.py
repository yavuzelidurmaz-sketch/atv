import requests
import re
import time
import os

# --- AYARLAR ---
BASE_URL = "https://www.atv.com.tr"

# 1. Taranacak Kategori Sayfaları
DIRECTORIES = [
    {"name": "Güncel Diziler", "url": "/diziler", "type": "DIZI"},
    {"name": "Eski Diziler", "url": "/eski-diziler", "type": "DIZI"},
    {"name": "Programlar", "url": "/programlar", "type": "PROGRAM"}
]

# 2. Manuel Eklenecek Özel Haber/Program Linkleri (Slug'ları)
MANUAL_SHOWS = [
    {"slug": "atv-ana-haber", "name": "ATV Ana Haber", "type": "HABER"},
    {"slug": "kahvalti-haberleri", "name": "Kahvaltı Haberleri", "type": "HABER"},
    {"slug": "gun-ortasi-bulteni", "name": "Gün Ortası Bülteni", "type": "HABER"},
    {"slug": "atvde-hafta-sonu", "name": "ATV'de Hafta Sonu", "type": "HABER"}
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Referer': 'https://www.atv.com.tr/'
}

def get_all_content():
    """Tüm dizileri, programları ve haberleri toplar"""
    content_dict = {}

    # 1. Kategori Sayfalarını Tara
    for directory in DIRECTORIES:
        try:
            print(f"[{directory['name']}] Sayfası taranıyor...")
            r = requests.get(f"{BASE_URL}{directory['url']}", headers=HEADERS, timeout=15)

            # Regex ile linkleri ve resimleri bul
            pattern = r'<a href="/([^"]+)"[^>]*?class="[^"]*blankpage[^"]*"[^>]*?>.*?<img[^>]*?src="([^"]+)"[^>]*?alt="([^"]+)"'
            matches = re.findall(pattern, r.text, re.DOTALL)

            for slug, logo, name in matches:
                # Gereksizleri atla
                if any(x in slug.lower() for x in ['canli-yayin', 'fragman', 'yayin-akisi']):
                    continue

                # Resim URL temizle
                clean_logo = logo.split('?')[0]

                if slug not in content_dict:
                    content_dict[slug] = {
                        'name': name.strip(),
                        'slug': slug,
                        'logo': clean_logo,
                        'group': directory['type']
                    }
            print(f"  -> {len(matches)} içerik bulundu.")

        except Exception as e:
            print(f"  Hata: {e}")

    # 2. Manuel Haber Bültenlerini Ekle
    print("[Özel Haber Bültenleri] Kontrol ediliyor...")
    for show in MANUAL_SHOWS:
        if show['slug'] not in content_dict:
            content_dict[show['slug']] = {
                'name': show['name'],
                'slug': show['slug'],
                'logo': "https://www.atv.com.tr/assets/img/atv-logo-meta.jpg", 
                'group': show['type']
            }
            print(f"  -> {show['name']} listeye eklendi.")

    return list(content_dict.values())

def get_episodes(series_slug, series_name):
    """İçeriğin bölümlerini çeker"""
    episodes = []
    bolumler_url = f"{BASE_URL}/{series_slug}/bolumler"

    try:
        r = requests.get(bolumler_url, headers=HEADERS, timeout=10)

        # 1. Dropdown Yöntemi
        dropdown_pattern = r'<option[^>]*value="/([^/]+)/([^"]+)"[^>]*>'
        matches = re.findall(dropdown_pattern, r.text)

        if matches:
            for slug, path in matches:
                if slug == series_slug and 'izle' in path:
                    full_url = f"{BASE_URL}/{slug}/{path}"

                    # Bölüm adını/numarasını path'den çıkar
                    ep_name = path.replace('-izle', '').replace('-bolum', '').replace('-', ' ').title()

                    # Sıralama için numara bulmaya çalış
                    ep_num = 0
                    num_match = re.search(r'^(\d+)', ep_name)
                    if num_match:
                        ep_num = int(num_match.group(1))
                    
                    # İsimlendirme: Numara varsa "X. Bölüm", yoksa (tarih vb.) olduğu gibi bırak
                    final_name = f"{ep_name}. Bölüm" if ep_num > 0 and len(str(ep_num)) < 5 else ep_name

                    episodes.append({
                        'url': full_url,
                        'name': final_name,
                        'order': ep_num
                    })

    except Exception as e:
        print(f"    Bölüm hatası: {e}")

    # Bölüm numarasına göre sırala (Eskiden yeniye)
    episodes.sort(key=lambda x: x['order'])
    
    return episodes

def fix_fake_url(video_url):
    """
    Karmaşık ATV url'lerini düzeltir.
    Haberler ve özel tokenlı linkler için koruma sağlar.
    """
    if not video_url: return None

    # --- ÖZEL KORUMA: Haber Linkleri ---
    # erbvr.com ve karmaşık tokenlı linkleri BOZMADAN döndür
    if 'erbvr.com' in video_url or 'hlssubplaylist' in video_url:
        return video_url
    # -----------------------------------

    # Pattern: i.tmgrup.com.trvideo/dizi_001_...
    if 'i.tmgrup.com.trvideo/' in video_url:
        try:
            filename = video_url.split('/')[-1]
            match = re.match(r'([a-zA-Z0-9-]+)_(\d+)_', filename)
            if match:
                dizi = match.group(1)
                bolum = int(match.group(2))
                real = f"https://atv-vod.ercdn.net/{dizi}/{bolum:03d}/{dizi}_{bolum:03d}.smil/playlist.m3u8"
                return real
        except:
            pass

    return video_url

def extract_video_url(episode_url):
    """Sayfaya gidip video linkini cımbızlar"""
    try:
        r = requests.get(episode_url, headers=HEADERS, timeout=10)

        # 1. JSON-LD içindeki contentUrl
        match = re.search(r'"contentUrl"\s*:\s*"([^"]+)"', r.text)
        if match:
            url = fix_fake_url(match.group(1))
            if url: return url

        # 2. Direkt mp4/m3u8 ve Gelişmiş Regexler
        patterns = [
            r'(https?://atv-vod\.ercdn\.net/[^\s"\']+\.m3u8[^\s"\']*)',
            r'src="(https?://[^"]+\.(?:mp4|m3u8)[^"]*)"',
            r'video-src="([^"]+)"',
            # Haberler için tırnak içindeki karmaşık linkleri yakalayan regex
            r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']'
        ]

        for p in patterns:
            m = re.findall(p, r.text)
            for url in m:
                if 'fragman' not in url and 'reklam' not in url:
                    # Unicode temizliği
                    url = url.encode('utf-8').decode('unicode_escape')
                    fixed = fix_fake_url(url)
                    if fixed: return fixed

    except:
        pass
    return None

def create_m3u(data):
    """M3U Dosyası Oluşturur - HER ŞEY KENDİ KLASÖRÜNDE"""
    filename = "atv.m3u"
    print(f"\n📝 {filename} dosyası yazılıyor...")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")

        for slug, item in data.items():
            # Kategori mantığı: item['group'] yerine item['name'] kullanıyoruz.
            # Böylece her dizi/program M3U içinde kendi klasörüne sahip olur.
            group_folder = item['name'] 
            logo = item['logo']

            for ep in item['episodes']:
                ep_name = ep['name']
                url = ep['url']

                # Başlık: Dizi Adı - Bölüm Adı
                full_title = f"{group_folder} - {ep_name}"
                
                # group-title="{group_folder}" -> Klasörleme burası
                f.write(f'#EXTINF:-1 group-title="{group_folder}" tvg-logo="{logo}",{full_title}\n')
                f.write(f'{url}\n')

    print("✅ M3U Tamamlandı!")

def main():
    print("🚀 ATV VOD Scraper Başlatıldı (SINIRSIZ MOD)...")

    all_content = get_all_content()
    final_data = {}

    total = len(all_content)
    for i, item in enumerate(all_content, 1):
        print(f"\n[{i}/{total}] İşleniyor: {item['name']}")

        episodes = get_episodes(item['slug'], item['name'])

        if episodes:
            valid_episodes = []
            print(f"  -> {len(episodes)} bölüm bulundu, taranıyor...")

            # --- SINIRSIZ DÖNGÜ ---
            # Burada herhangi bir [:25] limiti YOK. Hepsi taranacak.
            for ep in episodes: 
                video_url = extract_video_url(ep['url'])
                if video_url:
                    valid_episodes.append({
                        'name': ep['name'],
                        'url': video_url
                    })
                    print(f"    + {ep['name']} eklendi.")
                else:
                    print(f"    - {ep['name']} video bulunamadı.")

            if valid_episodes:
                # M3U'da en yeni bölümü en üste koymak için ters çeviriyoruz
                valid_episodes.reverse()
                
                final_data[item['slug']] = {
                    'name': item['name'],
                    'group': item['group'],
                    'logo': item['logo'],
                    'episodes': valid_episodes
                }
        else:
            print("  -> Bölüm bulunamadı.")

    create_m3u(final_data)

if __name__ == "__main__":
    main()
