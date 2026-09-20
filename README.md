# Whale Tracking Bot 🐋

Kripto para piyasasında balina hareketlerini, borsa hacmini ve alış/satış baskısını
izleyip Telegram üzerinden anlık bildirim gönderen bot.

## Ne yapıyor?

1. **On-chain balina takibi** (`whale_alert_monitor.py`)
   Whale Alert API üzerinden belirlediğin eşiğin (varsayılan $1M) üzerindeki
   transferleri izler. Transferin borsaya girip girmediğini (satış sinyali) veya
   borsadan çıkıp çıkmadığını (biriktirme sinyali) sınıflandırır.

2. **Borsa hacim/akış takibi** (`exchange_monitor.py`)
   Binance'in `@aggTrade` WebSocket akışına bağlanır (API key gerekmez), her işlemi
   veritabanına kaydeder. Periyodik olarak:
   - Ortalamaya göre anormal hacim artışlarını
   - Alış/satış baskısındaki dengesizliği (örn. %70+ alım ağırlıklı)
   kontrol eder.

3. **Bildirim** (`notifier.py`)
   Eşik aşıldığında Telegram'a mesaj gönderir.

4. **Veritabanı** (`database.py`)
   SQLite ile tüm transferler, işlemler ve gönderilen uyarılar saklanır — sonradan
   analiz/backtest yapmak istersen veri hazır olur.

## Kurulum

```bash
pip install -r requirements.txt
cp .env.example .env
# .env dosyasını kendi API anahtarlarınla doldur
```

### Gerekli API anahtarları

| Anahtar | Nereden alınır | Zorunlu mu? |
|---|---|---|
| `WHALE_ALERT_API_KEY` | https://whale-alert.io (ücretsiz plan mevcut, başvuru gerekir) | On-chain takip için evet |
| `TELEGRAM_BOT_TOKEN` | Telegram'da @BotFather ile bot oluştur | Bildirim için evet |
| `TELEGRAM_CHAT_ID` | @userinfobot'a mesaj atarak kendi chat ID'ni öğren | Bildirim için evet |

Binance WebSocket için **API key gerekmez** (public veri).

## Çalıştırma

```bash
python main.py
```

Bot sürekli çalışır; Ctrl+C ile durdurabilirsin.

## Ayarları özelleştirme (`config.py`)

- `SYMBOLS`: İzlenecek işlem çiftleri
- `WHALE_MIN_USD_VALUE`: Balina sayılacak minimum transfer tutarı
- `VOLUME_SPIKE_MULTIPLIER`: Hacim artışı için ortalamanın kaç katı eşik
- `TRADE_IMBALANCE_THRESHOLD`: Alış/satış dengesizliği eşiği (0.70 = %70)

## Genişletme fikirleri

- **Order book duvarları**: Binance `@depth` akışını dinleyip büyük limit emirlerini tespit et
- **Çoklu borsa**: `exchange_monitor.py`'ı ccxt ile Bybit/OKX gibi borsalara genişlet
- **Dashboard**: `whale_bot.db` verisini Streamlit veya Grafana ile görselleştir
- **Coin bazlı filtreleme**: Whale Alert'te sadece belirli coinleri izlemek için `symbol` parametresi ekle
- **Backtest**: Geçmiş `trade_flow` verisiyle stratejinin ne kadar erken sinyal verdiğini test et

## Önemli notlar

- Whale Alert ücretsiz planı **istek limitli** ve bazen **gecikmeli** olabilir; prodüksiyon
  kullanımı için ücretli plan veya doğrudan Etherscan/BscScan/Solscan API'lerine geçmeyi düşün.
- Bu bot **yatırım tavsiyesi vermez**, sadece veri/sinyal toplar. Kararları sen veriyorsun.
- WebSocket bağlantısı kopmalarına karşı otomatik yeniden bağlanma (exponential backoff) eklendi.
